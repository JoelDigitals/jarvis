import json, os, sys
from pathlib import Path
from datetime import datetime

try:
    import requests
    _OK = True
except ImportError:
    _OK = False

BASE_URL = "https://joel-digitals.de/api/admin"

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_secret() -> str:
    try:
        p = _base_dir() / "config" / "settings.json"
        if p.exists():
            val = json.loads(p.read_text(encoding="utf-8")).get("admin_api_secret", "")
            if val:
                return val
    except: pass
    return os.environ.get("ADMIN_API_SECRET", "") or os.environ.get("admin_api_secret", "")

def _headers() -> dict:
    secret = _get_secret()
    if not secret:
        return {}
    return {
        "Authorization": f"Bearer {secret}",
        "Accept": "application/json",
    }

def _get(endpoint: str) -> dict:
    if not _OK:
        return {"error": "requests nicht installiert."}
    secret = _get_secret()
    if not secret:
        return {"error": "Admin-API-Secret nicht konfiguriert (Einstellungen → Admin-API)."}
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", headers=_headers(), timeout=15)
        if r.status_code == 200:
            return {"ok": True, "data": r.json()}
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}

def _post(endpoint: str, body: dict = None) -> dict:
    if not _OK:
        return {"error": "requests nicht installiert."}
    secret = _get_secret()
    if not secret:
        return {"error": "Admin-API-Secret nicht konfiguriert."}
    try:
        r = requests.post(f"{BASE_URL}{endpoint}", headers=_headers(), json=body, timeout=15)
        if r.status_code in (200, 201):
            return {"ok": True, "data": r.json()}
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}

def action_dashboard() -> str:
    r = _get("/dashboard/")
    if not r.get("ok"):
        return r.get("error", "Fehler")
    d = r["data"]
    lines = [
        "📊 Joel-Digitals Dashboard:",
        f"  Termine: {d.get('appointments', {}).get('pending', 0)} offen, {d.get('appointments', {}).get('today', 0)} heute",
        f"  Blog: {d.get('blog_views', 0)} Views, {d.get('blog_posts', 0)} Posts",
        f"  Tickets: {d.get('open_tickets', 0)} offen",
        f"  Bestellungen: {d.get('orders', {}).get('pending', 0)} offen, {d.get('orders', {}).get('shipped', 0)} versandt",
    ]
    return "\n".join(lines)

def action_appointments(status: str = "") -> str:
    r = _get("/appointments/")
    if not r.get("ok"):
        return r.get("error", "Fehler")
    apps = r["data"]
    if isinstance(apps, dict):
        apps = apps.get("results", apps.get("appointments", []))
    if not apps:
        return "Keine Termine gefunden."
    lines = ["📅 Termine:"]
    for a in (apps if isinstance(apps, list) else [apps]):
        if status and a.get("status") != status:
            continue
        date = a.get("date", "?")[:10]
        time = a.get("time", "?")[:5]
        name = a.get("name", a.get("customer", "?"))
        lines.append(f"  {date} {time} — {name} [{a.get('status', '?')}]")
    return "\n".join(lines) if len(lines) > 1 else "Keine passenden Termine."

def action_confirm_appointment(appointment_id: int) -> str:
    r = _post(f"/appointments/{appointment_id}/confirm/")
    if r.get("ok"):
        return f"Termin {appointment_id} bestätigt ✅"
    return r.get("error", "Fehler")

def action_reject_appointment(appointment_id: int) -> str:
    r = _post(f"/appointments/{appointment_id}/reject/")
    if r.get("ok"):
        return f"Termin {appointment_id} abgelehnt ❌"
    return r.get("error", "Fehler")

def action_blog_stats() -> str:
    r = _get("/blog-stats/")
    if not r.get("ok"):
        return r.get("error", "Fehler")
    d = r["data"]
    lines = [
        f"📝 Blog: {d.get('total_views', 0)} Views, {d.get('total_posts', 0)} Posts",
    ]
    top = d.get("top_posts", [])
    if top:
        lines.append("Top-Beiträge:")
        for i, p in enumerate(top[:10], 1):
            lines.append(f"  {i}. {p.get('title', '?')} — {p.get('views', 0)} Views")
    return "\n".join(lines)

def action_tickets(status: str = "", ticket_id: int = None) -> str:
    if ticket_id:
        r = _get(f"/support/tickets/{ticket_id}/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        t = r["data"]
        msgs = t.get("messages", [])
        lines = [
            f"🎫 Ticket #{ticket_id}: {t.get('subject', '?')}",
            f"  Status: {t.get('status', '?')}",
        ]
        for m in msgs[-5:]:
            sender = m.get("sender", "?")
            text = m.get("message", "")[:200]
            lines.append(f"  [{sender}] {text}")
        return "\n".join(lines)
    r = _get("/support/tickets/")
    if not r.get("ok"):
        return r.get("error", "Fehler")
    tickets = r["data"]
    if isinstance(tickets, dict):
        tickets = tickets.get("results", tickets.get("tickets", []))
    if not tickets:
        return "Keine Tickets."
    lines = ["🎫 Support-Tickets:"]
    for t in (tickets if isinstance(tickets, list) else [tickets]):
        if status and t.get("status") != status:
            continue
        lines.append(f"  #{t.get('id','?')} {t.get('subject','?')} [{t.get('status','?')}]")
    return "\n".join(lines)

def action_reply_ticket(ticket_id: int, message: str) -> str:
    if not message:
        return "Keine Nachricht angegeben."
    r = _post(f"/support/tickets/{ticket_id}/reply/", {"message": message})
    if r.get("ok"):
        return f"Antwort an Ticket #{ticket_id} gesendet ✅"
    return r.get("error", "Fehler")

def action_orders(status: str = "") -> str:
    r = _get("/orders/")
    if not r.get("ok"):
        return r.get("error", "Fehler")
    orders = r["data"]
    if isinstance(orders, dict):
        orders = orders.get("results", orders.get("orders", []))
    if not orders:
        return "Keine Bestellungen."
    lines = ["📦 Bestellungen:"]
    for o in (orders if isinstance(orders, list) else [orders]):
        if status and o.get("status") != status:
            continue
        date = (o.get("date") or o.get("created_at") or "?")[:10]
        customer = o.get("customer", o.get("name", "?"))
        total = o.get("total", o.get("amount", "?"))
        lines.append(f"  {date} — {customer} — {total}€ [{o.get('status', '?')}]")
    return "\n".join(lines)

def admin_action(parameters: dict, player=None) -> str:
    action = (parameters.get("action") or "dashboard").strip().lower()
    if action == "dashboard":
        return action_dashboard()
    elif action == "appointments":
        return action_appointments(parameters.get("status", ""))
    elif action == "confirm_appointment":
        return action_confirm_appointment(int(parameters.get("id", 0)))
    elif action == "reject_appointment":
        return action_reject_appointment(int(parameters.get("id", 0)))
    elif action == "blog":
        return action_blog_stats()
    elif action == "tickets":
        return action_tickets(parameters.get("status", ""), parameters.get("id"))
    elif action == "reply_ticket":
        return action_reply_ticket(int(parameters.get("id", 0)), parameters.get("message", ""))
    elif action == "orders":
        return action_orders(parameters.get("status", ""))
    elif action == "briefing":
        parts = [
            action_dashboard(),
            "",
            action_appointments(),
            "",
            action_orders("pending"),
        ]
        return "\n".join(parts)
    return f"Unbekannte Aktion: {action}"
