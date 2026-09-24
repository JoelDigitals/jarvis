"""Discord-Anbindung: pro Benutzer ein eigener Bot (Token in den eigenen Einstellungen).

Einstellungen (settings.json → "discord_config"):
    bot_token          Token aus dem Discord Developer Portal (Message Content Intent aktivieren!)
    owner_discord_id   Deine Discord-User-ID: nur du darfst per DM mit JARVIS sprechen
    allowed_channels   Kanal-IDs, in denen JARVIS antwortet (bei @Erwähnung oder immer, s. respond_all)
    respond_all        In erlaubten Kanälen auf jede Nachricht antworten (sonst nur bei @Erwähnung)
    notify_dm          Erinnerungen, Wecker, Hermes-Ergebnisse usw. zusätzlich als DM schicken
"""
from __future__ import annotations

import asyncio
import logging
import threading

from django.contrib.auth import get_user_model
from django.db import close_old_connections

log = logging.getLogger("jarvis.discord")


def _chunks(text: str, size: int = 1900):
    text = text or "…"
    return [text[i:i + size] for i in range(0, len(text), size)]


class DiscordManager:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bots: dict[int, dict] = {}  # user_id -> {"token", "client", "cfg"}
        self._lock = threading.Lock()

    # ── Lebenszyklus ──

    def start(self):
        if self.loop:
            return
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="discord-loop").start()

    def refresh(self):
        """Bots passend zu den aktuellen Einstellungen aller Benutzer starten/stoppen."""
        try:
            import discord  # noqa: F401
        except ImportError:
            return
        self.start()
        from .config_store import load_settings
        from .userdata import user_scope

        wanted: dict[int, dict] = {}
        for user in get_user_model().objects.filter(is_active=True):
            with user_scope(user) as profile:
                if not profile.license_valid():
                    continue
                cfg = load_settings().get("discord_config") or {}
            if cfg.get("bot_token"):
                wanted[user.id] = cfg
        with self._lock:
            for uid in list(self.bots):
                if uid not in wanted or wanted[uid].get("bot_token") != self.bots[uid]["token"]:
                    self._stop(uid)
            for uid, cfg in wanted.items():
                if uid in self.bots:
                    self.bots[uid]["cfg"] = cfg  # Kanäle/Owner ohne Neustart übernehmen
                else:
                    self._start_bot(uid, cfg)

    def _stop(self, uid: int):
        entry = self.bots.pop(uid, None)
        if entry:
            asyncio.run_coroutine_threadsafe(entry["client"].close(), self.loop)
            log.info("[Discord] Bot von Benutzer %s gestoppt", uid)

    def _start_bot(self, uid: int, cfg: dict):
        import discord

        manager = self
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True

        class UserBot(discord.Client):
            async def on_ready(self):
                log.info("[Discord] Bot %s online für Benutzer %s", self.user, uid)

            async def on_message(self, message):
                await manager._on_message(uid, self, message)

        client = UserBot(intents=intents)
        self.bots[uid] = {"token": cfg["bot_token"], "client": client, "cfg": cfg}

        async def runner():
            try:
                await client.start(cfg["bot_token"])
            except Exception as e:
                log.warning("[Discord] Bot von Benutzer %s beendet: %s", uid, e)
                await asyncio.to_thread(_notify_safe, uid, "Discord-Bot gestoppt", f"{e}")

        asyncio.run_coroutine_threadsafe(runner(), self.loop)

    # ── Nachrichten ──

    async def _on_message(self, uid: int, client, message):
        import discord

        if message.author.bot:
            return
        cfg = self.bots.get(uid, {}).get("cfg") or {}
        owner = str(cfg.get("owner_discord_id") or "").strip()
        is_dm = isinstance(message.channel, discord.DMChannel)
        if is_dm:
            if not owner or str(message.author.id) != owner:
                return
        else:
            allowed = {str(c).strip() for c in cfg.get("allowed_channels") or []}
            if str(message.channel.id) not in allowed:
                return
            mentioned = client.user in message.mentions
            if not (mentioned or cfg.get("respond_all")):
                return

        text = message.content
        if client.user:
            text = text.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "")
        text = text.strip()
        if not text:
            return
        if not is_dm:
            text = f"[Discord #{getattr(message.channel, 'name', '?')}, {message.author.display_name}] {text}"

        async with message.channel.typing():
            answer = await asyncio.to_thread(_chat, uid, text)
        for i, part in enumerate(_chunks(answer)):
            if i == 0:
                await message.reply(part, mention_author=False)
            else:
                await message.channel.send(part)

    # ── Benachrichtigungen als DM ──

    def send_dm(self, uid: int, text: str):
        entry = self.bots.get(uid)
        if not entry or not self.loop:
            return
        cfg = entry["cfg"]
        owner = str(cfg.get("owner_discord_id") or "").strip()
        if not (cfg.get("notify_dm") and owner.isdigit()):
            return
        client = entry["client"]

        async def _send():
            try:
                user = client.get_user(int(owner)) or await client.fetch_user(int(owner))
                for part in _chunks(text):
                    await user.send(part)
            except Exception as e:
                log.warning("[Discord] DM an %s fehlgeschlagen: %s", owner, e)

        asyncio.run_coroutine_threadsafe(_send(), self.loop)

    def status(self, uid: int) -> dict:
        entry = self.bots.get(uid)
        if not entry:
            return {"running": False}
        client = entry["client"]
        ready = client.is_ready()
        return {"running": True, "ready": ready, "bot": str(client.user) if ready else ""}


def _chat(uid: int, text: str) -> str:
    try:
        from .engine import chat
        user = get_user_model().objects.get(id=uid)
        return chat(user, text, channel="discord")["response"]
    except Exception as e:
        return f"Fehler: {e}"
    finally:
        close_old_connections()


def _notify_safe(uid, title, body):
    try:
        from .notify import notify
        notify(uid, title, body, kind="warning", to_discord=False)
    finally:
        close_old_connections()


manager = DiscordManager()
