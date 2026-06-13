import datetime, json, os, pickle, sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = BASE_DIR / "config" / "google_calendar_credentials.json"
TOKEN_FILE = BASE_DIR / "config" / "google_calendar_token.pickle"
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "rb") as f:
                creds = pickle.load(f)
        except:
            pass

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    if not creds or not creds.valid:
        if not CREDENTIALS_FILE.exists():
            return None, (
                "Keine Google Calendar Anmeldedaten gefunden.\n"
                f"1. Gehe zu https://console.cloud.google.com/apis/credentials\n"
                f"2. Erstelle OAuth 2.0 Client-ID (Desktop-App)\n"
                f"3. Lade sie herunter und speichere als:\n"
                f"   {CREDENTIALS_FILE}"
            )
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
        except Exception as e:
            return None, f"Google Calendar Authentifizierung fehlgeschlagen: {e}"

    try:
        service = build("calendar", "v3", credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Calendar API Fehler: {e}"


def _format_event(e) -> str:
    start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "?")
    end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", "?")
    summary = e.get("summary", "(Kein Titel)")
    location = e.get("location", "")
    desc = e.get("description", "")
    parts = [f"📅 {summary}", f"   Von: {start}", f"   Bis: {end}"]
    if location:
        parts.append(f"   Ort: {location}")
    if desc:
        parts.append(f"   Notiz: {desc[:200]}")
    return "\n".join(parts)


def calendar_action(parameters: dict = None, player=None) -> str:
    action = (parameters or {}).get("action", "list").strip().lower()
    service, err = _get_service()
    if err:
        return err

    try:
        if action == "list":
            max_results = int(parameters.get("max", 10))
            days = int(parameters.get("days", 7))
            time_min = datetime.datetime.utcnow().isoformat() + "Z"
            time_max = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat() + "Z"
            events_result = service.events().list(
                calendarId="primary", timeMin=time_min, timeMax=time_max,
                maxResults=max_results, singleEvents=True, orderBy="startTime"
            ).execute()
            events = events_result.get("items", [])
            if not events:
                return "Keine Termine in den nächsten Tagen."
            lines = [f"Termine (nächste {days} Tage):", ""]
            for e in events:
                lines.append(_format_event(e))
                lines.append("")
            return "\n".join(lines).strip()

        elif action == "today":
            max_results = int(parameters.get("max", 20))
            time_min = datetime.datetime.utcnow().isoformat() + "Z"
            time_max = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat() + "Z"
            events_result = service.events().list(
                calendarId="primary", timeMin=time_min, timeMax=time_max,
                maxResults=max_results, singleEvents=True, orderBy="startTime"
            ).execute()
            events = events_result.get("items", [])
            if not events:
                return "Keine Termine heute."
            lines = ["Heutige Termine:", ""]
            for e in events:
                lines.append(_format_event(e))
                lines.append("")
            return "\n".join(lines).strip()

        elif action == "create":
            summary = parameters.get("summary", "").strip()
            start_str = parameters.get("start", "").strip()
            end_str = parameters.get("end", "").strip()
            if not summary or not start_str:
                return "Bitte summary (Titel) und start (Startzeit) angeben."
            if not end_str:
                try:
                    start_dt = datetime.datetime.fromisoformat(start_str)
                    end_dt = start_dt + datetime.timedelta(hours=1)
                    end_str = end_dt.isoformat()
                except:
                    return f"Endzeit fehlt und konnte nicht automatisch berechnet werden."
            event = {
                "summary": summary,
                "start": {"dateTime": start_str, "timeZone": "Europe/Berlin"},
                "end": {"dateTime": end_str, "timeZone": "Europe/Berlin"},
            }
            location = parameters.get("location", "").strip()
            if location:
                event["location"] = location
            description = parameters.get("description", "").strip()
            if description:
                event["description"] = description
            created = service.events().insert(calendarId="primary", body=event).execute()
            return f"Termin erstellt: {summary} am {start_str} (Link: {created.get('htmlLink','')})"

        elif action == "update":
            event_id = parameters.get("event_id", "").strip()
            if not event_id:
                return "Bitte event_id angeben."
            event = service.events().get(calendarId="primary", eventId=event_id).execute()
            for key in ("summary", "location", "description"):
                val = parameters.get(key)
                if val is not None:
                    event[key] = str(val).strip()
            start_str = parameters.get("start", "").strip()
            if start_str:
                event["start"] = {"dateTime": start_str, "timeZone": "Europe/Berlin"}
            end_str = parameters.get("end", "").strip()
            if end_str:
                event["end"] = {"dateTime": end_str, "timeZone": "Europe/Berlin"}
            updated = service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
            return f"Termin aktualisiert: {updated.get('summary')}"

        elif action == "delete":
            event_id = parameters.get("event_id", "").strip()
            if not event_id:
                return "Bitte event_id angeben."
            summary = ""
            try:
                event = service.events().get(calendarId="primary", eventId=event_id).execute()
                summary = event.get("summary", "")
            except:
                pass
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            return f"Termin gelöscht: {summary or event_id}"

        elif action == "find":
            query = parameters.get("query", "").strip()
            if not query:
                return "Bitte eine Suchanfrage angeben."
            max_results = int(parameters.get("max", 10))
            events_result = service.events().list(
                calendarId="primary", maxResults=max_results, singleEvents=True,
                orderBy="startTime", q=query
            ).execute()
            events = events_result.get("items", [])
            if not events:
                return f"Keine Termine gefunden für: {query}"
            lines = [f"Gefundene Termine für '{query}':", ""]
            for e in events:
                lines.append(_format_event(e))
                lines.append("")
            return "\n".join(lines).strip()

        else:
            return f"Unbekannte Aktion: {action}. Verfügbar: list, today, create, update, delete, find"
    except Exception as e:
        return f"Calendar API Fehler: {e}"
