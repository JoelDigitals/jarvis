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
    order_counts = d.get("order_counts", {})
    pending_orders = sum(1 for s, c in order_counts.items() if s.lower() in ("pending", "new"))
    lines = [
        "Joel-Digitals Dashboard:",
        f"  Termine: {len(d.get('appointments_upcoming', []))} anstehend",
        f"  Blog: {d.get('blog_views_total', 0)} Views, {d.get('blog_posts_total', 0)} Posts",
        f"  Tickets: {d.get('support_open_tickets', 0)} offen",
        f"  Bestellungen: {d.get('orders_total', 0)} gesamt, {pending_orders} offen",
    ]
    return "\n".join(lines)

def action_appointments(status: str = "") -> str:
    r = _get("/appointments/")
    if not r.get("ok"):
        return r.get("error", "Fehler")
    d = r["data"]
    all_apps = []
    for key in ("pending", "accepted", "confirmed"):
        for a in d.get(key, []):
            a["_status"] = key
            all_apps.append(a)
    if not all_apps:
        return "Keine Termine gefunden."
    lines = ["Termine:"]
    for a in all_apps:
        if status and a["_status"] != status:
            continue
        date = (a.get("date") or "?")[:10]
        time = (a.get("time") or "?")[:5]
        name = a.get("name", "?")
        s = a.get("_status", "?")
        lines.append(f"  {date} {time} — {name} [{s}]")
    return "\n".join(lines) if len(lines) > 1 else "Keine passenden Termine."

def action_confirm_appointment(appointment_id: int) -> str:
    r = _post(f"/appointments/{appointment_id}/confirm/")
    if r.get("ok"):
        return f"Termin {appointment_id} bestaetigt"
    return r.get("error", "Fehler")

def action_reject_appointment(appointment_id: int) -> str:
    r = _post(f"/appointments/{appointment_id}/reject/")
    if r.get("ok"):
        return f"Termin {appointment_id} abgelehnt"
    return r.get("error", "Fehler")

def action_blog_stats() -> str:
    r = _get("/blog-stats/")
    if not r.get("ok"):
        return r.get("error", "Fehler")
    d = r["data"]
    lines = [
        f"Blog: {d.get('total_views', 0)} Views, {d.get('published_posts', 0)} Posts",
    ]
    top = d.get("top_posts", [])
    if top:
        lines.append("Top-Beitraege:")
        for i, p in enumerate(top[:10], 1):
            lines.append(f"  {i}. {p.get('title_de', p.get('title', '?'))} — {p.get('views', 0)} Views")
    return "\n".join(lines)

def action_tickets(status: str = "", ticket_id: int = None) -> str:
    if ticket_id:
        r = _get(f"/support/tickets/{ticket_id}/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        t = r["data"]
        msgs = t.get("messages", [])
        lines = [
            f"Ticket #{ticket_id}: {t.get('subject', '?')}",
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
    d = r["data"]
    all_tickets = []
    for key in ("open", "recently_resolved", "closed"):
        for t in d.get(key, []):
            t["_status"] = key
            all_tickets.append(t)
    if not all_tickets:
        return "Keine Tickets."
    lines = ["Support-Tickets:"]
    for t in all_tickets:
        if status and t["_status"] != status:
            continue
        lines.append(f"  #{t.get('id','?')} {t.get('subject','?')} [{t['_status']}]")
    return "\n".join(lines)

def action_reply_ticket(ticket_id: int, message: str) -> str:
    if not message:
        return "Keine Nachricht angegeben."
    r = _post(f"/support/tickets/{ticket_id}/reply/", {"message": message})
    if r.get("ok"):
        return f"Antwort an Ticket #{ticket_id} gesendet"
    return r.get("error", "Fehler")

def action_orders(status: str = "") -> str:
    r = _get("/orders/")
    if not r.get("ok"):
        return r.get("error", "Fehler")
    d = r["data"]
    orders = d.get("recent_orders", [])
    if not orders:
        return "Keine Bestellungen."
    lines = ["Bestellungen:"]
    for o in orders:
        if status and o.get("status", "").lower() != status.lower():
            continue
        date = (o.get("created_at") or "?")[:10]
        name = f"{o.get('first_name', '')} {o.get('last_name', '')}".strip() or "?"
        total = o.get("total_amount", "?")
        lines.append(f"  {date} — {name} — {total} EUR [{o.get('status', '?')}]")
    return "\n".join(lines) if len(lines) > 1 else "Keine passenden Bestellungen."

def action_publish_blog(title: str, content: str, lang: str = "de", status: str = "published") -> str:
    if not title or not content:
        return "Titel und Inhalt erforderlich."
    r = _post("/blog/create/", {
        "title": title,
        "content": content,
        "lang": lang,
        "status": status,
    })
    if r.get("ok"):
        d = r["data"]
        post_id = d.get("id", d.get("post_id", "?"))
        return f"Blog-Beitrag veröffentlicht: [{post_id}] {title}"
    return r.get("error", "Fehler")

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
    elif action == "publish_blog":
        return action_publish_blog(
            parameters.get("title", ""),
            parameters.get("content", ""),
            parameters.get("lang", "de"),
            parameters.get("status", "published"),
        )
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
