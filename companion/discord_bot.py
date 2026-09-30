"""Read-only guild voice roster. No messages, audio connection, or moderation."""

import asyncio
import contextlib
import threading
import time

import discord


def blank(message, status=0):
    return {
        "status": status,
        "members": [],
        "mic": None,
        "channel": "",
        "message": message,
        "source": "bot",
        "speaking_available": False,
    }


# Keep microphone mute and deafen separate; identify the local user by account ID, not display name.
def channel_snapshot(channel, own_id=""):
    members = []
    mic = None
    for member in sorted(
        channel.members, key=lambda m: (str(m.id) != own_id, m.display_name.casefold(), m.id)
    ):
        voice = member.voice
        if voice is None or voice.channel is None or voice.channel.id != channel.id:
            continue
        muted = bool(voice.self_mute or voice.mute or voice.suppress)
        deafened = bool(voice.self_deaf or voice.deaf)
        if str(member.id) == own_id:
            mic = muted
        if len(members) < 100:
            members.append(
                {
                    "id": str(member.id),
                    "name": member.display_name,
                    "mute": muted,
                    "deaf": deafened,
                    "speaking": False,
                }
            )
    return {
        "status": 1,
        "members": members,
        "mic": mic,
        "channel": channel.name,
        "message": channel.name + " · Bot bağlı",
        "source": "bot",
        "speaking_available": False,
    }


def fingerprint(config):
    return tuple(
        config.get(k, "") for k in ("discord_mode", "bot_token", "voice_channel", "discord_user_id")
    )


class VoiceRosterClient(discord.Client):
    def __init__(self, monitor, config):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        flags = discord.MemberCacheFlags.none()
        flags.voice = True
        super().__init__(
            intents=intents,
            member_cache_flags=flags,
            chunk_guilds_at_startup=False,
            max_messages=None,
        )
        self.monitor = monitor
        self.channel_id = int(config["voice_channel"])
        self.own_id = config.get("discord_user_id", "")
        self.live = False

    def publish_roster(self):
        if not self.live:
            return
        channel = self.get_channel(self.channel_id)
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            self.monitor.publish(
                blank(
                    "Ses kanalı bulunamadı: botu sunucuya ekleyin ve kanal bağlantısını kontrol edin.",
                    2,
                )
            )
            return
        if channel.guild.unavailable or channel.guild.me is None:
            self.monitor.publish(blank("Discord sunucusu geçici olarak erişilemiyor.", 2))
            return
        if not channel.permissions_for(channel.guild.me).view_channel:
            self.monitor.publish(blank("Botun bu ses kanalında Kanalı Görüntüle izni yok.", 2))
            return
        self.monitor.publish(channel_snapshot(channel, self.own_id))

    async def on_ready(self):
        self.live = True
        self.publish_roster()

    async def on_resumed(self):
        self.live = True
        self.publish_roster()

    async def on_disconnect(self):
        self.live = False
        self.monitor.publish(blank("Discord bağlantısı kesildi; yeniden bağlanılıyor.", 2))

    async def on_voice_state_update(self, member, before, after):
        if any(
            channel and channel.id == self.channel_id for channel in (before.channel, after.channel)
        ):
            self.publish_roster()

    async def on_guild_unavailable(self, guild):
        channel = self.get_channel(self.channel_id)
        if channel and channel.guild.id == guild.id:
            self.monitor.publish(blank("Discord sunucusu geçici olarak erişilemiyor.", 2))

    async def on_guild_available(self, guild):
        self.publish_roster()

    async def on_error(self, event_method, *args, **kwargs):
        # Discord exceptions may include request context; never copy it into logs.
        self.monitor.publish(
            blank("Discord kanal verisi işlenemedi; bağlantı yeniden kontrol edilecek.", 2)
        )


class BotMonitor(threading.Thread):
    def __init__(self, settings, emit):
        super().__init__(daemon=True, name="deck-discord-bot")
        self.settings, self.emit = settings, emit
        self.stop_event = threading.Event()
        self.latest = blank("Takım listesi için bot anahtarı ve ses kanalı bağlantısı gerekli.")

    def publish(self, value):
        if value != self.latest:
            self.latest = value
            self.emit("game_discord", dict(value))

    async def connect(self, config):
        client = VoiceRosterClient(self, config)
        task = asyncio.create_task(client.start(config["bot_token"], reconnect=True))
        try:
            while not self.stop_event.is_set() and fingerprint(self.settings()) == fingerprint(
                config
            ):
                if task.done():
                    await task
                    break
                client.publish_roster()  # cached data only; also notices channel/permission changes
                await asyncio.sleep(0.5)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            await client.close()
            self.publish(blank("Discord bağlantısı kapalı."))

    def run(self):
        while not self.stop_event.is_set():
            config = self.settings()
            if (
                config.get("discord_mode", "bot") != "bot"
                or not config.get("bot_token")
                or not config.get("voice_channel")
            ):
                self.publish(
                    blank("Takım listesi için bot anahtarı ve ses kanalı bağlantısı gerekli.")
                )
                self.stop_event.wait(0.5)
                continue
            self.publish(blank("Discord botuna bağlanılıyor…"))
            try:
                asyncio.run(self.connect(config))
            except discord.LoginFailure:
                self.publish(
                    blank("Bot anahtarı geçersiz. Bot sayfasındaki Token değerini kontrol edin.", 2)
                )
            except discord.PrivilegedIntentsRequired:
                self.publish(blank("Discord bağlantı izinlerini reddetti.", 2))
            except Exception:
                self.publish(
                    blank(
                        "Discord bot bağlantısı kurulamadı; ağ ve kanal ayarlarını kontrol edin.", 2
                    )
                )
            # Back off on errors, but changed settings and shutdown take effect promptly.
            until = time.monotonic() + 30
            while (
                not self.stop_event.is_set()
                and time.monotonic() < until
                and fingerprint(self.settings()) == fingerprint(config)
            ):
                self.stop_event.wait(0.5)

    def close(self):
        self.stop_event.set()
