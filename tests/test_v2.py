import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from test_firmware import Firmware, ROOT

sys.path.insert(0, str(ROOT / "tools"))
from upgrade_deck import pack_record, valid_record, points_valid
from protocol import Decoder
from actions import Actions, normalize_config, empty_slot
from icons import get_icon, rgb565, deck_label
from sync import Sync
from profiles import export_profile, import_profile

POINTS = (3559, 1445, 624, 2361, 1985, 3721)


class V2Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.profile = Path(temporary.name) / "actions.json"
        items = [{"name": f"Media {i}", "type": "keys", "keys": ["PLAY"]} for i in range(6)]
        items += [{"name": f"App {i}", "type": "launch", "argv": ["notepad.exe"]} for i in range(6)]
        items += [empty_slot() for _ in range(6)]
        self.profile.write_text(json.dumps(items), encoding="utf-8")

    def test_upgrade_record_rejects_bad_points_and_crc(self):
        record = pack_record(POINTS)
        self.assertTrue(valid_record(record))
        broken = bytearray(record)
        broken[8] ^= 1
        self.assertFalse(valid_record(broken))
        self.assertFalse(points_valid((1, 1, 2, 2, 3, 3)))
        with self.assertRaises(ValueError):
            pack_record((100, 100, 100, 100, 100, 100))

    def test_arm_loads_newest_valid_calibration_and_ignores_torn_write(self):
        fw = Firmware()
        fw.uc.mem_write(0x78000, b"\xff" * 32768)
        self.assertEqual(fw.call("touch_load"), 0)
        fw.uc.mem_write(0x78000, pack_record(POINTS))
        newer = tuple(n + 2 for n in POINTS)
        fw.uc.mem_write(0x78100, pack_record(newer))
        torn = bytearray(pack_record(POINTS))
        torn[32] ^= 1
        fw.uc.mem_write(0x78200, bytes(torn))
        self.assertEqual(fw.call("touch_load"), 1)
        fw.call("touch_get_calibration", 0x10009000)
        self.assertEqual(struct.unpack("<6i", fw.uc.mem_read(0x10009000, 24)), newer)

    def test_invalid_calibration_does_not_replace_current_mapping(self):
        fw = Firmware()
        scratch = 0x10009000
        fw.uc.mem_write(scratch, struct.pack("<6i", *POINTS))
        self.assertEqual(fw.call("touch_calibrate", scratch), 1)
        fw.uc.mem_write(scratch, b"\0" * 24)
        self.assertEqual(fw.call("touch_calibrate", scratch), 0)
        fw.call("touch_get_calibration", scratch)
        self.assertEqual(struct.unpack("<6i", fw.uc.mem_read(scratch, 24)), POINTS)

    def request(self, fw, body):
        fw.outgoing.clear()
        fw.uc.mem_write(0x10009000, body.encode() + b"\0")
        self.assertEqual(fw.call("deck_receive", 0x10009000), 1)
        return Decoder().feed(bytes(fw.outgoing))[0]

    def test_transfer_rejects_gaps_truncated_pixels_and_premature_commit(self):
        fw = Firmware()
        for body, expected in [
            ("X,1,B,42", 1),
            ("X,2,L,6,1,NOTLAR", 1),
            ("X,3,I,6,16," + "0000" * 16, 0),
            ("X,4,I,6,0,FFF", 0),
            ("X,5,F,6", 0),
            ("X,6,Z,42", 0),
        ]:
            self.assertEqual(self.request(fw, body), f'Y,{body.split(",")[1]},{expected}')
        self.assertEqual(fw.uc.mem_read(fw.symbols["deck_revision"], 4), b"\0" * 4)
        self.assertEqual(fw.uc.mem_read(fw.symbols["deck_syncing"], 1), b"\1")

    def test_full_host_to_arm_transfer_with_duplicate_ack_retry(self):
        fw = Firmware()
        actions = Actions(self.profile, True)
        items = actions.items
        images = [get_icon(item) for item in items]
        layout = {
            "revision": actions.revision,
            "items": items,
            "pixels": [rgb565(im).hex().upper() for im in images],
        }
        sync = Sync(layout)
        n = 0
        while not sync.done:
            packet = sync.next_packet(now=n + 1)
            self.assertIsNotNone(packet)
            body = Decoder().feed(packet)[0]
            ack = self.request(fw, body)
            if n == 4:
                self.assertEqual(
                    self.request(fw, body), ack
                )  # lost ACK retry cannot append pixels twice
            self.assertTrue(sync.acknowledge(ack))
            self.assertFalse(sync.failed)
            n += 1
            self.assertLess(n, 1600)
        self.assertEqual(
            struct.unpack("<I", fw.uc.mem_read(fw.symbols["deck_revision"], 4))[0], actions.revision
        )
        self.assertEqual(fw.uc.mem_read(fw.symbols["deck_syncing"], 1), b"\0")
        self.assertEqual(fw.uc.mem_read(fw.symbols["deck_configured"], 1), b"\1")
        slot6 = fw.slot_address(6)
        expected = bytes.fromhex(layout["pixels"][6])
        self.assertEqual(
            fw.uc.mem_read(slot6, 2048),
            b"".join(expected[i : i + 2][::-1] for i in range(0, 2048, 2)),
        )
        self.assertEqual(
            bytes(fw.uc.mem_read(slot6 + 2048, 11)).split(b"\0")[0].decode(), deck_label(items[6])
        )
        for i in range(12, 24):
            self.assertEqual(fw.uc.mem_read(fw.slot_address(i) + 2059, 1), b"\0")

    def test_sync_timeout_bounded_and_wrong_ack_ignored(self):
        items = [empty_slot() for _ in range(24)]
        sync = Sync({"revision": 1, "items": items, "pixels": [""] * 24})
        self.assertIsNotNone(sync.next_packet(0))
        self.assertFalse(sync.acknowledge(f"Y,{sync.token+1},1"))
        self.assertIsNone(sync.next_packet(0.1))
        self.assertIsNotNone(sync.next_packet(0.31))
        self.assertIsNotNone(sync.next_packet(0.62))
        self.assertIsNone(sync.next_packet(0.93))
        self.assertTrue(sync.failed)

    def test_revision_guard_atomic_save_reload_and_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_bytes((self.profile).read_bytes())
            actions = Actions(path, True)
            old = actions.revision
            items = actions.items
            self.assertEqual(len(items), 24)
            items[6], items[12] = items[12], items[6]
            actions.replace(items)
            self.assertNotEqual(old, actions.revision)
            with self.assertRaises(ValueError):
                actions.run(12, old)
            self.assertTrue(actions.run(12, actions.revision).startswith("DENEME:"))
            self.assertEqual(Actions(path).items, items)
            self.assertTrue(path.with_suffix(".json.bak").exists())
            with self.assertRaises(ValueError):
                actions.run(6)

    def test_profile_backup_contains_icons_and_roundtrips(self):
        actions = Actions(self.profile)
        items = actions.items
        images = [get_icon(item) for item in items]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            export_profile(path, items, images)
            with patch("profiles.ROOT", Path(tmp)):
                restored = import_profile(path)
            self.assertEqual([i["type"] for i in items], [i["type"] for i in restored])
            self.assertTrue(all((Path(tmp) / i["icon"]).is_file() for i in restored))

    def test_packaged_firmware_matches_build_and_manifest(self):
        import hashlib

        data = (ROOT / "companion/firmware/mini-deck.bin").read_bytes()
        info = json.loads((ROOT / "companion/firmware/mini-deck.json").read_text())
        self.assertEqual(data, (ROOT / "build/mini-deck.bin").read_bytes())
        self.assertEqual(hashlib.sha256(data).hexdigest(), info["sha256"])
        self.assertEqual(f"{zlib.crc32(data):08X}", info["crc32"])
        self.assertLess(len(data), 0x78000)


if __name__ == "__main__":
    unittest.main()
