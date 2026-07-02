"""JARVIS Server Handler – vollständig serverunabhängig, keine main.py-Abhängigkeit"""
import os, json, threading, traceback
from pathlib import Path
from datetime import datetime

import google.genai as genai
from google.genai import types

BASE = Path(__file__).resolve().parent.parent

# Erkennt ob JARVIS auf einem Server (Linux/Cloud) oder lokal (Windows) läuft
_IS_SERVER = os.name != "nt" or bool(os.environ.get("JARVIS_SERVER_MODE"))


def _load_settings():
    try:
        p = BASE / "config" / "settings.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Handler] settings.json Fehler: {e}")
    return {}


def _load_system_prompt():
    p = BASE / "core" / "prompt.txt"
    return p.read_text(encoding="utf-8") if p.exists() else "Du bist JARVIS, ein KI-Assistent von Joel Digitals."


def _get_api_key():
    for env in ("GEMINI_API_KEY", "gemini_api_key"):
        val = os.environ.get(env, "")
        if val:
            return val
    try:
        p = BASE / "config" / "api_keys.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for k in ("gemini_api_key", "GEMINI_API_KEY", "api_key"):
                if data.get(k):
                    return data[k]
    except Exception:
        pass
    try:
        return json.loads((BASE / "config" / "settings.json").read_text(encoding="utf-8")).get("api_key", "")
    except Exception:
        pass
    return ""


# ── Tool-Deklarationen (vollständig, ohne main.py) ─────────────────────────

