import json, threading
from pathlib import Path
import sys
from datetime import datetime

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _call_with_timeout(fn, timeout=5):
    result = []
    def _run():
        try:
            result.append(fn())
        except Exception as e:
            result.append(e)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if not result:
        return None
    r = result[0]
    if isinstance(r, Exception):
        return None
    return r

def _get_home_location() -> str:
    try:
        p = _base_dir() / "config" / "settings.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")).get("home_location", "")
    except:
        pass
    return ""

def _get_weather() -> str:
    try:
        from actions.weather_report import weather_action
        city = _get_home_location()
        if city:
            r = _call_with_timeout(lambda: weather_action({"city": city, "days": 1}), 5)
            if r:
                print(f"[BRIEFING] Wetter: {str(r)[:80]}")
                return r
        return ""
    except Exception as e:
        print(f"[BRIEFING] Wetter-Fehler: {e}")
        return ""

def _get_jds_tasks() -> str:
    try:
        from actions.jds_client import jds_connect
        r = _call_with_timeout(lambda: jds_connect({"action": "tasks", "filter": "me"}), 5)
        if r:
            print(f"[BRIEFING] JDS: {str(r)[:80]}")
            if "nicht verbunden" not in r.lower() and "nicht konfiguriert" not in r.lower():
                lines = r.strip().split("\n")
                if len(lines) > 5:
                    return f"{len(lines)} Aufgaben. Nächste: " + "; ".join(lines[:5])
                return r.strip()
        return ""
    except Exception as e:
        print(f"[BRIEFING] JDS-Fehler: {e}")
        return ""

def _get_emails() -> str:
    try:
        from actions.email_manager import email_action
        r = _call_with_timeout(lambda: email_action({"action": "list", "count": 5, "unread_only": True}), 5)
        if r:
            print(f"[BRIEFING] Emails: {str(r)[:80]}")
            if "fehler" not in r.lower()[:20] and "auth" not in r.lower()[:20]:
                return r.strip()
        return ""
    except Exception as e:
        print(f"[BRIEFING] Email-Fehler: {e}")
        return ""

def _get_admin_briefing() -> str:
    try:
        from actions.admin_api import admin_action
        r = _call_with_timeout(lambda: admin_action({"action": "briefing"}), 5)
        if r:
            print(f"[BRIEFING] Admin: {str(r)[:80]}")
            if "nicht konfiguriert" not in r:
                return r.strip()
        return ""
    except Exception as e:
        print(f"[BRIEFING] Admin-Fehler: {e}")
        return ""

def do_briefing(parameters: dict = None, player=None, session_memory=None) -> str:
    print("[BRIEFING] Starte...")
    parts = []
    date_str = datetime.now().strftime("%d.%m.%Y")
    parts.append(f"Guten Morgen! Heute ist der {date_str}.")
    weather = _get_weather()
    if weather:
        parts.append(weather)
    tasks = _get_jds_tasks()
    if tasks:
        parts.append(f"JDS: {tasks}")
    emails = _get_emails()
    if emails:
        lines = emails.strip().split("\n")
        parts.append(f"E-Mail: {len(lines)} ungelesen.")
    admin = _get_admin_briefing()
    if admin:
        parts.append(admin)
    result = "\n\n".join(parts)
    if not result.strip():
        result = "Keine Daten verfügbar."
    print(f"[BRIEFING] Ergebnis: {str(result)[:200]}")
    return result
