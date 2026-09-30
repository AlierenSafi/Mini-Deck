import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from PIL import Image
from test_firmware import Firmware, ROOT
from protocol import Decoder, encode
from game_audio import DiscordAudio
from game_config import DEFAULTS, load, save
from game import GameController, lcd_label
from game_integrations import pubg_summary


def feed(fw, body):
    fw.incoming.extend(encode(body))
    fw.call("receive")


class Volume:
    def __init__(self, volume):
        self.volume = volume
        self.muted = False

    def GetMasterVolume(self):
        return self.volume

    def SetMasterVolume(self, value, _):
        self.volume = value

    def GetMute(self):
        return self.muted

    def SetMute(self, value, _):
        self.muted = value


class Session:
    def __init__(self, key, value):
        self.InstanceIdentifier = key
        self.SimpleAudioVolume = Volume(value)


class GameTests(unittest.TestCase):
    def test_focus_restores_each_session_and_handles_new_sessions(self):
        sessions = [Session("a", 0.8), Session("b", 0.1)]
        audio = DiscordAudio(lambda: sessions)
        audio.command(4)
        self.assertEqual(audio.sample(), (20, False))
        sessions.append(Session("c", 0.9))
        audio.sample()
        self.assertEqual(sessions[-1].SimpleAudioVolume.volume, 0.2)
        audio.command(1)
        self.assertEqual(audio.sample(), (20, True))
        audio.command(4)
        self.assertEqual([s.SimpleAudioVolume.volume for s in sessions], [0.8, 0.1, 0.9])
        self.assertTrue(all(s.SimpleAudioVolume.muted for s in sessions))
        audio.command(3)
        self.assertEqual(audio.sample(), (100, True))

    def test_absent_audio_fails_without_faking_state(self):
        audio = DiscordAudio(lambda: [])
        self.assertEqual(audio.sample(), (None, None))
        with self.assertRaises(ValueError):
            audio.command(4)
        self.assertFalse(audio.focus)

    def test_settings_encrypt_secret_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = dict(DEFAULTS, pubg_key="test-private-value", mic_keys="CTRL+ALT+F10")
            save(config, path)
            self.assertNotIn("test-private-value", path.read_text(encoding="utf-8"))
            self.assertEqual(load(path), config)

    def test_remote_navigation_is_validated_and_acknowledged(self):
        fw = Firmware()
        for page, detail, bank in (
            (3, 0, 0),
            (3, 1, 0),
            (3, 2, 0),
            (3, 3, 0),
            (2, 4, 0),
            (1, 0, 2),
            (0, 0, 0),
        ):
            feed(fw, f"W,8,{page},{detail},{bank}")
            self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["page"], 4))[0], page)
            self.assertIn("H,8,1", Decoder().feed(bytes(fw.outgoing)))
            fw.outgoing.clear()
            fw.call("screen")
        for body in ("W,9,4,0,0", "W,9,3,8,0", "W,9,1,0,3", "W,0,3,0,0", "W,1,3,0,0,0"):
            feed(fw, body)
            self.assertEqual(bytes(fw.outgoing), b"")

    def test_game_touch_commands_and_navigation(self):
        fw = Firmware()
        fw.write("online", b"\1")
        feed(fw, "W,2,3,0,0")
        fw.outgoing.clear()
        for action in range(5):
            fw.write("pending", struct.pack("<I", 0))
            fw.call(
                "handle_tap",
                50 + (action % 2) * 116,
                120 if action < 2 else 194 + ((action - 2) // 2) * 32,
            )
            self.assertIn(f"J,{action+1},{action}", Decoder().feed(bytes(fw.outgoing)))
            fw.outgoing.clear()
        fw.call("handle_tap", 160, 226)
        self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["game_detail"], 4))[0], 3)
        fw.call("handle_tap", 40, 255)
        self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["game_detail"], 4))[0], 0)

    def test_auto_switch_only_on_foreground_transition(self):
        fw = Firmware()
        feed(fw, "G,1,50,0,2,0,5,16")
        self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["page"], 4))[0], 3)
        feed(fw, "W,1,1,0,2")
        feed(fw, "G,1,50,0,2,0,5,16")
        self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["page"], 4))[0], 1)
        feed(fw, "G,0,50,0,2,0,5,16")
        feed(fw, "G,1,50,0,2,0,5,16")
        self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["page"], 4))[0], 3)

    def test_game_render_extremes_fit_and_unchanged_draws_nothing(self):
        fw = Firmware()
        fw.write("online", b"\1")
        feed(fw, "G,0,100,1,1,1,999,9999")
        feed(fw, "U,1,1,999,99999,999,9999,1")
        fw.write("monitor_values", struct.pack("<5i", 100, 100, 100, 9999, 9999))
        for row in range(6):
            feed(fw, f"N,{row},1," + "W" * 22)
        for detail in range(4):
            feed(fw, f"W,1,3,{detail},0")
            fw.call("screen")
            for x, y, text, scale in fw.texts:
                self.assertLessEqual(x + len(text) * 6 * scale, 240, text)
                self.assertLessEqual(y + 8 * scale, 320, text)
            for x, y, w, h in fw.rectangles:
                self.assertTrue(0 <= x < 240 and 0 <= y < 320 and x + w <= 240 and y + h <= 320)
            fw.texts.clear()
            fw.rectangles.clear()
            fw.call("update_metrics")
            self.assertEqual(fw.texts, [])
            self.assertEqual(fw.rectangles, [])

    def test_game_digits_incremental_render_matches_full(self):
        fw = Firmware()
        fw.write("online", b"\1")
        feed(fw, "W,1,3,0,0")
        fw.call("screen")
        for volume in (100, 1, 101):
            feed(fw, f"G,0,{volume},0,2,0,1,16")
            fw.call("update_metrics")
            incremental = fw.image.tobytes()
            fw.call("screen")
            self.assertEqual(incremental, fw.image.tobytes())

    def test_voice_icons_refresh_clear_and_match_full_in_both_themes(self):
        for theme in (0, 1):
            fw = Firmware()
            fw.write("preferences", struct.pack("<I", theme))
            fw.write("online", b"\1")
            feed(fw, "G,0,50,0,0,0,1,16")
            feed(fw, "W,1,3,1,0")
            fw.call("screen")
            icons = []
            for state in (0, 2, 4, 5, 3, 0):
                feed(fw, f"N,0,{state}," + ("Member".ljust(22)))
                fw.call("update_metrics")
                partial = fw.image.tobytes()
                icons.append(fw.image.crop((176, 87, 224, 109)).tobytes())
                fw.call("screen")
                self.assertEqual(partial, fw.image.tobytes())
                fw.rectangles.clear()
                fw.texts.clear()
                fw.call("update_metrics")
                self.assertEqual(fw.rectangles, [])
                self.assertEqual(fw.texts, [])
            self.assertEqual(len(set(icons[:5])), 5)
            self.assertEqual(icons[0], icons[-1])
            fw.write("online", b"\0")
            fw.call("update_metrics")
            self.assertEqual(fw.image.crop((176, 87, 224, 109)).tobytes(), icons[4])

    def test_own_mic_icon_changes_with_confirmed_status(self):
        fw = Firmware()
        fw.write("online", b"\1")
        feed(fw, "W,1,3,0,0")
        fw.call("screen")
        icons = []
        for state in (0, 1, 0, 2):
            feed(fw, f"G,0,50,0,{state},0,1,16")
            fw.call("update_metrics")
            icons.append(fw.image.crop((48, 104, 76, 132)).tobytes())
            partial = fw.image.tobytes()
            fw.call("screen")
            self.assertEqual(partial, fw.image.tobytes())
        self.assertEqual(icons[0], icons[2])
        self.assertNotEqual(icons[0], icons[1])
        self.assertNotEqual(icons[0], icons[3])

    def test_game_event_duplicate_is_not_replayed(self):
        game = GameController(None, lambda *_: None, True)
        game.submit(1, 7)
        game.submit(1, 7)
        self.assertEqual(game.commands.qsize(), 1)
        game.seen[7] = 1
        game.submit(1, 7)
        self.assertEqual(game.replies.get_nowait(), (7, 1))
        self.assertFalse(game.submit(9, 8))

    def test_names_cannot_inject_serial_commands(self):
        self.assertEqual(len(lcd_label("Çığlık\n@W,1,3,0,0*FFFF")), 22)
        self.assertNotIn("@", lcd_label("@W,1"))

    def test_match_summary_selects_newest_date_not_relationship_order(self):
        player = {
            "data": [
                {"id": "p1", "relationships": {"matches": {"data": [{"id": "old"}, {"id": "new"}]}}}
            ]
        }

        def match(date, kills):
            return {
                "data": {"attributes": {"createdAt": date}},
                "included": [
                    {
                        "type": "participant",
                        "attributes": {
                            "stats": {
                                "playerId": "p1",
                                "kills": kills,
                                "damageDealt": 120.5,
                                "winPlace": 2,
                            }
                        },
                    }
                ],
            }

        with patch(
            "game_integrations.http_json",
            side_effect=[player, match("2026-09-23", 1), match("2026-09-25", 5)],
        ):
            result = pubg_summary(dict(DEFAULTS, player="tester", pubg_key="test"))
        self.assertEqual(result["kills"], 5)