TOOL_DECLARATIONS = [
    {
        "name": "web_search",
        "description": "Sucht im Web nach aktuellen Informationen, Nachrichten, Preisen, etc.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Suchanfrage"},
                "mode":   {"type": "STRING", "description": "search (Standard) oder compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Zu vergleichende Elemente"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gibt den aktuellen Wetterbericht für eine Stadt zurück.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "Stadtname"},
                "days": {"type": "INTEGER", "description": "Vorhersage-Tage (Standard 1)"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "email_manager",
        "description": "E-Mail-Management: list (ungelesene), read (einzelne lesen), send (senden), accounts (Konten anzeigen).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | read | send | accounts"},
                "account":     {"type": "STRING", "description": "Konto-Name (optional)"},
                "count":       {"type": "INTEGER", "description": "Anzahl (list)"},
                "unread_only": {"type": "BOOLEAN", "description": "Nur ungelesene"},
                "email_id":    {"type": "STRING", "description": "E-Mail-ID (read)"},
                "to":          {"type": "STRING", "description": "Empfänger (send)"},
                "subject":     {"type": "STRING", "description": "Betreff (send)"},
                "body":        {"type": "STRING", "description": "Inhalt (send)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "jds_connect",
        "description": "JDS CRM & ERP: dashboard, tasks, customers, meetings, leads, products, invoices, events, notifications, finance, incomes, expenses.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "setup | connect | status | dashboard | tasks | task | meetings | leads | customers | products | vacations | deliveries | invoices | events | notifications | storage | users | finance | incomes | expenses | away_briefing"},
                "base_url":  {"type": "STRING", "description": "JDS-Basis-URL"},
                "team_code": {"type": "STRING", "description": "Teamcode"},
                "api_token": {"type": "STRING", "description": "API-Token"},
                "filter":    {"type": "STRING", "description": "Filter für tasks: me | todo | user:name"},
                "id":        {"type": "INTEGER", "description": "ID für Detail-Ansicht"},
                "from":      {"type": "STRING", "description": "Start-Datum YYYY-MM-DD"},
                "to":        {"type": "STRING", "description": "End-Datum YYYY-MM-DD"},
                "since":     {"type": "STRING", "description": "Seit-Datum YYYY-MM-DD"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "admin_api",
        "description": "Joel-Digitals.de Admin-API: Bestellungen, Termine, Blog-Stats, Support-Tickets, Briefing.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "dashboard | appointments | confirm_appointment | reject_appointment | blog | tickets | reply_ticket | orders | briefing"},
                "status":  {"type": "STRING", "description": "pending | confirmed | rejected | open | closed"},
                "id":      {"type": "INTEGER", "description": "ID für confirm/reject/reply"},
                "message": {"type": "STRING", "description": "Nachricht für reply_ticket"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "maps_api",
        "description": "Karten-Funktionen: geocode, directions, distance, search via OpenStreetMap.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "geocode | directions | distance | search"},
                "location":    {"type": "STRING", "description": "Ort für geocode"},
                "origin":      {"type": "STRING", "description": "Startort"},
                "destination": {"type": "STRING", "description": "Zielort"},
                "query":       {"type": "STRING", "description": "Suchbegriff"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "tankpreise",
        "description": "Deutsche Tankstellenpreise (Tankerkoenig API).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "search | stations | prices"},
                "lat":        {"type": "NUMBER", "description": "Breitengrad"},
                "lng":        {"type": "NUMBER", "description": "Längengrad"},
                "radius":     {"type": "INTEGER", "description": "Suchradius km"},
                "fuel":       {"type": "STRING", "description": "e5 | e10 | diesel"},
                "station_id": {"type": "STRING", "description": "Station-ID"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "web_summarizer",
        "description": "Webseite zusammenfassen, analysieren oder Inhalte extrahieren.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url":    {"type": "STRING", "description": "Webseiten-URL"},
                "action": {"type": "STRING", "description": "summarize | analyze | extract"},
            },
            "required": ["url", "action"]
        }
    },
    {
        "name": "memory_manager",
        "description": "Persönliches Gedächtnis: Informationen speichern und abrufen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "recall | save"},
                "key":    {"type": "STRING", "description": "Schlüssel"},
                "value":  {"type": "STRING", "description": "Wert (save)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "save_memory",
        "description": "Speichert eine persönliche Information. Kategorien: identity, preferences, projects, relationships, wishes, notes.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "Kategorie"},
                "key":      {"type": "STRING", "description": "Schlüsselname"},
                "value":    {"type": "STRING", "description": "Wert"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "knowledge_base",
        "description": "Wissensdatenbank für Firma, Kunden, Prozesse, Produkte. Aktionen: set, get, delete.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "set | get | delete"},
                "category": {"type": "STRING", "description": "company | customers | processes | products | contacts | support | notes"},
                "key":      {"type": "STRING", "description": "Schlüsselname"},
                "value":    {"type": "STRING", "description": "Wert (set)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "do_briefing",
        "description": "Komplettes Morgen-Briefing: Wetter, JDS-Aufgaben, E-Mails, Admin-Dashboard in einem Aufruf.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "greeting": {"type": "STRING", "description": "Begrüßungsformel (optional)"}
            },
            "required": []
        }
    },
    {
        "name": "db_action",
        "description": "Datenbank-Client: connect, tables, query, schema. SQLite/PostgreSQL/MySQL.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "connect | disconnect | tables | query | schema"},
                "name":     {"type": "STRING", "description": "Verbindungsname"},
                "type":     {"type": "STRING", "description": "sqlite | postgresql | mysql"},
                "host":     {"type": "STRING", "description": "DB-Host"},
                "port":     {"type": "INTEGER", "description": "DB-Port"},
                "database": {"type": "STRING", "description": "Datenbankname"},
                "user":     {"type": "STRING", "description": "DB-Benutzer"},
                "password": {"type": "STRING", "description": "DB-Passwort"},
                "path":     {"type": "STRING", "description": "SQLite-Pfad"},
                "sql":      {"type": "STRING", "description": "SQL-Abfrage"},
                "table":    {"type": "STRING", "description": "Tabellenname"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "claude_bridge",
        "description": "Nutzt Claude AI für komplexe Code-Aufgaben, Projekt-Analysen und autonome Programmier-Tasks (project_task).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":       {"type": "STRING", "description": "ask | project_task"},
                "prompt":       {"type": "STRING", "description": "Aufgabe oder Frage"},
                "project_path": {"type": "STRING", "description": "Projektpfad für project_task"},
                "task":         {"type": "STRING", "description": "Aufgabenbeschreibung"},
                "run_command":  {"type": "STRING", "description": "Test-Befehl (optional)"},
            },
            "required": ["action", "prompt"]
        }
    },
    {
        "name": "project_watch",
        "description": "Projektordner auf Fehler überwachen: add, remove, list, scan_now.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "add | remove | list | scan_now"},
                "path":   {"type": "STRING", "description": "Projektpfad"},
                "name":   {"type": "STRING", "description": "Projektname"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "calendar_manager",
        "description": "Kalender verwalten: Termine anlegen, anzeigen, löschen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "add | list | delete | today | week"},
                "title":  {"type": "STRING", "description": "Titel"},
                "date":   {"type": "STRING", "description": "Datum YYYY-MM-DD"},
                "time":   {"type": "STRING", "description": "Uhrzeit HH:MM"},
                "end":    {"type": "STRING", "description": "Endzeit HH:MM"},
                "id":     {"type": "STRING", "description": "Termin-ID (delete)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_processor",
        "description": "Dateien verarbeiten: lesen, konvertieren, analysieren (PDF, DOCX, CSV, Bilder, etc.).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "read | convert | analyze | summarize"},
                "path":   {"type": "STRING", "description": "Dateipfad"},
                "format": {"type": "STRING", "description": "Zielformat (convert)"},
            },
            "required": ["action", "path"]
        }
    },
    {
        "name": "reminder",
        "description": "Erinnerung einstellen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Datum YYYY-MM-DD"},
                "time":    {"type": "STRING", "description": "Uhrzeit HH:MM"},
                "message": {"type": "STRING", "description": "Erinnerungstext"},
            },
            "required": ["date", "time", "message"]
        }
    },
]

