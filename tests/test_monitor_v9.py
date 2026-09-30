import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from test_firmware import Firmware
from test_game import feed
from monitor_wire import frames, number, label
from weather_service import Weather, fetch, load, save, search


class MonitorV9Tests(unittest.TestCase):
    def test_all_banks_themes_partial_redraw_stale_and_bounds(self):
        for theme in (0, 1):
            for bank in range(3):
                fw = Firmware()
                fw.write("preferences", struct.pack("<I", theme))
                fw.write("online", b"\1")
                fw.write("page", struct.pack("<I", 2))
                fw.write("monitor_bank", struct.pack("<I", bank))
                fw.call("screen")
                for value in (0, 100, 999999):
                    feed(fw, "S," + ",".join([str(value)] * 6))
                    feed(fw, f"L,{value},{value}")
                    feed(fw, "I,0," + "W" * 26)
                    feed(fw, "I,1," + "W" * 26)
                    fw.write(
                        "metrics",
                        struct.pack(
                            "<7I",
                            100,
                            100,
                            100,
                            999999 if value else 0,
                            999999 if value else 0,
                            23,
                            59,
                        ),
                    )
                    fw.write("monitor_values", struct.pack("<5i", 100, 100, 100, 9999, 9999))
                    feed(fw, "O,0,65,0")
                    fw.call("update_metrics")
                    partial = fw.image.tobytes()
                    fw.call("screen")
                    self.assertEqual(partial, fw.image.tobytes())
                    for x, y, w, h in fw.rectangles + fw.bitmap_regions:
                        self.assertTrue(
                            0 <= x and 0 <= y and x + w <= 240 and y + h <= 320, (x, y, w, h)
                        )
                    for x, y, text, scale in fw.texts:
                        self.assertLessEqual(x + len(text) * 6 * scale, 240)
                    fw.rectangles.clear()
                    fw.texts.clear()
                    fw.bitmap_regions.clear()
                    fw.call("update_metrics")
                    self.assertEqual(fw.rectangles, [])
                    self.assertEqual(fw.texts, [])
                    self.assertEqual(fw.bitmap_regions, [])
                fw.write("ticks", struct.pack("<I", 6000))
                fw.call("update_metrics")
                stale = fw.image.tobytes()
                fw.call("screen")
                self.assertEqual(stale, fw.image.tobytes())
                fw.write("online", b"\0")
                fw.call("update_metrics")
                offline = fw.image.tobytes()
                fw.call("screen")
                self.assertEqual(offline, fw.image.tobytes())

    def test_navigation_wrap_and_does_not_launch_action(self):
        fw = Firmware()
        fw.write("page", struct.pack("<I", 2))
        for x, expected in ((210, 1), (210, 2), (210, 0), (20, 2), (80, 0), (120, 1), (160, 2)):
            fw.call("handle_tap", x, 260)
            self.assertEqual(
                struct.unpack("<I", fw.uc.mem_read(fw.symbols["monitor_bank"], 4))[0], expected
            )
        self.assertEqual(bytes(fw.outgoing), b"")

    def test_sensor_validation_keeps_last_valid_packet(self):
        fw = Firmware()
        feed(fw, "S,49,0,539,1740,125,600")
        before = bytes(fw.uc.mem_read(fw.symbols["sensors"], 24))
        for invalid in (
            "S,201,0,539,1740,125,600",
            "S,49,101,539,1740,125,600",
            "S,-1,0,539,1740,125,600",
            "S,1,2",
        ):
            feed(fw, invalid)
            self.assertEqual(bytes(fw.uc.mem_read(fw.symbols["sensors"], 24)), before)
        feed(fw, "I,0," + "A" * 26)
        before = bytes(fw.uc.mem_read(fw.symbols["model_names"], 54))
        feed(fw, "I,0," + "B" * 27)
        self.assertEqual(bytes(fw.uc.mem_read(fw.symbols["model_names"], 54)), before)

    def test_wire_units_and_missing_values(self):
        result = frames(
            {
                "sensors": dict(
                    temp=49,
                    fan=0,
                    power=53941,
                    clock=1740,
                    vram_used=1.25 * 1024**3,
                    vram_total=6 * 1024**3,
                )
            }
        )
        self.assertEqual(result[0], "S,49,0,539,1740,125,600")
        self.assertEqual(result[1], "L,999999,999999")
        self.assertEqual(result[2], "O,255,255,1")
        self.assertNotIn("@", label("Model\n@W,1*"))
        self.assertEqual(len(label("a" * 100)), 26)
        for value in (None, float("nan"), float("inf"), -1):
            self.assertEqual(number(value), 999999)


class WeatherTests(unittest.TestCase):
    def test_config_roundtrip_and_invalid_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weather.json"
            config = dict(name="İzmir", latitude=38.4, longitude=27.1, enabled=True)
            save(config, path)
            self.assertEqual(load(path), config)
            save(dict(config, latitude=999), path)
            self.assertEqual(load(path), {})
            path.write_text("[]")
            self.assertEqual(load(path), {})

    def test_temperature_negative_and_invalid_response(self):
        with patch(
            "weather_service.request",
            return_value={"current": {"temperature_2m": -12.4, "weather_code": 71, "is_day": 0}},
        ):
            self.assertEqual(fetch(dict(latitude=1, longitude=2)), (88, 71, 0))
        for value in (None, float("nan"), 1000):
            with patch(
                "weather_service.request",
                return_value={"current": {"temperature_2m": value, "weather_code": 0, "is_day": 1}},
            ):
                with self.assertRaises((ValueError, TypeError)):
                    fetch(dict(latitude=1, longitude=2))

    def test_unknown_and_expired_weather_not_reported_as_zero(self):
        worker = Weather()
        self.assertEqual(worker.snapshot(), (255, 255, 1))
        worker.value = (122, 0, 1)
        worker.updated = time.monotonic()
        self.assertEqual(worker.snapshot(), (122, 0, 1))
        worker.updated -= 1801
        self.assertEqual(worker.snapshot(), (255, 255, 1))

    def test_ambiguous_search_returns_choices_not_guessed_location(self):
        with patch(
            "weather_service.request",
            return_value={
                "results": [
                    dict(name="Merkez", admin1="A", country="Türkiye", latitude=1, longitude=2),
                    dict(name="Merkez", admin1="B", country="Türkiye", latitude=3, longitude=4),
                ]
            },
        ):
            choices = search("Merkez")
            self.assertEqual(len(choices), 2)
            self.assertNotEqual(choices[0]["name"], choices[1]["name"])


if __name__ == "__main__":
    unittest.main()
