import asyncio
import gc
import threading
import json
import sys
import traceback
from pathlib import Path

import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)

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
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000  # Gemini braucht 16kHz für Audio-Input
RECEIVE_SAMPLE_RATE = 24000  # Wiedergabe bleibt gut
CHUNK_SIZE          = 16384   # große Blöcke = minimale CPU-Interrupts


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

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
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
        "description": "Gives the weather report to user. Wenn keine Stadt angegeben wird, wird der eingestellte Heimatort verwendet.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name (optional, default: home_location)"},
                "days": {"type": "INTEGER", "description": "Forecast days (default 1)"}
            },
            "required": []
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
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
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
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
    "name": "shutdown_jarvis",
    "description": (
        "Shuts down the assistant completely. "
        "Call this when the user expresses intent to end the conversation, "
        "close the assistant, say goodbye, or stop Jarvis. "
        "The user can say this in ANY language."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "email_manager",
        "description": (
            "Verwaltet E-Mails: list (lesen), read (einzelne Nachricht), send (senden), setup (einrichten). "
            "Mehrere Konten möglich — Parameter account wählt per Name/Label. "
            "list: zeigt die letzten E-Mails an. read(index): liest eine bestimmte E-Mail. "
            "send(to, subject, body): sendet eine E-Mail. "
            "setup(email, password, name): konfiguriert ein neues E-Mail-Konto."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "list | read | send | setup"},
                "account":  {"type": "STRING", "description": "Name des E-Mail-Kontos (z.B. Privat, Geschäftlich)"},
                "count":    {"type": "INTEGER", "description": "Anzahl E-Mails für list (default: 5)"},
                "index":    {"type": "INTEGER", "description": "Index für read (1 = neueste)"},
                "folder":   {"type": "STRING", "description": "IMAP-Ordner (default: INBOX)"},
                "to":       {"type": "STRING", "description": "Empfänger für send"},
                "subject":  {"type": "STRING", "description": "Betreff für send"},
                "body":     {"type": "STRING", "description": "Nachrichtentext für send"},
                "email":    {"type": "STRING", "description": "E-Mail-Adresse für setup"},
                "password": {"type": "STRING", "description": "Passwort/App-Passwort für setup"},
                "name":     {"type": "STRING", "description": "Name/Label für setup (z.B. Privat)"},
                "unread_only": {"type": "BOOLEAN", "description": "Nur ungelesene E-Mails (list)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "web_summarize",
        "description": (
            "Ruft eine Webseite ab und fasst sie auf Deutsch zusammen. "
            "Aktionen: summarize (Standard), analyze, extract, rohtext. "
            "Übergib die URL und die gewünschte Aktion."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url":    {"type": "STRING", "description": "Vollständige URL der Webseite"},
                "action": {"type": "STRING", "description": "summarize | analyze | extract | rohtext (default: summarize)"},
            },
            "required": ["url"]
        }
    },
    {
        "name": "jds_connect",
        "description": (
            "JDS Management-System. Aktionen: setup (einrichten), connect (verbinden), "
            "status, dashboard, tasks (Aufgaben), task (einzelne Aufgabe), "
            "meetings, leads, customers, products, vacations, deliveries, "
            "invoices, events, notifications, storage, users. "
            "Bei setup: base_url, team_code, api_token angeben."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "setup | connect | status | dashboard | tasks | task | meetings | leads | customers | products | vacations | deliveries | invoices | events | notifications | storage | users"},
                "base_url":  {"type": "STRING", "description": "Basis-URL für setup (z.B. https://jds.example.com)"},
                "team_code": {"type": "STRING", "description": "Team-UUID für setup"},
                "api_token": {"type": "STRING", "description": "API-Token für setup"},
                "filter":    {"type": "STRING", "description": "Filter für tasks: me, todo"},
                "id":        {"type": "INTEGER", "description": "ID für task"},
                "title":     {"type": "STRING", "description": "Titel zum Erstellen einer Aufgabe"},
                "description": {"type": "STRING", "description": "Beschreibung für neue Aufgabe"},
                "due_date":  {"type": "STRING", "description": "Fälligkeitsdatum ISO (für Aufgabe)"},
                "stage":     {"type": "STRING", "description": "Stage für leads (new, contacted, qualified)"},
                "status":    {"type": "STRING", "description": "Status für invoices/vacations"},
                "days":      {"type": "INTEGER", "description": "Tage für events (default: 7)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "tankpreise",
        "description": (
            "Deutsche Tankstellenpreise via Tankerkoenig API. "
            "Aktionen: search (günstigste suchen), stations (Liste), prices (Preise einer Station). "
            "Parameter: lat, lng (Koordinaten), radius (km), fuel (e5/e10/diesel), station_id."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "search | stations | prices"},
                "lat":        {"type": "NUMBER", "description": "Breitengrad"},
                "lng":        {"type": "NUMBER", "description": "Längengrad"},
                "radius":     {"type": "INTEGER", "description": "Suchradius in km (default 5, max 25)"},
                "fuel":       {"type": "STRING", "description": "Kraftstoff: e5 (Super), e10, diesel (default: e5)"},
                "station_id": {"type": "STRING", "description": "Tankerkoenig Station-ID für prices"},
                "sort":       {"type": "STRING", "description": "Sortierung: price (Standard), dist"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "maps_api",
        "description": (
            "Karten- und Routendienst via OpenStreetMap. "
            "Aktionen: geocode (Adresse → Koordinaten), directions (Route von→zu), "
            "distance (Entfernung), search (POI-Suche in der Nähe)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "geocode | directions | distance | search"},
                "address": {"type": "STRING", "description": "Adresse für geocode"},
                "from":    {"type": "STRING", "description": "Startadresse für directions/distance"},
                "to":      {"type": "STRING", "description": "Zieladresse für directions/distance"},
                "query":   {"type": "STRING", "description": "Suchbegriff für search (POI)"},
                "lat":     {"type": "NUMBER", "description": "Breitengrad (für search)"},
                "lng":     {"type": "NUMBER", "description": "Längengrad (für search)"},
                "radius":  {"type": "INTEGER", "description": "Suchradius in Metern (search, default 1000)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "db_action",
        "description": (
            "Datenbank-Client. Unterstützt SQLite, PostgreSQL, MySQL. "
            "Aktionen: connect (verbinden), disconnect, tables (Tabellen auflisten), "
            "query (SQL ausführen), schema (Tabellenstruktur). "
            "Für SQLite: path angeben. Für PostgreSQL/MySQL: type, host, port, database, user, password."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "connect | disconnect | tables | query | schema"},
                "name":     {"type": "STRING", "description": "Verbindungsname (default: default)"},
                "type":     {"type": "STRING", "description": "sqlite | postgresql | mysql"},
                "host":     {"type": "STRING", "description": "DB-Host (default: localhost)"},
                "port":     {"type": "INTEGER", "description": "DB-Port"},
                "database": {"type": "STRING", "description": "Datenbankname"},
                "user":     {"type": "STRING", "description": "DB-Benutzer"},
                "password": {"type": "STRING", "description": "DB-Passwort"},
                "path":     {"type": "STRING", "description": "Dateipfad für SQLite"},
                "sql":      {"type": "STRING", "description": "SQL-Abfrage für query"},
                "table":    {"type": "STRING", "description": "Tabellenname für schema"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "knowledge_sites",
        "description": (
            "Durchsucht konfigurierte Wissensseiten (aus Einstellungen). "
            "Aktionen: list (alle Seiten auflisten), query (Seite öffnen + ggf. einloggen + Inhalt holen). "
            "Bei query: site_name filtert auf eine bestimmte Seite; query durchsucht Seiteninhalte."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "list | query"},
                "site_name": {"type": "STRING", "description": "Name der Wissensseite (filtert auf eine Seite)"},
                "query":     {"type": "STRING", "description": "Suchbegriff zum Durchsuchen der Seiteninhalte"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "admin_api",
        "description": (
            "Joel-Digitals.de Admin-API. Prüft Bestellungen, Termine, Blog-Statistiken, Support-Tickets. "
            "Nützlich fürs Morgen-Briefing. Aktionen: dashboard (Übersicht), appointments (Termine), "
            "orders (Bestellungen), blog (Blog-Stats), tickets (Support-Tickets), "
            "confirm_appointment / reject_appointment (Termin bestätigen/ablehnen), "
            "reply_ticket (auf Ticket antworten), briefing (alles auf einmal fürs Morgen-Briefing)."
        ),
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
]


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

    def _build_context(self) -> str:
        recent = self._history[-6:]
        lines = ["Letzter Gesprächsverlauf (weiter machen wo wir aufgehört haben):"]
        for h in recent:
            role = "Du" if h["role"] == "user" else "Du"
            lines.append(f"{role}: {h['text']}")
        lines.append("---")
        return "\n".join(lines)

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

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
                turns={"parts": [{"text": text}]},
                turn_complete=True
            )
            try:
                return await asyncio.wait_for(q.get(), timeout=30)
            except asyncio.TimeoutError:
                return None
        finally:
            if q in self._response_queues:
                self._response_queues.remove(q)

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

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
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")
        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
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
                from actions.briefing_action import do_briefing
                r = await loop.run_in_executor(None, lambda: do_briefing(parameters=args, player=self.ui))
                result = r or "Briefing abgeschlossen."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Herunterfahren angefordert.")
                self.speak("Auf Wiedersehen, Sir.")

                def _shutdown():
                    import time, sys, os
                    time.sleep(1)
                    os._exit(0)

                threading.Thread(target=_shutdown, daemon=True).start()
            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")

        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            try:
                await self.session.send_realtime_input(media=msg)
            except Exception:
                self.out_queue.put_nowait(msg)
                raise

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            if self.ui.muted:
                return
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if jarvis_speaking:
                return
            data = indata.tobytes()
            loop.call_soon_threadsafe(
                self.out_queue.put_nowait,
                {"data": data, "mime_type": "audio/pcm"}
            )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                await asyncio.Event().wait()
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        self.set_speaking(True)
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            self.set_speaking(False)

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"Du: {full_in}")
                                self._history.append({"role": "user", "text": full_in})
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                                self._forward_response(full_out)
                                self._history.append({"role": "model", "text": full_out})

                            out_buf = []

                            if full_in and len(full_in) > 5:
                                _MEMORY_POOL.submit(_update_memory_async, full_in, full_out)

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
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
            raise

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
                chunk = await self.audio_in_queue.get()
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    def _setup_hourly_reminder(self):
        try:
            now = __import__("datetime").datetime.now()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + __import__("datetime").timedelta(hours=1)
            delay = (next_hour - now).total_seconds()

            def _tick():
                self.speak("Sir, es ist Zeit etwas zu trinken! Bleiben Sie hydriert.")
                self.ui.write_log("SYS: Trink-Erinnerung 🔔")
                threading.Timer(3600.0, _tick).start()

            threading.Timer(delay, _tick).start()
            print(f"[JARVIS] 💧 Trink-Erinnerung aktiv — erste in {delay:.0f}s")
            self.ui.write_log("SYS: Stündliche Trink-Erinnerung aktiviert.")
        except Exception as e:
            print(f"[Reminder] ⚠️ {e}")

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
            if bu and at:
                from actions.jds_client import jds_connect
                result = jds_connect({"action": "setup", "base_url": bu, "team_code": tc, "api_token": at})
                result = jds_connect({"action": "connect"})
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
        while True:
            await asyncio.sleep(120)
            gc.collect()
            print(f"[GC] Collect — {gc.get_stats()[0].get('collected',0)} objects freed")

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                print("[JARVIS] 🔌 Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue(maxsize=200)
                    self.out_queue      = asyncio.Queue(maxsize=10)

                    print("[JARVIS] ✅ Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS bereit.")

                    if self._history:
                        context = self._build_context()
                        if context:
                            await session.send_client_content(
                                turns={"parts": [{"text": context}]},
                                turn_complete=True
                            )
                            print(f"[JARVIS] 📜 Context restored ({len(self._history)} turns)")

                    self._setup_hourly_reminder()
                    self._connect_jds()
                    self._auto_setup_email()
                    self._start_discord()
                    from actions.wecker import schedule_all
                    schedule_all()

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._gc_loop())
                    
            except Exception as e:
                print(f"[JARVIS] ⚠️ {e}")
                traceback.print_exc()

            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[JARVIS] 🔄 Reconnecting in 3s...")
            await asyncio.sleep(3)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="JARVIS")
    parser.add_argument("--server", action="store_true", help="Starte als Web-Server (ohne Qt)")
    parser.add_argument("--port", type=int, default=5789, help="Web-Server Port")
    parser.add_argument("--host", default="0.0.0.0", help="Web-Server Host")
    args, _ = parser.parse_known_args()

    if args.server:
        from server.app import start as start_server
        print("[JARVIS] 🌐 Starte im Server-Modus (kein Qt)")
        start_server(host=args.host, port=args.port, debug=False)
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

    ui = JarvisUI("face.png")

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