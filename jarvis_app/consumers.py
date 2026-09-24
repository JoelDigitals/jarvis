"""WebSocket-Endpunkte.

/ws/events/  – Browser-Tab: Live-Protokoll, Benachrichtigungen, Browser-Befehle, Bildschirm-Frames
/ws/agent/   – Desktop-Agent auf dem PC (Token-Authentifizierung)
/ws/live/    – Sprachmodus: Browser-Mikrofon ⇄ Gemini Live (Audio + optional Video)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.db import close_old_connections

from .hub import hub

log = logging.getLogger("jarvis.ws")


def _query(scope) -> dict:
    return {k: v[0] for k, v in parse_qs(scope.get("query_string", b"").decode()).items()}


# ── Browser-Events ─────────────────────────────────────────────────────────

class EventsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.user = user
        self.client_id = _query(self.scope).get("cid") or self.channel_name
        await self.accept()
        hub.add_client(user.id, self.client_id, self, is_admin=user.is_superuser)
        agent = hub.agent(user.id)
        await self.send(text_data=json.dumps({
            "type": "hello",
            "agent": {"connected": bool(agent), "host": agent.host if agent else "",
                      "platform": agent.platform if agent else "", "metrics": agent.metrics if agent else {}},
            "sync": {"logs": list(hub.sync_logs)[-20:], "state": hub.sync_state} if user.is_superuser else None,
        }))

    async def disconnect(self, code):
        if hasattr(self, "user"):
            hub.remove_client(self.user.id, self.client_id, self)

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:  # JPEG-Frame der Bildschirm-/Kamerafreigabe
            angle = "camera" if bytes_data[:1] == b"C" else "screen"
            hub.put_frame(self.user.id, bytes_data[1:], angle)
            return
        try:
            msg = json.loads(text_data or "{}")
        except ValueError:
            return
        kind = msg.get("type")
        if kind == "ping":
            await self.send(text_data=json.dumps({"type": "pong", "t": msg.get("t")}))
        elif kind == "share_stopped":
            hub.clear_frames(self.user.id)


# ── Desktop-Agent ──────────────────────────────────────────────────────────

@database_sync_to_async
def _user_for_token(token: str):
    from .models import Profile
    close_old_connections()
    p = Profile.objects.select_related("user").filter(api_token=token, user__is_active=True).first()
    if p and p.has_full_access:
        return p.user
    return None


class AgentConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        token = _query(self.scope).get("token", "")
        self.user = await _user_for_token(token) if token else None
        if not self.user:
            await self.close(code=4401)
            return
        await self.accept()
        self.info = None

    async def disconnect(self, code):
        if getattr(self, "user", None) and self.info:
            hub.remove_agent(self.user.id, self)
            log.info("[Agent] %s getrennt", self.user.username)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            msg = json.loads(text_data or "{}")
        except ValueError:
            return
        kind = msg.get("type")
        if kind == "hello":
            self.info = hub.add_agent(self.user.id, self, host=msg.get("host", ""), platform=msg.get("platform", ""))
            log.info("[Agent] %s verbunden von %s", self.user.username, self.info.host)
            await self.send(text_data=json.dumps({"type": "welcome", "user": self.user.username}))
        elif kind == "result":
            hub.agent_result(self.user.id, str(msg.get("id")), str(msg.get("result", "")))
        elif kind == "log":
            hub.send_to_user(self.user.id, {"type": "log", "text": f"[PC] {str(msg.get('text', ''))[:400]}"})
        elif kind == "metrics" and self.info:
            self.info.metrics = msg.get("metrics") or {}
            hub.send_to_user(self.user.id, {"type": "metrics", "metrics": self.info.metrics})
        elif kind == "push_state":
            saved = await self._push_state(msg.get("files") or [])
            await self.send(text_data=json.dumps({"type": "push_state_done", "saved": saved}))

    @database_sync_to_async
    def _push_state(self, files):
        import base64
        from . import state_sync
        from .config_store import ensure_api_keys
        close_old_connections()
        saved = []
        for f in files:
            path = str(f.get("path", ""))
            try:
                state_sync.write_file(path, base64.b64decode(f.get("b64", "")))
                saved.append(path)
            except Exception as e:
                log.warning("[Agent] push_state %s abgelehnt: %s", path, e)
        ensure_api_keys()  # os_system/Env-Keys wieder korrekt setzen
        return saved


# ── Sprachmodus (Gemini Live) ──────────────────────────────────────────────

WAKE_WORDS = ("jarvis", "javis", "jervis")
CONVO_WINDOW = 25.0


class LiveConsumer(AsyncWebsocketConsumer):
    """Leitet Mikrofon-Audio (PCM16, 16 kHz) und Frames an Gemini Live weiter und streamt
    die gesprochene Antwort (PCM16, 24 kHz) zurück. Tool-Aufrufe laufen über denselben Router
    wie der Text-Chat."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.user = user
        self.client_id = _query(self.scope).get("cid")
        self.session = None
        self.live_task = None
        self.closing = False
        self.in_buf: list[str] = []
        self.out_buf: list[str] = []
        self.turn_addressed = False
        self.addressed_until = 0.0
        await self.accept()

    async def disconnect(self, code):
        self.closing = True
        if self.live_task:
            self.live_task.cancel()

    async def _json(self, **payload):
        try:
            await self.send(text_data=json.dumps(payload, default=str))
        except Exception:
            pass

    # Browser → Server
    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            if not self.session:
                return
            kind, data = bytes_data[:1], bytes_data[1:]
            from google.genai import types
            try:
                if kind == b"A":
                    await self.session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
                elif kind in (b"S", b"C"):
                    hub.put_frame(self.user.id, data, "camera" if kind == b"C" else "screen")
                    await self.session.send_realtime_input(video=types.Blob(data=data, mime_type="image/jpeg"))
            except Exception as e:
                log.warning("[Live] Senden fehlgeschlagen: %s", e)
            return

        try:
            msg = json.loads(text_data or "{}")
        except ValueError:
            return
        kind = msg.get("type")
        if kind == "start":
            if self.live_task and not self.live_task.done():
                return
            self.live_task = asyncio.create_task(self._run_live())
        elif kind == "stop":
            if self.live_task:
                self.live_task.cancel()
        elif kind == "text" and self.session:
            text = str(msg.get("text", "")).strip()
            if text:
                self.turn_addressed = True
                await self._send_text(text)

    async def _send_text(self, text: str):
        from google.genai import types
        try:
            await self.session.send_realtime_input(text=text)
        except Exception:
            await self.session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=True)

    # Gemini-Live-Sitzung
    def _setup(self, loop):
        from .config_store import gemini_key
        from .engine import build_system_instruction, recent_history
        from .models import Profile
        from .tools import ToolContext, declarations_for

        close_old_connections()
        self.ctx = ToolContext.for_user(
            self.user, channel="voice", client_id=self.client_id,
            on_shutdown=lambda: loop.call_soon_threadsafe(self._cancel_live))
        self.wake_mode = Profile.objects.get(user=self.user).wake_word_mode
        system = build_system_instruction(self.ctx, "voice")
        history = recent_history(self.user.id, 12)
        if history:
            system += "\n\n[LETZTER GESPRÄCHSVERLAUF]\n" + "\n".join(
                f"{'Nutzer' if m.role == 'user' else 'JARVIS'}: {m.text[:300]}" for m in history)
        return gemini_key(), system, declarations_for(self.ctx.full_access)

    def _cancel_live(self):
        if self.live_task:
            self.live_task.cancel()

    def _build_config(self, system, decls):
        from google.genai import types
        cfg = dict(
            response_modalities=[types.Modality.AUDIO],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=system,
            tools=[{"function_declarations": decls}],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.JARVIS_VOICE))),
        )
        try:
            cfg["context_window_compression"] = types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow())
        except Exception:
            pass
        return types.LiveConnectConfig(**cfg)

    async def _run_live(self):
        from google import genai

        try:
            key, system, decls = await database_sync_to_async(self._setup)(asyncio.get_running_loop())
            if not key:
                await self._json(type="error", message="Kein Gemini-API-Key konfiguriert.")
                return
            client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
            await self._json(type="state", state="CONNECTING")
            async with client.aio.live.connect(model=settings.JARVIS_LIVE_MODEL,
                                               config=self._build_config(system, decls)) as session:
                self.session = session
                await self._json(type="state", state="LISTENING", wake_mode=self.wake_mode)
                await self._receive_loop()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("[Live] Sitzung beendet: %s", e)
            traceback.print_exc()
            await self._json(type="error", message=f"Sprachsitzung beendet: {e}")
        finally:
            self.session = None
            if not self.closing:
                await self._json(type="state", state="OFF")

    def _is_addressed(self) -> bool:
        if not self.wake_mode:
            return True
        return self.turn_addressed or time.time() < self.addressed_until

    async def _receive_loop(self):
        while True:
            async for resp in self.session.receive():
                if resp.data and self._is_addressed():
                    await self.send(bytes_data=resp.data)

                sc = resp.server_content
                if sc:
                    if sc.input_transcription and sc.input_transcription.text:
                        txt = sc.input_transcription.text
                        if any(w in txt.lower() for w in WAKE_WORDS):
                            self.turn_addressed = True
                        self.in_buf.append(txt)
                        if self._is_addressed():
                            await self._json(type="transcript", role="user", text=txt)
                    if sc.output_transcription and sc.output_transcription.text:
                        self.out_buf.append(sc.output_transcription.text)
                        if self._is_addressed():
                            await self._json(type="transcript", role="model", text=sc.output_transcription.text)
                    if sc.interrupted:
                        await self._json(type="interrupted")
                    if sc.turn_complete:
                        await self._finish_turn()

                if resp.tool_call:
                    await self._handle_tools(resp.tool_call.function_calls or [])

    async def _finish_turn(self):
        addressed = self._is_addressed()
        full_in = "".join(self.in_buf).strip()
        full_out = "".join(self.out_buf).strip()
        self.in_buf, self.out_buf = [], []
        await self._json(type="turn_complete", addressed=addressed)
        if addressed and (full_in or full_out):
            await database_sync_to_async(self._save_turn)(full_in, full_out)
            self.addressed_until = time.time() + CONVO_WINDOW
        self.turn_addressed = False

    def _save_turn(self, full_in, full_out):
        from .engine import remember_async
        from .models import ChatMessage
        close_old_connections()
        if full_in:
            ChatMessage.objects.create(user=self.user, role="user", text=full_in, source="voice")
        if full_out:
            ChatMessage.objects.create(user=self.user, role="model", text=full_out, source="voice")
        if self.ctx.full_access and full_in:
            remember_async(full_in, full_out)

    async def _handle_tools(self, calls):
        from google.genai import types
        from .tools import run_tool

        await self._json(type="state", state="THINKING")
        addressed = self._is_addressed()
        responses, seen = [], set()
        for fc in calls:
            args = dict(fc.args or {})
            key = (fc.name, json.dumps(args, sort_keys=True, default=str))
            if key in seen:
                continue
            seen.add(key)
            if not addressed:
                result = "ignored: user did not address Jarvis"
            else:
                result = await asyncio.to_thread(self._run_tool_sync, run_tool, fc.name, args)
            responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response={"result": result}))
        try:
            await self.session.send_tool_response(function_responses=responses)
        except Exception as e:
            log.warning("[Live] send_tool_response: %s", e)
        await self._json(type="state", state="LISTENING")

    def _run_tool_sync(self, run_tool, name, args):
        try:
            return run_tool(name, args, self.ctx)
        finally:
            close_old_connections()
