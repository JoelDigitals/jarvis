"""Autoupdate API – Apps/Versionen verwalten + Update-Check"""
import json, os, re, threading
from datetime import datetime
from functools import wraps
from pathlib import Path
from flask import Blueprint, jsonify, request

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "config" / "autoupdate"
DATA_DIR.mkdir(parents=True, exist_ok=True)
APPS_FILE = DATA_DIR / "apps.json"
_lock = threading.Lock()

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")

autoupdate_bp = Blueprint("autoupdate", __name__)


def _admin_secret() -> str:
    secret = os.environ.get("ADMIN_API_SECRET", "")
    if secret:
        return secret
    try:
        from server.app import _load_settings
        return (_load_settings().get("admin_api_secret") or "")
    except Exception:
        return ""


def require_admin(fn):
    """Schützt schreibende Endpunkte (POST/DELETE) mit dem Admin-API-Secret."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        secret = _admin_secret()
        if secret and request.headers.get("X-Admin-Secret") != secret:
            return jsonify({"error": "Nicht autorisiert"}), 401
        return fn(*args, **kwargs)
    return wrapper


def _load():
    if APPS_FILE.exists():
        return json.loads(APPS_FILE.read_text(encoding="utf-8"))
    return {"apps": []}


def _save(data):
    APPS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _parse_version(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


@autoupdate_bp.route("/api/autoupdate/apps", methods=["GET"])
def list_apps():
    data = _load()
    return jsonify(data["apps"])


@autoupdate_bp.route("/api/autoupdate/apps", methods=["POST"])
@require_admin
def create_app():
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    slug = (body.get("slug") or "").strip()
    desc = (body.get("description") or "").strip()
    if not name or not slug:
        return jsonify({"error": "name und slug erforderlich"}), 400
    data = _load()
    for app in data["apps"]:
        if app["slug"] == slug:
            return jsonify({"error": "App existiert bereits"}), 409
    app = {"name": name, "slug": slug, "description": desc, "versions": []}
    data["apps"].append(app)
    _save(data)
    return jsonify(app), 201


@autoupdate_bp.route("/api/autoupdate/apps/<slug>", methods=["DELETE"])
@require_admin
def delete_app(slug):
    data = _load()
    data["apps"] = [a for a in data["apps"] if a["slug"] != slug]
    _save(data)
    return jsonify({"ok": True})


@autoupdate_bp.route("/api/autoupdate/versions/<slug>", methods=["GET"])
def list_versions(slug):
    data = _load()
    for app in data["apps"]:
        if app["slug"] == slug:
            return jsonify(app["versions"])
    return jsonify({"error": "App nicht gefunden"}), 404


@autoupdate_bp.route("/api/autoupdate/versions/<slug>", methods=["POST"])
@require_admin
def add_version(slug):
    body = request.get_json(force=True)
    version = (body.get("version") or "").strip()
    if not VERSION_RE.match(version):
        return jsonify({"error": "Version muss Format x.x.x.x haben"}), 400
    download_link = (body.get("download_link") or "").strip()
    release_notes = (body.get("release_notes") or "").strip()
    release_date = (body.get("release_date") or datetime.now().strftime("%Y-%m-%d")).strip()
    if not download_link:
        return jsonify({"error": "download_link erforderlich"}), 400
    data = _load()
    for app in data["apps"]:
        if app["slug"] == slug:
            for v in app["versions"]:
                if v["version"] == version:
                    return jsonify({"error": "Version existiert bereits"}), 409
            entry = {
                "version": version,
                "release_date": release_date,
                "download_link": download_link,
                "release_notes": release_notes,
                "is_active": True,
            }
            app["versions"].append(entry)
            app["versions"].sort(key=lambda x: _parse_version(x["version"]), reverse=True)
            _save(data)
            return jsonify(entry), 201
    return jsonify({"error": "App nicht gefunden"}), 404


@autoupdate_bp.route("/api/autoupdate/check/<slug>", methods=["GET"])
def check_update(slug):
    current = (request.args.get("current_version") or "").strip()
    if not VERSION_RE.match(current):
        return jsonify({"error": "current_version muss Format x.x.x.x haben"}), 400
    data = _load()
    for app in data["apps"]:
        if app["slug"] == slug:
            active = [v for v in app["versions"] if v.get("is_active", True)]
            if not active:
                return jsonify({
                    "update_available": False,
                    "latest_version": current,
                    "download_link": None,
                    "release_notes": None,
                })
            latest = active[0]
            if _parse_version(latest["version"]) > _parse_version(current):
                return jsonify({
                    "update_available": True,
                    "latest_version": latest["version"],
                    "download_link": latest["download_link"],
                    "release_notes": latest["release_notes"],
                    "release_date": latest["release_date"],
                })
            return jsonify({
                "update_available": False,
                "latest_version": latest["version"],
                "download_link": None,
                "release_notes": None,
            })
    return jsonify({"error": "App nicht gefunden"}), 404
