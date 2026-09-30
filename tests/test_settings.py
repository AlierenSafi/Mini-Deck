import struct
import unittest
import zlib
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_PC, UC_ARM_REG_LR
from test_firmware import Firmware
from test_game import feed


def prefs(fw):
    return struct.unpack("<5I", fw.uc.mem_read(fw.symbols["preferences"], 20))


def record(values):
    body = struct.pack("<8I", 0x32554950, 1, *values, 0xFFFFFFFF)
    return body + struct.pack("<I", zlib.crc32(body)) + b"\xff" * 220


class SettingsTests(unittest.TestCase):
    def test_logo_flag_migrates_old_records_and_can_be_cancelled(self):
        fw = Firmware()
        fw.uc.mem_write(0x70000, b"\xff" * 32768)
        fw.uc.mem_write(0x70000, record((1, 1, 2, 0, 0)))
        fw.call("preferences_load")
        self.assertEqual(struct.unpack("<6I", fw.uc.mem_read(fw.symbols["preferences"], 24))[-1], 1)
        body = struct.pack("<8I", 0x32554950, 1, 1, 1, 2, 0, 0, 0)
        fw.uc.mem_write(0x70100, body + struct.pack("<I", zlib.crc32(body)) + b"\xff" * 220)
        fw.call("preferences_load")
        self.assertEqual(struct.unpack("<6I", fw.uc.mem_read(fw.symbols["preferences"], 24))[-1], 0)
        fw.call("handle_tap", 220, 18)
        fw.call("handle_tap", 50, 230)
        self.assertEqual(struct.unpack("<6I", fw.uc.mem_read(fw.symbols["preferences"], 24))[-1], 1)
        fw.call("handle_tap", 40, 298)
        self.assertEqual(struct.unpack("<6I", fw.uc.mem_read(fw.symbols["preferences"], 24))[-1], 0)

    def test_logo_matches_packed_artwork_in_both_palettes(self):
        fw = Firmware()
        mask = bytes(fw.uc.mem_read(fw.symbols["logo_mask"], 5950))
        for theme in (0, 1):
            fw.write("preferences", struct.pack("<I", theme))
            fw.call("boot_logo")
            colors = struct.unpack("<7H", fw.uc.mem_read(fw.symbols["palettes"] + theme * 14, 14))
            for y in range(170):
                fg = colors[3 if y >= 150 else 4]
                bg = colors[0]
                for x in range(140):
                    a = (mask[y * 35 + x // 4] >> (6 - 2 * (x % 4))) & 3
                    mixed = (
                        ((((fg >> 11) * a + (bg >> 11) * (3 - a)) // 3) << 11)
                        | (((((fg >> 5) & 63) * a + ((bg >> 5) & 63) * (3 - a)) // 3) << 5)
                        | (((fg & 31) * a + (bg & 31) * (3 - a)) // 3)
                    )
                    self.assertEqual(fw.image.getpixel((50 + x, 80 + y)), fw.color(mixed))
            self.assertTrue(
                all(
                    0 <= x and 0 <= y and x + w <= 240 and y + h <= 320
                    for x, y, w, h in fw.rectangles
                )
            )

    def test_modal_theme_cancel_and_telemetry_isolation(self):
        fw = Firmware()
        fw.write("online", b"\1")
        fw.call("handle_tap", 220, 18)
        fw.call("handle_tap", 40, 60)
        self.assertEqual(prefs(fw)[0], 1)
        fw.call("screen")
        before = fw.image.tobytes()
        fw.rectangles.clear()
        fw.texts.clear()
        feed(fw, "M,40,60,0,0,0,12,30")
        fw.call("update_metrics")
        self.assertEqual(before, fw.image.tobytes())
        self.assertEqual(fw.rectangles, [])
        fw.call("handle_tap", 40, 297)
        self.assertEqual(prefs(fw)[0], 0)
        self.assertEqual(bytes(fw.outgoing), b"")

    def test_all_settings_and_pages_fit_in_both_themes_and_text_sizes(self):
        fw = Firmware()
        fw.write("online", b"\1")
        fw.call("deck_init")
        for i in range(24):
            fw.uc.mem_write(fw.slot_address(i) + 2048, b"WWWWWWWWWW\0\1")
        for theme in (0, 1):
            for large in (0, 1):
                fw.write("preferences", struct.pack("<5I", theme, large, 1, 1, 1))
                for page, details in ((0, [0]), (1, [0]), (2, range(5)), (3, range(8))):
                    for detail in details:
                        feed(fw, f"W,1,{page},{detail},0")
                        fw.call("screen")
                fw.call("handle_tap", 220, 18)
                fw.call("screen")
                for x, y, t, scale in fw.texts:
                    self.assertTrue(x + len(t) * 6 * scale <= 240 and y + 8 * scale <= 320, t)
                for x, y, w, h in fw.rectangles:
                    self.assertTrue(0 <= x and 0 <= y and x + w <= 240 and y + h <= 320)
                fw.call("handle_tap", 30, 298)
                fw.texts.clear()
                fw.rectangles.clear()

    def test_corrupt_latest_record_falls_back_and_auto_game_can_be_disabled(self):
        fw = Firmware()
        fw.uc.mem_write(0x70000, b"\xff" * 32768)
        fw.uc.mem_write(0x70000, record((1, 1, 2, 0, 0)))
        fw.uc.mem_write(0x70100, record((3, 1, 2, 0, 0)))
        fw.call("preferences_load")
        self.assertEqual(prefs(fw), (1, 1, 2, 0, 0))
        feed(fw, "G,1,50,0,0,0,0,7")
        self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["page"], 4))[0], 1)

    def test_save_readback_no_duplicate_writes_and_sector_isolation(self):
        fw = Firmware()
        fw.uc.mem_write(0x70000, b"\xff" * 32768)
        fw.uc.mem_write(0x78000, b"Z" * 32768)
        fw.uc.mem_map(0x1FFF0000, 65536)
        calls = []

        def skip(uc, address, size, data):
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

        fw.uc.hook_add(
            UC_HOOK_CODE,
            skip,
            begin=fw.symbols["watchdog_feed"] & ~1,
            end=fw.symbols["watchdog_feed"] & ~1,
        )

        def iap(uc, address, size, data):
            v = struct.unpack("<5I", uc.mem_read(uc.reg_read(UC_ARM_REG_R0), 20))
            calls.append(v)
            if v[0] in (50, 52):
                self.assertEqual(v[1:3], (28, 28))
            if v[0] == 52:
                uc.mem_write(0x70000, b"\xff" * 32768)
            if v[0] == 51:
                self.assertTrue(0x70000 <= v[1] < 0x78000)
                uc.mem_write(v[1], bytes(uc.mem_read(v[2], v[3])))
            uc.mem_write(uc.reg_read(UC_ARM_REG_R1), b"\0" * 20)
            skip(uc, address, size, data)

        fw.uc.hook_add(UC_HOOK_CODE, iap, begin=0x1FFF1FF0, end=0x1FFF1FF0)
        self.assertEqual(fw.call("preferences_save"), 1)
        n = len(calls)
        self.assertEqual(fw.call("preferences_save"), 1)
        self.assertEqual(n, len(calls))
        fw.uc.mem_write(0x70000, b"\0" * 32768)
        self.assertEqual(fw.call("preferences_save"), 1)
        self.assertEqual(bytes(fw.uc.mem_read(0x78000, 32768)), b"Z" * 32768)


if __name__ == "__main__":
    unittest.main()
