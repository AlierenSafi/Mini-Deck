"""Three-page navigation, SRAM partitioning and backward-compatible profiles."""

import json
import queue
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_firmware import Firmware, ROOT
from actions import normalize_config, empty_slot
from bridge import Bridge
from protocol import Decoder, encode, parse_event
from profiles import export_profile, import_profile
from icons import get_icon


class LargeSlotTests(unittest.TestCase):
    def ready_firmware(self):
        fw = Firmware()
        fw.call("deck_init")
        fw.write("online", b"\1")
        fw.write("deck_configured", b"\1")
        fw.write("deck_revision", struct.pack("<I", 123))
        fw.write("page", struct.pack("<I", 1))
        for i in range(24):
            fw.uc.mem_write(fw.slot_address(i) + 2048, b"TEST LABEL\0\1")
        return fw

    def test_each_large_target_sends_its_own_action_on_all_three_pages(self):
        fw = self.ready_firmware()
        for bank in range(3):
            fw.write("app_page", struct.pack("<I", bank))
            for slot in range(6):
                for dx, dy in ((0, 0), (54, 32), (107, 63)):
                    fw.write("pending", b"\0" * 4)
                    fw.outgoing.clear()
                    fw.call("handle_tap", 8 + (slot % 2) * 116 + dx, 38 + (slot // 2) * 70 + dy)
                    event = parse_event(Decoder().feed(bytes(fw.outgoing))[0])
                    self.assertEqual(event[1:], (6 + bank * 6 + slot, 123))

    def test_navigation_wrap_direct_selection_and_gaps_never_launch(self):
        fw = self.ready_firmware()
        for x, expected in ((210, 1), (210, 2), (210, 0), (25, 2), (82, 0), (120, 1), (158, 2)):
            fw.call("handle_tap", x, 261)
            self.assertEqual(
                struct.unpack("<I", fw.uc.mem_read(fw.symbols["app_page"], 4))[0], expected
            )
        for x, y in ((116, 60), (20, 102), (20, 172), (52, 260), (98, 260), (232, 60), (20, 278)):
            fw.call("handle_tap", x, y)
        self.assertEqual(bytes(fw.outgoing), b"")

    def test_bank_memory_and_initialization_fit_real_sram_and_leave_stack(self):
        fw = Firmware()
        self.assertLessEqual(fw.symbols["_ebss"], fw.symbols["_stack_top"] - 4096)
        for i in range(24):
            address = fw.slot_address(i)
            start, end = (0x10000000, fw.symbols["_ebss"]) if i < 12 else (0x2007C000, 0x20084000)
            self.assertTrue(start <= address and address + 2060 <= end)
            fw.uc.mem_write(address, b"\xff" * 2060)
        fw.call("deck_init")
        for i in range(24):
            self.assertEqual(bytes(fw.uc.mem_read(fw.slot_address(i), 2060)), b"\0" * 2060)
        self.assertEqual(fw.slot_address(24), 0)

    def test_full_icon_upload_to_last_slot_in_ahb_sram(self):
        fw = Firmware()
        requests = ["B,42", "L,23,1,LAST SLOT"]
        requests += [f"I,23,{offset}," + ("F81F" * 16) for offset in range(0, 1024, 16)]
        requests += ["F,23"]
        for token, request in enumerate(requests, 1):
            fw.uc.mem_write(0x10009000, f"X,{token},{request}".encode() + b"\0")
            fw.outgoing.clear()
            fw.call("deck_receive", 0x10009000)
            self.assertEqual(Decoder().feed(bytes(fw.outgoing)), [f"Y,{token},1"])
        self.assertEqual(bytes(fw.uc.mem_read(fw.slot_address(23), 2048)), b"\x1f\xf8" * 1024)
        fw.uc.mem_write(0x10009000, b"X,100,L,24,1,INVALID\0")
        fw.outgoing.clear()
        fw.call("deck_receive", 0x10009000)
        self.assertEqual(Decoder().feed(bytes(fw.outgoing)), ["Y,100,0"])

    def test_render_all_app_pages_with_icons_and_long_labels_in_bounds(self):
        fw = self.ready_firmware()
        for bank in range(3):
            fw.write("app_page", struct.pack("<I", bank))
            fw.call("screen")
        for x, y, w, h in fw.rectangles:
            self.assertTrue(0 <= x and 0 <= y and x + w <= 240 and y + h <= 320)
        for x, y, text, scale in fw.texts:
            self.assertTrue(x + len(text) * 6 * scale <= 240 and y + 8 * scale <= 320, text)

    def test_old_profiles_keep_order_and_add_only_empty_slots(self):
        for count in (12, 18, 24):
            old = [dict(empty_slot(), name=f"Slot {i}") for i in range(count)]
            result = normalize_config(old)
            self.assertEqual(result[:count], old)
            self.assertEqual(len(result), 24)
            self.assertTrue(all(i["type"] == "empty" for i in result[count:]))
            self.assertEqual(len(old), count)

    def test_v2_export_with_icons_imports_as_three_app_pages(self):
        items = [empty_slot() for _ in range(18)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            export_profile(path, items, [get_icon(i) for i in items])
            value = json.loads(path.read_text(encoding="utf-8"))
            value["version"] = 2
            path.write_text(json.dumps(value), encoding="utf-8")
            with patch("profiles.ROOT", Path(tmp)):
                restored = import_profile(path)
            self.assertEqual(len(restored), 24)
            self.assertTrue(all((Path(tmp) / i["icon"]).exists() for i in restored[:18]))
            self.assertTrue(all(i["type"] == "empty" for i in restored[18:]))

    def test_v3_diagnostic_is_connected_and_v2_cannot_trigger_actions(self):
        for version in (2, 3):
            stop = threading.Event()
            messages = queue.Queue()

            class Actions:
                def run(self, *args):
                    raise AssertionError("Old firmware must not trigger actions")

            class Port:
                def __init__(self):
                    self.data = encode(f"D,0,48000000,{version},1,0,1")
                    if version == 2:
                        self.data += encode("E,1,0,1")

                @property
                def in_waiting(self):
                    return len(self.data)

                def read(self, count):
                    result = self.data[:count]
                    self.data = self.data[count:]
                    if not self.data:
                        stop.set()
                    return result

                def write(self, data):
                    pass

            Bridge("FAKE", Actions(), messages, stop).serve(Port())
            states = []
            while not messages.empty():
                kind, value = messages.get()
                if kind == "state":
                    states.append(value)
            self.assertEqual(any("eski sürüm" in s for s in states), version == 2)
            self.assertEqual(any("Mini Deck bağlı" in s for s in states), version == 3)


if __name__ == "__main__":
    unittest.main()
