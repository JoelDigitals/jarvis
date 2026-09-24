import asyncio
import gc
import math
import threading
import json
import os
import sys
import time
import traceback
from collections import deque
from pathlib import Path

import numpy as np

import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)

from actions.autoupdater import check_for_update, _read_current_version
from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.reminder          import reminder
from actions.web_search        import web_search as web_search_action
from concurrent.futures import ThreadPoolExecutor
_MEMORY_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mem")


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-3.1-flash-live-preview"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000  # Gemini braucht 16kHz für Audio-Input
RECEIVE_SAMPLE_RATE = 24000  # Wiedergabe bleibt gut
CHUNK_SIZE          = 16384   # große Blöcke = minimale CPU-Interrupts
AUDIO_BUF_MAX       = 300     # max Audio-Chunks im Puffer (ältere werden verworfen)


class _AudioBuffer:
    """Async-fähiger Ringpuffer: verwirft älteste Chunks bei Überlauf."""
    def __init__(self, maxlen: int = AUDIO_BUF_MAX):
        self._dq = deque(maxlen=maxlen)
        self._ev = asyncio.Event()
        self._interrupted = False

    def put(self, item: bytes):
        self._dq.append(item)
        self._ev.set()

    def interrupt(self):
        self._interrupted = True
        self._dq.clear()
        self._ev.set()

    def clear(self):
        self._dq.clear()

    def qsize(self) -> int:
        return len(self._dq)

    async def get(self) -> bytes:
        while not self._dq:
            if self._interrupted:
                self._interrupted = False
                raise asyncio.CancelledError()
            self._ev.clear()
            await self._ev.wait()
        return self._dq.popleft()


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "Du bist JARVIS, Tony Starks KI-Assistent. "
            "Sei präzise und direkt. Antworte auf Deutsch."
            "Verwende immer die bereitgestellten Werkzeuge. "
            "Simuliere oder rate niemals Ergebnisse."
        )
    
_last_memory_input = ""

