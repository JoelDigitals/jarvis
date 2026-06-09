import asyncio, json, threading, time
from pathlib import Path

import discord

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.json"


class DiscordBridge:
    def __init__(self, jarvis_ref=None):
        self.jarvis = jarvis_ref
        self._bot: discord.Client | None = None
        self._token = ""
        self._allowed = set()
        self._ready = asyncio.Event()
        self._user_id = 0
        self._response_queue: asyncio.Queue[str] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None

    def _load_cfg(self):
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            dc = cfg.get("discord_config", {})
            self._token = dc.get("bot_token", "")
            self._allowed = set(dc.get("allowed_channels", []))
            return bool(self._token)
        except:
            return False

    async def start(self):
        if not self._load_cfg():
            return
        self._loop = asyncio.get_running_loop()
        intents = discord.Intents.default()
        intents.message_content = True

        class _Client(discord.Client):
            async def on_ready(_, *_a, **_kw):
                print(f"[DISCORD] ✅ Bot online als {_.user} (ID {_.user.id})")
                self._user_id = _.user.id
                self._ready.set()

            async def on_message(_, msg):
                if msg.author.bot:
                    return
                if msg.channel.id == self._user_id:
                    pass
                elif self._allowed and str(msg.channel.id) not in self._allowed:
                    return
                await self._handle_message(msg)

        self._bot = _Client(intents=intents)
        try:
            await self._bot.start(self._token)
        except Exception as e:
            print(f"[DISCORD] ❌ Fehler: {e}")

    async def stop(self):
        if self._bot:
            await self._bot.close()

    async def send_to_channel(self, channel_id: int, text: str):
        if not self._bot or not self._bot.is_ready():
            return
        try:
            ch = self._bot.get_channel(channel_id)
            if ch:
                await ch.send(text[:2000])
        except:
            pass

    async def send_to_user(self, text: str):
        await self.send_to_channel(self._user_id, text)

    # ── internal ──

    async def _handle_message(self, msg):
        if not self.jarvis:
            return
        content = msg.clean_content.strip()
        if not content:
            return

        channel_name = getattr(msg.channel, "name", "DM")
        print(f"[DISCORD] 📩 #{channel_name} <{msg.author}>: {content[:80]}")

        try:
            await msg.add_reaction("🤖")
        except:
            pass

        try:
            response = await self.jarvis.process_text(content)
            if response:
                for chunk in _chunk_text(response, 1950):
                    await msg.reply(chunk, mention_author=False)
            else:
                await msg.reply("Keine Antwort erhalten.", mention_author=False)
        except Exception as e:
            await msg.reply(f"Fehler: {e}", mention_author=False)


def _chunk_text(text: str, size: int):
    return [text[i : i + size] for i in range(0, len(text), size)]
