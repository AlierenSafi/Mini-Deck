"""A fresh clone must start without personal profiles or machine-specific paths."""

from pathlib import Path
import tempfile
import unittest
from test_firmware import ROOT
from actions import Actions


class FirstRunTests(unittest.TestCase):
    def test_creates_portable_defaults_and_preserves_saved_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "actions.json"
            profile = Actions(path, dry_run=True)
            self.assertEqual(len(profile.items), 24)
            self.assertTrue(all(p["type"] == "empty" for p in profile.items[6:]))
            self.assertFalse(any("path" in p or "icon" in p for p in profile.items))
            items = profile.items
            items[6] = dict(name="Custom", label="CUSTOM", type="keys", keys=["CTRL", "A"])
            profile.replace(items)
            self.assertEqual(Actions(path, dry_run=True).items[6]["name"], "Custom")


if __name__ == "__main__":
    unittest.main()
