"""JARVIS Desktop-Agent – verbindet diesen PC mit der JARVIS Web-App.

Die Web-App (lokal oder online auf Render) schickt PC-Tools (Apps öffnen, Lautstärke,
Tastatur, Dateien, Browser-Automation, …) über eine WebSocket-Verbindung hierher.
Der Agent führt sie mit denselben actions/-Modulen wie der Desktop-JARVIS aus.

Start:
    python desktop_agent.py --server https://jarvis-joel.onrender.com --token <TOKEN> --save
    python desktop_agent.py                 # danach mit gespeicherten Daten
    python desktop_agent.py --push-config   # lokale Einstellungen/Gedächtnis auf den Server laden

Das Token steht in der Web-App unter Einstellungen → Desktop-Agent.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import platform
import socket
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

for _stream in (sys.stdout, sys.stderr):  # Windows-Konsole (cp1252) verträgt keine Emojis
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

AGENT_CFG = BASE / "config" / "agent.json"
PUSH_PATTERNS = [
    ("config", ("*.json", "*.pickle")),
    ("memory", ("*.json",)),
    ("content", ("**/*.json",)),
]
PUSH_EXCLUDE = {"agent.json", ".django_secret"}


def load_cfg() -> dict:
    try:
        return json.loads(AGENT_CFG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cfg(server: str, token: str):
    AGENT_CFG.parent.mkdir(parents=True, exist_ok=True)
    AGENT_CFG.write_text(json.dumps({"server": server, "token": token}, indent=2), encoding="utf-8")


def collect_state_files() -> list[dict]:
    files = []
    for folder, patterns in PUSH_PATTERNS:
        root = BASE / folder
        if not root.exists():
            continue
        for pattern in patterns:
            for p in root.glob(pattern):
                if p.is_file() and p.name not in PUSH_EXCLUDE and p.stat().st_size <= 5 * 1024 * 1024:
                    files.append({"path": p.relative_to(BASE).as_posix(),
                                  "b64": base64.b64encode(p.read_bytes()).decode()})
    return files


def metrics() -> dict:
    try:
        import psutil
        m = {"cpu": psutil.cpu_percent(interval=None), "ram": psutil.virtual_memory().percent}
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if bat:
            m["battery"] = bat.percent
            m["plugged"] = bat.power_plugged
        return m
    except Exception:
        return {}


def show_toast(title: str, body: str):
    try:
        if sys.platform == "win32":
            try:
                import winsound
                for f in (800, 1000, 1200):
                    winsound.Beep(f, 150)
            except Exception:
                pass
            from win10toast import ToastNotifier
            ToastNotifier().show_toast(title, body or " ", duration=8, threaded=True)
        else:
            print(f"\a[{title}] {body}")
    except Exception as e:
        print(f"[Agent] Benachrichtigung: {title} – {body} ({e})")


class Agent:
    def __init__(self, server: str, token: str, push: bool):
        self.server = server.rstrip("/")
        self.token = token
        self.push = push
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")
        self.ws = None
        self.loop = None

    @property
    def ws_url(self) -> str:
        u = urlparse(self.server)
        scheme = "wss" if u.scheme == "https" else "ws"
        return f"{scheme}://{u.netloc}/ws/agent/?token={self.token}"

    def log(self, text: str):
        print(f"[Agent] {text}")
        if self.ws and self.loop:
            asyncio.run_coroutine_threadsafe(self._send({"type": "log", "text": str(text)[:400]}), self.loop)

    async def _send(self, obj: dict):
        try:
            await self.ws.send(json.dumps(obj, default=str))
        except Exception:
            pass

    def _execute(self, tool: str, args: dict) -> str:
        from jarvis_core.actions_map import NullPlayer, call_action

        player = NullPlayer(log=self.log)
        try:
            result = call_action(tool, args, player=player, speak=lambda t: self.log(f"🗣 {t}"))
        except KeyError:
            result = f"Unbekanntes Tool am PC: {tool}"
        except Exception as e:
            traceback.print_exc()
            result = f"Fehler am PC bei '{tool}': {e}"
        return str(result if result not in (None, "") else "Erledigt.")

    async def _handle_call(self, msg: dict):
        tool, args = msg.get("tool", ""), msg.get("args") or {}
        print(f"[Agent] 🔧 {tool} {json.dumps(args, ensure_ascii=False)[:120]}")
        result = await self.loop.run_in_executor(self.pool, self._execute, tool, args)
        print(f"[Agent] ✅ {tool} → {result[:120]}")
        await self._send({"type": "result", "id": msg.get("id"), "result": result})

    async def _metrics_loop(self):
        while True:
            await self._send({"type": "metrics", "metrics": await self.loop.run_in_executor(None, metrics)})
            await asyncio.sleep(5)

    async def run_once(self):
        import websockets

        origin = f"{urlparse(self.server).scheme}://{urlparse(self.server).netloc}"
        async with websockets.connect(self.ws_url, origin=origin, max_size=32 * 1024 * 1024,
                                      ping_interval=20, ping_timeout=20) as ws:
            self.ws = ws
            await self._send({"type": "hello", "host": socket.gethostname(),
                              "platform": f"{platform.system()} {platform.release()}"})
            print(f"[Agent] ✅ Verbunden mit {self.server}")
            if self.push:
                files = collect_state_files()
                await self._send({"type": "push_state", "files": files})
                print(f"[Agent] ⇪ {len(files)} Konfigurationsdatei(en) gesendet")
                self.push = False
            metrics_task = asyncio.create_task(self._metrics_loop())
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    kind = msg.get("type")
                    if kind == "call":
                        asyncio.create_task(self._handle_call(msg))
                    elif kind == "notify":
                        self.loop.run_in_executor(None, show_toast, msg.get("title", "JARVIS"), msg.get("body", ""))
                    elif kind == "push_state_done":
                        print(f"[Agent] ✓ Server hat gespeichert: {', '.join(msg.get('saved', [])) or '–'}")
                    elif kind == "welcome":
                        print(f"[Agent] Angemeldet als {msg.get('user')}")
            finally:
                metrics_task.cancel()
                self.ws = None

    async def run(self):
        self.loop = asyncio.get_running_loop()
        delay = 2
        while True:
            started = time.time()
            try:
                await self.run_once()
            except Exception as e:
                code = getattr(getattr(e, "rcvd", None), "code", None)
                if code == 4401 or "4401" in str(e) or "403" in str(e):
                    print("[Agent] ❌ Token ungültig oder Account ohne Vollzugriff. Neues Token in den Einstellungen holen.")
                    return
                print(f"[Agent] ⚠️ Verbindung getrennt: {e}")
            if time.time() - started > 60:
                delay = 2
            print(f"[Agent] 🔄 Neuer Versuch in {delay}s …")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


def main():
    cfg = load_cfg()
    ap = argparse.ArgumentParser(description="JARVIS Desktop-Agent")
    ap.add_argument("--server", default=cfg.get("server", "https://jarvis-joel.onrender.com"),
                    help="URL der JARVIS Web-App")
    ap.add_argument("--token", default=cfg.get("token", ""), help="Agent-Token aus den Web-Einstellungen")
    ap.add_argument("--save", action="store_true", help="Server und Token in config/agent.json merken")
    ap.add_argument("--push-config", action="store_true",
                    help="Lokale config/, memory/ und content/ Dateien auf den Server übertragen")
    args = ap.parse_args()

    if not args.token:
        ap.error("Kein Token. Hol es in der Web-App unter Einstellungen → Desktop-Agent.")
    if args.save:
        save_cfg(args.server, args.token)
        print(f"[Agent] Gespeichert in {AGENT_CFG}")

    print(f"[Agent] JARVIS Desktop-Agent – {socket.gethostname()} → {args.server}")
    try:
        asyncio.run(Agent(args.server, args.token, args.push_config).run())
    except KeyboardInterrupt:
        print("\n[Agent] Beendet.")


if __name__ == "__main__":
    main()
