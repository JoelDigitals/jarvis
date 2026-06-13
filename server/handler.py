import os, json, sys, traceback
from pathlib import Path
from datetime import datetime

import google.genai as genai
from google.genai import types

BASE = Path(__file__).resolve().parent.parent

def _load_settings():
    try:
        p = BASE / "config" / "settings.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except: pass
    return {}

def _load_system_prompt():
    p = BASE / "core" / "prompt.txt"
    return p.read_text(encoding="utf-8") if p.exists() else "Du bist JARVIS."

def _get_api_key():
    key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("gemini_api_key", "")
    if key:
        return key
    try:
        p = BASE / "config" / "api_keys.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for k in ("gemini_api_key", "GEMINI_API_KEY", "api_key"):
                val = data.get(k)
                if val:
                    return val
    except: pass
    try:
        p = BASE / "config" / "settings.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")).get("api_key", "")
    except: pass
    return ""

def _execute_action(name: str, args: dict) -> str:
    try:
        if name == "open_app":
            from actions.open_app import open_app
            return open_app(parameters=args)
        elif name == "weather_report":
            from actions.weather_report import weather_action
            return weather_action(parameters=args)
        elif name == "weather_action":
            from actions.weather_report import weather_action
            return weather_action(parameters=args)
        elif name == "web_search":
            from actions.web_search import web_search
            return web_search(parameters=args)
        elif name == "web_summarizer":
            from actions.web_summarizer import web_summarizer
            return web_summarizer(parameters=args)
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
                save_memory(args.get("key",""), args.get("value",""))
                return f"Gemerkt: {args.get('key')} = {args.get('value')}"
            else:
                return recall_memory(args.get("key",""))
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
        elif name == "do_briefing":
            from actions.briefing_action import do_briefing
            return do_briefing(parameters=args)
        elif name == "wecker":
            from actions.wecker import wecker
            return wecker(parameters=args)
        elif name == "knowledge_base":
            from actions.knowledge_base import kb_action
            return kb_action(parameters=args)
        elif name == "save_memory":
            from memory.memory_manager import recall_memory, save_memory
            cat = args.get("category", "notes")
            key = args.get("key", "")
            val = args.get("value", "")
            if key and val:
                save_memory({cat: {key: {"value": val}}})
                return f"Gemerkt: {cat} → {key} = {val}"
            return "Key und value erforderlich."
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
            else:
                return "Autopilot deaktiviert."
        elif name == "calendar_manager":
            from actions.calendar_manager import calendar_action
            return calendar_action(parameters=args)
        elif name == "morning_routine":
            from actions.wake_manager import run_morning_routine
            return run_morning_routine()
        elif name == "play_music":
            from actions.wake_manager import open_spotify
            url = args.get("url", "")
            ok = open_spotify(url) if url else open_spotify()
            return "Musik gestartet." if ok else "Konnte Musik nicht starten."
        elif name == "focus_app":
            app = args.get("app", "").strip().lower()
            if app in ("cursor", "code", "vscode"):
                from actions.wake_manager import focus_cursor
                ok = focus_cursor()
                return "Cursor fokussiert." if ok else "Cursor gestartet."
            elif app == "chrome":
                from actions.wake_manager import _chrome_exe
                exe = _chrome_exe()
                if exe:
                    import subprocess
                    subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return "Chrome geöffnet."
                return "Chrome nicht gefunden."
            return f"Unbekannte App: {app}"
        elif name == "open_chrome":
            from actions.wake_manager import open_chrome_url
            url = args.get("url", "")
            if not url:
                return "Keine URL angegeben."
            monitor = args.get("monitor", 1)
            fullscreen = args.get("fullscreen", True)
            open_chrome_url(url, monitor, fullscreen)
            return f"Chrome geöffnet: {url[:50]}"
        elif name == "computer_settings":
            from actions.computer_settings import computer_settings
            return computer_settings(parameters=args)
        elif name == "screen_process":
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
            from actions.file_controller import file_controller
            return file_controller(parameters=args)
        elif name == "agent_task":
            from actions.agent_task import agent_task
            return agent_task(parameters=args)
        else:
            return f"Unbekannte Aktion: {name}"
    except Exception as e:
        return f"Fehler in {name}: {e}"

