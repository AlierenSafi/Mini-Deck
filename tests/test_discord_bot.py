import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from discord_bot import BotMonitor, VoiceRosterClient, blank, channel_snapshot
from game_config import DEFAULTS, load, save
from game import GameController


class BotTests(unittest.TestCase):
    def test_roster_mutes_names_and_own_status(self):
        channel = NS(id=123, name="PUBG", members=[])

        def member(uid, name, muted=False, other=False):
            voice = NS(
                channel=NS(id=456) if other else channel,
                self_mute=muted,
                mute=False,
                self_deaf=False,
                deaf=False,
                suppress=False,
            )
            return NS(id=uid, display_name=name, voice=voice)

        channel.members = [
            member(2, "Takım"),
            member(1, "Ben", True),
            member(3, "Başka kanal", other=True),
        ]
        value = channel_snapshot(channel, "1")
        self.assertEqual([m["name"] for m in value["members"]], ["Ben", "Takım"])
        self.assertTrue(value["mic"])
        self.assertTrue(value["members"][0]["mute"])
        self.assertFalse(value["speaking_available"])
        self.assertTrue(all(not m["speaking"] for m in value["members"]))
        self.assertIsNone(channel_snapshot(channel, "999")["mic"])
        channel.members = []
        self.assertEqual(channel_snapshot(channel)["members"], [])

    def test_mic_and_deaf_are_independent_and_refresh(self):
        channel = NS(id=123, name="Team", members=[])
        voice = NS(
            channel=channel,
            self_mute=False,
            mute=False,
            self_deaf=False,
            deaf=False,
            suppress=False,
        )
        channel.members = [NS(id=1, display_name="Self", voice=voice)]
        for mute, deaf in ((False, False), (True, False), (False, True), (True, True)):
            voice.self_mute = mute
            voice.self_deaf = deaf
            snapshot = channel_snapshot(channel, "1")
            self.assertEqual(snapshot["mic"], mute)
            self.assertEqual(
                (snapshot["members"][0]["mute"], snapshot["members"][0]["deaf"]), (mute, deaf)
            )
        voice.self_mute = voice.self_deaf = False
        voice.mute = voice.deaf = True
        snapshot = channel_snapshot(channel, "1")
        self.assertTrue(snapshot["mic"])
        self.assertTrue(snapshot["members"][0]["deaf"])
        self.assertIsNone(channel_snapshot(channel, "")["mic"])

    def test_deaf_frames_negotiate_legacy_and_new_firmware(self):
        controller = GameController(None, lambda *_: None, True)
        controller.config.update(discord_mode="bot")
        for mute, deaf, state in (
            (False, False, 0),
            (True, False, 2),
            (False, True, 4),
            (True, True, 5),
        ):
            controller.bot.latest = dict(
                blank("ok"),
                status=1,
                mic=mute,
                members=[dict(id="1", name="Self", mute=mute, deaf=deaf, speaking=False)],
            )
            self.assertEqual(controller.frames(version=8)[2].split(",")[2], str(state))
            self.assertEqual(
                controller.frames(version=7)[2].split(",")[2], str(2 if deaf else state)
            )

    def test_members_are_bounded(self):
        channel = NS(id=123, name="PUBG", members=[])
        voice = NS(
            channel=channel,
            self_mute=False,
            mute=False,
            self_deaf=False,
            deaf=False,
            suppress=False,
        )
        channel.members = [NS(id=i, display_name=str(i), voice=voice) for i in range(200)]
        self.assertEqual(len(channel_snapshot(channel)["members"]), 100)

    def test_encrypted_bot_settings_preserve_pubg_and_normalize_channel_link(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = dict(
                DEFAULTS,
                pubg_key="private-pubg",
                bot_token="private-bot",
                player="tester",
                voice_channel="https://discord.com/channels/123456789/987654321",
                mic_keys="CTRL+ALT+F10",
            )
            save(config, path)
            value = load(path)
            self.assertEqual(value["voice_channel"], "987654321")
            self.assertEqual(value["pubg_key"], "private-pubg")
            self.assertEqual(value["bot_token"], "private-bot")
            self.assertNotIn("private-", path.read_text())
            for invalid in (
                "https://example.com/channels/1/2",
                "https://discord.com/channels/@me/2",
                "-2",
                "PUBG",
                "0",
            ):
                config["voice_channel"] = invalid
                with self.assertRaises(ValueError):
                    save(config, path)

    def test_bot_roster_uses_existing_board_frames_without_rpc_microphone(self):
        controller = GameController(None, lambda *_: None, True)
        controller.config.update(discord_mode="bot")
        controller.bot.latest = dict(
            blank("ok"),
            status=1,
            channel="PUBG",
            mic=True,
            members=[{"id": "1", "name": "Takım", "mute": True, "speaking": False}],
        )
        controller.discord.latest = blank("RPC kapalı")
        frames = controller.frames()
        self.assertEqual(frames[0].split(",")[4], "1")
        self.assertTrue(frames[2].startswith("N,0,2,TAKIM"))
        controller.bot.publish(blank("Disconnected", 2))
        self.assertEqual(controller.snapshot()["discord"]["members"], [])


class AsyncBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_nonprivileged_voice_and_guild_intents_and_disconnect_clears_state(self):
        monitor = BotMonitor(lambda: dict(DEFAULTS), lambda *_: None)
        client = VoiceRosterClient(monitor, dict(DEFAULTS, voice_channel="123"))
        self.assertEqual(client.intents.value, 129)
        self.assertFalse(client.intents.members)
        self.assertFalse(client.intents.message_content)
        self.assertIsNone(client._connection.max_messages)
        monitor.latest = dict(blank("ready"), status=1, members=[{"name": "old"}])
        await client.on_disconnect()
        self.assertEqual(monitor.latest["members"], [])
        self.assertEqual(monitor.latest["status"], 2)
        await client.close()

    async def test_settings_change_cancels_connection_without_leaking_token(self):
        config = dict(DEFAULTS, voice_channel="123", bot_token="secret")
        events = []
        closed = []
        monitor = BotMonitor(lambda: dict(config), lambda *args: events.append(args))

        class FakeClient:
            def __init__(self, *args):
                pass

            async def start(self, token, reconnect):
                await asyncio.Event().wait()

            def publish_roster(self):
                config["voice_channel"] = "456"

            async def close(self):
                closed.append(True)

        with patch("discord_bot.VoiceRosterClient", FakeClient):
            await asyncio.wait_for(monitor.connect(dict(config)), 2)
        self.assertEqual(closed, [True])
        self.assertNotIn("secret", repr(events))


if __name__ == "__main__":
    unittest.main()
