"""JARVIS Auth – Lizenz-Keys, Benutzerregistrierung, Login, Session-Tokens"""
import hashlib
import hmac
import json
import os
import secrets
import time
from functools import wraps
from pathlib import Path

from flask import request, jsonify

BASE = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE / "config"
USERS_FILE  = CONFIG_DIR / "users.json"
KEYS_FILE   = CONFIG_DIR / "license_keys.json"
TOKENS_FILE = CONFIG_DIR / "sessions.json"

# Hardcoded Admin
_ADMIN_USER = "JoelDigitals"
_ADMIN_PASS = "Jo240207!"

_TOKEN_TTL = 30 * 24 * 3600   # 30 Tage
_MAX_KEY_USES = 20


# ── Hilfsfunktionen ───────────────────────────────────────────────────────

def _hash_pw(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{h.hex()}"

def _verify_pw(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        h2 = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return hmac.compare_digest(h2.hex(), h)
    except Exception:
        return False


def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Users ─────────────────────────────────────────────────────────────────

def _users() -> dict:
    return _load_json(USERS_FILE, {})

def _save_users(u: dict):
    _save_json(USERS_FILE, u)

def user_exists(username: str) -> bool:
    if username.lower() == _ADMIN_USER.lower():
        return True
    return username in _users()

def create_user(username: str, password: str) -> bool:
    users = _users()
    if username in users or username.lower() == _ADMIN_USER.lower():
        return False
    users[username] = {
        "password": _hash_pw(password),
        "role": "user",
        "created_at": int(time.time()),
    }
    _save_users(users)
    return True

def verify_user(username: str, password: str) -> bool:
    if username == _ADMIN_USER:
        return password == _ADMIN_PASS
    users = _users()
    if username not in users:
        return False
    return _verify_pw(password, users[username]["password"])

def get_role(username: str) -> str:
    if username == _ADMIN_USER:
        return "admin"
    return _users().get(username, {}).get("role", "user")


# ── Sessions / Tokens ─────────────────────────────────────────────────────

def _sessions() -> dict:
    return _load_json(TOKENS_FILE, {})

def _save_sessions(s: dict):
    _save_json(TOKENS_FILE, s)

def create_token(username: str) -> str:
    token = secrets.token_urlsafe(32)
    sessions = _sessions()
    # Alte Token des Users bereinigen
    sessions = {t: v for t, v in sessions.items() if v["username"] != username and v["expires"] > time.time()}
    sessions[token] = {"username": username, "expires": int(time.time() + _TOKEN_TTL)}
    _save_sessions(sessions)
    return token

def verify_token(token: str) -> str | None:
    """Gibt den Benutzernamen zurück oder None wenn ungültig/abgelaufen."""
    if not token:
        return None
    sessions = _sessions()
    entry = sessions.get(token)
    if not entry:
        return None
    if entry["expires"] < time.time():
        return None
    return entry["username"]

def revoke_token(token: str):
    sessions = _sessions()
    sessions.pop(token, None)
    _save_sessions(sessions)


# ── License Keys ──────────────────────────────────────────────────────────

def _keys() -> dict:
    return _load_json(KEYS_FILE, {})

def _save_keys(k: dict):
    _save_json(KEYS_FILE, k)

def generate_license_key(max_uses: int = _MAX_KEY_USES, label: str = "") -> str:
    key = "JARVIS-" + secrets.token_hex(8).upper()
    keys = _keys()
    keys[key] = {
        "max_uses": max_uses,
        "uses": 0,
        "label": label,
        "created_at": int(time.time()),
        "active": True,
    }
    _save_keys(keys)
    return key

def use_license_key(key: str) -> tuple[bool, str]:
    """Verbraucht einen Einsatz. Gibt (ok, message) zurück."""
    keys = _keys()
    if key not in keys:
        return False, "Ungültiger Lizenzschlüssel."
    entry = keys[key]
    if not entry.get("active", True):
        return False, "Dieser Schlüssel wurde deaktiviert."
    if entry["uses"] >= entry["max_uses"]:
        return False, "Lizenzschlüssel aufgebraucht (max. Aktivierungen erreicht)."
    entry["uses"] += 1
    _save_keys(keys)
    return True, "OK"

def list_license_keys() -> list:
    keys = _keys()
    return [
        {
            "key": k,
            "label": v.get("label", ""),
            "uses": v["uses"],
            "max_uses": v["max_uses"],
            "active": v.get("active", True),
            "created_at": v.get("created_at"),
        }
        for k, v in keys.items()
    ]

def revoke_license_key(key: str) -> bool:
    keys = _keys()
    if key not in keys:
        return False
    keys[key]["active"] = False
    _save_keys(keys)
    return True


# ── Flask Decorators ──────────────────────────────────────────────────────

def _get_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("jarvis_token", "")

def require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = _get_token()
        username = verify_token(token)
        if not username:
            return jsonify({"error": "Nicht eingeloggt"}), 401
        request.jarvis_user = username
        request.jarvis_role = get_role(username)
        return f(*args, **kwargs)
    return wrapper

def require_admin_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = _get_token()
        username = verify_token(token)
        if not username or get_role(username) != "admin":
            return jsonify({"error": "Kein Admin-Zugriff"}), 403
        request.jarvis_user = username
        request.jarvis_role = "admin"
        return f(*args, **kwargs)
    return wrapper
