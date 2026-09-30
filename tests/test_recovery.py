import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_firmware import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import upgrade_deck


class RecoveryTests(unittest.TestCase):
    def make_package(self, root, corrupt=False):
        data = (ROOT / "companion/firmware/mini-deck.bin").read_bytes()
        info = json.loads((ROOT / "companion/firmware/mini-deck.json").read_text())
        image = root / "recovery.bin"
        image.write_bytes(data if not corrupt else data[:-1] + bytes([data[-1] ^ 1]))
        image.with_suffix(".json").write_text(json.dumps(info))
        return image, info

    def test_bad_package_fails_before_opening_port(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, _ = self.make_package(root, True)
            with (
                patch.object(upgrade_deck, "ROOT", root),
                patch.object(sys, "argv", ["upgrade", "--image", str(image), "--port", "FAKE"]),
                patch.object(upgrade_deck, "ISP") as isp,
            ):
                with self.assertRaises(RuntimeError):
                    upgrade_deck.main()
                isp.assert_not_called()

    def test_erased_firmware_recovery_and_runtime_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, info = self.make_package(root)

            class Port:
                def __init__(self):
                    self.timeout = 0
                    self.closed = False

                def read(self, count):
                    return f'FLASH_CRC32={info["crc32"]} LEN={info["image_bytes"]}\r\n@R,3*1234\n'.encode()

                def close(self):
                    self.closed = True

            class FakeISP:
                def __init__(self):
                    self.s = Port()
                    self.flashed = None
                    self.reset_done = False

                def sync(self):
                    pass

                def identify(self):
                    pass

                def read(self, address, size):
                    return b"\xff" * size

                def flash(self, path):
                    self.flashed = path

                def reset(self):
                    self.reset_done = True

            isp = FakeISP()
            with (
                patch.object(upgrade_deck, "ROOT", root),
                patch.object(sys, "argv", ["upgrade", "--image", str(image), "--port", "FAKE"]),
                patch.object(upgrade_deck, "ISP", return_value=isp),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                upgrade_deck.main()
            self.assertEqual(isp.flashed, image)
            self.assertTrue(isp.reset_done and isp.s.closed)
            report = json.loads((root / "build/runtime-verification.json").read_text())
            self.assertTrue(report["full_image_matches"])
            self.assertEqual(report["sha256"], info["sha256"])


if __name__ == "__main__":
    unittest.main()