# Desktop-Only Tools (nur lokal sinnvoll, auf dem Server wird eine Meldung zurückgegeben)
_DESKTOP_ONLY = {
    "open_app", "computer_control", "computer_settings", "screen_process",
    "focus_app", "open_chrome", "morning_routine", "play_music", "game_updater",
    "wecker", "youtube_video", "dev_agent", "code_helper", "flight_finder",
    "file_controller", "agent_task",
}

# Desktop-Only Tools werden auf dem Server mit Hinweis zurückgegeben, lokal normal ausgeführt
_DESKTOP_TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": "Öffnet eine Anwendung auf dem lokalen Computer (nur lokal verfügbar).",
        "parameters": {"type": "OBJECT", "properties": {"app_name": {"type": "STRING"}}, "required": ["app_name"]}
    },
    {
        "name": "computer_control",
        "description": "Steuert den lokalen Computer: Lautstärke, Bildschirm, etc. (nur lokal).",
        "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}}, "required": ["action"]}
    },
    {
        "name": "wecker",
        "description": "Wecker stellen und Musik abspielen auf dem lokalen PC (nur lokal).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "set | list | remove | play | stop"},
                "time":   {"type": "STRING"},
                "id":     {"type": "INTEGER"},
                "music":  {"type": "STRING"},
            },
            "required": ["action"]
        }
    },
]