def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    global _last_memory_input

    user_text   = (user_text   or "").strip()
    jarvis_text = (jarvis_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, jarvis_text, api_key):
            return
        data = extract_memory(user_text, jarvis_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ {list(data.keys())}")
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")

from jarvis_core.tool_declarations import TOOL_DECLARATIONS

try:
    from actions.plugin_loader import get_plugin_tool_declarations
    TOOL_DECLARATIONS += get_plugin_tool_declarations()
except Exception as _e:
    print(f"[PLUGIN] ⚠️ Plugins konnten nicht geladen werden: {_e}")

class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._response_queues: list[asyncio.Queue[str]] = []
        self._history: list[dict] = []
        self._discord = None
        self.ui.on_text_command = self._on_text_command
        self._wake_buffer = deque(maxlen=48)
        self._wake_running = False
        self._autopilot_active = False
        self._mic_hold_until = 0.0  # Timestamp bis wann Mic-Input ignoriert wird (Echo-Schutz)
        self._last_wake_trigger = 0.0  # Cooldown für Google-STT-Wake
        self._quiet_hours_start = 22  # 22:00
        self._quiet_hours_end   = 7   # 07:00
        self._night_voice_until = 0.0  # Timestamp bis wann Audio nachts erlaubt ist (0 = blockiert)
        self._night_logged = False      # Ob Nachtmodus-Log bereits geschrieben wurde
        self._session_active = False       # Ob aktuelle Session noch lebt
        self._user_has_spoken = False    # Ob Nutzer in aktueller Session schon Input gesendet hat
        self._suppress_response = False
        # ── Ansprache-Gate: verhindert Reagieren auf nicht an JARVIS gerichtete Sprache ──
        self._WAKE_WORDS = ("jarvis", "javis")
        self._CONVO_WINDOW = 25.0  # Sekunden, in denen Folgesätze ohne erneutes "Jarvis" zählen
        self._turn_addressed = False   # Wake-Word in aktuellem Turn erkannt
        self._addressed_until = 0.0    # Aktives Gesprächsfenster läuft bis hier
        self._initialized = False        # Ob Setup (Timer etc.) bereits einmal ausgeführt wurde
        self.ui.on_mic_unmute = self._flush_wake_buffer

    def _start_wake_listener(self):
        import concurrent.futures
        self._wake_buffer.clear()
        self._wake_running = True
        def _listen():
            try:
                import speech_recognition as sr
                r = sr.Recognizer()
                pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                while self._wake_running and self._is_speaking:
                    time.sleep(0.2)
                    now = time.time()
                    if not self._wake_buffer or now - self._last_wake_trigger < 3.0:
                        continue
                    # Nur das letzte ~0.5s-Chunk (Nutzer sagt "JARVIS", nicht Echo)
                    chunk = self._wake_buffer[-1] if self._wake_buffer else b""
                    if len(chunk) < 8000:  # ~0.5s
                        continue
                    try:
                        audio = sr.AudioData(chunk, SEND_SAMPLE_RATE, 2)
                        fut = pool.submit(r.recognize_google, audio, language="de-DE", show_all=False)
                        txt = fut.result(timeout=5).lower()
                        if "jarvis" in txt or "javis" in txt:
                            print("[JARVIS] ⚡ Wake word via Google STT")
                            self._last_wake_trigger = now
                            self.audio_buf.interrupt()
                            self.set_speaking(False)
                    except concurrent.futures.TimeoutError:
                        pass
                    except (LookupError, sr.UnknownValueError, sr.RequestError):
                        pass
                pool.shutdown(wait=False)
            except ImportError:
                pass
        t = threading.Thread(target=_listen, daemon=True)
        t.start()

    def _stop_wake_listener(self):
        self._wake_running = False

    def _build_context(self) -> str:
        recent = self._history[-10:]
        lines = ["Letzter Gesprächsverlauf (weiter machen wo wir aufgehört haben):"]
        for h in recent:
            role = "Du" if h["role"] == "user" else "Jarvis"
            lines.append(f"{role}: {h['text']}")
        lines.append("---")
        return "\n".join(lines)

    def _flush_wake_buffer(self):
        """Flushed Wake-Buffer nach Mic-Unmute → sendet Nutzersprache an Gemini."""
        buf = self._wake_buffer
        if not buf or not self._loop or not hasattr(self, "out_queue") or self.out_queue is None:
            return
        try:
            raw = b"".join(buf)
        except Exception:
            return
        buf.clear()
        if len(raw) < SEND_SAMPLE_RATE * 2:  # <2s → zu kurz
            return
        # Nur letzten ~2s (Nutzer hat während Ende des Sprechens gesprochen, nicht Echo vom Anfang)
        chunk = raw[-SEND_SAMPLE_RATE * 2:]
        try:
            self._loop.call_soon_threadsafe(
                self.out_queue.put_nowait,
                {"data": chunk, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"}
            )
        except (RuntimeError, AttributeError):
            pass

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        self._user_has_spoken = True
        try:
            asyncio.run_coroutine_threadsafe(
                self.session.send_client_content(
                    turns=types.ContentDict(role="user", parts=[types.PartDict(text=text)]),
                    turn_complete=True
                ),
                self._loop
            )
        except RuntimeError:
            pass

    def _forward_response(self, text: str):
        for q in self._response_queues:
            q.put_nowait(text)

    async def process_text(self, text: str) -> str | None:
        if not self.session or not self._loop:
            return None
        q: asyncio.Queue[str] = asyncio.Queue()
        self._response_queues.append(q)
        try:
            await self.session.send_client_content(
                turns=types.ContentDict(role="user", parts=[types.PartDict(text=text)]),
                turn_complete=True
            )
            try:
                return await asyncio.wait_for(q.get(), timeout=30)
            except asyncio.TimeoutError:
                return None
        finally:
            if q in self._response_queues:
                self._response_queues.remove(q)

    def _is_addressed(self) -> bool:
        """True, wenn im aktuellen Turn das Wake-Word fiel oder wir uns in einem aktiven Gesprächsfenster befinden."""
        return self._turn_addressed or time.time() < self._addressed_until

    def _is_quiet_hours(self) -> bool:
        from datetime import datetime
        h = datetime.now().hour
        if self._quiet_hours_start > self._quiet_hours_end:
            return h >= self._quiet_hours_start or h < self._quiet_hours_end
        return self._quiet_hours_start <= h < self._quiet_hours_end

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        try:
            if value:
                self._safe_set_state("SPEAKING")
                self._start_wake_listener()
            else:
                self._stop_wake_listener()
                self._mic_hold_until = time.time() + 3.0
                self._safe_set_state("LISTENING")
        except RuntimeError:
            pass

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        # Proaktive Ansage von JARVIS selbst — umgeht das Ansprache-Gate (kein Wake-Word nötig).
        self._turn_addressed = True
        self._addressed_until = time.time() + self._CONVO_WINDOW
        try:
            asyncio.run_coroutine_threadsafe(
                self.session.send_client_content(
                    turns=types.ContentDict(role="user", parts=[types.PartDict(text=text)]),
                    turn_complete=True
                ),
                self._loop
            )
        except RuntimeError:
            pass

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")

        from config.settings import load as load_settings
        settings = load_settings()
        user_name = settings.get("user_name", "Sir")

        parts = [
            f"[CURRENT DATE & TIME]\nRight now it is: {time_str}\n",
            f"[USER]\nDer Nutzer heißt: {user_name}\nSprich ihn IMMER mit diesem Namen an.\n\n",
        ]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    def _safe_set_state(self, state: str):
        try:
            self.ui.set_state(state)
        except Exception:
            pass

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")
        self._safe_set_state("THINKING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self._safe_set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        if name == "knowledge_base":
            from actions.knowledge_base import kb_action
            r = kb_action(args, player=self.ui)
            if not self.ui.muted:
                self._safe_set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": r}
            )

        if name == "set_autopilot":
            active = args.get("active", False)
            summary = self._set_autopilot(active)
            if not self.ui.muted:
                self._safe_set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": summary if not active else "Autopilot aktiviert"}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                from actions.open_app import open_app
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                from actions.weather_report import weather_action
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                from actions.browser_control import browser_control
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                from actions.file_controller import file_controller
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                from actions.send_message import send_message
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                from actions.reminder import reminder
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                from actions.youtube_video import youtube_video
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "file_processor":
                from actions.file_processor import file_processor
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "screen_process":
                from actions.screen_processor import screen_process
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = "Vision module activated. Stay completely silent — vision module will speak directly."

            elif name == "computer_settings":
                from actions.computer_settings import computer_settings
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                from actions.desktop import desktop_control
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                from actions.code_helper import code_helper
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                from actions.dev_agent import dev_agent
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "web_search":
                from actions.web_search import web_search as web_search_action
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "computer_control":
                from actions.computer_control import computer_control
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                from actions.game_updater import game_updater
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                from actions.flight_finder import flight_finder
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "email_manager":
                from actions.email_manager import email_action
                r = await loop.run_in_executor(None, lambda: email_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "web_summarize":
                from actions.web_summarizer import web_summarize
                r = await loop.run_in_executor(None, lambda: web_summarize(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "jds_connect":
                from actions.jds_client import jds_connect
                print(f"[JDS] Args: {json.dumps({k: str(v) for k,v in args.items()})[:200]}")
                r = await loop.run_in_executor(None, lambda: jds_connect(parameters=args, player=self.ui))
                result = r or "Done."
                print(f"[JDS] Result: {str(result)[:100]}")

            elif name == "tankpreise":
                from actions.tankpreise import tankpreise
                r = await loop.run_in_executor(None, lambda: tankpreise(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "maps_api":
                from actions.maps_api import maps_api
                r = await loop.run_in_executor(None, lambda: maps_api(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "db_action":
                from actions.db_client import db_action
                r = await loop.run_in_executor(None, lambda: db_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "knowledge_sites":
                from actions.knowledge_sites import knowledge_action
                r = await loop.run_in_executor(None, lambda: knowledge_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "admin_api":
                from actions.admin_api import admin_action
                r = await loop.run_in_executor(None, lambda: admin_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "wecker":
                from actions.wecker import wecker
                r = await loop.run_in_executor(None, lambda: wecker(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "do_briefing":
                now = time.time()
                if now - getattr(self, '_last_briefing', 0) < 15.0:
                    result = "Bereits durchgeführt. Lies den vorherigen Text vor."
                else:
                    self._last_briefing = now
                    from actions.briefing_action import do_briefing
                    r = await loop.run_in_executor(None, lambda: do_briefing(parameters=args, player=self.ui))
                    result = (r or "").strip()

            elif name == "morning_routine":
                from actions.briefing_action import do_briefing
                r = await loop.run_in_executor(None, lambda: do_briefing({"greeting": "Guten Morgen"}, player=self.ui))
                result = r or "Morgen-Briefing abgeschlossen."

            elif name == "play_music":
                from actions.wake_manager import open_spotify
                url = args.get("url", "")
                r = await loop.run_in_executor(None, lambda: open_spotify(url) if url else open_spotify())
                result = "Musik gestartet." if r else "Konnte Musik nicht starten."

            elif name == "focus_app":
                app = args.get("app", "").strip().lower()
                if app in ("cursor", "code", "vscode"):
                    from actions.wake_manager import focus_cursor
                    r = await loop.run_in_executor(None, focus_cursor)
                    result = "Cursor fokussiert." if r else "Cursor gestartet."
                elif app == "chrome":
                    from actions.wake_manager import _chrome_exe
                    exe = await loop.run_in_executor(None, _chrome_exe)
                    if exe:
                        import subprocess
                        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        result = "Chrome geöffnet."
                    else:
                        result = "Chrome nicht gefunden."
                else:
                    result = f"Unbekannte App: {app}"

            elif name == "open_chrome":
                url = args.get("url", "")
                monitor = args.get("monitor", 1)
                fullscreen = args.get("fullscreen", True)
                if url:
                    from actions.wake_manager import open_chrome_url
                    await loop.run_in_executor(None, lambda: open_chrome_url(url, monitor, fullscreen))
                    result = f"Chrome geöffnet: {url[:50]}"
                else:
                    result = "Keine URL angegeben."

            elif name == "calendar_manager":
                from actions.calendar_manager import calendar_action
                r = await loop.run_in_executor(None, lambda: calendar_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Herunterfahren angefordert.")
                self.speak("Auf Wiedersehen, Sir.")

                def _shutdown():
                    import time, sys, os
                    time.sleep(1)
                    os._exit(0)

                threading.Thread(target=_shutdown, daemon=True).start()
            elif name == "social_manager":
                from actions.social_manager import social_action
                r = await loop.run_in_executor(None, lambda: social_action(parameters=args, player=self.ui))
                result = r or "Social-Manager ausgeführt."
            elif name == "video_creator":
                from actions.video_creator import video_action
                r = await loop.run_in_executor(None, lambda: video_action(parameters=args, player=self.ui))
                result = r or "Video-Aktion ausgeführt."
            elif name == "claude_bridge":
                from actions.claude_bridge import claude_action
                r = await loop.run_in_executor(None, lambda: claude_action(parameters=args, player=self.ui))
                result = r or "Claude Code ausgeführt."
            elif name == "hermes_agent":
                from actions.hermes_agent import hermes_action
                if str(args.get("action", "")).lower() == "start":
                    def _bg():
                        res = hermes_action(parameters=dict(args, action="run"), player=self.ui)
                        self.ui.write_log(f"Hermes: {str(res)[:300]}")
                        self.speak(f"Der Hermes Agent ist fertig. {str(res)[:400]}")
                    threading.Thread(target=_bg, daemon=True).start()
                    result = "Hermes Agent arbeitet im Hintergrund. Ich melde mich, sobald er fertig ist."
                else:
                    r = await loop.run_in_executor(None, lambda: hermes_action(parameters=args, player=self.ui))
                    result = r or "Hermes Agent ausgeführt."
            elif name == "project_watch":
                from actions.project_watcher import project_watch_action
                r = await loop.run_in_executor(None, lambda: project_watch_action(parameters=args, player=self.ui))
                result = r or "Projekt-Überwachung ausgeführt."
            else:
                from actions.plugin_loader import run_plugin
                r = await loop.run_in_executor(None, lambda: run_plugin(name, args, player=self.ui))
                result = r if r is not None else f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        self._log_autopilot(f"{name}: {str(result)[:60]}")

        if not self.ui.muted:
            self._safe_set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")

        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while self._session_active:
            try:
                msg = await asyncio.wait_for(self.out_queue.get(), timeout=3.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(0.1)
                continue
            try:
                await self.session.send_realtime_input(
                    audio=types.Blob(data=msg["data"], mime_type=msg["mime_type"])
                )
            except Exception as e:
                print(f"[JARVIS] ⚠️ send_realtime fehlgeschlagen – Session beendet: {e}")
                self._session_active = False
                return

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def _safe_put(data):
            try:
                self.out_queue.put_nowait(data)
            except asyncio.QueueFull:
                pass

        try:
            from actions.wecker import is_radio_playing as _check_radio
        except Exception:
            _check_radio = lambda: False

        def callback(indata, frames, time_info, status):
            if self.ui.muted:
                return
            data = indata.tobytes()
            # Während JARVIS spricht oder in der Echo-Totzeit: Audio an Wake-Buffer
            if self._is_speaking or time.time() < self._mic_hold_until:
                self._wake_buffer.append(data)
                return
            # Während Radio läuft: Audio nur an Wake-Buffer, nicht an Gemini (verhindert Fehlauslösung durch Radiosprache)
            if _check_radio():
                self._wake_buffer.append(data)
                return
            if self._is_quiet_hours():
                self._night_voice_until = time.time() + 20.0
            rms = float(np.sqrt(np.mean(indata.astype(np.float64)**2)))
            if rms > 0.025:
                self._user_has_spoken = True
            try:
                loop.call_soon_threadsafe(_safe_put, {"data": data, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"})
            except RuntimeError:
                pass

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                while self._session_active:
                    await asyncio.sleep(1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data and isinstance(response.data, bytes) and len(response.data) > 0:
                        if self._user_has_spoken and self._is_addressed():
                            self.set_speaking(True)
                            self.audio_buf.put(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                if not self._turn_addressed and any(w in txt.lower() for w in self._WAKE_WORDS):
                                    self._turn_addressed = True
                                if self._is_speaking and ("jarvis" in txt.lower() or "javis" in txt.lower()):
                                    print("[JARVIS] ⚡ Wake word per Gemini erkannt")
                                    self.audio_buf.interrupt()
                                    self.set_speaking(False)
                                in_buf.append(txt)

                        if sc.turn_complete:
                            addressed = self._is_addressed()
                            # Warte bis letzte Audio aus dem Puffer abgespielt + Speaker-Latenz
                            while self.audio_buf.qsize() > 0:
                                await asyncio.sleep(0.05)
                            await asyncio.sleep(0.5)
                            self.set_speaking(False)

                            full_in = " ".join(in_buf).strip()
                            if full_in and addressed:
                                self.ui.write_log(f"Du: {full_in}")
                                self._history.append({"role": "user", "text": full_in})
                            elif full_in:
                                print(f"[JARVIS] 🚫 Nicht angesprochen, ignoriert: {full_in[:60]}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out and addressed:
                                self.ui.write_log(f"Jarvis: {full_out}")
                                self._forward_response(full_out)
                                self._history.append({"role": "model", "text": full_out})

                            # History begrenzen auf max 20 Einträge (10 Turns)
                            if len(self._history) > 20:
                                self._history = self._history[-20:]

                            out_buf = []

                            if full_in and len(full_in) > 5 and addressed:
                                _MEMORY_POOL.submit(_update_memory_async, full_in, full_out)

                            if addressed:
                                self._addressed_until = time.time() + self._CONVO_WINDOW
                            self._turn_addressed = False

                    if response.tool_call:
                        fn_responses = []
                        seen = set()
                        addressed = self._is_addressed()
                        for fc in response.tool_call.function_calls:
                            key = (fc.name, json.dumps(dict(fc.args or {}), sort_keys=True))
                            if key in seen:
                                continue
                            seen.add(key)
                            if not addressed:
                                print(f"[JARVIS] 🚫 Tool {fc.name} ignoriert (nicht angesprochen)")
                                fn_responses.append(types.FunctionResponse(
                                    id=fc.id, name=fc.name,
                                    response={"result": "ignored: user did not address Jarvis"}
                                ))
                                continue
                            print(f"[JARVIS] 📞 {fc.name}")
                            try:
                                fr = await self._execute_tool(fc)
                                fn_responses.append(fr)
                            except Exception as e2:
                                print(f"[JARVIS] ❌ Tool {fc.name}: {e2}")
                                traceback.print_exc()
                                fn_responses.append(types.FunctionResponse(
                                    id=fc.id, name=fc.name,
                                    response={"result": f"Fehler: {e2}"}
                                ))
                        try:
                            await self.session.send_tool_response(
                                function_responses=fn_responses
                            )
                        except Exception as e2:
                            print(f"[JARVIS] ❌ send_tool_response: {e2}")

        except asyncio.CancelledError:
            print("[JARVIS] Recv cancelled")
            return
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            self.set_speaking(False)
            self._session_active = False
            return

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")
        loop = asyncio.get_event_loop()

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(self.audio_buf.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    if not self._session_active:
                        return
                    continue
                except asyncio.CancelledError:
                    if self.audio_buf._interrupted:
                        # Wake-Word-Unterbrechung — Stream neu aufbauen
                        self.audio_buf._interrupted = False
                        self.set_speaking(False)
                        stream.stop()
                        stream.close()
                        stream = sd.RawOutputStream(
                            samplerate=RECEIVE_SAMPLE_RATE,
                            channels=CHANNELS,
                            dtype="int16",
                            blocksize=CHUNK_SIZE,
                        )
                        stream.start()
                        continue
                    else:
                        # TaskGroup-Shutdown — sauber beenden
                        raise
                if not self._is_speaking:
                    self.set_speaking(True)
                if self._is_quiet_hours():
                    if time.time() > self._night_voice_until:
                        if not self._night_logged:
                            self.ui.write_log("[🌙] Nachtmodus aktiv – Audio stumm (sprich um Antwort zu hören)")
                            self._night_logged = True
                        continue
                    elif self._night_logged:
                        self._night_logged = False
                    # Deadline während laufender Antwort verlängern
                    self._night_voice_until = time.time() + 5.0
                await asyncio.to_thread(stream.write, chunk)
                if not self._session_active:
                    return
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            return
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    def _check_autoupdate(self):
        try:
            from config.settings import load as load_cfg
            cfg = load_cfg()
            server_url = os.environ.get("SERVER_URL") or cfg.get("server_url", "")
            if not server_url:
                server_url = "https://jarvis-joel.onrender.com"
            app_slug = cfg.get("autoupdate_app_slug", "jarvis")
            result = check_for_update(server_url, app_slug, timeout=3)
            if result.get("error"):
                print(f"[AUTOUPDATE] ⚠️ {result['error']}")
                return
            if result.get("update_available"):
                ver = result["latest_version"]
                link = result["download_link"]
                notes = result.get("release_notes", "")
                self.ui.write_log(f"SYS: Update {ver} gefunden, installiere automatisch...")
                self.ui.write_result(
                    "UPDATE WIRD INSTALLIERT",
                    f'Version <b>{ver}</b> wird automatisch installiert.'
                    + (f'<br><small>{notes[:200]}</small>' if notes else '')
                )
                from actions.autoupdater import apply_update
                status = apply_update(link, ver)
                self.ui.write_log(f"SYS: {status}")
                if "wird installiert" in status:
                    self.ui.show_update_available(ver, link)
                    os._exit(0)
                else:
                    # Quellcode-Betrieb: kein automatischer Ersatz möglich, nur anzeigen
                    self.ui.show_update_available(ver, link)
            else:
                print(f"[AUTOUPDATE] ✓ Kein Update nötig (aktuell: {_read_current_version()})")
        except Exception as e:
            print(f"[AUTOUPDATE] ⚠️ {e}")
        finally:
            threading.Timer(4 * 3600.0, self._check_autoupdate).start()

    def _setup_hourly_reminder(self):
        try:
            now = __import__("datetime").datetime.now()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + __import__("datetime").timedelta(hours=1)
            delay = (next_hour - now).total_seconds()

            def _tick():
                if not self.ui.muted and not self._is_quiet_hours():
                    self.speak("Sir, es ist Zeit etwas zu trinken! Bleiben Sie hydriert.")
                    self.ui.write_log("SYS: Trink-Erinnerung 🔔")
                threading.Timer(3600.0, _tick).start()

            threading.Timer(delay, _tick).start()
            print(f"[JARVIS] 💧 Trink-Erinnerung aktiv — erste in {delay:.0f}s")
            self.ui.write_log("SYS: Stündliche Trink-Erinnerung aktiviert.")
        except Exception as e:
            print(f"[Reminder] ⚠️ {e}")

    def _setup_daily_report(self):
        try:
            import datetime
            from config.settings import load as load_cfg
            from actions.email_manager import email_action
            from actions.briefing_action import do_briefing

            cfg = load_cfg().get("daily_report", {})
            if not cfg.get("enabled") or not cfg.get("recipient_email"):
                print("[DAILY REPORT] Deaktiviert oder keine Empfänger-Adresse")
                return

            recipient = cfg["recipient_email"]
            times = cfg.get("times", ["08:00", "13:00", "18:00", "23:00"])
            inc_dash = cfg.get("include_dashboard", True)
            inc_wthr = cfg.get("include_weather", True)
            inc_eml = cfg.get("include_emails", True)

            def _send_report():
                try:
                    print(f"[DAILY REPORT] Erstelle Bericht...")
                    parts = []
                    if inc_dash:
                        r = do_briefing({"action": "briefing"}, player=self.ui)
                        parts.append(r)
                    if inc_wthr:
                        from actions.weather_report import weather_action
                        r = weather_action({"parameters": {}}, player=self.ui)
                        parts.append(r)
                    if inc_eml:
                        r = email_action({"action": "list", "count": 3, "unread_only": False}, player=self.ui)
                        parts.append(r)

                    body = "\n\n---\n\n".join(parts)
                    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
                    result = email_action({
                        "action": "send",
                        "to": recipient,
                        "subject": f"JARVIS Tagesbericht — {now_str}",
                        "body": body,
                    }, player=self.ui)
                    print(f"[DAILY REPORT] {result}")
                    self.ui.write_log(f"SYS: Tagesbericht gesendet an {recipient}")
                except Exception as e:
                    print(f"[DAILY REPORT] Fehler: {e}")

            now = datetime.datetime.now()
            for t_str in times:
                try:
                    h, m = t_str.strip().split(":")
                    t = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                    if t <= now:
                        t += datetime.timedelta(days=1)
                    delay = (t - now).total_seconds()
                    threading.Timer(delay, _send_report).start()
                    print(f"[DAILY REPORT] ⏰ Nächster Bericht um {t_str} — in {delay:.0f}s")
                except Exception as e:
                    print(f"[DAILY REPORT] ⚠️ Ungültige Zeit '{t_str}': {e}")

            self.ui.write_log(f"SYS: Täglicher Bericht aktiv — {len(times)} Zeitpunkte")
        except Exception as e:
            print(f"[DAILY REPORT] ⚠️ {e}")

    def _setup_email_scanner(self):
        try:
            from actions.email_manager import email_action
            from config.settings import load as load_cfg
            self._email_scan_count = 0
            self._email_scan_log = []
            self._email_scan_replied = set()
            self._email_scan_gen = getattr(self, "_email_scan_gen", 0) + 1
            _my_gen = self._email_scan_gen

            cfg = load_cfg()
            self._email_forward_to = cfg.get("email_forward_to", "") or cfg.get("daily_report", {}).get("recipient_email", "")

            def _scan():
                if self._email_scan_gen != _my_gen:
                    return
                try:
                    r = email_action({"action": "list", "count": 5, "unread_only": True}, player=self.ui)
                    self._email_scan_count += 1
                    if r and "Keine" not in r and "Fehler" not in r:
                        self._email_scan_log.append(f"[{time.strftime('%H:%M')}] Neue E-Mails")
                        print(f"[EMAIL-SCAN] Neue E-Mails erkannt")
                        _forward_unread(email_action)
                except:
                    pass
                threading.Timer(900.0, _scan).start()

            def _is_important(sender: str, subject: str, body: str) -> bool:
                """Nur wichtige E-Mails weiterleiten (keine Newsletter/Spam)."""
                sender_lower = sender.lower()
                subject_lower = subject.lower()
                body_lower = body.lower()[:1000]

                # Newsletter/Marketing erkennen
                newsletter_signals = [
                    "unsubscribe", "abbestellen", "newsletter", "werbung",
                    "marketing", "no-reply", "noreply", "mailjet", "sendgrid",
                    "mailchimp", "constant contact", "kampagne",
                ]
                for s in newsletter_signals:
                    if s in sender_lower or s in subject_lower:
                        return False
                    if s in body_lower:
                        return False

                # Wichtige Keywords in Betreff
                important_keywords = [
                    "auftrag", "bestellung", "rechnung", "angebot",
                    "problem", "hilfe", "dringend", "support",
                    "beschwerde", "widerruf", "kündigung",
                    "stornierung", "reklamation", "frage", "anfrage",
                    "defekt", "schaden", "fehler", "kaputt",
                    "termin", "vereinbarung", "rückruf",
                    "bezahlung", "zahlung", "überweisung",
                    "account", "zugang", "passwort", "login",
                ]
                for kw in important_keywords:
                    if kw in subject_lower:
                        return True

                # Bekannte Kunden-Domains oder Namen (optional: aus knowledge_base)
                # Im Zweifel: wichtig, wenn es kein Newsletter ist
                return True

            def _forward_unread(ea):
                if not self._email_forward_to:
                    return
                is_auto = bool(getattr(self, "_autopilot_active", False))
                for idx in range(1, 4):
                    try:
                        raw = ea({"action": "read", "index": idx, "unread_only": True}, player=self.ui)
                        if not raw or "Keine" in raw or "Fehler" in raw:
                            continue
                        sender = ""
                        subject = ""
                        for line in raw.split("\n"):
                            if line.startswith("Von:"):
                                sender = line[4:].strip()
                            elif line.startswith("Betreff:"):
                                subject = line[8:].strip()
                        if not sender:
                            continue
                        uid = f"{sender}|{subject}"
                        if uid in self._email_scan_replied:
                            continue
                        self._email_scan_replied.add(uid)

                        if not is_auto and not _is_important(sender, subject, raw):
                            print(f"[EMAIL-SCAN] ⏭ Unwichtig: {subject} von {sender}")
                            continue

                        tag = "AUTOPILOT" if is_auto else "Autopilot"
                        fwd_body = (
                            f"--- WEITERGELEITETE KUNDENANFRAGE ({tag}) ---\n\n"
                            f"{raw}\n\n"
                            f"--- Ende der Weiterleitung ---\n\n"
                            f"Diese E-Mail wurde automatisch vom JARVIS-Assistenten "
                            f"weitergeleitet."
                        )
                        ea({"action": "send", "to": self._email_forward_to,
                            "subject": f"✉ {subject} (weitergeleitet von {sender})",
                            "body": fwd_body}, player=self.ui)
                        self._log_autopilot(f"E-Mail weitergeleitet: {subject} von {sender}")
                        self.ui.write_log(f"SYS: E-Mail weitergeleitet → {self._email_forward_to}")
                        print(f"[EMAIL-SCAN] ✅ {'Autopilot' if is_auto else 'Wichtig'}: {subject} von {sender}")
                    except:
                        pass

            self._email_scan_fn = _scan
            threading.Timer(900.0, _scan).start()
            print("[EMAIL-SCAN] ✅ Scan alle 15 Minuten aktiv")
            if self._email_forward_to:
                print(f"[EMAIL-SCAN] 📬 Weiterleitung an: {self._email_forward_to}")
            self.ui.write_log("SYS: E-Mail-Scan alle 15 Minuten aktiviert")
        except Exception as e:
            print(f"[EMAIL-SCAN] ⚠️ {e}")

    def _setup_project_watcher(self):
        """Scannt überwachte Projekte alle 30 Minuten selbstständig auf Fehler und meldet Neues proaktiv."""
        try:
            from actions.project_watcher import _load as _load_watched, scan_project
            self._watch_known_issues = {}  # path -> letzte Issue-Liste, um Spam zu vermeiden
            self._project_watch_gen = getattr(self, "_project_watch_gen", 0) + 1
            _my_gen = self._project_watch_gen

            def _scan():
                if self._project_watch_gen != _my_gen:
                    return
                try:
                    data = _load_watched()
                    for p in data.get("projects", []):
                        issues = scan_project(p["path"])
                        prev = self._watch_known_issues.get(p["path"], [])
                        new_issues = [i for i in issues if i not in prev]
                        self._watch_known_issues[p["path"]] = issues
                        if new_issues and not self.ui.muted and not self._is_quiet_hours():
                            text = f"Sir, ich habe ein Problem in {p['name']} gefunden: {new_issues[0][:200]}"
                            self.speak(text)
                            self.ui.write_log(f"SYS: ⚠️ Watcher — {p['name']}: {new_issues[0][:120]}")
                            self._log_autopilot(f"Projekt-Watcher: {p['name']} — {new_issues[0][:80]}")
                except Exception as e:
                    print(f"[PROJECT-WATCH] ⚠️ {e}")
                threading.Timer(1800.0, _scan).start()

            threading.Timer(1800.0, _scan).start()
            print("[PROJECT-WATCH] ✅ Scan alle 30 Minuten aktiv")
            self.ui.write_log("SYS: Projekt-Überwachung alle 30 Minuten aktiviert.")
        except Exception as e:
            print(f"[PROJECT-WATCH] ⚠️ Setup fehlgeschlagen: {e}")

    def _set_autopilot(self, active: bool, parameters: dict = None):
        self._autopilot_active = active
        self.ui.set_autopilot(active)
        if active:
            self._autopilot_log = []
            print(f"[AUTOPILOT] ✅ Aktiviert — JARVIS hält Stellung")
            self.ui.write_log("SYS: AUTOPILOT AKTIV — JARVIS hält Stellung")
            threading.Thread(target=self._run_autopilot_start, daemon=True).start()
        else:
            summary = "\n".join(self._autopilot_log[-50:]) if hasattr(self, "_autopilot_log") else "Keine Aktionen."
            print(f"[AUTOPILOT] Deaktiviert.\n{summary}")
            self.ui.write_log(f"SYS: Autopilot beendet")
            threading.Thread(target=self._send_autopilot_summary, args=(summary,), daemon=True).start()
            return summary

    def _log_autopilot(self, action: str):
        if getattr(self, "_autopilot_active", False):
            ts = time.strftime("%H:%M")
            self._autopilot_log.append(f"[{ts}] {action}")

    def _run_autopilot_start(self):
        try:
            from actions.email_manager import email_action
            if hasattr(self, "_email_scan_fn"):
                self._email_scan_fn()
            self._log_autopilot("E-Mail-Scan durchgeführt")
        except Exception as e:
            print(f"[AUTOPILOT] ⚠️ Scan-Fehler: {e}")
        try:
            from actions.jds_client import jds_connect
            r = jds_connect({"action": "dashboard"})
            self._log_autopilot(f"JDS-Dashboard: {str(r)[:150]}")
        except Exception as e:
            print(f"[AUTOPILOT] ⚠️ JDS-Fehler: {e}")
        try:
            from actions.admin_api import admin_action
            r = admin_action({"action": "tickets"})
            self._log_autopilot(f"Support-Tickets: {str(r)[:150]}")
        except Exception as e:
            print(f"[AUTOPILOT] ⚠️ Admin-Fehler: {e}")
        self._log_autopilot("Autopilot gestartet (E-Mail deaktiviert)")

    def _send_autopilot_summary(self, summary: str):
        pass

    def _connect_jds(self):
        try:
            cfg = {}
            settings_p = get_base_dir() / "config" / "settings.json"
            if settings_p.exists():
                s = json.loads(settings_p.read_text(encoding="utf-8"))
                cfg = s.get("jds_config", {})
            if not cfg.get("base_url"):
                legacy_p = get_base_dir() / "config" / "jds_config.json"
                if legacy_p.exists():
                    cfg = json.loads(legacy_p.read_text(encoding="utf-8"))
            bu = cfg.get("base_url", "").strip()
            tc = cfg.get("team_code", "").strip()
            at = cfg.get("api_token", "").strip()
            tuid = cfg.get("task_user_id", "").strip()
            if bu and at:
                from actions.jds_client import jds_connect
                result = jds_connect({"action": "setup", "base_url": bu, "team_code": tc, "api_token": at})
                result = jds_connect({"action": "connect"})
                if tuid:
                    self._jds_task_user = tuid
                    print(f"[JDS] 🤖 JARVIS-Aufgaben-User: {tuid}")
                else:
                    self._jds_task_user = ""
                print(f"[JDS] {result}")
                self.ui.write_log(f"SYS: {result}")
            else:
                print("[JDS] Keine gültige Konfiguration gefunden.")
        except Exception as e:
            print(f"[JDS] ⚠️ {e}")
            traceback.print_exc()

    def _auto_setup_email(self):
        try:
            # first try settings.json (central config)
            cfg = {}
            settings_p = get_base_dir() / "config" / "settings.json"
            if settings_p.exists():
                s = json.loads(settings_p.read_text(encoding="utf-8"))
                accounts = s.get("email_accounts", [])
                if accounts:
                    a0 = accounts[0]
                    cfg = {"email": a0.get("email",""), "password": a0.get("password","")}
            # fallback to legacy
            if not cfg.get("email"):
                cfg_path = get_base_dir() / "config" / "email_config.json"
                if cfg_path.exists():
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if cfg.get("email") and cfg.get("password"):
                    from actions.email_manager import email_action
                    r = email_action({"action": "list", "count": 1}, player=self.ui)
                    if "fehler" in r.lower() or "auth" in r.lower():
                        print(f"[EMAIL] ⚠️ Konfiguration vorhanden, aber Verbindung fehlgeschlagen: {r}")
                    else:
                        print(f"[EMAIL] ✅ Auto-Konfiguration geladen: {cfg['email']}")
        except Exception as e:
            print(f"[EMAIL] ⚠️ {e}")

    def _start_discord(self):
        from actions.discord_bot import DiscordBridge
        self._discord = DiscordBridge(jarvis_ref=self)
        tg = asyncio.create_task(self._discord.start())
        print("[DISCORD] 🤖 Bot gestartet (sofern Token gesetzt)")

    async def _gc_loop(self):
        while self._session_active:
            for _ in range(24):
                await asyncio.sleep(5)
                if not self._session_active:
                    return
            gc.collect()
            print(f"[GC] Collect — {gc.get_stats()[0].get('collected',0)} objects freed")

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        _fail_streak = 0
        _session_start = 0.0

        # Nur initial ausführen (kein Crash-Loop durch Setup)
        if not self._initialized:
            try:
                self._setup_hourly_reminder()
                self._setup_daily_report()
                self._setup_email_scanner()
                self._setup_project_watcher()
                self._start_discord()
                from actions.wecker import schedule_all
                schedule_all()
                self._check_autoupdate()
            except Exception as ex:
                print(f"[JARVIS] ⚠️ Setup-Fehler: {ex}")
            self._initialized = True

        while True:
            try:
                # JDS und Email vor Session (Fehler crashen nicht die Session)
                try:
                    await asyncio.to_thread(self._connect_jds)
                except Exception as ex:
                    print(f"[JARVIS] ⚠️ JDS nicht erreichbar: {ex}")
                try:
                    await asyncio.to_thread(self._auto_setup_email)
                except Exception:
                    pass

                print("[JARVIS] 🔌 Connecting...")
                self._safe_set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_buf      = _AudioBuffer()
                    self.out_queue      = asyncio.Queue(maxsize=10)
                    self._user_has_spoken = False
                    self._wake_buffer.clear()
                    self._session_active = True

                    print("[JARVIS] ✅ Connected.")
                    _fail_streak = 0
                    _session_start = time.time()
                    self._safe_set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS bereit.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._gc_loop())
                    
            except Exception as e:
                print(f"[JARVIS] ⚠️ {e}")
                traceback.print_exc()

            try:
                self.set_speaking(False)
                self._safe_set_state("THINKING")
            except Exception:
                pass
            # UI-State hart zurücksetzen (auch wenn Signal nicht durchkam)
            try:
                self.ui.hud._speaking = False
                self.ui.hud.state = "LISTENING"
                self.ui.hud.update()
            except Exception:
                pass
            # Exponential backoff: 10s → 20s → 40s → 80s → max 120s
            # Wenn Session >30s lief → kein echter Crash-Loop, kurz warten
            if time.time() - _session_start > 30:
                _fail_streak = 0
            _fail_streak += 1
            wait = min(10 * (2 ** (_fail_streak - 1)), 120)
            print(f"[JARVIS] 🔄 Reconnecting in {wait}s... (Versuch {_fail_streak})")
            await asyncio.sleep(wait)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="JARVIS")
    parser.add_argument("--server", action="store_true", help="Starte als Web-Server (ohne Qt)")
    parser.add_argument("--port", type=int, default=5789, help="Web-Server Port")
    parser.add_argument("--host", default="0.0.0.0", help="Web-Server Host")
    args, _ = parser.parse_known_args()

    if args.server:
        import subprocess
        print(f"[JARVIS] 🌐 Starte Django-Web-App auf http://{args.host}:{args.port} (kein Qt)")
        base = Path(__file__).resolve().parent
        subprocess.run([sys.executable, str(base / "manage.py"), "migrate", "--noinput"], check=False)
        subprocess.run([sys.executable, "-m", "daphne", "-b", args.host, "-p", str(args.port),
                        "jarvis_web.asgi:application"], cwd=str(base))
        return

    # ── Desktop-Modus (Qt) ──
    try:
        import psutil
        p = psutil.Process()
        if hasattr(p, "nice"):
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            print("[JARVIS] ⚡ Priorität auf BELOW_NORMAL gesetzt")
    except:
        pass

    # ── Sync-URL für Web-Interface ──
    _sync_url = os.environ.get("SYNC_URL", "")
    if not _sync_url:
        try:
            _cfg = json.loads((Path(__file__).parent / "config" / "settings.json").read_text(encoding="utf-8"))
            _sync_url = _cfg.get("web_sync_url", "https://jarvis-joel.onrender.com")
        except Exception:
            _sync_url = "https://jarvis-joel.onrender.com"

    ui = JarvisUI("face.png", sync_url=_sync_url)

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()