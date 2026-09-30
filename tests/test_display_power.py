import struct
import unittest
import zlib
from test_firmware import Firmware
from test_game import feed
from test_settings import record


class DisplayPowerTests(unittest.TestCase):
    def set_value(self, fw, index, value):
        fw.uc.mem_write(fw.symbols["preferences"] + index * 4, struct.pack("<I", value))

    def reg(self, fw, address):
        return struct.unpack("<I", fw.uc.mem_read(address, 4))[0]

    def tick(self, fw, time):
        fw.write("ticks", struct.pack("<I", time & 0xFFFFFFFF))
        fw.call("display_tick")

    def clock(self, fw, h, m):
        fw.uc.mem_write(0x40024044, struct.pack("<I", 0x4D44434B))
        fw.uc.mem_write(0x40024008, struct.pack("<I", 1))
        fw.uc.mem_write(0x40024014, struct.pack("<I", (h << 16) | (m << 8)))

    def test_pwm_2khz_and_exact_gpio_endpoints_preserve_other_pins(self):
        fw = Firmware()
        fw.write("cpu_hz", struct.pack("<I", 48000000))
        fw.uc.mem_write(0x4002C00C, struct.pack("<I", 0xAAA00000))
        fw.call("backlight_set", 50)
        self.assertEqual(self.reg(fw, 0x40018018), 24000)
        self.assertEqual(self.reg(fw, 0x40018048), 12000)
        self.assertEqual(self.reg(fw, 0x4001804C), 1 << 14)
        self.assertEqual(self.reg(fw, 0x4002C00C) & ~(3 << 20), 0xAAA00000 & ~(3 << 20))
        fw.call("backlight_set", 0)
        self.assertEqual(self.reg(fw, 0x2009C03C), 1 << 26)
        self.assertEqual(self.reg(fw, 0x4002C00C) & (3 << 20), 0)
        fw.call("backlight_set", 100)
        self.assertEqual(self.reg(fw, 0x2009C038), 1 << 26)

    def test_two_minutes_dim_then_ten_seconds_off_and_wake_consumed(self):
        fw = Firmware()
        fw.call("display_init")
        self.tick(fw, 119999)
        self.assertEqual(fw.call("display_sleeping"), 0)
        self.tick(fw, 120000)
        self.assertEqual(fw.call("display_sleeping"), 1)
        self.assertEqual(self.reg(fw, 0x40018048), self.reg(fw, 0x40018018) // 2)
        self.tick(fw, 130000)
        self.assertEqual(self.reg(fw, 0x2009C03C), 1 << 26)
        fw.call("handle_tap", 220, 18)
        self.assertEqual(bytes(fw.uc.mem_read(fw.symbols["settings_open"], 1)), b"\0")
        self.assertEqual(fw.call("display_sleeping"), 0)
        self.assertEqual(bytes(fw.outgoing), b"")
        fw.call("handle_tap", 220, 18)
        self.assertEqual(bytes(fw.uc.mem_read(fw.symbols["settings_open"], 1)), b"\1")

    def test_idle_disabled_hold_activity_wrap_and_dim_clamped(self):
        fw = Firmware()
        self.set_value(fw, 6, 30)
        self.set_value(fw, 8, 80)
        fw.write("ticks", struct.pack("<I", 0xFFFFFFF0))
        fw.call("display_init")
        self.tick(fw, 0xFFFFFFF0 + 120000)
        self.assertEqual(self.reg(fw, 0x40018048), self.reg(fw, 0x40018018) * 30 // 100)
        fw.call("display_activity")
        self.tick(fw, 0xFFFFFFF0 + 130000)
        self.assertEqual(fw.call("display_sleeping"), 0)
        self.set_value(fw, 7, 0)
        self.tick(fw, 900000)
        self.assertEqual(fw.call("display_sleeping"), 0)

    def test_telemetry_does_not_wake_or_auto_navigate_but_remote_command_does(self):
        fw = Firmware()
        fw.call("display_init")
        self.tick(fw, 130000)
        fw.write("page", struct.pack("<I", 1))
        feed(fw, "M,10,20,0,0,0,19,30")
        feed(fw, "G,1,50,0,0,0,0,7")
        self.assertEqual(fw.call("display_sleeping"), 1)
        self.assertEqual(self.reg(fw, fw.symbols["page"]), 1)
        feed(fw, "W,1,2,4,0")
        self.assertEqual(fw.call("display_sleeping"), 0)

    def test_schedule_boundaries_overnight_daytime_equal_and_unknown_clock(self):
        fw = Firmware()
        self.set_value(fw, 10, 1)
        self.set_value(fw, 0, 1)
        self.assertEqual(fw.call("display_theme_refresh"), 0)
        for h, m, theme in [(18, 59, 1), (19, 0, 0), (23, 59, 0), (0, 0, 0), (5, 59, 0), (6, 0, 1)]:
            self.clock(fw, h, m)
            fw.call("display_theme_refresh")
            self.assertEqual(self.reg(fw, fw.symbols["preferences"]), theme)
        self.set_value(fw, 11, 360)
        self.set_value(fw, 12, 1140)
        for h, theme in [(5, 1), (6, 0), (18, 0), (19, 1)]:
            self.clock(fw, h, 0)
            fw.call("display_theme_refresh")
            self.assertEqual(self.reg(fw, fw.symbols["preferences"]), theme)
        self.set_value(fw, 11, 1140)
        fw.call("display_theme_refresh")
        self.assertEqual(self.reg(fw, fw.symbols["preferences"]), 0)

    def test_clock_sync_and_startup_schedule_and_manual_choice(self):
        fw = Firmware()
        fw.call("display_clock_sync", 19, 25)
        self.assertEqual(self.reg(fw, 0x40024028), 19)
        self.assertEqual(self.reg(fw, 0x40024024), 25)
        self.clock(fw, 19, 25)
        fw.uc.mem_write(0x40024020, struct.pack("<I", 42))
        fw.call("display_clock_sync", 19, 25)
        self.assertEqual(self.reg(fw, 0x40024020), 42)
        self.set_value(fw, 10, 1)
        self.set_value(fw, 0, 1)
        fw.call("display_init")
        self.assertEqual(self.reg(fw, fw.symbols["preferences"]), 0)
        fw.call("handle_tap", 220, 18)
        fw.call("handle_tap", 30, 60)
        self.assertEqual(self.reg(fw, fw.symbols["preferences"]), 1)
        self.assertEqual(self.reg(fw, fw.symbols["preferences"] + 40), 0)
        self.assertEqual(fw.call("display_theme_refresh"), 0)

    def test_legacy_migration_v2_validation_and_corrupt_record_fallback(self):
        fw = Firmware()
        fw.uc.mem_write(0x70000, b"\xff" * 32768)
        fw.uc.mem_write(0x70000, record((1, 1, 2, 0, 0)))
        fw.call("preferences_load")
        values = struct.unpack("<13I", fw.uc.mem_read(fw.symbols["preferences"], 52))
        self.assertEqual(values[6:], (100, 120, 50, 10, 0, 1140, 360))
        values = (0, 1, 2, 0, 0, 1, 70, 300, 20, 30, 1, 1200, 420)
        body = struct.pack("<15I", 0x32554950, 2, *values)
        v2 = body + struct.pack("<I", zlib.crc32(body)) + b"\xff" * 192
        fw.uc.mem_write(0x70100, v2)
        bad = bytearray(v2)
        bad[32] ^= 1
        fw.uc.mem_write(0x70200, bytes(bad))
        fw.call("preferences_load")
        self.assertEqual(
            struct.unpack("<13I", fw.uc.mem_read(fw.symbols["preferences"], 52)), values
        )

    def test_settings_pages_fit_and_cancel_restores_all_fields(self):
        fw = Firmware()
        before = bytes(fw.uc.mem_read(fw.symbols["preferences"], 52))
        fw.call("handle_tap", 220, 18)
        for theme in (0, 1):
            self.set_value(fw, 0, theme)
            for page in range(3):
                fw.write("settings_page", struct.pack("<I", page))
                fw.call("screen")
                for x, y, t, s in fw.texts:
                    self.assertTrue(x + len(t) * 6 * s <= 240 and y + 8 * s <= 320, t)
                fw.texts.clear()
        fw.write("settings_page", struct.pack("<I", 1))
        fw.call("handle_tap", 200, 60)
        fw.call("handle_tap", 40, 298)
        self.assertEqual(bytes(fw.uc.mem_read(fw.symbols["preferences"], 52)), before)


if __name__ == "__main__":
    unittest.main()