def preview():
    images = []
    fw = Firmware()
    fw.write("online", b"\1")
    fw.write("metrics", struct.pack("<7I", 32, 48, 60, 0, 0, 21, 45))
    fw.write("monitor_values", struct.pack("<5i", 32, 48, 87, 144, 7))
    fw.write("history_count", struct.pack("<I", 60))
    fw.write("history", struct.pack("<300H", *([30] * 240 + [6 + (i % 7) for i in range(60)])))
    feed(fw, "G,0,65,0,0,0,42,7")
    feed(fw, "U,1,1,6,742,3,118,1")
    for row, name in enumerate(
        (
            "SEN",
            "TAKIM ARKADASI 1",
            "TAKIM ARKADASI 2",
            "TAKIM ARKADASI 3",
            "PUBG TAKIM ODASI",
            "25.09.2026 18.45 UTC",
        )
    ):
        feed(fw, f"N,{row},{1 if row==1 else 2 if row==2 else 0}," + name.ljust(22))
    for detail in range(4):
        feed(fw, f"W,1,3,{detail},0")
        fw.call("screen")
        images.append(fw.image.resize((480, 640), Image.Resampling.NEAREST))
    out = Image.new("RGB", (1970, 680), "#101522")
    for i, image in enumerate(images):
        out.paste(image, (10 + i * 490, 20))
    out.save(ROOT / "docs/game-panel-preview.png")


if __name__ == "__main__":
    import sys

    if "--preview" in sys.argv:
        preview()
    else:
        unittest.main()
