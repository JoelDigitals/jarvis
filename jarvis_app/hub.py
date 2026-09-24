"""Verbindungs-Hub: Browser-Tabs, Desktop-Agents und Bildschirm-Frames pro Benutzer.

Alles lebt im Speicher des (einzigen) Server-Prozesses. Die Methoden sind aus normalen
Threads (Tools, Scheduler) aufrufbar und leiten auf die asyncio-Loop von Daphne um.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger("jarvis.hub")


@dataclass
class AgentInfo:
    consumer: object
    host: str = ""
    platform: str = ""
    connected_at: float = field(default_factory=time.time)
    metrics: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)  # call_id -> concurrent Future


class Hub:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._clients: dict[int, dict[str, object]] = {}  # user_id -> {client_id: consumer}
        self._agents: dict[int, AgentInfo] = {}
        self._frames: dict[int, tuple[float, bytes, str]] = {}  # user_id -> (ts, jpeg, angle)
        self._ids = itertools.count(1)
        self._admins: set[int] = set()
        self.sync_logs: deque = deque(maxlen=200)  # Logs vom lokalen Desktop-JARVIS (/api/push)
        self.sync_state = "LISTENING"

    # ── Registrierung ──

    def bind_loop(self):
        if self.loop is None:
            self.loop = asyncio.get_running_loop()

    def add_client(self, user_id: int, client_id: str, consumer, is_admin: bool = False):
        self.bind_loop()
        with self._lock:
            self._clients.setdefault(user_id, {})[client_id] = consumer
            if is_admin:
                self._admins.add(user_id)

    def remove_client(self, user_id: int, client_id: str, consumer=None):
        with self._lock:
            clients = self._clients.get(user_id, {})
            if client_id in clients and (consumer is None or clients[client_id] is consumer):
                del clients[client_id]

    def client_count(self, user_id: int) -> int:
        return len(self._clients.get(user_id, {}))

    def add_agent(self, user_id: int, consumer, host: str = "", platform: str = "") -> AgentInfo:
        self.bind_loop()
        info = AgentInfo(consumer=consumer, host=host, platform=platform)
        with self._lock:
            old = self._agents.get(user_id)
            self._agents[user_id] = info
        if old:
            for fut in old.pending.values():
                if not fut.done():
                    fut.set_result("Desktop-Agent wurde durch eine neue Verbindung ersetzt.")
        self.send_to_user(user_id, {"type": "agent", "connected": True, "host": host, "platform": platform})
        return info

    def remove_agent(self, user_id: int, consumer):
        with self._lock:
            info = self._agents.get(user_id)
            if not info or info.consumer is not consumer:
                return
            del self._agents[user_id]
        for fut in info.pending.values():
            if not fut.done():
                fut.set_result("Desktop-Agent hat die Verbindung verloren.")
        self.send_to_user(user_id, {"type": "agent", "connected": False})

    def agent(self, user_id: int) -> AgentInfo | None:
        return self._agents.get(user_id)

    # ── Senden (thread-safe) ──

    def _submit(self, coro):
        if self.loop is None or self.loop.is_closed():
            coro.close()
            return None
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            return asyncio.ensure_future(coro)
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def send_to_user(self, user_id: int, payload: dict, client_id: str | None = None):
        clients = dict(self._clients.get(user_id, {}))
        if client_id and client_id in clients:
            clients = {client_id: clients[client_id]}
        text = json.dumps(payload, default=str)
        for consumer in clients.values():
            self._submit(consumer.send(text_data=text))

    def send_to_admins(self, payload: dict):
        for uid in list(self._admins):
            self.send_to_user(uid, payload)

    # ── Desktop-Agent: synchroner Tool-Aufruf ──

    def agent_call(self, user_id: int, tool: str, args: dict, timeout: float = 300.0) -> str:
        import concurrent.futures

        info = self._agents.get(user_id)
        if not info:
            raise ConnectionError("Kein Desktop-Agent verbunden.")
        call_id = str(next(self._ids))
        fut: concurrent.futures.Future = concurrent.futures.Future()
        info.pending[call_id] = fut
        msg = json.dumps({"type": "call", "id": call_id, "tool": tool, "args": args}, default=str)
        self._submit(info.consumer.send(text_data=msg))
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return f"Desktop-Agent: Zeitüberschreitung bei '{tool}' ({int(timeout)}s)."
        finally:
            info.pending.pop(call_id, None)

    def agent_result(self, user_id: int, call_id: str, result: str):
        info = self._agents.get(user_id)
        if info and call_id in info.pending and not info.pending[call_id].done():
            info.pending[call_id].set_result(result)

    def agent_notify(self, user_id: int, title: str, body: str):
        info = self._agents.get(user_id)
        if info:
            msg = json.dumps({"type": "notify", "title": title, "body": body})
            self._submit(info.consumer.send(text_data=msg))

    # ── Bildschirm/Kamera-Frames aus dem Browser ──

    def put_frame(self, user_id: int, jpeg: bytes, angle: str = "screen"):
        self._frames[user_id] = (time.time(), jpeg, angle)

    def latest_frame(self, user_id: int, max_age: float = 15.0) -> tuple[bytes, str] | None:
        item = self._frames.get(user_id)
        if item and time.time() - item[0] <= max_age:
            return item[1], item[2]
        return None

    def clear_frames(self, user_id: int):
        self._frames.pop(user_id, None)


hub = Hub()
