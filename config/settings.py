import json, os, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SETTINGS_PATH = BASE / "settings.json"

DEFAULT = {
    "user_name": "Sir",
    "home_location": "",
    "admin_api_secret": "",
    "default_sender": "",
    "email_accounts": [],
    "knowledge_sites": [],
    "briefing_enabled": True,
    "briefing_time": "08:00",
    "jds_config": {
        "base_url": "",
        "team_code": "",
        "api_token": "",
        "task_user_id": "",
    },
    "discord_config": {
        "bot_token": "",
        "allowed_channels": [],
    },
    "email_forward_to": "",
    "daily_report": {
        "enabled": True,
        "recipient_email": "",
        "times": ["08:00", "13:00", "18:00", "23:00"],
        "include_dashboard": True,
        "include_weather": True,
        "include_emails": True,
    },
}

def load():
    try:
        if SETTINGS_PATH.exists():
            d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            merged = DEFAULT.copy()
            merged.update(d)
            return merged
    except: pass
    return dict(DEFAULT)

def save(data):
    merged = dict(DEFAULT)
    merged.update(data)
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

def get(key, default=None):
    return load().get(key, default)

def set_key(key, value):
    d = load()
    d[key] = value
    save(d)

def add_email(name, email, password, imap="imap.gmail.com", smtp="smtp.gmail.com", smtp_port=587):
    d = load()
    accounts = d.get("email_accounts", [])
    accounts.append({
        "name": name, "email": email, "password": password,
        "imap_server": imap, "smtp_server": smtp, "smtp_port": smtp_port
    })
    d["email_accounts"] = accounts
    save(d)

def remove_email(name_or_email):
    d = load()
    d["email_accounts"] = [a for a in d.get("email_accounts", [])
                           if a.get("name") != name_or_email and a.get("email") != name_or_email]
    save(d)

def add_site(name, url, login_url, username, password, pages=None):
    d = load()
    sites = d.get("knowledge_sites", [])
    sites.append({
        "name": name, "url": url.rstrip("/"),
        "login_url": login_url, "username": username, "password": password,
        "pages": pages or []
    })
    d["knowledge_sites"] = sites
    save(d)
