import copy
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from test_firmware import Firmware
from protocol import Decoder
from sync import Sync
from icons import themed_pixels, get_icon, cached_file_icon
from app_picker import AppPicker


class V6Tests(unittest.TestCase):
    def request(self, fw, body):
        fw.outgoing.clear()
        fw.uc.mem_write(0x10009000, body.encode() + b"\0")
        fw.call("deck_receive", 0x10009000)
        return Decoder().feed(bytes(fw.outgoing))[0]

    def transfer(self, fw, sync):
        n = 0
        while not sync.done:
            packet = sync.next_packet(n + 1)
            # Feed through the actual ARM frame parser too (including >96-byte packets).
            fw.incoming.extend(packet)
            while not fw.call("protocol_poll", 0x10009000):
                pass
            body = fw.cstr(0x10009000)
            ack = self.request(fw, body)
            if n == 3:
                self.assertEqual(self.request(fw, body), ack)
            self.assertTrue(sync.acknowledge(ack))
            self.assertFalse(sync.failed)
            n += 1
            self.assertLess(n, 1700)
        return n

    def layout(self, revision=10):
        return dict(
            revision=revision,
            items=[dict(name=f"App {i}", type="open", path="app.exe") for i in range(24)],
            pixels=["1234" * 1024] * 24,
            themed_pixels=["0001" + "1234" * 1023] * 24,
        )

    def test_full_delta_empty_and_unchanged_transfers(self):
        fw = Firmware()
        old = self.layout()
        self.assertEqual(len(Sync(old, version=5).jobs), 1586)
        self.assertEqual(self.transfer(fw, Sync(old, version=6)), 578)
        untouched = bytes(fw.uc.mem_read(fw.slot_address(7), 2060))
        new = copy.deepcopy(old)
        new["revision"] = 11
        new["items"][6]["name"] = "Changed"
        self.assertEqual(self.transfer(fw, Sync(new, old, 6)), 26)
        self.assertEqual(bytes(fw.uc.mem_read(fw.slot_address(7), 2060)), untouched)
        self.assertEqual(bytes(fw.uc.mem_read(fw.slot_address(6), 2)), b"\1\0")
        empty = copy.deepcopy(new)
        empty["revision"] = 12
        empty["items"][6] = dict(name="Empty", type="empty")
        self.assertEqual(self.transfer(fw, Sync(empty, new, 6)), 4)
        self.assertEqual(bytes(fw.uc.mem_read(fw.slot_address(6) + 2059, 1)), b"\0")
        self.assertEqual(self.transfer(fw, Sync(empty, empty, 6)), 2)
        self.assertEqual(struct.unpack("<I", fw.uc.mem_read(fw.symbols["deck_revision"], 4))[0], 12)

    def test_delta_requires_matching_committed_base_and_rejects_oversize(self):
        fw = Firmware()
        self.assertEqual(self.request(fw, "X,1,b,20,10"), "Y,1,0")
        self.transfer(fw, Sync(self.layout(), version=6))
        for body, result in [
            ("X,2,b,20,9", 0),
            ("X,3,b,20,10", 1),
            ("X,4,L,6,1,EDIT", 1),
            ("X,5,I,6,0," + "0000" * 49, 0),
            ("X,6,I,6,0," + "0000" * 47 + "ZZZZ", 0),
            ("X,7,I,6,0," + "FFFF" * 48, 1),
            ("X,8,Z,20", 0),
        ]:
            self.assertEqual(self.request(fw, body), f'Y,{body.split(",")[1]},{result}')
        self.transfer(
            fw, Sync(self.layout(30), version=6)
        )  # interrupted delta recovers via full transfer

    def test_transparency_keeps_real_black_and_avoids_reserved_collision(self):
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 255))
        image.putpixel((0, 0), (100, 90, 80, 0))
        image.putpixel((1, 0), (0, 0, 8, 255))
        self.assertEqual(themed_pixels(image)[:6], b"\0\1\0\0\0\0")
        self.assertEqual(themed_pixels(image, True)[:6], b"\0\1\0\2\0\2")

    def test_tile_background_changes_with_theme_without_new_transfer(self):
        fw = Firmware()
        fw.call("deck_init")
        fw.write("page", struct.pack("<I", 1))
        for i in range(24):
            fw.uc.mem_write(
                fw.slot_address(i), b"\1\0" * 1023 + b"\2\0" + b"APP\0" + b"\0" * 7 + b"\1"
            )
        backgrounds = []
        for theme in (0, 1):
            fw.write("preferences", struct.pack("<I", theme))
            fw.call("screen")
            bg = struct.unpack("<H", fw.uc.mem_read(fw.symbols["lcd_icon_background"], 2))[0]
            backgrounds.append(bg)
            fg = struct.unpack("<H", fw.uc.mem_read(fw.symbols["lcd_icon_foreground"], 2))[0]
            for x, y, w, h in fw.rectangles:
                if w == 48 and h == 48:
                    self.assertEqual(fw.image.getpixel((x + 24, y + 24)), fw.color(bg))
                    self.assertEqual(fw.image.getpixel((x + 47, y + 47)), fw.color(fg))
            fw.rectangles.clear()
        self.assertNotEqual(*backgrounds)

    def test_steam_shortcut_uses_iconfile_and_web_links_arent_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            icon = folder / "game.ico"
            Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(icon)
            link = folder / "Game.url"
            link.write_text(
                "[InternetShortcut]\nURL=steam://rungameid/42\nIconFile=" + str(icon),
                encoding="utf-8",
            )
            web = folder / "Web.url"
            web.write_text("[InternetShortcut]\nURL=https://example.com", encoding="utf-8")
            self.assertEqual(AppPicker.source(str(link)), "Steam")
            self.assertEqual(AppPicker.source(str(web)), "Uygulama")
            with patch("icons.shell_icon", side_effect=AssertionError("Must use Steam icon")):
                self.assertEqual(
                    get_icon(dict(type="open", path=str(link))).getpixel((16, 16)), (255, 0, 0, 255)
                )
            cached_file_icon.cache_clear()
            AppPicker.source.cache_clear()


if __name__ == "__main__":
    unittest.main()
