import struct
import unittest
from test_firmware import Firmware
from performance import FrameRates


class MonitorTests(unittest.TestCase):
    def test_unchanged_metrics_do_not_redraw_any_pixels(self):
        for detail in (4, 0, 1, 2, 3):
            fw = Firmware()
            fw.write("page", struct.pack("<I", 2))
            fw.write("online", b"\1")
            fw.write("monitor_detail", struct.pack("<I", detail))
            fw.call("screen")
            fw.rectangles.clear()
            fw.texts.clear()
            fw.call("update_metrics")
            self.assertEqual(fw.rectangles, [])
            self.assertEqual(fw.texts, [])

    def test_changed_card_only_updates_changed_digits_and_matches_full_render(self):
        fw = Firmware()
        fw.write("page", struct.pack("<I", 2))
        fw.write("online", b"\1")
        fw.write("monitor_values", struct.pack("<4i", 100, 100, 100, 144))
        fw.call("screen")
        for value in (5, -1, 90):
            fw.rectangles.clear()
            fw.texts.clear()
            fw.write("monitor_values", struct.pack("<4i", value, 100, 100, 144))
            fw.call("update_metrics")
            self.assertEqual(fw.rectangles, [])  # No erase-then-redraw of card backgrounds.
            self.assertLessEqual(len(fw.texts), 3)
            incremental = fw.image.tobytes()
            fw.call("screen")
            self.assertEqual(incremental, fw.image.tobytes())

    def test_graph_delta_matches_full_render_after_shrink_grow_and_missing_samples(self):
        fw = Firmware()
        fw.write("page", struct.pack("<I", 2))
        fw.write("online", b"\1")
        fw.write("monitor_detail", struct.pack("<I", 3))
        fw.write("history_count", struct.pack("<I", 60))
        fw.call("screen")
        for history in ([180] * 60, [20] * 60, [65535] * 60, [100 + i for i in range(60)]):
            fw.write("history", struct.pack("<240H", *([0] * 180 + history)))
            fw.rectangles.clear()
            fw.call("update_metrics")
            self.assertTrue(all(w <= 2 for _, _, w, _ in fw.rectangles))
            incremental = fw.image.tobytes()
            fw.call("screen")
            self.assertEqual(incremental, fw.image.tobytes())

    def test_fps_uses_dominant_swapchain_and_expires_stale_frames(self):
        rates = FrameRates()
        for i in range(60):
            rates.add(
                {
                    "ProcessID": "42",
                    "TimeInSeconds": str(i / 60),
                    "msBetweenPresents": str(1000 / 60),
                    "SwapChainAddress": "main",
                },
                now=1,
            )
        rates.add(
            {
                "ProcessID": "42",
                "TimeInSeconds": "1",
                "msBetweenPresents": "100",
                "SwapChainAddress": "menu",
            },
            now=1,
        )
        self.assertEqual(rates.sample(42, now=1.1), 60)
        self.assertEqual(rates.sample([42, 99], now=1.1), 60)
        self.assertIsNone(rates.sample(99, now=1.1))
        self.assertIsNone(rates.sample(42, now=3.1))

    def test_invalid_frames_are_ignored_and_capture_memory_is_bounded(self):
        rates = FrameRates()
        for value in ("nan", "inf", "-1", "0", "oops", "10001"):
            rates.add(
                {
                    "ProcessID": "42",
                    "TimeInSeconds": "1",
                    "msBetweenPresents": value,
                    "SwapChainAddress": "main",
                },
                now=1,
            )
        self.assertIsNone(rates.sample(42, now=1))
        for i in range(200):
            rates.add(
                {
                    "ProcessID": str(i),
                    "TimeInSeconds": "1",
                    "msBetweenPresents": "16",
                    "SwapChainAddress": "main",
                },
                now=1,
            )
        self.assertEqual(len(rates.chains), 128)

    def test_touch_selects_each_graph_and_back_without_emitting_action(self):
        fw = Firmware()
        fw.write("page", struct.pack("<I", 2))
        for i, y in ((0, 90), (2, 160), (1, 220)):
            fw.write("monitor_detail", struct.pack("<I", 4))
            fw.call("handle_tap", 50, y)
            self.assertEqual(
                struct.unpack("<I", fw.uc.mem_read(fw.symbols["monitor_detail"], 4))[0], i
            )
            fw.call("handle_tap", 40, 258)
            self.assertEqual(
                struct.unpack("<I", fw.uc.mem_read(fw.symbols["monitor_detail"], 4))[0], 4
            )
        self.assertEqual(bytes(fw.outgoing), b"")

    def test_history_ring_missing_values_pid_change_and_timeout(self):
        fw = Firmware()
        fw.write("metrics", struct.pack("<7I", 25, 70, 0, 0, 0, 12, 30))
        self.assertEqual(fw.call("monitor_telemetry", 45, 144, 42), 1)
        fw.call("monitor_sample")
        self.assertEqual(
            struct.unpack("<4i", fw.uc.mem_read(fw.symbols["monitor_values"], 16)),
            (25, 70, 45, 144),
        )
        self.assertEqual(fw.call("monitor_telemetry", 102, 144, 42), 0)
        fw.call("monitor_telemetry", 45, 90, 43)
        self.assertEqual(bytes(fw.uc.mem_read(fw.symbols["history"] + 360, 120)), b"\xff" * 120)
        fw.write("ticks", struct.pack("<I", 2501))
        fw.call("monitor_sample")
        self.assertEqual(
            struct.unpack("<4i", fw.uc.mem_read(fw.symbols["monitor_values"], 16))[2:], (-1, -1)
        )
        for i in range(70):
            fw.write("ticks", struct.pack("<I", 3000 + i * 500))
            fw.call("monitor_sample")
        self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["history_count"], 4))[0], 60)
        self.assertEqual(bytes(fw.uc.mem_read(fw.symbols["history"] + 240, 240)), b"\xff" * 240)

    def test_all_graphs_extreme_values_and_missing_data_fit_screen(self):
        fw = Firmware()
        fw.write("page", struct.pack("<I", 2))
        fw.write("online", b"\1")
        fw.write("history_count", struct.pack("<I", 60))
        fw.write("history", struct.pack("<240H", *([100] * 180 + [9999] * 60)))
        fw.write("monitor_values", struct.pack("<4i", 100, 100, 100, 9999))
        for detail in (4, 0, 1, 2, 3):
            fw.write("monitor_detail", struct.pack("<I", detail))
            fw.call("screen")
        fw.write("monitor_values", struct.pack("<4i", -1, -1, -1, -1))
        fw.call("screen")
        for x, y, w, h in fw.rectangles:
            self.assertTrue(0 <= x and 0 <= y and x + w <= 240 and y + h <= 320, (x, y, w, h))
        for x, y, text, scale in fw.texts:
            self.assertTrue(x + len(text) * 6 * scale <= 240 and y + 8 * scale <= 320, text)


if __name__ == "__main__":
    unittest.main()
