"""Tool-Router der Web-App.

Jedes JARVIS-Tool wird dort ausgeführt, wo es sinnvoll ist:
  • Server       – Web-Suche, Wetter, E-Mail, JDS, Admin-API, Gedächtnis, Dateien, …
  • Browser      – URLs/Musik/Radio öffnen, Wecker & Erinnerungen, Bildschirm/Kamera
  • Desktop-PC   – Apps öffnen, Lautstärke, Tastatur, Dateien am PC (über den Desktop-Agent
                   oder direkt, wenn der Django-Server selbst auf dem Windows-PC läuft)
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from jarvis_core.actions_map import NullPlayer, call_action
from jarvis_core.paths import use_data_root
from jarvis_core.tool_declarations import TOOL_DECLARATIONS

from . import state_sync
from .hub import hub
from .models import Alarm, JobState, Reminder

log = logging.getLogger("jarvis.tools")

# Jeder Benutzer arbeitet auf seinen eigenen Daten (userdata/<id>/). Diese Tools würden aber auf das
# Dateisystem des SERVERS zugreifen – für Nicht-Admins laufen sie daher nur über den eigenen Desktop-Agent.
SERVER_FS_TOOLS = {"video_creator"}

# Brauchen den echten PC
DESKTOP_TOOLS = {
    "open_app", "computer_settings", "computer_control", "desktop_control", "file_controller",
    "send_message", "game_updater", "browser_control", "dev_agent", "code_helper", "agent_task",
    "project_watch", "focus_app",
}
LONG_RUNNING = {"dev_agent", "code_helper", "agent_task", "game_updater", "browser_control"}

# Läuft der Django-Server selbst auf dem Windows-PC, können PC-Tools direkt ausgeführt werden
LOCAL_DESKTOP = os.name == "nt" or os.environ.get("JARVIS_LOCAL_DESKTOP") == "1"

RADIO_STATIONS = {
    "sr1": "https://liveradio.sr.de/sr/sr1/mp3/128/stream.mp3",
    "sr1wie": "https://sr.audiostream.io/sr/1013/mp3/128/stream.mp3",
    "sr3": "https://liveradio.sr.de/sr/sr3/mp3/128/stream.mp3",
    "sr kultur": "https://liveradio.sr.de/sr/srkultur/mp3/128/stream.mp3",
    "swr1": "https://liveradio.swr.de/sw282p3/swr1bw/128.mp3",
    "swr3": "https://liveradio.swr.de/sw282p3/swr3/128.mp3",
    "1live": "https://wdr-1live-live.icecastssl.wdr.de/wdr/1live/live/mp3/128/stream.mp3",
    "wdr2": "https://wdr-wdr2-live.icecastssl.wdr.de/wdr/wdr2/live/mp3/128/stream.mp3",
    "deutschlandfunk": "https://st01.sslstream.dlf.de/dlf/01/high/aac/stream.aac",
}

WEB_APPS = {
    "whatsapp": "https://web.whatsapp.com", "spotify": "https://open.spotify.com",
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
    "google": "https://www.google.com", "chrome": "https://www.google.com",
    "browser": "https://www.google.com", "instagram": "https://www.instagram.com",
    "telegram": "https://web.telegram.org", "discord": "https://discord.com/app",
    "netflix": "https://www.netflix.com", "github": "https://github.com",
    "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "outlook": "https://outlook.live.com", "kalender": "https://calendar.google.com",
    "calendar": "https://calendar.google.com", "maps": "https://maps.google.com",
    "twitter": "https://x.com", "x": "https://x.com", "linkedin": "https://www.linkedin.com",
    "tiktok": "https://www.tiktok.com", "notion": "https://www.notion.so",
    "figma": "https://www.figma.com", "canva": "https://www.canva.com",
    "drive": "https://drive.google.com", "teams": "https://teams.microsoft.com",
    "word": "https://www.office.com/launch/word", "excel": "https://www.office.com/launch/excel",
    "powerpoint": "https://www.office.com/launch/powerpoint", "amazon": "https://www.amazon.de",
    "twitch": "https://www.twitch.tv", "facebook": "https://www.facebook.com",
}


@dataclass
class ToolContext:
    user_id: int
    username: str
    is_admin: bool
    data_root: Path
    channel: str = "text"            # text | voice | discord | system
    client_id: str | None = None     # auslösender Browser-Tab
    current_file: str = ""
    on_shutdown: object = None       # Callback der Voice-Session
    uses_main_data: bool = False
    full_access: bool = False

    @classmethod
    def for_user(cls, user, channel="text", client_id=None, on_shutdown=None) -> "ToolContext":
        from .userdata import profile_of
        profile = profile_of(user)
        return cls(
            user_id=user.id, username=user.username, is_admin=user.is_superuser,
            data_root=profile.data_root, channel=channel, client_id=client_id,
            current_file=profile.current_file, on_shutdown=on_shutdown, uses_main_data=profile.uses_main_data,
            full_access=profile.has_full_access,
        )


# ── Deklarationen ──────────────────────────────────────────────────────────

def declarations_for(ctx: "ToolContext") -> list[dict]:
    decls = list(TOOL_DECLARATIONS)
    try:
        from actions.plugin_loader import get_plugin_tool_declarations
        decls += list(get_plugin_tool_declarations())
    except Exception as e:
        log.warning("Plugins nicht geladen: %s", e)
    return decls


# ── Hilfen für Browser/Logs ────────────────────────────────────────────────

class WebPlayer(NullPlayer):
    """`player`-Ersatz: Logs der Actions landen live im Aktivitätsprotokoll des Browsers."""

    def __init__(self, ctx: ToolContext):
        super().__init__()
        self.ctx = ctx
        self.current_file = ctx.current_file or None

    def write_log(self, text: str):
        hub.send_to_user(self.ctx.user_id, {"type": "log", "text": str(text)[:500]})


def _speaker(ctx: ToolContext):
    def speak(text: str):
        hub.send_to_user(ctx.user_id, {"type": "speak", "text": str(text)}, client_id=ctx.client_id)
    return speak


def browser_command(ctx: ToolContext, command: str, **payload) -> bool:
    """Schickt einen Befehl an den Browser-Tab des Nutzers. False, wenn kein Tab offen ist."""
    if hub.client_count(ctx.user_id) == 0:
        return False
    hub.send_to_user(ctx.user_id, {"type": "command", "command": command, **payload}, client_id=ctx.client_id)
    return True


def _open_url(ctx: ToolContext, url: str, label: str = "") -> str:
    if browser_command(ctx, "open_url", url=url):
        return f"{label or url} im Browser geöffnet."
    return f"Kein Browser-Fenster offen. Link: {url}"


def _user_upload_dir(user_id: int) -> Path:
    d = Path(settings.MEDIA_ROOT) / "uploads" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Autopilot-Protokoll ────────────────────────────────────────────────────

def autopilot_active(user_id: int) -> bool:
    return bool((JobState.get(f"autopilot:{user_id}") or {}).get("active"))


def autopilot_log(user_id: int, text: str):
    key = f"autopilot:{user_id}"
    state = JobState.get(key) or {}
    if state.get("active"):
        state.setdefault("log", []).append(f"[{time.strftime('%H:%M')}] {text}")
        state["log"] = state["log"][-100:]
        JobState.put(key, state)


# ── Web-Implementierungen ──────────────────────────────────────────────────

def _tool_reminder(args, ctx):
    date_s, time_s = args.get("date"), args.get("time")
    message = (args.get("message") or "Erinnerung").strip()[:500]
    if not date_s or not time_s:
        return "Ich brauche Datum und Uhrzeit für die Erinnerung."
    try:
        naive = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "Datum oder Uhrzeit nicht verstanden (Format YYYY-MM-DD und HH:MM)."
    due = timezone.make_aware(naive, timezone.get_default_timezone())
    if due <= timezone.now():
        return "Dieser Zeitpunkt liegt in der Vergangenheit."
    Reminder.objects.create(user_id=ctx.user_id, due_at=due, message=message)
    hub.send_to_user(ctx.user_id, {"type": "refresh", "what": "reminders"})
    return f"Erinnerung gesetzt für {naive.strftime('%d.%m.%Y um %H:%M')} Uhr: {message}"


def _tool_wecker(args, ctx):
    action = str(args.get("action") or "status").strip().lower()
    if action == "set":
        t = str(args.get("time") or "").strip()
        if not re.fullmatch(r"\d{1,2}:\d{2}", t):
            return "Bitte eine Uhrzeit im Format HH:MM angeben."
        h, m = t.split(":")
        t = f"{int(h):02d}:{int(m):02d}"
        a = Alarm.objects.create(user_id=ctx.user_id, time=t, music=str(args.get("music") or "").strip())
        hub.send_to_user(ctx.user_id, {"type": "refresh", "what": "alarms"})
        return f"Wecker {a.id} auf {t} Uhr gestellt. Er klingelt im Browser (und am PC, falls der Desktop-Agent läuft)."
    if action == "list" or action == "status":
        alarms = Alarm.objects.filter(user_id=ctx.user_id)
        if not alarms:
            return "Keine Wecker gesetzt."
        return "Wecker:\n" + "\n".join(
            f"  {'✅' if a.active else '❌'} [{a.id}] {a.time}{' (' + a.music + ')' if a.music else ''}" for a in alarms)
    if action == "remove":
        n, _ = Alarm.objects.filter(user_id=ctx.user_id, id=int(args.get("id") or 0)).delete()
        hub.send_to_user(ctx.user_id, {"type": "refresh", "what": "alarms"})
        return "Wecker entfernt." if n else "Wecker nicht gefunden."
    if action == "radio":
        station = str(args.get("music") or "sr1").strip().lower()
        url = RADIO_STATIONS.get(station)
        if not url:
            return f"Unbekannter Sender. Verfügbar: {', '.join(RADIO_STATIONS)}"
        if browser_command(ctx, "play_stream", url=url, label=station.upper()):
            return f"Radio {station.upper()} läuft im Browser."
        return f"Kein Browser-Fenster offen. Stream: {url}"
    if action == "play":
        if browser_command(ctx, "alarm_tone"):
            return "Wecksignal wird im Browser abgespielt."
        return "Kein Browser-Fenster offen."
    if action == "stop":
        browser_command(ctx, "stop_audio")
        return "Musik gestoppt."
    return f"Unbekannte Wecker-Aktion: {action}"


def _tool_play_music(args, ctx):
    url = str(args.get("url") or "").strip() or "https://open.spotify.com"
    return _open_url(ctx, url, "Musik")


def _tool_open_chrome(args, ctx):
    url = str(args.get("url") or "").strip()
    if not url:
        return "Keine URL angegeben."
    if not re.match(r"^https?://", url):
        url = "https://" + url
    return _open_url(ctx, url)


def _tool_youtube(args, ctx):
    action = str(args.get("action") or "play").lower().strip()
    args = dict(args, save=False)  # "In Notepad speichern" gibt es online nicht
    if action != "play":
        return _run_server("youtube_video", args, ctx)
    query = str(args.get("query") or "").strip()
    if not query:
        return "Was möchtest du sehen?"
    url = None
    try:
        from actions.youtube_video import _scrape_first_video_url
        url = _scrape_first_video_url(query)
    except Exception as e:
        log.warning("YouTube-Scrape fehlgeschlagen: %s", e)
    url = url or f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    return _open_url(ctx, url, f"YouTube: {query}")


def _tool_morning(args, ctx):
    return _run_server("do_briefing", {"greeting": "Guten Morgen"}, ctx)


def _tool_shutdown(args, ctx):
    if callable(ctx.on_shutdown):
        ctx.on_shutdown()
    browser_command(ctx, "voice_stop")
    return "Auf Wiedersehen. Sprachmodus beendet – im Web bleibe ich für dich erreichbar."


def _tool_set_autopilot(args, ctx):
    key = f"autopilot:{ctx.user_id}"
    active = bool(args.get("active", False))
    if active:
        JobState.put(key, {"active": True, "log": [], "since": time.time()})
        threading.Thread(target=_autopilot_start, args=(ctx,), daemon=True, name="autopilot").start()
        hub.send_to_user(ctx.user_id, {"type": "autopilot", "active": True})
        return "Autopilot aktiviert. Ich halte die Stellung: E-Mails, JDS und Tickets werden überwacht."
    state = JobState.get(key) or {}
    JobState.put(key, {"active": False, "log": []})
    hub.send_to_user(ctx.user_id, {"type": "autopilot", "active": False})
    return "Autopilot deaktiviert.\n" + ("\n".join(state.get("log", [])[-50:]) or "Keine Aktionen.")


def _autopilot_start(ctx):
    try:
        with use_data_root(ctx.data_root):
            from .scheduler import email_scan_once
            email_scan_once(ctx.user_id)
            autopilot_log(ctx.user_id, "E-Mail-Scan durchgeführt")
            for name, args, label in (("jds_connect", {"action": "dashboard"}, "JDS-Dashboard"),
                                      ("admin_api", {"action": "tickets"}, "Support-Tickets")):
                try:
                    autopilot_log(ctx.user_id, f"{label}: {str(call_action(name, args))[:150]}")
                except Exception as e:
                    autopilot_log(ctx.user_id, f"{label}: Fehler {e}")
    finally:
        close_old_connections()


def _vision(jpeg: bytes, question: str) -> str:
    from google import genai
    from google.genai import types
    from .config_store import gemini_key

    key = gemini_key()
    if not key:
        return "Für die Bildanalyse fehlt ein Gemini-API-Key (Einstellungen → API-Keys)."
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=settings.JARVIS_TEXT_MODEL,
        contents=[
            types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
            "Du bist JARVIS. Analysiere das Bild präzise und antworte auf Deutsch, knapp (max. 4 Sätze). "
            f"Aufgabe: {question}",
        ],
    )
    return (resp.text or "").strip() or "Ich konnte auf dem Bild nichts erkennen."


def _tool_screen(args, ctx):
    import base64

    angle = str(args.get("angle") or "screen").lower()
    question = str(args.get("text") or "Beschreibe, was zu sehen ist.")
    frame = hub.latest_frame(ctx.user_id)
    jpeg = frame[0] if frame else None
    if jpeg is None and hub.agent(ctx.user_id):
        raw = hub.agent_call(ctx.user_id, "screen_capture", {"angle": angle}, timeout=30)
        try:
            jpeg = base64.b64decode(json.loads(raw)["jpeg_b64"])
        except Exception:
            return f"Bildaufnahme am PC fehlgeschlagen: {raw[:200]}"
    if jpeg is None and LOCAL_DESKTOP and ctx.is_admin:
        try:
            jpeg = base64.b64decode(json.loads(call_action("screen_capture", {"angle": angle}))["jpeg_b64"])
        except Exception as e:
            log.warning("Lokale Bildaufnahme fehlgeschlagen: %s", e)
    if jpeg is None:
        browser_command(ctx, "request_share", angle=angle)
        what = "die Kamera" if angle == "camera" else "den Bildschirm"
        return (f"Ich sehe gerade nichts. Bitte gib {what} im Web-Interface frei "
                f"(Button '{'Kamera' if angle == 'camera' else 'Bildschirm'}') und frag dann noch einmal.")
    return _vision(jpeg, question)


def _tool_open_app(args, ctx):
    app = str(args.get("app_name") or "").strip()
    target = _desktop_target(ctx)
    if target:
        return target("open_app", args)
    url = WEB_APPS.get(app.lower())
    if url:
        return _open_url(ctx, url, f"{app} (Web-Version)")
    return (f"'{app}' ist eine Desktop-App. Starte den Desktop-Agent auf deinem PC "
            f"(python desktop_agent.py), dann kann ich sie öffnen.")


def _tool_file_processor(args, ctx):
    args = dict(args)
    path = str(args.get("file_path") or "").strip() or ctx.current_file
    if not path:
        return "Es ist keine Datei hochgeladen. Lade zuerst eine Datei über die Büroklammer hoch."
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = _user_upload_dir(ctx.user_id) / path
    if not ctx.is_admin:
        base = _user_upload_dir(ctx.user_id).resolve()
        if base not in resolved.resolve().parents:
            return "Zugriff nur auf deine hochgeladenen Dateien möglich."
    args["file_path"] = str(resolved)
    args["save"] = args.get("save", True)
    return _run_server("file_processor", args, ctx)


def _tool_calendar(args, ctx):
    from actions.calendar_manager import TOKEN_FILE
    if TOKEN_FILE.exists() or (LOCAL_DESKTOP and ctx.is_admin):
        return _run_server("calendar_manager", args, ctx)
    if hub.agent(ctx.user_id):
        return hub.agent_call(ctx.user_id, "calendar_manager", args, timeout=120)
    return ("Google Kalender ist noch nicht autorisiert. Einmal im Desktop-JARVIS anmelden und dann mit "
            "'python desktop_agent.py --push-config' hochladen – oder google_calendar_token.pickle "
            "unter Einstellungen → Dateien hochladen.")


def _tool_claude(args, ctx):
    if str(args.get("action") or "").lower() == "project_task":
        return _run_desktop("claude_bridge", args, ctx)
    return _run_server("claude_bridge", args, ctx)


def _tool_flights(args, ctx):
    return _run_server("flight_finder", dict(args, save=False), ctx)


def _hermes_cfg(ctx) -> dict:
    from actions.hermes_agent import load_config
    from .config_store import load_settings
    own = (load_settings().get("hermes_config") or {}).get("base_url")
    cfg = load_config()
    if ctx.is_admin and not own and os.environ.get("HERMES_API_URL"):
        # Server-weite Hermes-Instanz (Umgebungsvariablen) nur für Admins
        cfg["base_url"] = os.environ["HERMES_API_URL"].rstrip("/")
        cfg["api_key"] = os.environ.get("HERMES_API_KEY", "")
        if os.environ.get("HERMES_MODEL"):
            cfg["model"] = os.environ["HERMES_MODEL"]
    return cfg


def _is_local_url(url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local")


HERMES_ERRORS = ("Hermes Agent nicht erreichbar", "Hermes Agent Fehler", "Hermes Agent: API-Key",
                 "Hermes Agent ist auf", "Hermes Agent hat nach")


def _hermes_call(ctx, cfg: dict, args: dict) -> str:
    """Ruft Hermes direkt auf – oder über den Desktop-Agent, wenn Hermes auf dem PC des Nutzers läuft."""
    from actions.hermes_agent import hermes_action
    full = dict(args, _config=cfg, _session_key=f"jarvis-user-{ctx.user_id}",
                _context=f"Auftraggeber: JARVIS im Namen von {ctx.username}. Antworte auf Deutsch mit einem "
                         "klaren Ergebnisbericht (was wurde getan, Ergebnis, ggf. Dateipfade).")
    server_can_reach = not _is_local_url(cfg["base_url"]) or (LOCAL_DESKTOP and ctx.is_admin)
    if server_can_reach:
        return hermes_action(full)
    if hub.agent(ctx.user_id):
        return hub.agent_call(ctx.user_id, "hermes_agent", full, timeout=960)
    return (f"Hermes Agent ist auf {cfg['base_url']} eingestellt – das ist dein PC. Starte dort den Desktop-Agent "
            "oder trage in den Einstellungen eine öffentlich erreichbare Hermes-URL ein.")


def _tool_hermes(args, ctx):
    from .models import HermesTask
    action = str(args.get("action") or "start").strip().lower()
    cfg = _hermes_cfg(ctx)
    if action == "list":
        tasks = HermesTask.objects.filter(user_id=ctx.user_id)[:8]
        if not tasks:
            return "Noch keine Hermes-Aufträge."
        return "\n".join(f"[{t.id}] {t.status}: {t.task[:80]}" + (f" → {t.result[:120]}" if t.result else "")
                         for t in tasks)
    if action == "status":
        return _hermes_call(ctx, cfg, {"action": "status"})
    task = str(args.get("task") or "").strip()
    if not task:
        return "Bitte beschreibe den Auftrag für den Hermes Agent."
    if action == "run":
        return _hermes_call(ctx, cfg, {"action": "run", "task": task})

    ht = HermesTask.objects.create(user_id=ctx.user_id, task=task)
    hub.send_to_user(ctx.user_id, {"type": "hermes", "task": ht.as_dict()})

    def _bg():
        from .models import ChatMessage
        from .notify import notify
        try:
            with use_data_root(ctx.data_root):
                result = _hermes_call(ctx, cfg, {"action": "run", "task": task})
            failed = result.startswith(HERMES_ERRORS)
            ht.status, ht.result, ht.finished_at = ("failed" if failed else "done"), result, timezone.now()
            ht.save()
            ChatMessage.objects.create(user_id=ctx.user_id, role="model", source="hermes",
                                       text=f"🤖 Hermes-Auftrag #{ht.id}: {task[:120]}\n\n{result}")
            notify(ctx.user_id, "🤖 Hermes Agent " + ("fehlgeschlagen" if failed else "fertig"), result[:1500],
                   kind="hermes", data={"task_id": ht.id},
                   speak=None if failed else "Der Hermes Agent ist mit deinem Auftrag fertig.")
            hub.send_to_user(ctx.user_id, {"type": "hermes", "task": ht.as_dict()})
        except Exception as e:
            log.exception("Hermes-Hintergrundauftrag")
            HermesTask.objects.filter(id=ht.id).update(status="failed", result=str(e), finished_at=timezone.now())
        finally:
            close_old_connections()

    threading.Thread(target=_bg, daemon=True, name=f"hermes-{ht.id}").start()
    return (f"Auftrag #{ht.id} an den Hermes Agent übergeben. Er arbeitet im Hintergrund – "
            "ich melde mich mit dem Ergebnis.")


def _tool_db(args, ctx):
    is_sqlite = str(args.get("type") or "").lower() == "sqlite" or bool(args.get("path"))
    if is_sqlite and not ctx.is_admin:
        return _run_desktop("db_action", args, ctx)  # lokale SQLite-Dateien liegen auf dem PC
    return _run_server("db_action", args, ctx)


WEB_HANDLERS = {
    "hermes_agent": _tool_hermes,
    "db_action": _tool_db,
    "reminder": _tool_reminder,
    "wecker": _tool_wecker,
    "play_music": _tool_play_music,
    "open_chrome": _tool_open_chrome,
    "youtube_video": _tool_youtube,
    "morning_routine": _tool_morning,
    "shutdown_jarvis": _tool_shutdown,
    "set_autopilot": _tool_set_autopilot,
    "screen_process": _tool_screen,
    "open_app": _tool_open_app,
    "file_processor": _tool_file_processor,
    "calendar_manager": _tool_calendar,
    "claude_bridge": _tool_claude,
    "flight_finder": _tool_flights,
}


# ── Ausführung ─────────────────────────────────────────────────────────────

def _run_server(name, args, ctx):
    try:
        return call_action(name, args, player=WebPlayer(ctx), speak=_speaker(ctx))
    except (ImportError, ModuleNotFoundError) as e:
        if hub.agent(ctx.user_id):
            return hub.agent_call(ctx.user_id, name, args)
        return f"'{name}' ist auf dem Server nicht verfügbar ({e}). Mit verbundenem Desktop-Agent läuft es am PC."
    except KeyError:
        return f"Unbekanntes Tool: {name}"


def _desktop_target(ctx):
    """Liefert eine Funktion (name, args) -> str, die am PC ausführt, oder None."""
    if hub.agent(ctx.user_id):
        return lambda n, a: hub.agent_call(ctx.user_id, n, a, timeout=900 if n in LONG_RUNNING else 180)
    if LOCAL_DESKTOP and ctx.is_admin:
        return lambda n, a: call_action(n, a, player=WebPlayer(ctx), speak=_speaker(ctx))
    return None


def _run_desktop(name, args, ctx):
    target = _desktop_target(ctx)
    if target:
        return target(name, args)
    if name == "focus_app" and str(args.get("app", "")).lower() == "chrome":
        return _open_url(ctx, "https://www.google.com", "Browser")
    return (f"'{name}' steuert deinen PC und braucht den Desktop-Agent. Starte auf dem PC: "
            f"python desktop_agent.py --server <diese URL> --token <dein Token aus den Einstellungen>.")


def run_tool(name: str, args: dict, ctx: ToolContext) -> str:
    """Führt ein Tool im Datenverzeichnis des Benutzers aus und liefert das Ergebnis als Text. Wirft nie."""
    args = dict(args or {})
    started = time.time()
    hub.send_to_user(ctx.user_id, {"type": "tool", "phase": "start", "name": name, "args": args})
    try:
        with use_data_root(ctx.data_root):
            if name in SERVER_FS_TOOLS and not ctx.is_admin:
                result = _run_desktop(name, args, ctx)
            elif name in WEB_HANDLERS:
                result = WEB_HANDLERS[name](args, ctx)
            elif name in DESKTOP_TOOLS:
                result = _run_desktop(name, args, ctx)
            else:
                result = _run_server(name, args, ctx)
    except Exception as e:
        traceback.print_exc()
        result = f"Tool '{name}' fehlgeschlagen: {e}"
    result = str(result if result not in (None, "") else "Erledigt.")
    ms = int((time.time() - started) * 1000)
    hub.send_to_user(ctx.user_id, {"type": "tool", "phase": "end", "name": name, "result": result[:400], "ms": ms})
    log.info("[Tool] %s (%s, %dms) → %s", name, ctx.username, ms, result[:120].replace("\n", " "))
    try:
        autopilot_log(ctx.user_id, f"{name}: {result[:60]}")
    except Exception:
        pass
    state_sync.snapshot_async()
    return result