def _execute_action(name: str, args: dict) -> str:
    # Desktop-Only-Schutz
    if _IS_SERVER and name in _DESKTOP_ONLY:
        return f"'{name}' ist nur im lokalen JARVIS-Betrieb verfügbar (benötigt Windows/Desktop)."

    try:
        if name == "open_app":
            from actions.open_app import open_app
            return open_app(parameters=args)
        elif name in ("weather_report", "weather_action"):
            from actions.weather_report import weather_action
            return weather_action(parameters=args)
        elif name == "web_search":
            from actions.web_search import web_search
            return web_search(parameters=args)
        elif name == "web_summarizer":
            from actions.web_summarizer import web_summarize
            return web_summarize(parameters=args)
        elif name == "email_manager":
            from actions.email_manager import email_action
            return email_action(parameters=args)
        elif name == "reminder":
            from actions.reminder import reminder
            return reminder(parameters=args)
        elif name == "jds_connect":
            from actions.jds_client import jds_connect
            return jds_connect(parameters=args)
        elif name == "knowledge_sites":
            from actions.knowledge_sites import knowledge_action
            return knowledge_action(parameters=args)
        elif name == "memory_manager":
            from memory.memory_manager import recall_memory, save_memory
            a = (args.get("action") or "").strip().lower()
            if a == "save":
                save_memory(args.get("key", ""), args.get("value", ""))
                return f"Gemerkt: {args.get('key')} = {args.get('value')}"
            return recall_memory(args.get("key", ""))
        elif name == "save_memory":
            from memory.memory_manager import save_memory
            cat = args.get("category", "notes")
            key = args.get("key", "")
            val = args.get("value", "")
            if key and val:
                save_memory({cat: {key: {"value": val}}})
                return f"Gemerkt: {cat} → {key} = {val}"
            return "Key und value erforderlich."
        elif name == "tankpreise":
            from actions.tankpreise import tankpreise
            return tankpreise(parameters=args)
        elif name == "maps_api":
            from actions.maps_api import maps_api
            return maps_api(parameters=args)
        elif name == "db_action":
            from actions.db_client import db_action
            return db_action(parameters=args)
        elif name == "file_processor":
            from actions.file_processor import file_processor
            return file_processor(parameters=args)
        elif name == "computer_control":
            from actions.computer_control import computer_control
            return computer_control(parameters=args)
        elif name == "game_updater":
            from actions.game_updater import game_updater
            return game_updater(parameters=args)
        elif name == "youtube_video":
            from actions.youtube_video import youtube_video
            return youtube_video(parameters=args)
        elif name == "admin_api":
            from actions.admin_api import admin_action
            return admin_action(parameters=args)
        elif name == "claude_bridge":
            from actions.claude_bridge import claude_action
            return claude_action(parameters=args)
        elif name == "project_watch":
            from actions.project_watcher import project_watch_action
            return project_watch_action(parameters=args)
        elif name == "do_briefing":
            from actions.briefing_action import do_briefing
            return do_briefing(parameters=args)
        elif name == "wecker":
            from actions.wecker import wecker
            return wecker(parameters=args)
        elif name == "knowledge_base":
            from actions.knowledge_base import kb_action
            return kb_action(parameters=args)
        elif name == "set_autopilot":
            from actions.email_manager import email_action
            cfg = _load_settings()
            forward_to = cfg.get("email_forward_to", "") or cfg.get("daily_report", {}).get("recipient_email", "")
            active = args.get("active", False)
            if active:
                r = email_action({"action": "list", "count": 5, "unread_only": True})
                result = f"Autopilot aktiviert. E-Mails gescannt: {str(r)[:100]}"
                if forward_to:
                    email_action({"action": "send", "to": forward_to,
                        "subject": "🤖 JARVIS Autopilot aktiviert (Server)",
                        "body": "Autopilot wurde aktiviert. JARVIS hält die Stellung."})
                    result += " Status-Mail gesendet."
                return result
            return "Autopilot deaktiviert."
        elif name == "calendar_manager":
            from actions.calendar_manager import calendar_action
            return calendar_action(parameters=args)
        elif name == "morning_routine":
            if _IS_SERVER:
                return "morning_routine nur lokal verfügbar."
            from actions.wake_manager import run_morning_routine
            return run_morning_routine()
        elif name == "play_music":
            if _IS_SERVER:
                return "play_music nur lokal verfügbar."
            from actions.wake_manager import open_spotify
            url = args.get("url", "")
            ok = open_spotify(url) if url else open_spotify()
            return "Musik gestartet." if ok else "Musik nicht gestartet."
        elif name == "focus_app":
            if _IS_SERVER:
                return "focus_app nur lokal verfügbar."
            app = args.get("app", "").strip().lower()
            if app in ("cursor", "code", "vscode"):
                from actions.wake_manager import focus_cursor
                ok = focus_cursor()
                return "Cursor fokussiert." if ok else "Cursor gestartet."
            return f"Unbekannte App: {app}"
        elif name == "open_chrome":
            if _IS_SERVER:
                return "open_chrome nur lokal verfügbar."
            from actions.wake_manager import open_chrome_url
            url = args.get("url", "")
            if not url:
                return "Keine URL."
            open_chrome_url(url, args.get("monitor", 1), args.get("fullscreen", True))
            return f"Chrome geöffnet: {url[:60]}"
        elif name == "computer_settings":
            if _IS_SERVER:
                return "computer_settings nur lokal verfügbar."
            from actions.computer_settings import computer_settings
            return computer_settings(parameters=args)
        elif name == "screen_process":
            if _IS_SERVER:
                return "screen_process nur lokal verfügbar."
            from actions.screen_processor import screen_process
            return screen_process(parameters=args)
        elif name == "dev_agent":
            from actions.dev_agent import dev_agent
            return dev_agent(parameters=args)
        elif name == "code_helper":
            from actions.code_helper import code_helper
            return code_helper(parameters=args)
        elif name == "flight_finder":
            from actions.flight_finder import flight_finder
            return flight_finder(parameters=args)
        elif name == "file_controller":
            if _IS_SERVER:
                return "file_controller nur lokal verfügbar."
            from actions.file_controller import file_controller
            return file_controller(parameters=args)
        elif name == "agent_task":
            from actions.agent_task import agent_task
            return agent_task(parameters=args)
        else:
            # Plugin-System
            try:
                from actions.plugin_loader import run_plugin
                r = run_plugin(name, args)
                if r is not None:
                    return r
            except Exception:
                pass
            return f"Unbekannte Aktion: {name}"
    except Exception as e:
        traceback.print_exc()
        return f"Fehler in {name}: {e}"


