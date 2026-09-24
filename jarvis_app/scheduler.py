"""Hintergrund-Jobs der Web-App – entspricht den Timern aus main.py.

• Erinnerungen & Wecker            (pro Benutzer, Browser-Benachrichtigung + PC-Toast)
• Stündliche Trink-Erinnerung      (pro Benutzer, abschaltbar, Ruhezeit 22–7 Uhr)
• Tagesbericht per E-Mail          (settings.json → daily_report)
• E-Mail-Scan alle 15 Minuten      (Weiterleitung wichtiger Mails, Autopilot)
• Projekt-Watcher alle 30 Minuten  (über den Desktop-Agent)
• Discord-Bot                      (settings.json → discord_config)
• Zustand sichern jede Minute
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import traceback
from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.utils import timezone

from . import state_sync
from .config_store import load_settings
from .hub import hub
from .models import Alarm, JobState, Profile, Reminder
from .notify import notify

log = logging.getLogger("jarvis.scheduler")

QUIET_START, QUIET_END = 22, 7
_started = False
_start_lock = threading.Lock()


def _quiet(now: datetime) -> bool:
    return now.hour >= QUIET_START or now.hour < QUIET_END


def _owner():
    """Der Besitzer der JARVIS-Instanz (erster Superuser) – Ziel für Systemmeldungen."""
    return get_user_model().objects.filter(is_superuser=True, is_active=True).order_by("id").first()


# ── Einzelne Jobs ──────────────────────────────────────────────────────────

def check_reminders():
    for r in Reminder.objects.filter(done=False, due_at__lte=timezone.now()).select_related("user"):
        r.done = True
        r.save(update_fields=["done"])
        notify(r.user_id, "⏰ Erinnerung", r.message, kind="reminder", speak=f"Erinnerung: {r.message}")


def check_alarms(now: datetime):
    hhmm = now.strftime("%H:%M")
    today = now.date()
    for a in Alarm.objects.filter(active=True, time=hhmm).exclude(last_fired=today):
        a.last_fired = today
        if not a.repeat:
            a.active = False
        a.save(update_fields=["last_fired", "active"])
        from .tools import RADIO_STATIONS
        stream = RADIO_STATIONS.get(a.music.lower()) if a.music else None
        notify(a.user_id, "⏰ Wecker", f"Es ist {hhmm} Uhr.", kind="alarm",
               data={"stream": stream, "alarm_id": a.id}, speak=f"Guten Morgen! Es ist {hhmm} Uhr.")


def hydration(now: datetime):
    if now.minute != 0 or _quiet(now):
        return
    key = f"hydration:{now:%Y-%m-%d-%H}"
    if JobState.get(key):
        return
    JobState.put(key, {"sent": True})
    for p in Profile.objects.filter(hydration_reminder=True, user__is_active=True):
        notify(p.user_id, "💧 Trink-Erinnerung", "Zeit, etwas zu trinken! Bleib hydriert.", kind="hydration",
               speak="Es ist Zeit, etwas zu trinken. Bleiben Sie hydriert.", to_agent=False)


def daily_report(now: datetime):
    cfg = load_settings().get("daily_report") or {}
    if not cfg.get("enabled") or not cfg.get("recipient_email"):
        return
    hhmm = now.strftime("%H:%M")
    if hhmm not in [t.strip() for t in cfg.get("times", [])]:
        return
    key = f"daily_report:{now:%Y-%m-%d}:{hhmm}"
    if JobState.get(key):
        return
    JobState.put(key, {"sent": True})

    from jarvis_core.actions_map import call_action
    parts = []
    try:
        if cfg.get("include_dashboard", True):
            parts.append(str(call_action("do_briefing", {"action": "briefing"})))
        if cfg.get("include_weather", True):
            city = load_settings().get("home_location") or ""
            if city:
                parts.append(str(call_action("weather_report", {"city": city})))
        if cfg.get("include_emails", True):
            parts.append(str(call_action("email_manager", {"action": "list", "count": 3, "unread_only": False})))
        result = call_action("email_manager", {
            "action": "send", "to": cfg["recipient_email"],
            "subject": f"JARVIS Tagesbericht — {now:%d.%m.%Y %H:%M}",
            "body": "\n\n---\n\n".join(parts),
        })
        log.info("[Tagesbericht] %s", result)
        owner = _owner()
        if owner:
            notify(owner.id, "📧 Tagesbericht gesendet", f"an {cfg['recipient_email']}", kind="report", to_agent=False)
    except Exception as e:
        log.warning("[Tagesbericht] Fehler: %s", e)


_NEWSLETTER = ["unsubscribe", "abbestellen", "newsletter", "werbung", "marketing", "no-reply", "noreply",
               "mailjet", "sendgrid", "mailchimp", "constant contact", "kampagne"]


def _is_important(sender: str, subject: str, body: str) -> bool:
    s, subj, b = sender.lower(), subject.lower(), body.lower()[:1000]
    return not any(sig in s or sig in subj or sig in b for sig in _NEWSLETTER)


def email_scan_once():
    cfg = load_settings()
    if not cfg.get("email_accounts") and not (settings.BASE_DIR / "config" / "email_config.json").exists():
        return
    from jarvis_core.actions_map import call_action
    from .tools import autopilot_active, autopilot_log

    r = str(call_action("email_manager", {"action": "list", "count": 5, "unread_only": True}))
    if not r or "Keine" in r or "Fehler" in r:
        return
    forward_to = cfg.get("email_forward_to") or (cfg.get("daily_report") or {}).get("recipient_email", "")
    owner = _owner()
    if owner:
        hub.send_to_user(owner.id, {"type": "log", "text": "📬 Neue E-Mails erkannt"})
    if not forward_to:
        return
    state = JobState.get("email_scan") or {"replied": []}
    replied = set(state.get("replied", []))
    auto = autopilot_active()
    for idx in range(1, 4):
        try:
            raw = str(call_action("email_manager", {"action": "read", "index": idx, "unread_only": True}))
        except Exception:
            continue
        if not raw or "Keine" in raw or "Fehler" in raw:
            continue
        sender = subject = ""
        for line in raw.split("\n"):
            if line.startswith("Von:"):
                sender = line[4:].strip()
            elif line.startswith("Betreff:"):
                subject = line[8:].strip()
        uid = f"{sender}|{subject}"
        if not sender or uid in replied:
            continue
        replied.add(uid)
        if not auto and not _is_important(sender, subject, raw):
            continue
        tag = "AUTOPILOT" if auto else "Autopilot"
        call_action("email_manager", {
            "action": "send", "to": forward_to,
            "subject": f"✉ {subject} (weitergeleitet von {sender})",
            "body": (f"--- WEITERGELEITETE KUNDENANFRAGE ({tag}) ---\n\n{raw}\n\n--- Ende der Weiterleitung ---\n\n"
                     "Diese E-Mail wurde automatisch vom JARVIS-Assistenten weitergeleitet."),
        })
        autopilot_log(f"E-Mail weitergeleitet: {subject} von {sender}")
        if owner:
            hub.send_to_user(owner.id, {"type": "log", "text": f"E-Mail weitergeleitet → {forward_to}: {subject}"})
    JobState.put("email_scan", {"replied": sorted(replied)[-500:]})


def project_watch():
    owner = _owner()
    if not owner or not hub.agent(owner.id):
        return
    raw = hub.agent_call(owner.id, "project_watch_scan", {}, timeout=300)
    try:
        results = json.loads(raw)
    except ValueError:
        return
    known = JobState.get("project_watch") or {}
    for key, issues in results.items():
        new = [i for i in issues if i not in known.get(key, [])]
        known[key] = issues
        if new and not _quiet(datetime.now()):
            name = key.split("|", 1)[0]
            notify(owner.id, f"⚠️ Problem in {name}", new[0][:300], kind="warning",
                   speak=f"Ich habe ein Problem in {name} gefunden.")
    JobState.put("project_watch", known)


def connect_jds():
    cfg = load_settings().get("jds_config") or {}
    if not (cfg.get("base_url") and cfg.get("api_token")):
        return
    try:
        from actions.jds_client import jds_connect
        jds_connect({"action": "setup", "base_url": cfg["base_url"], "team_code": cfg.get("team_code", ""),
                     "api_token": cfg["api_token"]})
        log.info("[JDS] %s", jds_connect({"action": "connect"}))
    except Exception as e:
        log.warning("[JDS] Verbindung fehlgeschlagen: %s", e)


# ── Discord ────────────────────────────────────────────────────────────────

class _DiscordAdapter:
    """Stellt dem DiscordBridge die process_text()-Schnittstelle von JarvisLive bereit."""

    async def process_text(self, text: str) -> str:
        def _run():
            try:
                owner = _owner()
                if not owner:
                    return "Kein JARVIS-Besitzer eingerichtet."
                from .engine import chat
                return chat(owner, text, channel="discord")["response"]
            finally:
                close_old_connections()
        return await asyncio.to_thread(_run)


def start_discord():
    token = (load_settings().get("discord_config") or {}).get("bot_token")
    if not token:
        return

    def _run():
        try:
            from actions.discord_bot import DiscordBridge
            asyncio.run(DiscordBridge(jarvis_ref=_DiscordAdapter()).start())
        except Exception as e:
            log.warning("[Discord] %s", e)

    threading.Thread(target=_run, daemon=True, name="discord").start()
    log.info("[Discord] Bot wird gestartet")


# ── Hauptschleife ──────────────────────────────────────────────────────────

def _guard(fn, *args):
    try:
        fn(*args)
    except Exception:
        log.warning("[Scheduler] %s fehlgeschlagen:\n%s", fn.__name__, traceback.format_exc())


def _loop():
    time.sleep(3)
    _guard(connect_jds)
    if settings.JARVIS_DISCORD:
        _guard(start_discord)
    last_minute = None
    last_email = time.time()
    last_watch = time.time()
    last_snapshot = time.time()
    while True:
        try:
            now = datetime.now()
            _guard(check_reminders)
            minute = now.strftime("%Y-%m-%d %H:%M")
            if minute != last_minute:
                last_minute = minute
                _guard(check_alarms, now)
                _guard(hydration, now)
                _guard(daily_report, now)
            if settings.JARVIS_EMAIL_SCAN and time.time() - last_email >= 900:
                last_email = time.time()
                threading.Thread(target=lambda: (_guard(email_scan_once), close_old_connections()),
                                 daemon=True, name="email-scan").start()
            if time.time() - last_watch >= 1800:
                last_watch = time.time()
                threading.Thread(target=lambda: (_guard(project_watch), close_old_connections()),
                                 daemon=True, name="project-watch").start()
            if time.time() - last_snapshot >= 60:
                last_snapshot = time.time()
                _guard(state_sync.snapshot)
        finally:
            close_old_connections()
        time.sleep(15)


def start():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="jarvis-scheduler").start()
    log.info("[Scheduler] Hintergrund-Jobs gestartet")
