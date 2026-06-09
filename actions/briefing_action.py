import json, threading
from pathlib import Path
import sys
from datetime import datetime

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _call_with_timeout(fn, timeout=6):
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
                return str(r)
        return ""
    except Exception as e:
        return ""

def _get_jds_tasks() -> dict:
    try:
        from actions.jds_client import jds_connect
        r = _call_with_timeout(lambda: jds_connect({"action": "tasks", "filter": "me"}), 5)
        if r and "nicht verbunden" not in r.lower() and "nicht konfiguriert" not in r.lower():
            lines = [l.strip() for l in r.split("\n") if l.strip()]
            task_lines = [l for l in lines if l.startswith("\u25CB") or l.startswith("\u2713")]
            count_line = [l for l in lines if "Aufgaben" in l]
            count = 0
            if count_line:
                try: count = int(count_line[0].split("(")[1].split(")")[0])
                except: count = len(task_lines)
            open_tasks = [l for l in task_lines if l.startswith("\u25CB")]
            return {"count": count, "open": open_tasks[:5]}
        return {}
    except Exception as e:
        return {}

def _get_jds_events() -> list:
    try:
        from actions.jds_client import jds_connect
        r = _call_with_timeout(lambda: jds_connect({"action": "events", "days": 7}), 5)
        if r and "nicht verbunden" not in r.lower() and "Keine Events" not in r:
            lines = [l.strip() for l in r.split("\n") if l.strip()]
            events = [l for l in lines if l.startswith("\U0001F4C5")]
            return events[:5]
        return []
    except Exception as e:
        return []

def _get_jds_meetings() -> list:
    try:
        from actions.jds_client import jds_connect
        r = _call_with_timeout(lambda: jds_connect({"action": "meetings"}), 5)
        if r and "nicht verbunden" not in r.lower() and "Keine Meetings" not in r:
            lines = [l.strip() for l in r.split("\n") if l.strip()]
            meetings = [l for l in lines if l.startswith("\U0001F4C5")]
            return meetings[:5]
        return []
    except Exception as e:
        return []

def _get_jds_dashboard() -> dict:
    try:
        from actions.jds_client import jds_connect
        r = _call_with_timeout(lambda: jds_connect({"action": "dashboard"}), 5)
        if r and "nicht verbunden" not in r.lower():
            d = {}
            for line in r.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    d[k.strip().lower()] = v.strip()
            return d
        return {}
    except Exception as e:
        return {}

def _get_emails() -> str:
    try:
        from actions.email_manager import email_action
        r = _call_with_timeout(lambda: email_action({"action": "list", "count": 5, "unread_only": True}), 5)
        if r and "fehler" not in r.lower()[:20] and "auth" not in r.lower()[:20]:
            return r.strip()
        return ""
    except Exception as e:
        return ""

def _get_admin_briefing() -> dict:
    try:
        from actions.admin_api import admin_action
        r = _call_with_timeout(lambda: admin_action({"action": "briefing"}), 5)
        if r and "nicht konfiguriert" not in r:
            lines = [l.strip() for l in r.split("\n") if l.strip()]
            d = {"lines": lines}
            for l in lines:
                if "Termine" in l:
                    try: d["appointments"] = l.split(":")[1].strip()
                    except: pass
                elif "Blog" in l:
                    try: d["blog"] = l.split(":")[1].strip()
                    except: pass
                elif "Tickets" in l:
                    try: d["tickets"] = l.split(":")[1].strip()
                    except: pass
                elif "Bestellungen" in l:
                    try: d["orders"] = l.split(":")[1].strip()
                    except: pass
            return d
        return {}
    except Exception as e:
        return {}

def _get_user_name() -> str:
    try:
        p = _base_dir() / "config" / "settings.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")).get("user_name", "Sir")
    except:
        pass
    return "Sir"

def do_briefing(parameters: dict = None, player=None, session_memory=None) -> str:
    print("[BRIEFING] Starte...")
    params = parameters or {}
    name = _get_user_name()
    now = datetime.now()

    greeting = (params.get("greeting") or "").strip()
    if not greeting:
        h = now.hour
        if h < 11:
            greeting = "Guten Morgen"
        elif h < 17:
            greeting = "Guten Tag"
        else:
            greeting = "Guten Abend"

    sentences = [f"{greeting}, {name}! Heute ist der {now.strftime('%d. %B %Y')}.",]

    # ── Wetter ──
    weather = _get_weather()
    if weather:
        lines = [l.strip() for l in weather.split("\n") if l.strip()]
        current = [l for l in lines if "Aktuell" in l or "Aktuell" in l]
        forecast = [l for l in lines if "Vorhersage" in l or any(d in l for d in ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"))]
        if current:
            sentences.append("Wetter: " + current[0].replace("Aktuell:", "").strip())
        if forecast:
            sentences.append("Vorhersage: " + " | ".join(forecast[:2]))

    # ── Admin-Dashboard (volle Zeilen mit Kontext) ──
    admin = _get_admin_briefing()
    if admin and admin.get("lines"):
        context_lines = [l for l in admin["lines"] if ":" in l and l.split(":")[1].strip() != "0 anstehend" and l.split(":")[1].strip() != "0 offen"]
        if context_lines:
            sentences.append("Joel-Digitals: " + " — ".join(context_lines) + ".")

    # ── JDS Aufgaben + Kalender ──
    tasks = _get_jds_tasks()
    events = _get_jds_events()
    meetings = _get_jds_meetings()
    jds_dash = _get_jds_dashboard()

    jds_parts = []
    if tasks.get("open"):
        for t in tasks["open"][:5]:
            clean = t.replace("\u25CB", "").strip()
            if clean:
                jds_parts.append(clean)

    cal_entries = events + meetings
    if cal_entries:
        for e in cal_entries[:5]:
            clean = e.replace("\U0001F4C5", "").strip()
            if clean:
                jds_parts.append(clean)

    if jds_dash:
        m = jds_dash.get("heutige meetings", "0")
        o = jds_dash.get("uberfallige rechnungen", jds_dash.get("overdue_invoices", "0"))
        if m and m != "0":
            jds_parts.append(f"{m} Meeting{'s' if m != '1' else ''} heute")
        if o and o != "0":
            jds_parts.append(f"{o} überfällige Rechnung{'en' if o != '1' else ''}")

    if jds_parts:
        sentences.append("JDS: " + " | ".join(jds_parts) + ".")

    # ── E-Mails ──
    emails = _get_emails()
    if emails and "Keine" not in emails:
        lines = [l.strip() for l in emails.split("\n") if l.strip()]
        subjects = [l for l in lines if l and not l.startswith("E-Mail") and not l.startswith("Keine")]
        if subjects:
            sentences.append(f"E-Mails: {len(subjects)} ungelesen.")

    # ── Abschluss ──
    sentences.append("Soweit der aktuelle Stand. Was kann ich für Sie tun?")

    result = " ".join(sentences)
    print(f"[BRIEFING] Ergebnis: {str(result)[:200]}")
    return f"BRIEFING-TEXT ZUM VORLESEN: {result}"
