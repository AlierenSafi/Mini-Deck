import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pubg_reports import extract, aggregate, archive, report_lines
from firmware_package import validate
from test_firmware import Firmware, ROOT
from test_game import feed


class ReportsTests(unittest.TestCase):
    def test_team_uses_roster_and_excludes_opponents(self):
        people = [
            {
                "type": "participant",
                "id": str(i),
                "attributes": {
                    "stats": {
                        "playerId": "p" + str(i),
                        "name": "user" + str(i),
                        "kills": i,
                        "assists": i + 1,
                        "damageDealt": 100 * i,
                    }
                },
            }
            for i in range(6)
        ]
        roster = {
            "type": "roster",
            "relationships": {"participants": {"data": [{"id": str(i)} for i in (1, 2, 3, 4)]}},
        }
        result = extract(
            {
                "data": {"attributes": {"createdAt": "2026-09-26T10:00:00Z"}},
                "included": people + [roster],
            },
            "p2",
            "match",
        )
        self.assertEqual([p["name"] for p in result["team"]], ["user2", "user1", "user3", "user4"])
        self.assertEqual(result["assists"], 3)

    def test_local_day_archive_dedup_and_player_isolation(self):
        rows = [
            dict(
                id=str(i),
                created=f"2026-09-25T{hour}:30:00Z",
                kills=2,
                assists=1,
                damage=200,
                rank=1,
            )
            for i, hour in enumerate((20, 22))
        ]
        now = datetime(2026, 9, 26, 1, tzinfo=timezone(timedelta(hours=3)))
        result = aggregate(rows, now)
        self.assertEqual(result["daily"]["matches"], 1)
        self.assertEqual(result["daily"]["kills"], 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            archive("a", rows, path)
            self.assertEqual(len(archive("a", rows, path)), 2)
            self.assertEqual(archive("b", [], path), [])

    def test_stale_data_not_shown_as_current(self):
        self.assertTrue(
            all(p[0] == "VERI BEKLENIYOR" for p in report_lines({"status": 2, "summary": None}))
        )

    def test_stale_firmware_rejected(self):
        validate()
        with patch("firmware_package.source_digest", return_value="changed"):
            with self.assertRaises(RuntimeError):
                validate()

    def test_report_pages_bounds_no_flicker_and_navigation(self):
        fw = Firmware()
        fw.write("online", b"\1")
        feed(fw, "G,0,50,0,0,0,1,10")
        for page in range(4):
            for row in range(6):
                feed(fw, f"P,{page},{row}," + ("W" * 18))
        for i in range(10):
            feed(fw, f"B,{i},{i*99}")
        for detail in range(4, 8):
            feed(fw, f"W,1,3,{detail},0")
            fw.call("screen")
            for x, y, text, scale in fw.texts:
                self.assertLessEqual(x + len(text) * 6 * scale, 240)
            for x, y, w, h in fw.rectangles:
                self.assertTrue(0 <= x and 0 <= y and x + w <= 240 and y + h <= 320)
            fw.texts.clear()
            fw.rectangles.clear()
            fw.call("update_metrics")
            self.assertEqual(fw.texts, [])
            self.assertEqual(fw.rectangles, [])
        # A graph value can rise and fall without leaving old pixels.
        for value in (1, 999, 1000):
            feed(fw, f"B,3,{value}")
            fw.call("update_metrics")
            before = fw.image.tobytes()
            fw.call("screen")
            self.assertEqual(before, fw.image.tobytes())
        for bad in ("P,4,0," + "X" * 18, "P,0,6," + "X" * 18, "P,0,0,short", "B,10,5", "B,0,1001"):
            feed(fw, bad)


if __name__ == "__main__":
    unittest.main()
