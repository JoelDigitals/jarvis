"""Gemeinsamer Action-Dispatcher.

Führt ein JARVIS-Tool über die Module in actions/ aus. Wird vom Django-Server
(Server-Tools) und vom Desktop-Agent (PC-Tools) gleichermaßen benutzt, damit
beide exakt dieselbe Logik wie main.py verwenden.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


class NullPlayer:
    """Ersatz für das Qt-UI-Objekt, das die Actions als `player` erwarten."""

    muted = False
    current_file = None

    def __init__(self, log=None):
        self._log = log

    def write_log(self, text: str):
        if self._log:
            self._log(str(text))
        else:
            print(f"[JARVIS] {text}")

    def write_result(self, title: str, body: str = ""):
        self.write_log(f"{title}: {body}")

    def __getattr__(self, name):
        # Alle übrigen UI-Methoden (set_state, show_update_available, ...) ignorieren
        return lambda *a, **k: None


def call_action(name: str, args: dict, player=None, speak=None) -> str:
    """Ruft die Action `name` auf. Wirft KeyError für unbekannte Tools."""
    player = player or NullPlayer()
    speak = speak or (lambda text: player.write_log(f"JARVIS: {text}"))
    args = dict(args or {})

    if name == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=args, response=None, player=player) or f"{args.get('app_name')} geöffnet."
    if name == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=args, player=player)
    if name == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=args, player=player)
    if name == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=args, player=player)
    if name == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=args, response=None, player=player, session_memory=None)
    if name == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=args, response=None, player=player)
    if name == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=args, response=None, player=player, speak=speak)
    if name == "file_processor":
        from actions.file_processor import file_processor
        return file_processor(parameters=args, player=player, speak=speak)
    if name == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=args, response=None, player=player)
    if name == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=args, player=player)
    if name == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=args, player=player, speak=speak)
    if name == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=args, player=player, speak=speak)
    if name == "agent_task":
        from agent.task_queue import get_queue, TaskPriority
        prio = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
        task_id = get_queue().submit(
            goal=args.get("goal", ""),
            priority=prio.get(str(args.get("priority", "normal")).lower(), TaskPriority.NORMAL),
            speak=speak,
        )
        return f"Task gestartet (ID: {task_id})."
    if name == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=args, player=player)
    if name == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=args, player=player)
    if name == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=args, player=player, speak=speak)
    if name == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=args, player=player)
    if name == "email_manager":
        from actions.email_manager import email_action
        return email_action(parameters=args, player=player)
    if name in ("web_summarize", "web_summarizer"):
        from actions.web_summarizer import web_summarize
        return web_summarize(parameters=args, player=player)
    if name == "jds_connect":
        from actions.jds_client import jds_connect
        return jds_connect(parameters=args, player=player)
    if name == "tankpreise":
        from actions.tankpreise import tankpreise
        return tankpreise(parameters=args, player=player)
    if name == "maps_api":
        from actions.maps_api import maps_api
        return maps_api(parameters=args, player=player)
    if name == "db_action":
        from actions.db_client import db_action
        return db_action(parameters=args, player=player)
    if name == "knowledge_sites":
        from actions.knowledge_sites import knowledge_action
        return knowledge_action(parameters=args, player=player)
    if name == "admin_api":
        from actions.admin_api import admin_action
        return admin_action(parameters=args, player=player)
    if name == "wecker":
        from actions.wecker import wecker
        return wecker(parameters=args, player=player)
    if name == "do_briefing":
        from actions.briefing_action import do_briefing
        return do_briefing(parameters=args, player=player)
    if name == "morning_routine":
        from actions.briefing_action import do_briefing
        return do_briefing({"greeting": "Guten Morgen"}, player=player)
    if name == "play_music":
        from actions.wake_manager import open_spotify
        url = args.get("url", "")
        ok = open_spotify(url) if url else open_spotify()
        return "Musik gestartet." if ok else "Konnte Musik nicht starten."
    if name == "focus_app":
        app = str(args.get("app", "")).strip().lower()
        if app in ("cursor", "code", "vscode"):
            from actions.wake_manager import focus_cursor
            return "Cursor fokussiert." if focus_cursor() else "Cursor gestartet."
        if app == "chrome":
            import subprocess
            from actions.wake_manager import _chrome_exe
            exe = _chrome_exe()
            if exe:
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "Chrome geöffnet."
            return "Chrome nicht gefunden."
        return f"Unbekannte App: {app}"
    if name == "open_chrome":
        url = args.get("url", "")
        if not url:
            return "Keine URL angegeben."
        from actions.wake_manager import open_chrome_url
        open_chrome_url(url, args.get("monitor", 1), args.get("fullscreen", True))
        return f"Chrome geöffnet: {url[:50]}"
    if name == "calendar_manager":
        from actions.calendar_manager import calendar_action
        return calendar_action(parameters=args, player=player)
    if name == "social_manager":
        from actions.social_manager import social_action
        return social_action(parameters=args, player=player)
    if name == "video_creator":
        from actions.video_creator import video_action
        return video_action(parameters=args, player=player)
    if name == "claude_bridge":
        from actions.claude_bridge import claude_action
        return claude_action(parameters=args, player=player)
    if name == "hermes_agent":
        from actions.hermes_agent import hermes_action
        return hermes_action(parameters=args, player=player)
    if name == "project_watch":
        from actions.project_watcher import project_watch_action
        return project_watch_action(parameters=args, player=player)
    if name == "knowledge_base":
        from actions.knowledge_base import kb_action
        return kb_action(args, player=player)
    if name == "save_memory":
        from memory.memory_manager import update_memory
        category = args.get("category", "notes")
        key, value = args.get("key", ""), args.get("value", "")
        if not (key and value):
            return "key und value erforderlich."
        update_memory({category: {key: {"value": value}}})
        return f"Gemerkt: {category} → {key} = {value}"
    if name == "screen_capture":
        return _capture(args.get("angle", "screen"))
    if name == "project_watch_scan":
        # Scheduler-Hilfsaufruf: alle überwachten Projekte scannen → {"name|path": [issues]}
        from actions.project_watcher import _load as load_watched, scan_project
        return json.dumps({
            f"{p.get('name', p['path'])}|{p['path']}": scan_project(p["path"])
            for p in load_watched().get("projects", [])
        }, ensure_ascii=False)

    from actions.plugin_loader import run_plugin
    r = run_plugin(name, args, player=player)
    if r is None:
        raise KeyError(name)
    return r


def _capture(angle: str) -> str:
    """Bildschirm- oder Kamerabild als Base64-JPEG (für den Desktop-Agent)."""
    import base64
    import io
    from PIL import Image

    if angle == "camera":
        import cv2
        cam = cv2.VideoCapture(0)
        ok, frame = cam.read()
        cam.release()
        if not ok:
            raise RuntimeError("Kamera nicht verfügbar")
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    else:
        import mss
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.rgb)
    img.thumbnail((1280, 720))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return json.dumps({"jpeg_b64": base64.b64encode(buf.getvalue()).decode()})
