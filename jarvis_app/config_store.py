"""Einstellungen und API-Keys – immer im Datenverzeichnis des aktuellen Benutzers.

Welcher Benutzer „aktuell“ ist, bestimmt `userdata.user_scope(...)` (setzt das
Datenverzeichnis über jarvis_core.paths). Ohne Scope gilt der Projektordner (Besitzer).
"""
from __future__ import annotations

import json
import os
import platform

from config import settings as jarvis_settings
from jarvis_core.paths import PROJECT_ROOT, DataPath, data_root

CONFIG_DIR = DataPath("config")
API_KEYS_PATH = DataPath("config", "api_keys.json")
MAIN_API_KEYS = PROJECT_ROOT / "config" / "api_keys.json"

# Umgebungsvariable → Schlüssel in api_keys.json
ENV_KEYS = {
    "GEMINI_API_KEY": "gemini_api_key",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "TANKERKOENIG_API_KEY": "tankerkoenig_api_key",
}
KEY_FIELDS = ["gemini_api_key", "openrouter_api_key", "anthropic_api_key", "tankerkoenig_api_key"]
# Diese Server-Keys dürfen Lizenz-Nutzer mitverwenden (sofern ihre Lizenz es erlaubt)
SHAREABLE_KEYS = ["gemini_api_key", "openrouter_api_key", "tankerkoenig_api_key"]


def os_name() -> str:
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "mac"
    return "linux"


def is_main_root() -> bool:
    return data_root() == PROJECT_ROOT


# ── settings.json ──

def load_settings() -> dict:
    return jarvis_settings.load()


def save_settings(data: dict) -> None:
    current = jarvis_settings.load()
    current.update(data)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    jarvis_settings.save(current)
    _write_legacy_files(current)


def _write_legacy_files(cfg: dict) -> None:
    """Einige Actions lesen noch die alten Einzeldateien – synchron halten."""
    accounts = cfg.get("email_accounts") or []
    if accounts:
        a0 = accounts[0]
        (CONFIG_DIR / "email_config.json").write_text(json.dumps({
            "email": a0.get("email", ""), "password": a0.get("password", ""),
            "imap_server": a0.get("imap_server", "imap.gmail.com"),
            "smtp_server": a0.get("smtp_server", "smtp.gmail.com"),
            "smtp_port": a0.get("smtp_port", 587),
        }, indent=2), encoding="utf-8")
    jds = cfg.get("jds_config") or {}
    if jds.get("base_url"):
        (CONFIG_DIR / "jds_config.json").write_text(json.dumps(jds, indent=2), encoding="utf-8")


# ── api_keys.json ──

def load_api_keys() -> dict:
    try:
        return json.loads(API_KEYS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_api_keys(data: dict) -> None:
    data["os_system"] = os_name()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    API_KEYS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_api_keys(updates: dict) -> None:
    """Eigene Keys des Benutzers setzen. Ein eigener Key ersetzt einen mitgenutzten Server-Key."""
    data = load_api_keys()
    shared = set(data.get("_shared", []))
    for k, v in updates.items():
        v = str(v or "").strip()
        if v:
            data[k] = v
            shared.discard(k)
    data["_shared"] = sorted(shared)
    _write_api_keys(data)


def remove_api_key(field: str) -> None:
    data = load_api_keys()
    data.pop(field, None)
    data["_shared"] = [k for k in data.get("_shared", []) if k != field]
    _write_api_keys(data)


def server_keys() -> dict:
    """Keys des Besitzers/Servers (Umgebungsvariablen haben Vorrang)."""
    try:
        keys = json.loads(MAIN_API_KEYS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        keys = {}
    for env, field in ENV_KEYS.items():
        if os.environ.get(env):
            keys[field] = os.environ[env]
    return keys


def sync_shared_keys(allowed: bool) -> None:
    """Im Benutzer-Verzeichnis die mitgenutzten Server-Keys eintragen bzw. entfernen."""
    if is_main_root():
        return
    data = load_api_keys()
    shared = set(data.get("_shared", []))
    server = server_keys()
    changed = False
    for field in SHAREABLE_KEYS:
        own = data.get(field) and field not in shared
        if own:
            continue
        if allowed and server.get(field):
            if data.get(field) != server[field]:
                data[field] = server[field]
                changed = True
            shared.add(field)
        elif field in shared:
            data.pop(field, None)
            shared.discard(field)
            changed = True
    if changed or "os_system" not in data or sorted(shared) != data.get("_shared"):
        data["_shared"] = sorted(shared)
        _write_api_keys(data)


def ensure_api_keys() -> None:
    """Besitzer-Verzeichnis: Keys aus Umgebungsvariablen (Render) übernehmen und os_system setzen."""
    data = load_api_keys()
    for env, field in ENV_KEYS.items():
        if os.environ.get(env):
            data[field] = os.environ[env]
    _write_api_keys(data)
    secret = os.environ.get("ADMIN_API_SECRET", "")
    if secret and not load_settings().get("admin_api_secret"):
        save_settings({"admin_api_secret": secret})


def gemini_key() -> str:
    key = load_api_keys().get("gemini_api_key", "")
    if not key and is_main_root():
        key = os.environ.get("GEMINI_API_KEY", "")
    return key or ""


def key_status() -> dict:
    keys = load_api_keys()
    shared = set(keys.get("_shared", []))
    return {k: {"set": bool(keys.get(k)), "shared": k in shared,
                "preview": "Server-Key" if k in shared else mask(keys.get(k, ""))} for k in KEY_FIELDS}


def admin_secret() -> str:
    """Secret für Autoupdate/Desktop-Sync: immer das des Besitzers."""
    if os.environ.get("ADMIN_API_SECRET"):
        return os.environ["ADMIN_API_SECRET"]
    try:
        return json.loads((PROJECT_ROOT / "config" / "settings.json").read_text(encoding="utf-8")).get(
            "admin_api_secret", "") or ""
    except (OSError, ValueError):
        return ""


def mask(value: str) -> str:
    if not value:
        return ""
    return value[:4] + "…" + value[-4:] if len(value) > 10 else "••••"
