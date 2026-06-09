import json, os, sys, threading, webbrowser
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, redirect, url_for

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config"
EMAIL_CFG = CONFIG / "email_config.json"
JDS_CFG = CONFIG / "jds_config.json"
API_CFG = CONFIG / "api_keys.json"

app = Flask(__name__)

_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS Konfiguration</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:#0a0a0f;color:#c8d6e5;padding:20px}
h1{color:#00d4ff;font-size:1.5rem;margin-bottom:20px}
h2{color:#00d4ff;font-size:1.1rem;margin:20px 0 10px;border-bottom:1px solid #1e2a3a;padding-bottom:5px}
.card{background:#111520;border:1px solid #1e2a3a;border-radius:8px;padding:20px;margin-bottom:20px}
label{display:block;font-size:.8rem;color:#8899aa;margin:10px 0 3px}
input,select,textarea{width:100%;padding:8px 10px;background:#0d1117;border:1px solid #1e2a3a;border-radius:4px;color:#c8d6e5;font-size:.9rem}
input:focus{outline:none;border-color:#00d4ff}
.btn{background:#00d4ff;color:#000;border:none;padding:10px 20px;border-radius:4px;cursor:pointer;font-weight:bold;margin-top:10px}
.btn:hover{background:#00b8e6}
.btn.danger{background:#ff4444}
.btn.danger:hover{background:#cc3333}
.success{color:#00ff88;padding:8px;background:#003322;border-radius:4px;margin:10px 0}
.error{color:#ff4444;padding:8px;background:#330011;border-radius:4px;margin:10px 0}
.tab{display:flex;gap:4px;margin-bottom:20px;flex-wrap:wrap}
.tab a{padding:8px 16px;background:#111520;border:1px solid #1e2a3a;border-radius:4px;color:#8899aa;text-decoration:none;font-size:.85rem}
.tab a.active,.tab a:hover{background:#00d4ff22;border-color:#00d4ff;color:#00d4ff}
.mt10{margin-top:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:600px){.grid{grid-template-columns:1fr}}
</style>
</head><body>
<h1>🛠 JARVIS Konfiguration</h1>
<div class="tab">
<a href="/" class="{% if page=='dashboard' %}active{% endif %}">Dashboard</a>
<a href="/email" class="{% if page=='email' %}active{% endif %}">E-Mail</a>
<a href="/jds" class="{% if page=='jds' %}active{% endif %}">JDS</a>
<a href="/reminders" class="{% if page=='reminders' %}active{% endif %}">Erinnerungen</a>
<a href="/settings" class="{% if page=='settings' %}active{% endif %}">System</a>
</div>
{% block content %}{% endblock %}
</body></html>"""

_IDX_TPL = _HTML + """{% block content %}
<div class="card">
<h2>System-Status</h2>
<p>CPU: {{ snap.cpu }}% &nbsp;|&nbsp; RAM: {{ snap.mem }}% &nbsp;|&nbsp; GPU: {{ snap.gpu_percent }}</p>
</div>
<div class="card">
<h2>Schnellzugriff</h2>
<div class="grid">
<a href="/email" class="btn" style="text-align:center;text-decoration:none">📧 E-Mail einrichten</a>
<a href="/jds" class="btn" style="text-align:center;text-decoration:none">📋 JDS verbinden</a>
<a href="/reminders" class="btn" style="text-align:center;text-decoration:none">⏰ Erinnerungen</a>
<a href="/settings" class="btn" style="text-align:center;text-decoration:none">⚙ System</a>
</div>
</div>
{% endblock %}"""

_EML_TPL = _HTML + """{% block content %}
{% if msg %}<div class="{{ 'success' if ok else 'error' }}">{{ msg }}</div>{% endif %}
<div class="card">
<h2>E-Mail-Konten</h2>
<form method="POST" action="/email">
<input type="hidden" name="_action" value="save">
<div class="grid">
<div><label>Titel / Beschriftung</label><input name="title" value="{{ cfg.title }}" placeholder="z.B. Hauptkonto"></div>
<div><label>E-Mail-Adresse</label><input name="email" value="{{ cfg.email }}" placeholder="email@example.com"></div>
</div>
<label>Passwort</label><input type="password" name="password" placeholder="Leer lassen = unverändert">
<label>IMAP-Server</label><input name="imap" value="{{ cfg.imap_server }}" placeholder="imap.example.com">
<label>SMTP-Server</label><input name="smtp" value="{{ cfg.smtp_server }}" placeholder="smtp.example.com">
<button class="btn" type="submit">Speichern</button>
</form>
{% if cfg.email %}
<form method="POST" action="/email" style="margin-top:10px">
<input type="hidden" name="_action" value="test">
<button class="btn" type="submit">Verbindung testen</button>
</form>
{% endif %}
</div>
{% endblock %}"""

_JDS_TPL = _HTML + """{% block content %}
{% if msg %}<div class="{{ 'success' if ok else 'error' }}">{{ msg }}</div>{% endif %}
<div class="card">
<h2>JDS Management-System</h2>
<form method="POST" action="/jds">
<input type="hidden" name="_action" value="save">
<label>Basis-URL</label><input name="base_url" value="{{ cfg.base_url }}" placeholder="https://jds.example.com">
<label>Team-Code</label><input name="team_code" value="{{ cfg.team_code }}" placeholder="UUID">
<label>API-Token</label><input name="api_token" value="{{ cfg.api_token }}" placeholder="Token">
<button class="btn" type="submit">Speichern</button>
</form>
{% if cfg.base_url and cfg.api_token %}
<form method="POST" action="/jds" style="margin-top:10px">
<input type="hidden" name="_action" value="test">
<button class="btn" type="submit">Verbindung testen</button>
</form>
{% endif %}
</div>
{% endblock %}"""

_REM_TPL = _HTML + """{% block content %}
{% if msg %}<div class="{{ 'success' if ok else 'error' }}">{{ msg }}</div>{% endif %}
<div class="card">
<h2>Stündliche Erinnerung</h2>
<form method="POST" action="/reminders">
<input type="hidden" name="_action" value="reminder">
<label>Nachricht</label><input name="message" value="{{ reminder_msg }}" placeholder="Es ist Zeit etwas zu trinken! Bleiben Sie hydriert.">
<button class="btn" type="submit">Speichern</button>
</form>
</div>
<div class="card">
<h2>Kalender-Ereignisse</h2>
<p style="color:#8899aa">Kalender-Funktion in Entwicklung.</p>
</div>
{% endblock %}"""

_SET_TPL = _HTML + """{% block content %}
{% if msg %}<div class="{{ 'success' if ok else 'error' }}">{{ msg }}</div>{% endif %}
<div class="card">
<h2>API-Keys</h2>
<form method="POST" action="/settings">
<input type="hidden" name="_action" value="api_keys">
<label>Gemini API-Key</label><input name="gemini_api_key" value="{{ api.gemini_api_key }}">
<label>OpenRouter API-Key</label><input name="openrouter_api_key" value="{{ api.openrouter_api_key }}">
<label>Betriebssystem</label>
<select name="os_system">
<option value="Windows" {% if api.os_system=='Windows' %}selected{% endif %}>Windows</option>
<option value="Linux" {% if api.os_system=='Linux' %}selected{% endif %}>Linux</option>
<option value="Darwin" {% if api.os_system=='Darwin' %}selected{% endif %}>macOS</option>
</select>
<button class="btn" type="submit">Speichern</button>
</form>
</div>
{% endblock %}"""

def _read_json(p):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return {}

def _write_json(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

@app.route("/")
def dashboard():
    try:
        import psutil
        snap = {
            "cpu": psutil.cpu_percent(interval=None),
            "mem": psutil.virtual_memory().percent,
        }
        g = -1.0
        try:
            r = __import__("subprocess").run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals: g = sum(vals)/len(vals)
        except: pass
        snap["gpu_percent"] = f"NVIDIA {g:.0f}%" if g >= 0 else "N/A"
    except:
        snap = {"cpu":"?","mem":"?","gpu_percent":"?"}
    return render_template_string(_IDX_TPL, page="dashboard", snap=snap)

@app.route("/email", methods=["GET","POST"])
def email_page():
    cfg = _read_json(EMAIL_CFG)
    msg, ok = "", True
    if request.method == "POST":
        act = request.form.get("_action")
        if act == "save":
            cfg["title"] = request.form.get("title","")
            cfg["email"] = request.form.get("email","")
            if request.form.get("password"):
                cfg["password"] = request.form["password"]
            cfg["imap_server"] = request.form.get("imap","")
            cfg["smtp_server"] = request.form.get("smtp","")
            _write_json(EMAIL_CFG, cfg)
            msg, ok = "✅ Gespeichert", True
        elif act == "test":
            try:
                from actions.email_manager import test_connection
                r = test_connection()
                msg, ok = f"✅ {r}", True
            except Exception as e:
                msg, ok = f"❌ {e}", False
    return render_template_string(_EML_TPL, page="email", cfg=cfg, msg=msg, ok=ok)

@app.route("/jds", methods=["GET","POST"])
def jds_page():
    cfg = _read_json(JDS_CFG)
    msg, ok = "", True
    if request.method == "POST":
        act = request.form.get("_action")
        if act == "save":
            cfg["base_url"] = request.form.get("base_url","").rstrip("/")
            cfg["team_code"] = request.form.get("team_code","")
            cfg["api_token"] = request.form.get("api_token","")
            _write_json(JDS_CFG, cfg)
            msg, ok = "✅ Gespeichert", True
        elif act == "test":
            try:
                from actions.jds_client import jds_connect
                r = jds_connect({"action": "status"}, player=None)
                msg, ok = f"✅ {r}", True
            except Exception as e:
                msg, ok = f"❌ {e}", False
    return render_template_string(_JDS_TPL, page="jds", cfg=cfg, msg=msg, ok=ok)

@app.route("/reminders", methods=["GET","POST"])
def reminders_page():
    rcfg = _read_json(CONFIG / "reminder_config.json")
    msg, ok = "", True
    if request.method == "POST":
        act = request.form.get("_action")
        if act == "reminder":
            rcfg["message"] = request.form.get("message","")
            _write_json(CONFIG / "reminder_config.json", rcfg)
            msg, ok = "✅ Gespeichert", True
    return render_template_string(_REM_TPL, page="reminders",
        reminder_msg=rcfg.get("message",""), msg=msg, ok=ok)

@app.route("/settings", methods=["GET","POST"])
def settings_page():
    api = _read_json(API_CFG)
    msg, ok = "", True
    if request.method == "POST":
        act = request.form.get("_action")
        if act == "api_keys":
            api["gemini_api_key"] = request.form.get("gemini_api_key","")
            api["openrouter_api_key"] = request.form.get("openrouter_api_key","")
            api["os_system"] = request.form.get("os_system","Windows")
            _write_json(API_CFG, api)
            msg, ok = "✅ Gespeichert", True
    return render_template_string(_SET_TPL, page="settings", api=api, msg=msg, ok=ok)

# API-Routes für JARVIS-Integration
@app.route("/api/email", methods=["GET"])
def api_email():
    return jsonify(_read_json(EMAIL_CFG))

@app.route("/api/email", methods=["POST"])
def api_email_save():
    data = request.get_json(silent=True) or {}
    _write_json(EMAIL_CFG, data)
    return jsonify({"status":"ok"})

@app.route("/api/jds", methods=["GET"])
def api_jds():
    return jsonify(_read_json(JDS_CFG))

@app.route("/api/jds", methods=["POST"])
def api_jds_save():
    data = request.get_json(silent=True) or {}
    _write_json(JDS_CFG, data)
    return jsonify({"status":"ok"})

_server_thread = None

def start(port=5789, open_browser=True):
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        return "Config-Web läuft bereits"
    _server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True
    )
    _server_thread.start()
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")
    return f"Config-Web gestartet auf http://127.0.0.1:{port}"

def stop():
    import requests
    try:
        requests.get("http://127.0.0.1:5789/shutdown", timeout=1)
    except:
        pass
    return "Config-Web gestoppt"

if __name__ == "__main__":
    print(start())
    input("Enter zum Beenden...")
