"""Text-Chat mit Gemini inkl. Tool-Schleife + gemeinsamer System-Prompt für Text und Sprache."""
from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime

from django.conf import settings
from django.db import close_old_connections

from .config_store import gemini_key, load_settings
from .hub import hub
from .models import ChatMessage
from .tools import ToolContext, declarations_for, run_tool

log = logging.getLogger("jarvis.engine")

GENERIC_PROMPT = (
    "Du bist JARVIS, ein KI-Assistent von Joel Digitals. Antworte auf Deutsch, präzise, freundlich und knapp. "
    "Verwende immer die bereitgestellten Werkzeuge. Simuliere oder rate niemals Ergebnisse."
)
HISTORY_LIMIT = 30
MAX_TOOL_ROUNDS = 12

_user_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _user_lock(user_id: int) -> threading.Lock:
    with _locks_guard:
        return _user_locks.setdefault(user_id, threading.Lock())


def _load_prompt() -> str:
    try:
        return (settings.BASE_DIR / "core" / "prompt.txt").read_text(encoding="utf-8")
    except OSError:
        return GENERIC_PROMPT


def build_system_instruction(ctx: ToolContext, mode: str = "text") -> str:
    now = datetime.now().strftime("%A, %d.%m.%Y — %H:%M Uhr")
    parts = [f"[AKTUELLES DATUM & UHRZEIT]\nJetzt ist: {now} (Europe/Berlin)\n"]

    if ctx.full_access:
        user_name = load_settings().get("user_name") or ctx.username
        parts.append(f"[NUTZER]\nDer Nutzer heißt: {user_name}\nSprich ihn IMMER mit diesem Namen an.\n")
        try:
            from memory.memory_manager import format_memory_for_prompt, load_memory
            mem = format_memory_for_prompt(load_memory())
            if mem:
                parts.append(mem)
        except Exception as e:
            log.warning("Gedächtnis nicht geladen: %s", e)
        parts.append(_load_prompt().replace("{user_name}", user_name))
    else:
        parts.append(f"[NUTZER]\nDer Nutzer heißt: {ctx.username}\n")
        parts.append(GENERIC_PROMPT)

    agent = hub.agent(ctx.user_id) if ctx.full_access else None
    env = ["\n[UMGEBUNG]",
           "Du läufst als Web-App. Der Nutzer spricht mit dir über den Browser"
           + (" per Sprache." if mode == "voice" else " per Text-Chat.")]
    if agent:
        env.append(f"Desktop-Agent VERBUNDEN ({agent.host}, {agent.platform}): PC-Steuerung (Apps, Lautstärke, "
                   "Dateien, Tastatur, Browser-Automation) ist verfügbar.")
    elif ctx.full_access:
        env.append("Desktop-Agent NICHT verbunden: PC-Steuerung ist nicht möglich. Apps mit Web-Version öffnest du "
                   "im Browser. Sag dem Nutzer, dass er für PC-Steuerung den Desktop-Agent starten kann.")
    env.append("Browser-Funktionen: URLs öffnen, Musik/Radio abspielen, Wecker und Erinnerungen als Benachrichtigung. "
               "Bildschirm/Kamera siehst du nur, wenn der Nutzer sie im Web-Interface freigibt (screen_process).")
    if ctx.current_file:
        env.append(f"Aktuell hochgeladene Datei: {ctx.current_file} (für file_processor file_path leer lassen).")
    if mode == "text":
        env.append("Antworten werden als Text angezeigt; kurzes Markdown (fett, Listen) ist erlaubt.")
    parts.append("\n".join(env))
    return "\n".join(parts)


def recent_history(user_id: int, limit: int = HISTORY_LIMIT) -> list[ChatMessage]:
    msgs = list(ChatMessage.objects.filter(user_id=user_id).order_by("-created_at", "-id")[:limit])
    msgs.reverse()
    return msgs


def _client():
    from google import genai
    key = gemini_key()
    if not key:
        raise RuntimeError("Kein Gemini-API-Key konfiguriert. Bitte in den Einstellungen eintragen.")
    return genai.Client(api_key=key)


def _generate(client, contents, config):
    for attempt in range(4):
        try:
            return client.models.generate_content(model=settings.JARVIS_TEXT_MODEL, contents=contents, config=config)
        except Exception as e:
            msg = str(e)
            transient = "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg
            if attempt < 3 and transient:
                wait = min(2 ** attempt * 3 + random.uniform(0, 2), 30)
                log.warning("Gemini überlastet, neuer Versuch in %.0fs", wait)
                time.sleep(wait)
                continue
            raise


def chat(user, text: str, channel: str = "text", client_id: str | None = None) -> dict:
    """Beantwortet eine Nachricht. Rückgabe: {"response": str, "tools": [...]}."""
    from google.genai import types

    ctx = ToolContext.for_user(user, channel=channel, client_id=client_id)
    with _user_lock(user.id):
        history = recent_history(user.id)
        ChatMessage.objects.create(user_id=user.id, role="user", text=text, source=channel)
        hub.send_to_user(user.id, {"type": "state", "state": "THINKING"})

        contents = [types.Content(role=m.role, parts=[types.Part(text=m.text)]) for m in history if m.text]
        contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
        config = types.GenerateContentConfig(
            system_instruction=build_system_instruction(ctx, "text"),
            tools=[types.Tool(function_declarations=declarations_for(ctx.full_access))],
            temperature=0.7,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        used_tools: list[dict] = []
        answer = ""
        try:
            client = _client()
            for _ in range(MAX_TOOL_ROUNDS):
                resp = _generate(client, contents, config)
                cand = resp.candidates[0] if resp.candidates else None
                if cand is None or cand.content is None:
                    break
                contents.append(cand.content)
                calls = [p.function_call for p in (cand.content.parts or []) if p.function_call]
                texts = [p.text for p in (cand.content.parts or []) if p.text and not getattr(p, "thought", False)]
                if texts:
                    answer = "".join(texts).strip()
                if not calls:
                    break
                responses = []
                for fc in calls:
                    args = dict(fc.args or {})
                    result = run_tool(fc.name, args, ctx)
                    used_tools.append({"name": fc.name, "args": args, "result": result[:300]})
                    responses.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
                contents.append(types.Content(role="user", parts=responses))
            if not answer:
                answer = "Erledigt." if used_tools else "Dazu habe ich gerade keine Antwort."
        except Exception as e:
            log.exception("Chat-Fehler")
            answer = f"Fehler: {e}"
        finally:
            hub.send_to_user(user.id, {"type": "state", "state": "LISTENING"})

        ChatMessage.objects.create(user_id=user.id, role="model", text=answer, source=channel, tools=used_tools)

    if ctx.full_access:
        remember_async(text, answer)
    return {"response": answer, "tools": used_tools}


_last_memory_input = ""


def remember_async(user_text: str, jarvis_text: str):
    """Extrahiert wie der Desktop-JARVIS langfristige Fakten aus dem Gespräch."""
    global _last_memory_input
    user_text, jarvis_text = (user_text or "").strip(), (jarvis_text or "").strip()
    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    def _run():
        try:
            from memory.memory_manager import extract_memory, should_extract_memory, update_memory
            key = gemini_key()
            if key and should_extract_memory(user_text, jarvis_text, key):
                data = extract_memory(user_text, jarvis_text, key)
                if data:
                    update_memory(data)
                    from . import state_sync
                    state_sync.snapshot()
        except Exception as e:
            if "429" not in str(e):
                log.warning("Memory-Extraktion: %s", e)
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True, name="memory").start()
