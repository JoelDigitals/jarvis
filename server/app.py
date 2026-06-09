"""JARVIS Web-Server – Chat + Konfiguration + Mobile UI (Render.com ready)"""
import json, os, sys, threading
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "server" / "static"
TEMPLATES = BASE / "server" / "templates"

app = Flask(__name__, template_folder=str(TEMPLATES), static_folder=str(STATIC))
CORS(app)

CONFIG_DIR = BASE / "config"

def _load_settings():
    try:
        p = CONFIG_DIR / "settings.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except: pass
    return {}

def _save_settings(data):
    p = CONFIG_DIR / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_settings()
    existing.update(data)
    p.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    from server.handler import send_message
    data = request.get_json(force=True)
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "Leere Nachricht"}), 400
    try:
        answer, logs = send_message(text)
        return jsonify({"response": answer, "logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/reset", methods=["POST"])
def reset():
    import server.handler as h
    with h._session_lock:
        h._session = None
    return jsonify({"ok": True})

@app.route("/api/config", methods=["GET", "POST"])
def config():
    if request.method == "GET":
        return jsonify(_load_settings())
    data = request.get_json(force=True)
    _save_settings(data)
    return jsonify({"ok": True, "message": "Gespeichert."})

@app.route("/api/config/email", methods=["GET", "POST"])
def config_email():
    if request.method == "GET":
        cfg = _load_settings()
        return jsonify(cfg.get("email_accounts", []))
    data = request.get_json(force=True)
    cfg = _load_settings()
    cfg["email_accounts"] = data.get("accounts", [])
    _save_settings(cfg)
    if cfg["email_accounts"]:
        a0 = cfg["email_accounts"][0]
        (CONFIG_DIR / "email_config.json").write_text(json.dumps({
            "email": a0["email"], "password": a0["password"],
            "imap_server": a0["imap_server"], "smtp_server": a0["smtp_server"],
            "smtp_port": a0["smtp_port"],
        }, indent=2), encoding="utf-8")
    return jsonify({"ok": True})

@app.route("/api/config/jds", methods=["GET", "POST"])
def config_jds():
    if request.method == "GET":
        cfg = _load_settings()
        return jsonify(cfg.get("jds_config", {}))
    data = request.get_json(force=True)
    cfg = _load_settings()
    cfg["jds_config"] = {
        "base_url": data.get("base_url", ""),
        "team_code": data.get("team_code", ""),
        "api_token": data.get("api_token", ""),
    }
    _save_settings(cfg)
    (CONFIG_DIR / "jds_config.json").write_text(json.dumps(cfg["jds_config"], indent=2), encoding="utf-8")
    return jsonify({"ok": True})

@app.route("/api/config/sites", methods=["GET", "POST"])
def config_sites():
    if request.method == "GET":
        cfg = _load_settings()
        return jsonify(cfg.get("knowledge_sites", []))
    data = request.get_json(force=True)
    cfg = _load_settings()
    cfg["knowledge_sites"] = data.get("sites", [])
    _save_settings(cfg)
    return jsonify({"ok": True})

@app.route("/api/config/admin", methods=["GET", "POST"])
def config_admin():
    if request.method == "GET":
        cfg = _load_settings()
        return jsonify({
            "admin_api_secret": cfg.get("admin_api_secret", ""),
            "has_secret": bool(cfg.get("admin_api_secret")),
        })
    data = request.get_json(force=True)
    secret = (data.get("admin_api_secret") or "").strip()
    if secret:
        cfg = _load_settings()
        cfg["admin_api_secret"] = secret
        _save_settings(cfg)
        return jsonify({"ok": True, "message": "Admin-API-Secret gespeichert."})
    return jsonify({"error": "Secret erforderlich"}), 400

@app.route("/api/key", methods=["GET", "POST"])
def api_key():
    if request.method == "GET":
        key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("gemini_api_key", "")
        if not key:
            try:
                p = CONFIG_DIR / "api_keys.json"
                if p.exists():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    for k in ("gemini_api_key", "GEMINI_API_KEY", "api_key"):
                        val = data.get(k)
                        if val:
                            key = val
                            break
            except: pass
        return jsonify({"key": key, "has_key": bool(key)})
    data = request.get_json(force=True)
    key = (data.get("key") or "").strip()
    if key:
        p = CONFIG_DIR / "api_keys.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"gemini_api_key": key}, indent=2), encoding="utf-8")
        return jsonify({"ok": True, "message": "API-Key gespeichert."})
    return jsonify({"error": "Key erforderlich"}), 400

@app.route("/api/status", methods=["GET"])
def status():
    import server.handler as h
    session = h.get_session()
    has_session = getattr(session, "_chat", None) is not None
    cfg = _load_settings()
    return jsonify({
        "status": "online",
        "session_active": has_session,
        "user_name": cfg.get("user_name", "Sir"),
        "email_count": len(cfg.get("email_accounts", [])),
        "knowledge_sites": len(cfg.get("knowledge_sites", [])),
        "jds_configured": bool(cfg.get("jds_config", {}).get("base_url")),
        "admin_api_configured": bool(cfg.get("admin_api_secret")),
        "discord_configured": bool(cfg.get("discord_config", {}).get("bot_token")),
        "home_location": cfg.get("home_location", ""),
        "api_key_configured": bool(_get_api_key_any()),
    })

def _get_api_key_any():
    import server.handler as h
    return bool(h._get_api_key())

# ── Gunicorn entry point ────────────────────────────────────────────────
application = app

def start(host="0.0.0.0", port=5789, debug=False):
    print(f"[Server] JARVIS Web UI unter http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5789))
    debug = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
    start(host="0.0.0.0", port=port, debug=debug)
