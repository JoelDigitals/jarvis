"""Gemeinsame Tool-Deklarationen für Desktop (main.py) und Web (Django)."""

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
        "description": "KOMPLETTES Briefing in EINEM Aufruf: Wetter, Admin-Dashboard, JDS-Aufgaben + Kalender + Meetings, E-Mails. Ergebnis enthält 'BRIEFING-TEXT ZUM VORLESEN:'. Parameter greeting überschreibt die automatische Tageszeit-Begrüßung.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "greeting": {"type": "STRING", "description": "optional: 'Guten Morgen', 'Guten Tag' oder 'Guten Abend' — überschreibt Auto-Erkennung"}
            },
            "required": []
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
        "name": "knowledge_base",
        "description": (
            "Wissensdatenbank für dauerhafte Informationen über die Firma, "
            "Kunden, Prozesse, Produkte und alles was JARVIS wissen muss. "
            "Aktionen: set (speichern), get (abrufen), delete (löschen). "
            "Kategorien: company, customers, processes, products, contacts, support, notes. "
            "Beispiel: knowledge_base(action='set', category='company', key='address', value='Musterstr. 1')"
        ),
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
            "E-Mail-Verwaltung mit mehreren Konten. Aktionen: "
            "list (E-Mails lesen), read (einzelne), send (senden), "
            "accounts (konfigurierte Konten anzeigen), setup (neues Konto). "
            "WICHTIG: Vor dem Senden IMMER email_manager(action='accounts') aufrufen, "
            "um die echten Adressen der konfigurierten Konten zu sehen! "
            "Parameter 'account' wählt per Name. Standard-Absender in Einstellungen."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "list | read | send | setup | accounts"},
                "account":  {"type": "STRING", "description": "Name des E-Mail-Kontos (Groß-/Kleinschreibung egal)"},
                "count":    {"type": "INTEGER", "description": "Anzahl E-Mails für list (default: 5)"},
                "index":    {"type": "INTEGER", "description": "Index für read (1 = neueste)"},
                "folder":   {"type": "STRING", "description": "IMAP-Ordner (default: INBOX)"},
                "to":       {"type": "STRING", "description": "Empfänger für send"},
                "subject":  {"type": "STRING", "description": "Betreff für send"},
                "body":     {"type": "STRING", "description": "Nachrichtentext für send"},
                "email":    {"type": "STRING", "description": "E-Mail-Adresse für setup"},
                "password": {"type": "STRING", "description": "Passwort/App-Passwort für setup"},
                "name":     {"type": "STRING", "description": "Name/Label für setup"},
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
            "JDS CRM- & Management-System. Aktionen: setup, connect, status, "
            "dashboard (Übersicht), tasks (meine Aufgaben), task (einzelne), "
            "meetings (Termine), events (Kalender), leads, customers, products, "
            "vacations, deliveries, invoices, notifications, storage, users, "
            "finance (Umsatz gestern/heute), incomes, expenses, away_briefing. "
            "Für Briefing/Kalender: events(days=7) + meetings + finance aufrufen."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "setup | connect | status | dashboard | tasks | task | meetings | leads | customers | products | vacations | deliveries | invoices | events | notifications | storage | users | finance | incomes | expenses | away_briefing"},
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
                "from":      {"type": "STRING", "description": "Start-Datum (YYYY-MM-DD) für incomes/expenses/away_briefing"},
                "to":        {"type": "STRING", "description": "End-Datum (YYYY-MM-DD) für incomes/expenses"},
                "since":     {"type": "STRING", "description": "Start-Datum (YYYY-MM-DD) für away_briefing — seit wann warst du weg"},
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
            "Joel-Digitals.de Admin-API. Dashboard, Bestellungen, Termine, Blog, Support-Tickets, "
            "Blog-Veröffentlichung. Aktionen: dashboard, appointments, orders, blog, tickets, "
            "confirm_appointment, reject_appointment, reply_ticket, publish_blog, briefing."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "dashboard | appointments | confirm_appointment | reject_appointment | blog | tickets | reply_ticket | orders | publish_blog | briefing"},
                "status":  {"type": "STRING", "description": "Filter: pending | confirmed | rejected | open | closed"},
                "id":      {"type": "INTEGER", "description": "ID für confirm/reject/reply"},
                "message": {"type": "STRING", "description": "Nachricht für reply_ticket"},
                "title":   {"type": "STRING", "description": "Titel für publish_blog"},
                "content": {"type": "STRING", "description": "Inhalt für publish_blog (HTML/Markdown)"},
                "lang":    {"type": "STRING", "description": "Sprache: de (Default) | en"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "wecker",
        "description": "Wecker (Alarm), Musik-Steuerung und Radio. Aktionen: set (Wecker stellen), list (Wecker anzeigen), remove (Wecker entfernen), play (Musik abspielen), radio (Radio streamen z.B. sr1, sr3, swr3), stop (alles stoppen). Musikdateien im music/-Ordner.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "set | list | remove | play | radio | stop"},
                "time":   {"type": "STRING", "description": "Uhrzeit HH:MM für set"},
                "id":     {"type": "INTEGER", "description": "Wecker-ID für remove"},
                "music":  {"type": "STRING", "description": "Musikdatei-Name (play) oder Sendername (radio): sr1, sr3, swr1, swr3, 1live, wdr2, deutschlandfunk"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "calendar_manager",
        "description": (
            "Google Kalender Integration. Aktionen:\n"
            "- list: Termine der nächsten Tage (Parameter: days=7, max=10)\n"
            "- today: Heutige Termine\n"
            "- create: Neuen Termin (summary=Titel, start=Startzeit, end=Endzeit, location=Ort, description=Notiz)\n"
            "- update: Termin ändern (event_id, summary, start, end, location, description)\n"
            "- delete: Termin löschen (event_id)\n"
            "- find: Termin suchen (query=Suchbegriff)\n"
            "Datumsformat für start/end: ISO 8601 (z.B. 2025-06-12T14:00:00 oder 2025-06-12)"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "list | today | create | update | delete | find"},
                "summary": {"type": "STRING", "description": "Titel des Termins (bei create/update)"},
                "start": {"type": "STRING", "description": "Startzeit im ISO-Format (z.B. 2025-06-12T14:00:00)"},
                "end": {"type": "STRING", "description": "Endzeit im ISO-Format"},
                "location": {"type": "STRING", "description": "Ort (optional)"},
                "description": {"type": "STRING", "description": "Beschreibung/Notiz (optional)"},
                "days": {"type": "INTEGER", "description": "Anzahl Tage für list (default: 7)"},
                "max": {"type": "INTEGER", "description": "Maximale Anzahl Termine (default: 10)"},
                "query": {"type": "STRING", "description": "Suchbegriff für find"},
                "event_id": {"type": "STRING", "description": "Event-ID für update/delete"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "set_autopilot",
        "description": (
            "Aktiviert/deaktiviert den Autopilot-Modus. Wenn aktiv, arbeitet JARVIS "
            "selbstständig alle offenen Aufgaben ab, beantwortet E-Mails und "
            "protokolliert alle Aktionen. Nutze dies wenn der Benutzer sagt "
            "'ich bin weg', 'halt die Stellung', 'übernimm du' oder ähnliches. "
            "Beim Deaktivieren wird eine Zusammenfassung zurückgegeben."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "active": {"type": "BOOLEAN", "description": "true = aktivieren, false = deaktivieren"},
            },
            "required": ["active"]
        }
    },
    {
        "name": "morning_routine",
        "description": (
            "Liest das Morgen-Briefing vor: Wetter, Kalender-Termine, "
            "Admin-Dashboard, JDS-Aufgaben und E-Mails. "
            "Rufe dies NUR auf, wenn der Nutzer explizit danach fragt."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "play_music",
        "description": (
            "Spielt Musik ab. Ohne Parameter wird die Standard-Spotify-URI "
            "verwendet. Mit dem Parameter 'url' kann eine beliebige Spotify- "
            "oder YouTube-URL abgespielt werden."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Spotify/YouTube URL (optional)"},
            },
        }
    },
    {
        "name": "focus_app",
        "description": (
            "Fokussiert ein bestimmtes Fenster oder startet es. "
            "Verfügbare Optionen: 'cursor' (VS Code/Cursor), "
            "'chrome', 'code'. Ruft das Fenster in den Vordergrund "
            "und aktiviert den Vollbildmodus."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app": {
                    "type": "STRING",
                    "description": "cursor | chrome | code"
                },
            },
            "required": ["app"]
        }
    },
    {
        "name": "open_chrome",
        "description": (
            "Öffnet eine URL in Google Chrome auf einem bestimmten Monitor "
            "im Vollbildmodus. Monitor-Nummern sind 1-basiert "
            "(1 = links, 2 = mitte, 3 = rechts)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Vollständige URL"},
                "monitor": {"type": "INTEGER", "description": "Monitor-Nummer (1, 2, 3, ...)"},
                "fullscreen": {"type": "BOOLEAN", "description": "Vollbild (default: true)"},
            },
            "required": ["url"]
        }
    },
    {
        "name": "social_manager",
        "description": (
            "Social-Media-Content-Manager: Erstellt, listet und veröffentlicht "
            "Social-Media-Posts (Instagram, TikTok, Twitter/X, LinkedIn, YouTube, Facebook). "
            "Aktionen: create (Post-Entwurf erstellen), list (Entwürfe anzeigen), "
            "publish (veröffentlichen), analytics (Statistiken), platforms (verfügbare Plattformen)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "create | list | publish | analytics | platforms"
                },
                "platform": {
                    "type": "STRING",
                    "description": "instagram | tiktok | twitter | linkedin | youtube | facebook"
                },
                "content": {
                    "type": "STRING",
                    "description": "Text des Posts (bei action=create)"
                },
                "media": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Liste von Dateipfaden für Bilder/Videos"
                },
                "schedule": {
                    "type": "STRING",
                    "description": "Geplanter Zeitpunkt (optional, ISO-Format)"
                },
                "draft_path": {
                    "type": "STRING",
                    "description": "Pfad zum Entwurf (bei action=publish)"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "video_creator",
        "description": (
            "Erstellt und bearbeitet Videos mit FFmpeg. "
            "Aktionen: create (Video aus Bildern + Audio erstellen), "
            "trim (Video schneiden), concat (Videos zusammenfügen), "
            "text (Text-Overlay hinzufügen), info (FFmpeg-Status prüfen)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "create | trim | concat | text | info"
                },
                "images": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Bilddateien für Video-Erstellung"
                },
                "audio": {
                    "type": "STRING",
                    "description": "Audiodatei für Video-Hintergrund (optional)"
                },
                "duration": {
                    "type": "NUMBER",
                    "description": "Sekunden pro Bild (default: 3.0)"
                },
                "input": {
                    "type": "STRING",
                    "description": "Eingabedatei (bei trim/text)"
                },
                "start": {
                    "type": "STRING",
                    "description": "Startzeit (HH:MM:SS) für trim"
                },
                "end": {
                    "type": "STRING",
                    "description": "Endzeit (HH:MM:SS) für trim"
                },
                "text": {
                    "type": "STRING",
                    "description": "Text für Overlay (bei action=text)"
                },
                "paths": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Videodateien für concat"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "claude_bridge",
        "description": (
            "Claude Code (Anthropic) – KI-Programmier-Assistent. "
            "Aktionen: chat (Unterhaltung/Abfrage), write (Code schreiben + speichern), "
            "explain (Code erklären), debug (Fehler suchen + beheben), "
            "refactor (Code optimieren/refaktorisieren), review (Code-Review), "
            "project_task (an einem BESTEHENDEN Projekt weiterprogrammieren: liest relevante Dateien, "
            "setzt die Aufgabe um, schreibt Änderungen direkt ins Projekt, testet optional und behebt Fehler iterativ — "
            "nutze dies für 'mach an meiner App weiter', 'behebe den Fehler in Projekt X', neue Features in bestehendem Code). "
            "Erfordert anthropic_api_key in config/api_keys.json."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "chat | write | explain | debug | refactor | review"
                },
                "prompt": {
                    "type": "STRING",
                    "description": "Aufgabenbeschreibung oder Frage"
                },
                "code": {
                    "type": "STRING",
                    "description": "Quellcode (bei explain/debug/refactor)"
                },
                "language": {
                    "type": "STRING",
                    "description": "Programmiersprache (default: python)"
                },
                "output_path": {
                    "type": "STRING",
                    "description": "Dateipfad zum Speichern (bei action=write)"
                },
                "file_path": {
                    "type": "STRING",
                    "description": "Pfad zu einer existierenden Datei (bei review)"
                },
                "system": {
                    "type": "STRING",
                    "description": "System-Prompt für Claude (optional)"
                },
                "project_path": {
                    "type": "STRING",
                    "description": "Pfad zum Projektordner (bei action=project_task)"
                },
                "run_command": {
                    "type": "STRING",
                    "description": "Optionaler Befehl, um die Änderung zu testen (bei action=project_task), z.B. 'python main.py --check'"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "project_watch",
        "description": (
            "Überwacht Projektordner selbstständig im Hintergrund auf Fehler (Syntaxfehler, Tracebacks in Logs) "
            "und meldet neue Probleme proaktiv, ohne dass der Nutzer fragen muss. "
            "Aktionen: add (Projekt hinzufügen, braucht path), remove (entfernen), list (auflisten), "
            "scan_now (sofort prüfen)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "add | remove | list | scan_now"},
                "path": {"type": "STRING", "description": "Ordnerpfad des Projekts (bei add/remove)"},
                "name": {"type": "STRING", "description": "Anzeigename des Projekts (optional)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "hermes_agent",
        "description": (
            "Delegiert echte Arbeit an den Hermes Agent (Nous Research): ein autonomer Agent mit Terminal, "
            "Dateisystem, Web-Recherche, Code-Ausführung und lernenden Skills. Nutze ihn für mehrstufige Aufgaben, "
            "die mehr als eine Antwort brauchen: recherchieren und Bericht schreiben, Dateien/Projekte anlegen, "
            "Code schreiben und testen, Daten auswerten, Server/Repos bearbeiten. "
            "action='start' läuft im Hintergrund und meldet sich mit einer Benachrichtigung (für längere Aufträge), "
            "action='run' wartet auf das Ergebnis (für kurze Aufträge), action='status' prüft die Verbindung, "
            "action='list' zeigt die letzten Aufträge."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "start | run | status | list (Standard: start)"},
                "task": {"type": "STRING", "description": "Vollständige, eigenständige Auftragsbeschreibung inkl. Ziel und gewünschtem Ergebnis"},
            },
            "required": ["action"]
        }
    },
]
