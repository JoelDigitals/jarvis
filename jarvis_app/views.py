"""Seiten + JSON-API der JARVIS Web-App."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import platform
import re
import time
from datetime import datetime
from functools import wraps
from pathlib import Path

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db import close_old_connections, transaction
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie

from . import state_sync
from .config_store import (
    KEY_FIELDS, admin_secret, gemini_key, load_api_keys, load_settings, mask, save_api_keys, save_settings,
)
from .hub import hub
from .models import (
    Alarm, ChatMessage, JobState, LicenseKey, Notification, Profile, Reminder, StateFile, UpdateApp, UpdateVersion,
)

User = get_user_model()
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
SECRET_MASK = "••••••"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def _version() -> str:
    try:
        return (settings.BASE_DIR / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "?"


def _profile(user) -> Profile:
    return Profile.objects.get_or_create(user=user)[0]


def _body(request) -> dict:
    if request.content_type == "application/json":
        try:
            return json.loads(request.body or b"{}")
        except ValueError:
            raise ValueError("Ungültiges JSON")
    return request.POST.dict()


def _authenticate(request):
    """Bearer-Token (Agent/Skripte) oder Session-Login (Browser, mit CSRF-Prüfung)."""
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    if token:
        p = Profile.objects.select_related("user").filter(api_token=token, user__is_active=True).first()
        if p:
            return p.user, None
    if request.user.is_authenticated:
        if request.method not in SAFE_METHODS:
            reject = CsrfViewMiddleware(lambda r: None).process_view(request, None, (), {})
            if reject is not None:
                return None, JsonResponse({"error": "CSRF-Prüfung fehlgeschlagen. Seite neu laden."}, status=403)
        return request.user, None
    return None, None


def api(auth: str | None = "login", methods: tuple = ("GET", "POST")):
    """auth: None | "login" | "full" (voller Zugriff) | "admin"."""
    def deco(fn):
        @csrf_exempt
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return JsonResponse({"error": "Methode nicht erlaubt"}, status=405)
            user, err = _authenticate(request)
            if err:
                return err
            if auth and user is None:
                return JsonResponse({"error": "Nicht eingeloggt"}, status=401)
            if auth == "full" and not _profile(user).has_full_access:
                return JsonResponse({"error": "Kein Zugriff"}, status=403)
            if auth == "admin" and not user.is_superuser:
                return JsonResponse({"error": "Kein Admin-Zugriff"}, status=403)
            request.jarvis_user = user
            try:
                return fn(request, *args, **kwargs)
            except ValueError as e:
                return JsonResponse({"error": str(e)}, status=400)
        return wrapper
    return deco


# ── Seiten ─────────────────────────────────────────────────────────────────

def _setup_allowed() -> bool:
    return not User.objects.exists() and (settings.DEBUG or os.environ.get("JARVIS_ALLOW_SETUP") == "1")


@ensure_csrf_cookie
def login_view(request):
    if request.user.is_authenticated:
        return redirect("index")
    if _setup_allowed():
        return redirect("setup")
    ctx = {"tab": request.GET.get("tab", "login")}
    if request.method == "POST":
        mode = request.POST.get("mode", "login")
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        ctx["tab"] = mode
        if mode == "register":
            key = request.POST.get("license_key", "").strip()
            error = _register(key, username, password)
            if error:
                ctx["error"] = error
            else:
                login(request, authenticate(request, username=username, password=password))
                return redirect("index")
        else:
            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                return redirect(request.GET.get("next") or "index")
            ctx["error"] = "Ungültige Anmeldedaten."
        ctx["username"] = username
    return render(request, "jarvis/login.html", ctx)


def _register(key: str, username: str, password: str) -> str | None:
    if not key or not username or not password:
        return "Lizenzschlüssel, Benutzername und Passwort erforderlich."
    if len(username) < 3:
        return "Benutzername muss mindestens 3 Zeichen haben."
    if len(password) < 6:
        return "Passwort muss mindestens 6 Zeichen haben."
    if User.objects.filter(username__iexact=username).exists():
        return "Benutzername bereits vergeben."
    with transaction.atomic():
        lk = LicenseKey.objects.select_for_update().filter(key=key).first()
        if not lk:
            return "Ungültiger Lizenzschlüssel."
        if not lk.active:
            return "Dieser Schlüssel wurde deaktiviert."
        if lk.uses >= lk.max_uses:
            return "Lizenzschlüssel aufgebraucht (max. Aktivierungen erreicht)."
        lk.uses += 1
        lk.save(update_fields=["uses"])
        User.objects.create_user(username=username, password=password)
    return None


@ensure_csrf_cookie
def setup_view(request):
    if not _setup_allowed():
        return redirect("login")
    ctx = {}
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if len(username) < 3 or len(password) < 8:
            ctx["error"] = "Benutzername ≥ 3 und Passwort ≥ 8 Zeichen."
        else:
            user = User.objects.create_superuser(username=username, password=password)
            login(request, user)
            return redirect("settings")
    return render(request, "jarvis/setup.html", ctx)


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
@ensure_csrf_cookie
def index(request):
    p = _profile(request.user)
    return render(request, "jarvis/index.html", {
        "profile": p, "full_access": p.has_full_access, "version": _version(),
        "user_name": (load_settings().get("user_name") if p.has_full_access else None) or request.user.username,
    })


@login_required
@ensure_csrf_cookie
def settings_view(request):
    p = _profile(request.user)
    return render(request, "jarvis/settings.html", {
        "profile": p, "full_access": p.has_full_access, "version": _version(),
        "server_url": request.build_absolute_uri("/").rstrip("/"),
    })


@login_required
@ensure_csrf_cookie
def admin_panel(request):
    if not request.user.is_superuser:
        return redirect("index")
    return render(request, "jarvis/admin_panel.html", {"version": _version()})


def health(request):
    return JsonResponse({"status": "ok", "version": _version()})


# ── Chat ───────────────────────────────────────────────────────────────────

def _chat_sync(user_id: int, text: str, client_id: str | None):
    from .engine import chat
    try:
        return chat(User.objects.get(id=user_id), text, client_id=client_id)
    finally:
        close_old_connections()


@csrf_exempt
async def api_chat(request):
    """Asynchron, damit lange Antworten (Tools!) keine anderen Anfragen blockieren."""
    if request.method != "POST":
        return JsonResponse({"error": "POST erforderlich"}, status=405)
    user, err = await sync_to_async(_authenticate)(request)
    if err:
        return err
    if user is None:
        return JsonResponse({"error": "Nicht eingeloggt"}, status=401)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Ungültiges JSON"}, status=400)
    text = str(data.get("message") or "").strip()
    if not text:
        return JsonResponse({"error": "Leere Nachricht"}, status=400)
    result = await asyncio.to_thread(_chat_sync, user.id, text, data.get("client_id"))
    return JsonResponse(result)


@api(methods=("POST",))
def api_reset(request):
    ChatMessage.objects.filter(user=request.jarvis_user).delete()
    return JsonResponse({"ok": True})


@api(methods=("GET",))
def api_history(request):
    msgs = list(ChatMessage.objects.filter(user=request.jarvis_user).order_by("-created_at", "-id")[:80])
    msgs.reverse()
    return JsonResponse({"messages": [
        {"role": m.role, "text": m.text, "source": m.source, "tools": m.tools, "created_at": m.created_at.isoformat()}
        for m in msgs
    ]})


# ── Dateien ────────────────────────────────────────────────────────────────

def _upload_dir(user) -> Path:
    d = Path(settings.MEDIA_ROOT) / "uploads" / str(user.id)
    d.mkdir(parents=True, exist_ok=True)
    return d


@api(methods=("POST",))
def api_upload(request):
    f = request.FILES.get("file")
    if not f:
        raise ValueError("Keine Datei")
    safe = re.sub(r"[^\w.\- ]", "_", Path(f.name).name)[:120] or "upload"
    target = _upload_dir(request.jarvis_user) / f"{datetime.now():%Y%m%d_%H%M%S}_{safe}"
    with open(target, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    p = _profile(request.jarvis_user)
    p.current_file = str(target)
    p.save(update_fields=["current_file"])
    return JsonResponse({"ok": True, "name": safe, "path": str(target), "size": target.stat().st_size})


@api(methods=("GET", "POST"))
def api_files(request):
    base = _upload_dir(request.jarvis_user)
    p = _profile(request.jarvis_user)
    if request.method == "POST":  # aktuelle Datei wählen/abwählen
        name = str(_body(request).get("name") or "")
        p.current_file = str(base / Path(name).name) if name else ""
        p.save(update_fields=["current_file"])
    files = sorted((f for f in base.rglob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    return JsonResponse({
        "current": Path(p.current_file).name if p.current_file else "",
        "files": [{"name": f.relative_to(base).as_posix(), "size": f.stat().st_size,
                   "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()} for f in files[:100]],
    })


@login_required
def file_download(request, name: str):
    base = _upload_dir(request.user).resolve()
    target = (base / name).resolve()
    if base not in target.parents or not target.is_file():
        raise Http404
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(open(target, "rb"), content_type=ctype, as_attachment=request.GET.get("inline") != "1",
                        filename=target.name)


@api(methods=("POST",))
def api_file_delete(request):
    base = _upload_dir(request.jarvis_user).resolve()
    target = (base / str(_body(request).get("name") or "")).resolve()
    if base in target.parents and target.is_file():
        target.unlink()
    return JsonResponse({"ok": True})


# ── Status / Benachrichtigungen / Erinnerungen / Wecker ───────────────────

@api(methods=("GET",))
def api_status(request):
    user = request.jarvis_user
    p = _profile(user)
    agent = hub.agent(user.id) if p.has_full_access else None
    data = {
        "status": "online", "version": _version(), "username": user.username,
        "is_admin": user.is_superuser, "full_access": p.has_full_access,
        "api_key_configured": bool(gemini_key()),
        "agent": {"connected": bool(agent), "host": agent.host if agent else "",
                  "platform": agent.platform if agent else "", "metrics": agent.metrics if agent else {}},
        "server": {"platform": platform.system(), "local_desktop": os.name == "nt"},
        "unread": Notification.objects.filter(user=user, read=False).count(),
    }
    if p.has_full_access:
        cfg = load_settings()
        data.update({
            "user_name": cfg.get("user_name", "Sir"),
            "email_count": len(cfg.get("email_accounts", [])),
            "knowledge_sites": len(cfg.get("knowledge_sites", [])),
            "jds_configured": bool((cfg.get("jds_config") or {}).get("base_url")),
            "admin_api_configured": bool(cfg.get("admin_api_secret")),
            "discord_configured": bool((cfg.get("discord_config") or {}).get("bot_token")),
            "home_location": cfg.get("home_location", ""),
            "autopilot": bool((JobState.get("autopilot") or {}).get("active")),
        })
    try:
        import psutil
        data["server"]["metrics"] = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent}
    except Exception:
        pass
    return JsonResponse(data)


@api(methods=("GET",))
def api_hermes_status(request):
    """Verbindung zum Hermes Agent testen (Hintergrund-Thread, damit der Request nie hängt)."""
    import threading
    from actions.hermes_agent import load_config, status as hermes_probe

    user = request.jarvis_user
    p = _profile(user)
    if not p.has_full_access:
        return JsonResponse({"ok": False, "status": "Kein Zugriff."}, status=403)
    cfg = load_config()
    out = {"ok": False, "status": ""}

    def _probe():
        try:
            out["status"] = hermes_probe(cfg)
            out["ok"] = out["status"].startswith("Hermes Agent ist erreichbar")
        except Exception as e:
            out["status"] = f"Hermes-Statusfehler: {e}"
        finally:
            close_old_connections()

    t = threading.Thread(target=_probe, daemon=True, name="hermes-status")
    t.start()
    t.join(timeout=15)
    if t.is_alive():
        out["status"] = "Hermes Agent antwortet nicht (Timeout nach 15s)."
    return JsonResponse(out)


@api(methods=("GET", "POST"))
def api_notifications(request):
    qs = Notification.objects.filter(user=request.jarvis_user)
    if request.method == "POST":
        ids = _body(request).get("ids")
        (qs.filter(id__in=ids) if ids else qs).update(read=True)
    return JsonResponse({"notifications": [n.as_dict() for n in qs[:50]]})


@api(methods=("GET", "POST"))
def api_reminders(request):
    user = request.jarvis_user
    if request.method == "POST":
        data = _body(request)
        if data.get("delete"):
            Reminder.objects.filter(user=user, id=data["delete"]).delete()
        else:
            from .tools import ToolContext, _tool_reminder
            msg = _tool_reminder(data, ToolContext.for_user(user))
            return JsonResponse({"ok": True, "message": msg})
    return JsonResponse({"reminders": [
        {"id": r.id, "due_at": timezone.localtime(r.due_at).strftime("%d.%m.%Y %H:%M"), "message": r.message}
        for r in Reminder.objects.filter(user=user, done=False)
    ]})


@api(methods=("GET", "POST"))
def api_alarms(request):
    user = request.jarvis_user
    if request.method == "POST":
        data = _body(request)
        if data.get("delete"):
            Alarm.objects.filter(user=user, id=data["delete"]).delete()
        elif data.get("toggle"):
            a = Alarm.objects.filter(user=user, id=data["toggle"]).first()
            if a:
                a.active = not a.active
                a.save(update_fields=["active"])
        else:
            from .tools import ToolContext, _tool_wecker
            return JsonResponse({"ok": True, "message": _tool_wecker(
                {"action": "set", "time": data.get("time"), "music": data.get("music", "")}, ToolContext.for_user(user))})
    return JsonResponse({"alarms": [
        {"id": a.id, "time": a.time, "music": a.music, "active": a.active, "repeat": a.repeat}
        for a in Alarm.objects.filter(user=user)
    ]})


@api(auth="full", methods=("POST",))
def api_autopilot(request):
    from .tools import ToolContext, _tool_set_autopilot
    active = bool(_body(request).get("active"))
    return JsonResponse({"ok": True, "message": _tool_set_autopilot(
        {"active": active}, ToolContext.for_user(request.jarvis_user))})


# ── Profil & Token ─────────────────────────────────────────────────────────

@api(methods=("GET", "POST"))
def api_profile(request):
    p = _profile(request.jarvis_user)
    if request.method == "POST":
        data = _body(request)
        for field in ("wake_word_mode", "tts_enabled", "hydration_reminder"):
            if field in data:
                setattr(p, field, bool(data[field]))
        if data.get("regenerate_token"):
            import secrets
            p.api_token = secrets.token_urlsafe(32)
        if data.get("new_password"):
            if not request.jarvis_user.check_password(data.get("old_password", "")):
                raise ValueError("Altes Passwort ist falsch.")
            if len(data["new_password"]) < 6:
                raise ValueError("Neues Passwort zu kurz (min. 6 Zeichen).")
            request.jarvis_user.set_password(data["new_password"])
            request.jarvis_user.save()
            login(request, request.jarvis_user)
        p.save()
    return JsonResponse({
        "username": request.jarvis_user.username, "full_access": p.has_full_access,
        "wake_word_mode": p.wake_word_mode, "tts_enabled": p.tts_enabled,
        "hydration_reminder": p.hydration_reminder,
        "api_token": p.api_token if p.has_full_access else "",
    })


# ── JARVIS-Konfiguration (settings.json + api_keys.json) ──────────────────

_SECRET_PATHS = [("email_accounts", "password"), ("knowledge_sites", "password")]


def _masked_settings() -> dict:
    cfg = load_settings()
    for list_key, field in _SECRET_PATHS:
        for item in cfg.get(list_key) or []:
            if item.get(field):
                item[field] = SECRET_MASK
    for section, field in (("jds_config", "api_token"), ("discord_config", "bot_token"),
                           ("hermes_config", "api_key")):
        if (cfg.get(section) or {}).get(field):
            cfg[section][field] = SECRET_MASK
    if cfg.get("admin_api_secret"):
        cfg["admin_api_secret"] = SECRET_MASK
    return cfg


def _unmask(new: dict, old: dict) -> dict:
    """Maskierte Geheimnisse (••••••) durch die gespeicherten Werte ersetzen."""
    for list_key, field in _SECRET_PATHS:
        if list_key in new:
            old_items = {(i.get("email") or i.get("url") or i.get("name")): i for i in old.get(list_key) or []}
            for item in new[list_key] or []:
                if item.get(field) == SECRET_MASK:
                    prev = old_items.get(item.get("email") or item.get("url") or item.get("name")) or {}
                    item[field] = prev.get(field, "")
    for section, field in (("jds_config", "api_token"), ("discord_config", "bot_token"),
                           ("hermes_config", "api_key")):
        if section in new and (new[section] or {}).get(field) == SECRET_MASK:
            new[section][field] = (old.get(section) or {}).get(field, "")
    if new.get("admin_api_secret") == SECRET_MASK:
        new["admin_api_secret"] = old.get("admin_api_secret", "")
    return new


@api(auth="full", methods=("GET", "POST"))
def api_config(request):
    if request.method == "POST":
        data = _body(request)
        allowed = {"user_name", "home_location", "default_sender", "email_accounts", "knowledge_sites",
                   "briefing_enabled", "briefing_time", "jds_config", "discord_config", "email_forward_to",
                   "daily_report", "admin_api_secret", "web_sync_url", "server_url", "autoupdate_app_slug",
                   "hermes_config"}
        clean = _unmask({k: v for k, v in data.items() if k in allowed}, load_settings())
        save_settings(clean)
        state_sync.snapshot()
        if "jds_config" in clean:
            from .scheduler import connect_jds
            connect_jds()
        return JsonResponse({"ok": True, "message": "Gespeichert."})
    return JsonResponse(_masked_settings())


@api(auth="full", methods=("GET", "POST"))
def api_keys(request):
    if request.method == "POST":
        data = _body(request)
        save_api_keys({k: data.get(k) for k in KEY_FIELDS if data.get(k) and data.get(k) != SECRET_MASK})
        state_sync.snapshot()
        return JsonResponse({"ok": True, "message": "API-Keys gespeichert."})
    keys = load_api_keys()
    return JsonResponse({k: {"set": bool(keys.get(k)), "preview": mask(keys.get(k, ""))} for k in KEY_FIELDS})


@api(auth="full", methods=("GET", "POST"))
def api_memory(request):
    """Gedächtnis (memory/long_term.json) und Wissensdatenbank ansehen/bearbeiten."""
    from memory.memory_manager import load_memory, save_memory
    kb_path = settings.BASE_DIR / "memory" / "knowledge_base.json"
    if request.method == "POST":
        data = _body(request)
        if isinstance(data.get("memory"), dict):
            save_memory(data["memory"])
        if isinstance(data.get("knowledge_base"), dict):
            kb_path.write_text(json.dumps(data["knowledge_base"], indent=2, ensure_ascii=False), encoding="utf-8")
        state_sync.snapshot()
    try:
        kb = json.loads(kb_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kb = {}
    return JsonResponse({"memory": load_memory(), "knowledge_base": kb})


# ── Admin: Lizenzen, Benutzer, Zustandsdateien ─────────────────────────────

@api(auth="admin", methods=("GET", "POST"))
def api_admin_licenses(request):
    if request.method == "POST":
        data = _body(request)
        lk = LicenseKey.objects.create(key=LicenseKey.generate_key(), label=str(data.get("label") or "")[:120],
                                       max_uses=max(1, int(data.get("max_uses") or 20)))
        return JsonResponse({"ok": True, "key": lk.key, "max_uses": lk.max_uses})
    return JsonResponse([
        {"key": k.key, "label": k.label, "uses": k.uses, "max_uses": k.max_uses, "active": k.active,
         "created_at": k.created_at.isoformat()} for k in LicenseKey.objects.order_by("-created_at")
    ], safe=False)


@api(auth="admin", methods=("DELETE", "POST"))
def api_admin_license_revoke(request, key):
    n = LicenseKey.objects.filter(key=key).update(active=False)
    return JsonResponse({"ok": True} if n else {"error": "Key nicht gefunden"}, status=200 if n else 404)


@api(auth="admin", methods=("GET",))
def api_admin_users(request):
    return JsonResponse([
        {"id": u.id, "username": u.username, "role": "admin" if u.is_superuser else "user",
         "full_access": _profile(u).has_full_access, "active": u.is_active,
         "created_at": u.date_joined.isoformat(), "last_login": u.last_login.isoformat() if u.last_login else None}
        for u in User.objects.order_by("id")
    ], safe=False)


@api(auth="admin", methods=("POST", "DELETE"))
def api_admin_user(request, user_id):
    u = User.objects.filter(id=user_id).first()
    if not u:
        return JsonResponse({"error": "Benutzer nicht gefunden"}, status=404)
    if u == request.jarvis_user:
        raise ValueError("Den eigenen Account hier nicht ändern.")
    if request.method == "DELETE":
        u.delete()
        return JsonResponse({"ok": True})
    data = _body(request)
    p = _profile(u)
    if "full_access" in data:
        p.full_access = bool(data["full_access"])
        p.save(update_fields=["full_access"])
    if "active" in data:
        u.is_active = bool(data["active"])
        u.save(update_fields=["is_active"])
    return JsonResponse({"ok": True})


@api(auth="admin", methods=("GET", "POST"))
def api_admin_state(request):
    if request.method == "POST":
        f = request.FILES.get("file")
        path = (request.POST.get("path") or "").strip() or (f"config/{f.name}" if f else "")
        if not f:
            raise ValueError("Keine Datei")
        state_sync.write_file(path, f.read())
        if path.endswith("api_keys.json"):
            from .config_store import ensure_api_keys
            ensure_api_keys()
            state_sync.snapshot()
        return JsonResponse({"ok": True, "path": path})
    state_sync.snapshot()
    return JsonResponse([
        {"path": s.path, "size": len(s.content), "updated_at": s.updated_at.isoformat()}
        for s in StateFile.objects.order_by("path").defer("content")
    ], safe=False)


# ── Live-Sync vom lokalen Desktop-JARVIS ───────────────────────────────────

def _secret_ok(request) -> bool:
    secret = admin_secret()
    if not secret:
        return True
    return request.headers.get("X-Admin-Secret") == secret


@csrf_exempt
def api_push(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST erforderlich"}, status=405)
    if not _secret_ok(request):
        return JsonResponse({"error": "Nicht autorisiert"}, status=401)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = {}
    if data.get("log"):
        entry = {"text": str(data["log"])[:500], "ts": time.strftime("%H:%M:%S")}
        hub.sync_logs.append(entry)
        hub.send_to_admins({"type": "sync", "log": entry})
    if data.get("state"):
        hub.sync_state = str(data["state"])
        hub.send_to_admins({"type": "sync", "state": hub.sync_state})
    return JsonResponse({"ok": True})


@api(auth="admin", methods=("GET",))
def api_sync_logs(request):
    return JsonResponse({"logs": list(hub.sync_logs), "state": hub.sync_state})


# ── Autoupdate-API (kompatibel zur bisherigen Flask-Version) ──────────────

def _autoupdate_auth(request) -> bool:
    if request.method in SAFE_METHODS:
        return True
    user, _ = _authenticate(request)
    if user and user.is_superuser:
        return True
    return _secret_ok(request)


def autoupdate_endpoint(fn):
    @csrf_exempt
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        if not _autoupdate_auth(request):
            return JsonResponse({"error": "Nicht autorisiert"}, status=401)
        try:
            return fn(request, *args, **kwargs)
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)
    return wrapper


@autoupdate_endpoint
def au_apps(request):
    if request.method == "POST":
        body = _body(request)
        name, slug = str(body.get("name") or "").strip(), str(body.get("slug") or "").strip()
        if not name or not slug:
            return JsonResponse({"error": "name und slug erforderlich"}, status=400)
        if UpdateApp.objects.filter(slug=slug).exists():
            return JsonResponse({"error": "App existiert bereits"}, status=409)
        app = UpdateApp.objects.create(name=name, slug=slug, description=str(body.get("description") or "").strip())
        return JsonResponse(app.as_dict(), status=201)
    return JsonResponse([a.as_dict() for a in UpdateApp.objects.prefetch_related("versions")], safe=False)


@autoupdate_endpoint
def au_app_delete(request, slug):
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE erforderlich"}, status=405)
    UpdateApp.objects.filter(slug=slug).delete()
    return JsonResponse({"ok": True})


@autoupdate_endpoint
def au_versions(request, slug):
    app = UpdateApp.objects.filter(slug=slug).first()
    if not app:
        return JsonResponse({"error": "App nicht gefunden"}, status=404)
    if request.method == "POST":
        body = _body(request)
        version = str(body.get("version") or "").strip()
        if not VERSION_RE.match(version):
            return JsonResponse({"error": "Version muss Format x.x.x.x haben"}, status=400)
        link = str(body.get("download_link") or "").strip()
        if not link:
            return JsonResponse({"error": "download_link erforderlich"}, status=400)
        if app.versions.filter(version=version).exists():
            return JsonResponse({"error": "Version existiert bereits"}, status=409)
        v = UpdateVersion.objects.create(
            app=app, version=version, download_link=link,
            release_notes=str(body.get("release_notes") or "").strip(),
            release_date=str(body.get("release_date") or datetime.now().strftime("%Y-%m-%d")).strip())
        return JsonResponse(v.as_dict(), status=201)
    if request.method == "DELETE":
        app.versions.filter(version=request.GET.get("version", "")).delete()
        return JsonResponse({"ok": True})
    return JsonResponse([v.as_dict() for v in app.sorted_versions()], safe=False)


@autoupdate_endpoint
def au_check(request, slug):
    current = (request.GET.get("current_version") or "").strip()
    if not VERSION_RE.match(current):
        return JsonResponse({"error": "current_version muss Format x.x.x.x haben"}, status=400)
    app = UpdateApp.objects.filter(slug=slug).first()
    if not app:
        return JsonResponse({"error": "App nicht gefunden"}, status=404)
    active = [v for v in app.sorted_versions() if v.is_active]
    cur = tuple(int(x) for x in current.split("."))
    if active and active[0].version_tuple > cur:
        latest = active[0]
        return JsonResponse({"update_available": True, "latest_version": latest.version,
                             "download_link": latest.download_link, "release_notes": latest.release_notes,
                             "release_date": latest.release_date})
    return JsonResponse({"update_available": False, "latest_version": active[0].version if active else current,
                         "download_link": None, "release_notes": None})


# ── Kompatible JSON-Auth (für Skripte / alte Clients) ──────────────────────

@csrf_exempt
def api_auth_login(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST erforderlich"}, status=405)
    data = json.loads(request.body or b"{}")
    user = authenticate(request, username=str(data.get("username", "")).strip(), password=str(data.get("password", "")))
    if not user:
        return JsonResponse({"error": "Ungültige Anmeldedaten."}, status=401)
    p = _profile(user)
    return JsonResponse({"ok": True, "token": p.api_token, "username": user.username,
                         "role": "admin" if user.is_superuser else "user"})


@csrf_exempt
def api_auth_register(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST erforderlich"}, status=405)
    data = json.loads(request.body or b"{}")
    username = str(data.get("username", "")).strip()
    error = _register(str(data.get("license_key", "")).strip(), username, str(data.get("password", "")))
    if error:
        return JsonResponse({"error": error}, status=400)
    user = User.objects.get(username=username)
    return JsonResponse({"ok": True, "token": _profile(user).api_token, "username": username, "role": "user"})


@api(methods=("GET",))
def api_auth_me(request):
    return JsonResponse({"username": request.jarvis_user.username,
                         "role": "admin" if request.jarvis_user.is_superuser else "user"})


def forbidden(request):
    return HttpResponseForbidden()