# ── Chat Session (pro User) ────────────────────────────────────────────────

def _build_tools():
    declarations = TOOL_DECLARATIONS[:]
    if not _IS_SERVER:
        declarations += _DESKTOP_TOOL_DECLARATIONS
    return [types.Tool(function_declarations=[d]) for d in declarations]


class ChatSession:
    def __init__(self, username: str = "anon"):
        self._chat = None
        self._client = None
        self._username = username
        self._lock = threading.Lock()

    def start(self, api_key: str):
        client = genai.Client(api_key=api_key)
        self._client = client
        cfg = _load_settings()
        user_name = cfg.get("user_name", "Joel")
        system = _load_system_prompt().replace("{user_name}", user_name)

        accounts = cfg.get("email_accounts", [])
        if accounts:
            system += "\nE-Mail-Konten: " + ", ".join(a.get("name", a.get("email", "?")) for a in accounts)
        jds = cfg.get("jds_config", {})
        if jds.get("base_url"):
            system += f"\nJDS: {jds['base_url']}"
        if _IS_SERVER:
            system += "\n\nHinweis: JARVIS läuft im Server-Modus. Desktop-Funktionen (Apps öffnen, Wecker, etc.) sind nicht verfügbar."

        self._chat = client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=_build_tools(),
                temperature=0.7,
            ),
        )

    def _send_with_retry(self, msg):
        import time, random
        for attempt in range(3):
            try:
                return self._chat.send_message(msg)
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    wait = min(2 ** attempt * 3 + random.uniform(0, 2), 30)
                    print(f"[Handler] Rate limit, Retry in {wait:.0f}s ({attempt+1}/3)")
                    time.sleep(wait)
                    continue
                if attempt == 0:
                    time.sleep(2)
                    continue
                raise
        raise Exception("Rate limit nach 3 Versuchen erschöpft.")

    def send(self, text: str) -> tuple[str, list[dict]]:
        logs = []
        if not self._chat:
            return "Chat nicht initialisiert.", logs

        with self._lock:
            response = self._send_with_retry(text)
            answer_parts = []
            while True:
                try:
                    candidate = response.candidates[0]
                    for part in candidate.content.parts:
                        if part.text:
                            answer_parts.append(part.text)
                        elif part.function_call:
                            fc = part.function_call
                            name = fc.name
                            args = dict(fc.args)
                            print(f"[Handler] 🔧 {name} {str(args)[:80]}")
                            logs.append({"tool": name, "args": args})
                            result = _execute_action(name, args)
                            print(f"[Handler] ✅ {name} → {str(result)[:80]}")
                            logs.append({"result": (result or "")[:200]})
                            response = self._send_with_retry(
                                types.Content(parts=[
                                    types.Part.from_function_response(name=name, response={"content": result or ""})
                                ])
                            )
                except (IndexError, AttributeError):
                    break
        return " ".join(answer_parts) if answer_parts else "", logs


# ── Session Registry (pro User) ───────────────────────────────────────────

_sessions: dict[str, ChatSession] = {}
_sessions_lock = threading.Lock()


def get_session(username: str = "default") -> ChatSession:
    with _sessions_lock:
        if username not in _sessions:
            _sessions[username] = ChatSession(username)
        return _sessions[username]


def send_message(text: str, username: str = "default") -> tuple[str, list[dict]]:
    session = get_session(username)
    api_key = _get_api_key()
    if not api_key:
        return "Kein Gemini-API-Key konfiguriert. Bitte in den Einstellungen eintragen.", []
    if session._chat is None:
        session.start(api_key)
    return session.send(text)
