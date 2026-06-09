import json
import sys
import time
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from typing import Optional

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

JDS_CONFIG_PATH = _base_dir() / "config" / "jds_config.json"

MESZ = timezone(timedelta(hours=2))  # UTC+2

def _fmt_dt(iso_str: str) -> str:
    """Formatiert ISO-String (UTC) → deutsch 'DD.MM. HH:MM' (MESZ)."""
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(MESZ)
        return dt.strftime("%d.%m. %H:%M")
    except:
        return iso_str[:16]

def _fmt_date(iso_str: str) -> str:
    """Formatiert ISO-Datum → deutsch 'DD.MM.YYYY'."""
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(MESZ)
        return dt.strftime("%d.%m.%Y")
    except:
        return iso_str[:10]

def _load_config() -> dict:
    if JDS_CONFIG_PATH.exists():
        return json.loads(JDS_CONFIG_PATH.read_text(encoding="utf-8"))
    return {}

def _save_config(cfg: dict):
    JDS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    JDS_CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")

class JDSClient:
    def __init__(self):
        self._config = _load_config()
        self._base_url = self._config.get("base_url", "").rstrip("/")
        self._team_code = self._config.get("team_code", "")
        self._api_token = self._config.get("api_token", "")
        self._connected = False
        self._team_name = ""
        self._user_name = ""

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def team_name(self) -> str:
        return self._team_name

    def configure(self, base_url: str, team_code: str, api_token: str) -> str:
        self._base_url = base_url.rstrip("/")
        self._team_code = team_code
        self._api_token = api_token
        _save_config({
            "base_url": self._base_url,
            "team_code": self._team_code,
            "api_token": self._api_token,
        })
        self._connected = False
        return f"JDS konfiguriert: {self._base_url}"

    def _headers(self) -> dict:
        return {
            "X-Team-Code": self._team_code,
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

    def connect(self) -> str:
        if not self._base_url or not self._team_code or not self._api_token:
            return "JDS nicht konfiguriert. Bitte zuerst einrichten mit: jds_connect(base_url, team_code, api_token)"

        if not _REQUESTS_OK:
            return "requests nicht installiert. pip install requests"

        try:
            resp = requests.get(
                f"{self._base_url}/api/v2/info/",
                headers=self._headers(),
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    self._team_name = data.get("team_name") or data.get("name") or ""
                    user_data = data.get("user")
                    if isinstance(user_data, dict):
                        self._user_name = user_data.get("username") or user_data.get("name") or ""
                    else:
                        self._user_name = data.get("username") or ""
                else:
                    self._team_name = ""
                    self._user_name = ""
                self._connected = True
                return f"JDS verbunden: Team={self._team_name}, User={self._user_name}"
            elif resp.status_code == 401:
                return "JDS Auth fehlgeschlagen. Team-Code oder Token ungültig."
            else:
                return f"JDS Fehler: HTTP {resp.status_code}"
        except requests.ConnectionError:
            return f"JDS nicht erreichbar: {self._base_url}"
        except Exception as e:
            return f"JDS Fehler: {e}"

    def _get(self, endpoint: str, params: dict = None) -> dict:
        if not self._connected:
            return {"error": "Nicht verbunden"}
        try:
            resp = requests.get(
                f"{self._base_url}{endpoint}",
                headers=self._headers(),
                params=params,
                timeout=8,
            )
            if resp.status_code == 200:
                return {"ok": True, "data": resp.json()}
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def _post(self, endpoint: str, data: dict) -> dict:
        if not self._connected:
            return {"error": "Nicht verbunden"}
        try:
            resp = requests.post(
                f"{self._base_url}{endpoint}",
                headers=self._headers(),
                json=data,
                timeout=8,
            )
            if resp.status_code in (200, 201):
                return {"ok": True, "data": resp.json()}
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def _put(self, endpoint: str, data: dict) -> dict:
        if not self._connected:
            return {"error": "Nicht verbunden"}
        try:
            resp = requests.put(
                f"{self._base_url}{endpoint}",
                headers=self._headers(),
                json=data,
                timeout=8,
            )
            if resp.status_code == 200:
                return {"ok": True, "data": resp.json()}
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _unwrap_list(data) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("results", "data", "items", "tasks", "records"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
            return []
        return []

    def _delete(self, endpoint: str) -> dict:
        if not self._connected:
            return {"error": "Nicht verbunden"}
        try:
            resp = requests.delete(
                f"{self._base_url}{endpoint}",
                headers=self._headers(),
                timeout=8,
            )
            if resp.status_code in (200, 204):
                return {"ok": True}
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def get_dashboard(self) -> str:
        r = self._get("/api/v2/dashboard/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        d = r["data"]
        return (
            f"Dashboard:\n"
            f"Offene Aufgaben: {d.get('open_tasks', 0)}\n"
            f"Heutige Meetings: {d.get('today_meetings', 0)}\n"
            f"Offene Leads: {d.get('open_leads', 0)}\n"
            f"Überfällige Rechnungen: {d.get('overdue_invoices', 0)}\n"
            f"Ausstehende Urlaube: {d.get('pending_vacations', 0)}"
        )

    def list_tasks(self, filter_by: str = "") -> str:
        params = {}
        if filter_by == "me":
            params["assigned_to"] = "me"
        elif filter_by.startswith("user:"):
            params["assigned_to"] = filter_by.split(":")[1]
        elif filter_by == "todo":
            params["status"] = "todo"
        params["limit"] = 20
        r = self._get("/api/v2/tasks/", params)
        if not r.get("ok"):
            return r.get("error", "Fehler")
        tasks = self._unwrap_list(r["data"])
        if not tasks:
            return "Keine Aufgaben gefunden."
        lines = [f"Aufgaben ({len(tasks)}):"]
        for t in tasks[:15]:
            status = "✓" if t.get("status") == "done" else "○"
            title = t.get("title", "?")
            lines.append(f"  {status} {title}")
        return "\n".join(lines)

    def create_task(self, title: str, description: str = "", assigned_to: str = "", due_date: str = "") -> str:
        data = {"title": title}
        if description:
            data["description"] = description
        if assigned_to:
            data["assigned_to"] = assigned_to
        if due_date:
            data["due_date"] = due_date
        r = self._post("/api/v2/tasks/", data)
        if r.get("ok"):
            return f"Aufgabe erstellt: [{r['data'].get('id')}] {title}"
        return r.get("error", "Fehler")

    def get_task(self, task_id: int) -> str:
        r = self._get(f"/api/v2/tasks/{task_id}/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        t = r["data"]
        lines = [
            f"[{t['id']}] {t.get('title', '?')}",
            f"Status: {t.get('status', '?')}  Progress: {t.get('progress', 0)}%",
        ]
        if t.get("description"):
            lines.append(f"Beschreibung: {t['description']}")
        if t.get("due_date"):
            lines.append(f"Fällig: {_fmt_date(t['due_date'])}")
        if t.get("subtask_count"):
            lines.append(f"Unteraufgaben: {t['subtask_count']}")
        return "\n".join(lines)

    def update_task(self, task_id: int, **kwargs) -> str:
        r = self._put(f"/api/v2/tasks/{task_id}/", kwargs)
        if r.get("ok"):
            return f"Aufgabe {task_id} aktualisiert."
        return r.get("error", "Fehler")

    def delete_task(self, task_id: int) -> str:
        r = self._delete(f"/api/v2/tasks/{task_id}/")
        if r.get("ok"):
            return f"Aufgabe {task_id} gelöscht."
        return r.get("error", "Fehler")

    def list_meetings(self) -> str:
        r = self._get("/api/v2/meetings/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        meetings = self._unwrap_list(r["data"])
        if not meetings:
            return "Keine Meetings gefunden."
        lines = ["Meetings:"]
        for m in meetings[:10]:
            date_str = _fmt_date(m.get("date", ""))
            title = m.get("title", "?")
            lines.append(f"  {date_str} — {title}")
        return "\n".join(lines)

    def list_leads(self, stage: str = "") -> str:
        params = {}
        if stage:
            params["stage"] = stage
        r = self._get("/api/v2/leads/", params)
        if not r.get("ok"):
            return r.get("error", "Fehler")
        leads = self._unwrap_list(r["data"])
        if not leads:
            return "Keine Leads gefunden."
        lines = [f"Leads ({len(leads)}):"]
        for l in leads[:15]:
            company = l.get("company_name", "?")
            stage_s = l.get("stage", "new")
            lines.append(f"  [{stage_s}] {company}")
        return "\n".join(lines)

    def list_customers(self) -> str:
        r = self._get("/api/v2/customers/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        customers = self._unwrap_list(r["data"])
        if not customers:
            return "Keine Kunden gefunden."
        lines = [f"Kunden ({len(customers)}):"]
        for c in customers[:15]:
            name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
            email = c.get("email", "")
            lines.append(f"  {name} — {email}")
        return "\n".join(lines)

    def list_products(self) -> str:
        r = self._get("/api/v2/products/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        products = self._unwrap_list(r["data"])
        if not products:
            return "Keine Produkte gefunden."
        lines = [f"Produkte ({len(products)}):"]
        for p in products[:15]:
            name = p.get("name", "?")
            price = p.get("price", "?")
            stock = p.get("stock", 0)
            lines.append(f"  {name} — {price}€ (Lager: {stock})")
        return "\n".join(lines)

    def list_vacations(self, status: str = "pending") -> str:
        params = {}
        if status:
            params["status"] = status
        r = self._get("/api/v2/vacations/", params)
        if not r.get("ok"):
            return r.get("error", "Fehler")
        vactions = self._unwrap_list(r["data"])
        if not vactions:
            return "Keine Urlaubsanträge gefunden."
        lines = [f"Urlaubsanträge ({len(vactions)}):"]
        for v in vactions[:10]:
            user = v.get("user_name", "?")
            dates = f"{_fmt_date(v.get('start_date', ''))} — {_fmt_date(v.get('end_date', ''))}"
            lines.append(f"  {user}: {dates}")
        return "\n".join(lines)

    def list_deliveries(self) -> str:
        r = self._get("/api/v2/deliveries/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        deliveries = self._unwrap_list(r["data"])
        if not deliveries:
            return "Keine Lieferungen gefunden."
        lines = [f"Lieferungen ({len(deliveries)}):"]
        for d in deliveries[:10]:
            product = d.get("product_name", "?")
            qty = d.get("quantity", 0)
            supplier = d.get("supplier", "?")
            lines.append(f"  {product} x{qty} von {supplier}")
        return "\n".join(lines)

    def list_invoices(self, status: str = "") -> str:
        params = {}
        if status:
            params["status"] = status
        r = self._get("/api/v2/invoices/", params)
        if not r.get("ok"):
            return r.get("error", "Fehler")
        invoices = self._unwrap_list(r["data"])
        if not invoices:
            return "Keine Rechnungen gefunden."
        lines = [f"Rechnungen ({len(invoices)}):"]
        for inv in invoices[:10]:
            title = inv.get("title", "?")
            inv_status = inv.get("status", "?")
            amount = inv.get("total", "?")
            lines.append(f"  {title} — {amount}€ [{inv_status}]")
        return "\n".join(lines)

    def list_events(self, days: int = 7) -> str:
        from datetime import datetime, timedelta
        now = datetime.now()
        from_str = now.isoformat()
        to_str = (now + timedelta(days=days)).isoformat()
        r = self._get("/api/v2/events/", {"from": from_str, "to": to_str})
        if not r.get("ok"):
            return r.get("error", "Fehler")
        events = self._unwrap_list(r["data"])
        if not events:
            return f"Keine Events in den nächsten {days} Tagen."
        lines = [f"Events ({len(events)}):"]
        for e in events[:10]:
            title = e.get("title", "?")
            start = _fmt_dt(e.get("start_time", ""))
            lines.append(f"  {start} — {title}")
        return "\n".join(lines)

    def list_notifications(self, unread_only: bool = True) -> str:
        params = {}
        if unread_only:
            params["unread"] = "true"
        r = self._get("/api/v2/notifications/", params)
        if not r.get("ok"):
            return r.get("error", "Fehler")
        notifs = self._unwrap_list(r["data"])
        if not notifs:
            return "Keine Benachrichtigungen."
        lines = [f"Benachrichtigungen ({len(notifs)}):"]
        for n in notifs[:10]:
            msg = n.get("message", "?")
            lines.append(f"  {msg}")
        return "\n".join(lines)

    def list_storage_locations(self) -> str:
        r = self._get("/api/v2/storage-locations/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        locs = self._unwrap_list(r["data"])
        if not locs:
            return "Keine Lagerorte."
        lines = ["Lagerorte:"]
        for l in locs[:20]:
            num = l.get("number", "?")
            loc_type = l.get("location_type", "")
            desc = l.get("description", "")
            lines.append(f"  {num} ({loc_type}) {desc}")
        return "\n".join(lines)

    def list_users(self) -> str:
        r = self._get("/api/v2/users/")
        if not r.get("ok"):
            return r.get("error", "Fehler")
        users = self._unwrap_list(r["data"])
        if not users:
            return "Keine Benutzer."
        lines = ["Teammitglieder:"]
        for u in users:
            name = u.get("full_name", u.get("username", "?"))
            email = u.get("email", "")
            lines.append(f"  {name} — {email}")
        return "\n".join(lines)


_client = JDSClient()


def jds_connect(parameters: dict, player=None) -> str:
    try:
        return _jds_connect_inner(parameters, player)
    except Exception as e:
        import traceback
        err = f"JDS-interner Fehler: {e}"
        traceback.print_exc()
        return err

def _jds_connect_inner(parameters: dict, player=None) -> str:
    action = parameters.get("action", "status").strip().lower()

    if action == "setup":
        base_url = parameters.get("base_url", "").strip()
        team_code = parameters.get("team_code", "").strip()
        api_token = parameters.get("api_token", "").strip()
        if not base_url or not team_code or not api_token:
            return "Bitte base_url, team_code und api_token angeben."
        return _client.configure(base_url, team_code, api_token)

    if action == "connect":
        result = _client.connect()
        if player:
            player.write_log(f"[JDS] {result}")
        return result

    if action == "status":
        if _client.is_connected:
            return f"JDS verbunden: {_client.team_name}"
        cfg = _load_config()
        if cfg.get("base_url"):
            return "JDS konfiguriert aber nicht verbunden. Aktion: connect"
        return "JDS nicht konfiguriert. Aktion: setup(base_url, team_code, api_token)"

    if not _client.is_connected:
        return "JDS nicht verbunden. Erst jds_connect(action='connect') aufrufen."

    if action == "dashboard":
        return _client.get_dashboard()

    if action == "tasks":
        filter_by = parameters.get("filter", "")
        return _client.list_tasks(filter_by)

    if action == "task":
        task_id = int(parameters.get("id", 0))
        if parameters.get("title"):
            return _client.create_task(
                parameters["title"],
                parameters.get("description", ""),
                parameters.get("assigned_to", ""),
                parameters.get("due_date", ""),
            )
        if parameters.get("update"):
            return _client.update_task(task_id, **json.loads(parameters["update"]))
        if parameters.get("delete"):
            return _client.delete_task(task_id)
        return _client.get_task(task_id)

    if action == "meetings":
        return _client.list_meetings()

    if action == "leads":
        return _client.list_leads(parameters.get("stage", ""))

    if action == "customers":
        return _client.list_customers()

    if action == "products":
        return _client.list_products()

    if action == "vacations":
        return _client.list_vacations(parameters.get("status", "pending"))

    if action == "deliveries":
        return _client.list_deliveries()

    if action == "invoices":
        return _client.list_invoices(parameters.get("status", ""))

    if action == "events":
        return _client.list_events(int(parameters.get("days", 7)))

    if action == "notifications":
        return _client.list_notifications()

    if action == "storage":
        return _client.list_storage_locations()

    if action == "users":
        return _client.list_users()

    return f"Unbekannte Aktion: {action}"
