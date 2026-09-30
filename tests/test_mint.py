"""Navigation isolation and incremental rendering for the 240x320 mint UI."""

import struct
import unittest
from test_firmware import Firmware
from test_game import feed


def value(fw, name):
    return struct.unpack("<I", fw.uc.mem_read(fw.symbols[name], 4))[0]


class MintTests(unittest.TestCase):
    def test_bottom_dock_never_launches_slot_or_game_action(self):
        fw = Firmware()
        fw.write("online", b"\1")
        for source in range(4):
            for x in (0, 59, 60, 119, 120, 179, 180, 239):
                for y in (280, 299, 319):
                    fw.write("page", struct.pack("<I", source))
                    fw.outgoing.clear()
                    fw.call("handle_tap", x, y)
                    self.assertEqual(value(fw, "page"), x // 60)
                    self.assertEqual(bytes(fw.outgoing), b"")

    def test_mini_history_shrink_grow_offline_matches_full_render(self):
        fw = Firmware()
        fw.write("page", struct.pack("<I", 2))
        fw.write("online", b"\1")
        fw.write("history_count", struct.pack("<I", 60))
        fw.call("screen")
        for samples in ([180] * 240, [1] * 240, [65535] * 240, [i % 100 for i in range(240)]):
            fw.write("history", struct.pack("<240H", *samples))
            fw.rectangles.clear()
            fw.call("update_metrics")
            self.assertTrue(all(w == 2 for x, y, w, h in fw.rectangles))
            before = fw.image.tobytes()
            fw.call("screen")
            self.assertEqual(before, fw.image.tobytes())
        fw.write("online", b"\0")
        fw.call("update_metrics")
        before = fw.image.tobytes()
        fw.call("screen")
        self.assertEqual(before, fw.image.tobytes())

    def test_game_report_navigation_and_dock_survive_data_updates(self):
        fw = Firmware()
        fw.write("online", b"\1")
        feed(fw, "G,0,50,0,0,0,1,10")
        for row in range(6):
            feed(fw, f"N,{row},1," + "W" * 22)
        for detail in range(8):
            feed(fw, f"W,1,3,{detail},0")
            fw.call("screen")
            dock = fw.image.crop((0, 280, 240, 320)).tobytes()
            feed(fw, "G,0,22,1,1,1,33,18")
            fw.call("update_metrics")
            self.assertEqual(dock, fw.image.crop((0, 280, 240, 320)).tobytes())
            fw.texts.clear()
            fw.rectangles.clear()
            fw.call("update_metrics")
            self.assertEqual(fw.texts, [])
            self.assertEqual(fw.rectangles, [])
        feed(fw, "W,1,3,4,0")
        fw.call("handle_tap", 190, 257)
        self.assertEqual(value(fw, "game_detail"), 5)
        fw.call("handle_tap", 90, 257)
        self.assertEqual(value(fw, "game_detail"), 4)
        fw.call("handle_tap", 30, 257)
        self.assertEqual(value(fw, "game_detail"), 2)


if __name__ == "__main__":
    unittest.main()