# Importiere Tool-Deklarationen aus main.py, um Sync zu halten.
# Funktioniert sowohl bei python main.py --server als auch bei modularem Import.
_MAIN_TOOLS = None
try:
    import __main__ as _main_mod
    _MAIN_TOOLS = getattr(_main_mod, 'TOOL_DECLARATIONS', None)
except Exception:
    pass
if _MAIN_TOOLS is None:
    try:
        import importlib
        _spec = importlib.util.spec_from_file_location(
            'main', str(Path(__file__).resolve().parent.parent / 'main.py'))
        if _spec:
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _MAIN_TOOLS = getattr(_mod, 'TOOL_DECLARATIONS', None)
    except Exception:
        _MAIN_TOOLS = None

TOOLS = None

def _make_tools() -> list[dict]:
    if _MAIN_TOOLS:
        return [types.Tool(function_declarations=[d]) for d in _MAIN_TOOLS]
    # Fallback: eigene Liste
    declarations = [
        {
            "name": "open_app",
            "description": "Opens any application on the computer. Use this whenever the user asks to open, launch, or start any app, website, or program.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "app_name": {"type": "STRING", "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"}
                },
                "required": ["app_name"]
            }
        },
        {
            "name": "web_search",
            "description": "Searches the web for any information.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query":  {"type": "STRING", "description": "Search query"},
                    "mode":   {"type": "STRING", "description": "search (default) or compare"},
                    "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                    "aspect": {"type": "STRING", "description": "price | specs | reviews"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "weather_report",
            "description": "Gives the weather report to user",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "city": {"type": "STRING", "description": "City name"},
                    "days": {"type": "INTEGER", "description": "Forecast days (default 1)"}
                },
                "required": ["city"]
            }
        },
        {
            "name": "send_message",
            "description": "EXPLICIT USER REQUEST ONLY. Types a text message into a messaging app (WhatsApp, Telegram, etc.) for a DIFFERENT PERSON. NEVER use this to respond to the user — responses are spoken via audio automatically. Only use when the user explicitly says 'send a message to [person]'.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "receiver":     {"type": "STRING", "description": "Recipient contact name (a different person, NOT the user)"},
                    "message_text": {"type": "STRING", "description": "The message text to send"},
                    "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
                },
                "required": ["receiver", "message_text", "platform"]
            }
        },
        {
            "name": "reminder",
            "description": "Sets a timed reminder using Windows Task Scheduler.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                    "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                    "message": {"type": "STRING", "description": "Reminder message text"}
                },
                "required": ["date", "time", "message"]
            }
        },
        {
            "name": "youtube_video",
            "description": "Controls YouTube: play, summarize, get_info, trending.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING", "description": "play | summarize | get_info | trending"},
                    "query":  {"type": "STRING", "description": "Search query"},
                    "url":    {"type": "STRING", "description": "Video URL"},
                },
                "required": []
            }
        },
        {
            "name": "email_manager",
            "description": "E-Mail-Management: list (ungelesene auflisten), read (lesen), send (senden), setup (Konto einrichten). Jedes Konto hat einen Namen — account-Parameter nutzen.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action":   {"type": "STRING", "description": "list | read | send | setup"},
                    "account":  {"type": "STRING", "description": "Konto-Name/Label (optional, default: erstes Konto)"},
                    "count":    {"type": "INTEGER", "description": "Anzahl (list)"},
                    "email_id": {"type": "STRING", "description": "E-Mail-ID (read)"},
                    "to":       {"type": "STRING", "description": "Empfänger (send)"},
                    "subject":  {"type": "STRING", "description": "Betreff (send)"},
                    "body":     {"type": "STRING", "description": "Nachricht (send)"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "jds_connect",
            "description": "JDS ERP-System: dashboard/tasks/customers/meetings/leads/products/vacations/deliveries/invoices/events/notifications/storage/users/finance/incomes/expenses/away_briefing. setup zum Konfigurieren, connect zum Verbinden.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action":    {"type": "STRING", "description": "setup | connect | status | dashboard | tasks | task | meetings | leads | customers | products | vacations | deliveries | invoices | events | notifications | storage | users | finance | incomes | expenses | away_briefing"},
                    "base_url":  {"type": "STRING", "description": "JDS-Basis-URL (setup)"},
                    "team_code": {"type": "STRING", "description": "Teamcode (setup)"},
                    "api_token": {"type": "STRING", "description": "API-Token (setup)"},
                    "filter":    {"type": "STRING", "description": "Filter für tasks: me | todo | user:name"},
                    "id":        {"type": "INTEGER", "description": "ID für task-Detail"},
                    "from":      {"type": "STRING", "description": "Start-Datum (YYYY-MM-DD) für incomes/expenses/away_briefing"},
                    "to":        {"type": "STRING", "description": "End-Datum (YYYY-MM-DD) für incomes/expenses"},
                    "since":     {"type": "STRING", "description": "Start-Datum (YYYY-MM-DD) für away_briefing"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "knowledge_sites",
            "description": "Durchsucht konfigurierte Wissensseiten (Login + Scrape). Aktionen: list (auflisten), query (Seite öffnen + Inhalt holen).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action":    {"type": "STRING", "description": "list | query"},
                    "site_name": {"type": "STRING", "description": "Name der Wissensseite"},
                    "query":     {"type": "STRING", "description": "Suchbegriff"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "tankpreise",
            "description": "Deutsche Tankstellenpreise via Tankerkoenig API.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action":     {"type": "STRING", "description": "search | stations | prices"},
                    "lat":        {"type": "NUMBER", "description": "Breitengrad"},
                    "lng":        {"type": "NUMBER", "description": "Längengrad"},
                    "radius":     {"type": "INTEGER", "description": "Suchradius (default 5)"},
                    "fuel":       {"type": "STRING", "description": "e5 | e10 | diesel"},
                    "station_id": {"type": "STRING", "description": "Station-ID für prices"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "maps_api",
            "description": "Karten-Funktionen: geocode/directions/distance/search (OpenStreetMap).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action":    {"type": "STRING", "description": "geocode | directions | distance | search"},
                    "location":  {"type": "STRING", "description": "Ort für geocode"},
                    "origin":    {"type": "STRING", "description": "Startort für directions"},
                    "destination": {"type": "STRING", "description": "Zielort für directions"},
                    "query":     {"type": "STRING", "description": "Suchbegriff für search"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "db_action",
            "description": "Datenbank-Client: connect/disconnect/tables/query/schema. SQLite/PostgreSQL/MySQL.",
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
                    "path":     {"type": "STRING", "description": "Dateipfad für SQLite"},
                    "sql":      {"type": "STRING", "description": "SQL-Abfrage"},
                    "table":    {"type": "STRING", "description": "Tabellenname"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "web_summarize",
            "description": "Webseite zusammenfassen oder analysieren (url + action: summarize/analyze/extract).",
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
            "name": "admin_api",
            "description": "Joel-Digitals.de Admin-API. Prüft Bestellungen, Termine, Blog-Stats, Support-Tickets. Aktionen: dashboard (Übersicht), appointments (Termine), orders (Bestellungen), blog (Blog-Stats), tickets (Support-Tickets), confirm_appointment / reject_appointment (Termin bestätigen/ablehnen), reply_ticket (auf Ticket antworten), briefing (alles auf einmal fürs Morgen-Briefing).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action":  {"type": "STRING", "description": "dashboard | appointments | confirm_appointment | reject_appointment | blog | tickets | reply_ticket | orders | briefing"},
                    "status":  {"type": "STRING", "description": "Filter: pending | confirmed | rejected | open | closed"},
                    "id":      {"type": "INTEGER", "description": "ID für confirm/reject/reply"},
                    "message": {"type": "STRING", "description": "Nachricht für reply_ticket"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "memory_manager",
            "description": "Speichert und ruft Informationen aus dem Gedächtnis ab. Aktionen: recall (abrufen), save (speichern).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING", "description": "recall | save"},
                    "key":    {"type": "STRING", "description": "Schlüssel für recall/save"},
                    "value":  {"type": "STRING", "description": "Wert für save"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "do_briefing",
            "description": "Führt das gesamte Morgen-Briefing in EINEM Aufruf aus: Wetter, JDS-Aufgaben, E-Mails, Admin-Dashboard. Einziger Aufruf für das Briefing.",
            "parameters": {
                "type": "OBJECT",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "wecker",
            "description": "Wecker (Alarm) und Musik-Steuerung. Aktionen: set (stellen), list (anzeigen), remove (entfernen), play (Musik abspielen), stop (Musik stoppen). Musikdateien im music/-Ordner.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING", "description": "set | list | remove | play | stop"},
                    "time":   {"type": "STRING", "description": "Uhrzeit HH:MM für set"},
                    "id":     {"type": "INTEGER", "description": "Wecker-ID für remove"},
                    "music":  {"type": "STRING", "description": "Musikdatei-Name (optional)"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "knowledge_base",
            "description": "Wissensdatenbank für dauerhafte Informationen über die Firma, Kunden, Prozesse, Produkte. Aktionen: set (speichern), get (abrufen), delete (löschen). Kategorien: company, customers, processes, products, contacts, support, notes.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action":   {"type": "STRING", "description": "set | get | delete"},
                    "category": {"type": "STRING", "description": "Kategorie z.B. company, customers, processes, products"},
                    "key":      {"type": "STRING", "description": "Schlüsselname"},
                    "value":    {"type": "STRING", "description": "Wert für set"},
                },
                "required": ["action"]
            }
        },
        {
            "name": "save_memory",
            "description": "Speichert eine persönliche Information über den Nutzer im Gedächtnis. Kategorien: identity, preferences, projects, relationships, wishes, notes.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING", "description": "Kategorie: identity, preferences, projects, relationships, wishes, notes"},
                    "key":      {"type": "STRING", "description": "Schlüsselname (snake_case)"},
                    "value":    {"type": "STRING", "description": "Wert"},
                },
                "required": ["category", "key", "value"]
            }
        },
    ]
    return [types.Tool(function_declarations=[d]) for d in declarations]

TOOLS: list | None = None

def _get_tools():
    global TOOLS
    if TOOLS is not None:
        return TOOLS
    TOOLS = _make_tools()
    return TOOLS

class ChatSession:
    def __init__(self):
        self._chat = None
        self._client = None

    def start(self, api_key: str):
        genai_client = genai.Client(api_key=api_key)
        self._client = genai_client
        cfg = _load_settings()
        user_name = cfg.get("user_name", "Sir")
        email_info = ""
        accounts = cfg.get("email_accounts", [])
        if accounts:
            names = ", ".join(a.get("name", a.get("email", "?")) for a in accounts)
            email_info = f"\nE-Mail-Konten: {names}"
        jds = cfg.get("jds_config", {})
        jds_info = f"\nJDS: {jds.get('base_url','nicht konfiguriert')}" if jds.get("base_url") else ""

        system = _load_system_prompt()
        system = system.replace("{user_name}", user_name)
        system += f"\n\nAktuelle Konfiguration:{email_info}{jds_info}"

        self._chat = genai_client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=_get_tools(),
                temperature=0.7,
            ),
        )
        return self._chat

    def _send_with_retry(self, msg):
        import time
        import random
        for attempt in range(3):
            try:
                return self._chat.send_message(msg)
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    wait = min(2 ** attempt * 3 + random.uniform(0, 2), 30)
                    print(f"[JARVIS] Rate limit, retry in {wait:.0f}s ({attempt+1}/3)")
                    time.sleep(wait)
                    continue
                if attempt < 1:
                    wait = 2
                    print(f"[JARVIS] {err[:80]}, retry in {wait}s (1/3)")
                    time.sleep(wait)
                    continue
                raise
        raise Exception("Rate limit exceeded after 3 retries.")

    def send(self, text: str) -> tuple[str, list[dict]]:
        logs = []
        if not self._chat:
            return "Chat nicht initialisiert.", logs
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
                        args = {k: v for k, v in fc.args.items()}
                        logs.append({"tool": name, "args": args})
                        result = _execute_action(name, args)
                        logs.append({"result": (result or "")[:200]})
                        response = self._send_with_retry(
                            types.Content(
                                parts=[types.Part.from_function_response(
                                    name=name,
                                    response={"content": result or ""},
                                )]
                            )
                        )
            except (IndexError, AttributeError):
                break
        return " ".join(answer_parts) if answer_parts else "", logs

_session = None
_session_lock = __import__('threading').Lock()

def get_session():
    global _session
    with _session_lock:
        if _session is None:
            _session = ChatSession()
    return _session

def send_message(text: str) -> tuple[str, list[dict]]:
    session = get_session()
    api_key = _get_api_key()
    if not api_key:
        return "Kein API-Key konfiguriert. Bitte in den Einstellungen hinterlegen.", []
    if getattr(session, "_chat", None) is None:
        session.start(api_key)
    return session.send(text)
