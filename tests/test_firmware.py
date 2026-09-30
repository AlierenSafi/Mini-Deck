"""Run real ARM firmware functions with UART/LCD boundary stubs.
This checks application rendering and protocol code, not hardware timings or LCD bus wiring.
"""

from collections import deque
from pathlib import Path
import struct
import sys
import unittest

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_SP,
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
)
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from protocol import encode, Decoder

REGS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]


class Firmware:
    def __init__(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.mem_map(0, 512 * 1024)
        self.uc.mem_map(0x10000000, 64 * 1024)
        self.uc.mem_map(0x20000000, 4096)
        self.uc.mem_map(0x2007C000, 32 * 1024)
        self.uc.mem_map(
            0x40000000, 1024 * 1024
        )  # PWM/RTC/pin registers; no peripheral timing simulation
        self.uc.mem_map(0x2009C000, 4096)
        with (ROOT / "build/mini-deck.elf").open("rb") as stream:
            elf = ELFFile(stream)
            self.symbols = {
                s.name: s["st_value"]
                for s in elf.get_section_by_name(".symtab").iter_symbols()
                if s.name
            }
            for section in elf.iter_sections():
                if (
                    section["sh_flags"] & 2
                    and section["sh_type"] != "SHT_NOBITS"
                    and section.data_size
                ):
                    self.uc.mem_write(section["sh_addr"], section.data())
        self.incoming, self.outgoing = deque(), bytearray()
        self.image = Image.new("RGB", (240, 320))
        self.draw = ImageDraw.Draw(self.image)
        self.rectangles = []
        self.bitmap_regions = []
        self.texts = []
        self.hooks = {}
        for name, callback in [
            ("uart_get", self.uart_get),
            ("uart_puts", self.uart_puts),
            ("lcd_icon48", self.icon48),
            ("led_set", lambda: None),
            ("lcd_fill", self.fill),
            ("lcd_text", self.text),
            ("lcd_bitmap", self.bitmap),
        ]:
            address = self.symbols[name] & ~1
            self.hooks[address] = callback
            self.uc.hook_add(UC_HOOK_CODE, self.hook, begin=address, end=address)

    def hook(self, uc, address, size, data):
        callback = self.hooks[address]
        result = callback()
        if result is not None:
            uc.reg_write(UC_ARM_REG_R0, result & 0xFFFFFFFF)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def arg(self, i):
        return (
            self.uc.reg_read(REGS[i])
            if i < 4
            else struct.unpack(
                "<I", self.uc.mem_read(self.uc.reg_read(UC_ARM_REG_SP) + (i - 4) * 4, 4)
            )[0]
        )

    def cstr(self, address):
        result = bytearray()
        for i in range(256):
            byte = self.uc.mem_read(address + i, 1)[0]
            if not byte:
                return result.decode("ascii")
            result.append(byte)
        raise ValueError("Unterminated string")

    def uart_get(self):
        return self.incoming.popleft() if self.incoming else -1

    def uart_puts(self):
        self.outgoing.extend(self.cstr(self.arg(0)).encode("ascii"))

    @staticmethod
    def color(value):
        return (
            (value >> 11 & 31) * 255 // 31,
            (value >> 5 & 63) * 255 // 63,
            (value & 31) * 255 // 31,
        )

    def fill(self):
        x, y, width, height, color = [self.arg(i) for i in range(5)]
        x, y = ctypes_signed(x), ctypes_signed(y)
        if width and height:
            self.draw.rectangle((x, y, x + width - 1, y + height - 1), fill=self.color(color))
            self.rectangles.append((x, y, width, height))

    def text(self):
        x, y, pointer, fg, bg, scale = [self.arg(i) for i in range(6)]
        text = self.cstr(pointer)
        self.texts.append((x, y, text, scale))
        for char in text.upper():
            if x + 6 * scale > 240:
                break
            if char.isascii() and char.isdigit():
                glyph = self.uc.mem_read(self.symbols["digits"] + (ord(char) - 48) * 5, 5)
            elif "A" <= char <= "Z":
                glyph = self.uc.mem_read(self.symbols["letters"] + (ord(char) - 65) * 5, 5)
            else:
                glyph = {
                    "-": [8] * 5,
                    "+": [8, 8, 62, 8, 8],
                    ":": [0, 0, 36, 0, 0],
                    ".": [0, 0, 64, 0, 0],
                    "/": [32, 16, 8, 4, 2],
                    "%": [99, 19, 8, 100, 99],
                }.get(char, [0] * 5)
            self.draw.rectangle((x, y, x + 6 * scale - 1, y + 8 * scale - 1), fill=self.color(bg))
            for col in range(5):
                for row in range(7):
                    if glyph[col] & (1 << row):
                        self.draw.rectangle(
                            (
                                x + col * scale,
                                y + row * scale,
                                x + (col + 1) * scale - 1,
                                y + (row + 1) * scale - 1,
                            ),
                            fill=self.color(fg),
                        )
            x += 6 * scale

    def bitmap(self):
        x, y, w, h, pointer = [self.arg(i) for i in range(5)]
        self.bitmap_regions.append((x, y, w, h))
        pixels = struct.unpack("<" + "H" * (w * h), self.uc.mem_read(pointer, w * h * 2))
        image = Image.new("RGB", (w, h))
        image.putdata([self.icon_color(v) for v in pixels])
        self.image.paste(image, (x, y))

    def icon_color(self, value):
        if value == 1:
            value = struct.unpack("<H", self.uc.mem_read(self.symbols["lcd_icon_background"], 2))[0]
        elif value == 2:
            value = struct.unpack("<H", self.uc.mem_read(self.symbols["lcd_icon_foreground"], 2))[0]
        return self.color(value)

    def slot_address(self, index):
        return self.call("deck_slot", index)

    def icon48(self):
        x, y, pointer = [self.arg(i) for i in range(3)]
        pixels = struct.unpack("<1024H", self.uc.mem_read(pointer, 2048))
        image = Image.new("RGB", (48, 48))
        image.putdata(
            [
                self.icon_color(pixels[(r * 2 // 3) * 32 + c * 2 // 3])
                for r in range(48)
                for c in range(48)
            ]
        )
        self.image.paste(image, (x, y))
        self.rectangles.append((x, y, 48, 48))

    def write(self, name, data):
        self.uc.mem_write(self.symbols[name], data)

    def call(self, name, *args):
        stack = 0x1000E000
        self.uc.reg_write(UC_ARM_REG_SP, stack)
        self.uc.reg_write(UC_ARM_REG_LR, 0x20000001)
        for i, arg in enumerate(args):
            if i < 4:
                self.uc.reg_write(REGS[i], arg)
            else:
                self.uc.mem_write(stack + (i - 4) * 4, struct.pack("<I", arg))
        self.uc.emu_start(self.symbols[name] | 1, 0x20000000, count=2000000)
        if self.uc.reg_read(UC_ARM_REG_PC) != 0x20000000:
            raise RuntimeError("Firmware function exceeded instruction budget")
        return self.uc.reg_read(UC_ARM_REG_R0)


def ctypes_signed(value):
    return value if value < 0x80000000 else value - 0x100000000


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.fw = Firmware()
        self.scratch = 0x10009000

    def test_arm_crc_matches_host(self):
        self.fw.uc.mem_write(self.scratch, b"123456789\0")
        self.fw.call("protocol_send", self.scratch)
        self.assertEqual(bytes(self.fw.outgoing), encode("123456789"))

    def test_arm_fragmented_packet(self):
        wire = encode("M,25,38,50,124,5,19,30")
        for byte in wire[:-1]:
            self.fw.incoming.append(byte)
            self.assertEqual(self.fw.call("protocol_poll", self.scratch), 0)
        self.fw.incoming.append(10)
        self.assertEqual(self.fw.call("protocol_poll", self.scratch), 1)
        self.assertEqual(self.fw.cstr(self.scratch), "M,25,38,50,124,5,19,30")

    def test_arm_rejects_corruption_and_recovers(self):
        self.fw.incoming.extend(encode("E,1,1").replace(b"E,1,1", b"E,1,2") + encode("R,1"))
        self.assertEqual(self.fw.call("protocol_poll", self.scratch), 1)
        self.assertEqual(self.fw.cstr(self.scratch), "R,1")

    def test_arm_overlong_packet_recovers(self):
        self.fw.incoming.extend(b"@" + b"x" * 600 + b"\n" + encode("R,1"))
        results = [self.fw.call("protocol_poll", self.scratch) for _ in range(4)]
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.fw.cstr(self.scratch), "R,1")

    def test_arm_timeout_discards_partial_frame(self):
        wire = encode("R,1")
        self.fw.incoming.extend(wire[:3])
        self.fw.call("protocol_poll", self.scratch)
        self.fw.write("ticks", struct.pack("<I", 251))
        self.fw.incoming.extend(wire[3:])
        self.assertEqual(self.fw.call("protocol_poll", self.scratch), 0)
        self.fw.incoming.extend(wire)
        self.assertEqual(self.fw.call("protocol_poll", self.scratch), 1)

    def test_arm_unsigned_overflow_rejected(self):
        for body, valid in [
            (b"E,4294967295,11\0", 1),
            (b"E,4294967296,11\0", 0),
            (b"E,-1,0\0", 0),
            (b"E,1,2,3\0", 0),
            (b"E,1\0", 0),
        ]:
            self.fw.uc.mem_write(self.scratch, body)
            self.assertEqual(
                self.fw.call("protocol_parse", self.scratch, ord("E"), self.scratch + 128, 2), valid
            )

    def test_all_pages_with_extreme_values_fit_screen(self):
        self.fw.write("online", b"\1")
        self.fw.write("metrics", struct.pack("<7I", 100, 100, 100, 999999, 999999, 23, 59))
        for page in range(3):
            self.fw.write("page", struct.pack("<I", page))
            self.fw.call("screen")
        for x, y, text, scale in self.fw.texts:
            self.assertLessEqual(x + len(text) * 6 * scale, 240, text)
            self.assertLessEqual(y + 8 * scale, 320, text)
        for x, y, w, h in self.fw.rectangles:
            self.assertTrue(0 <= x < 240 and 0 <= y < 320 and x + w <= 240 and y + h <= 320)


def preview():
    images = []
    from actions import Actions
    from icons import get_icon, rgb565, deck_label, fallback_icon

    items = Actions(ROOT / "companion/actions.json").items
    for page, bank in ((1, 0), (1, 1), (1, 2), (0, 0), (2, 0)):
        fw = Firmware()
        fw.write("app_page", struct.pack("<I", bank))
        fw.write("online", b"\1")
        fw.write("page", struct.pack("<I", page))
        fw.write("deck_configured", b"\1")
        for i, item in enumerate(items):
            try:
                image = get_icon(item)
            except (OSError, ValueError):
                image = fallback_icon(item)
            data = rgb565(image)
            little = bytearray()
            for j in range(0, len(data), 2):
                little.extend(data[j : j + 2][::-1])
            label = deck_label(item).encode().ljust(11, b"\0")
            fw.uc.mem_write(
                fw.slot_address(i), bytes(little) + label + bytes([item["type"] != "empty"])
            )
        fw.write("metrics", struct.pack("<7I", 27, 38, 62, 1248, 86, 19, 42))
        fw.write("notice", b"PC BAGLI / DOKUN VE YONET\0")
        fw.write("history_count", struct.pack("<I", 60))
        fw.write("monitor_values", struct.pack("<4i", 27, 38, 54, 144))
        fw.write(
            "history",
            struct.pack(
                "<240H",
                *(
                    18 + ((i * 7) % 29) + (80 if bank == 3 else bank * 8)
                    for bank in range(4)
                    for i in range(60)
                ),
            ),
        )
        fw.call("screen")
        images.append(fw.image.resize((480, 640), Image.Resampling.NEAREST))
    combined = Image.new("RGB", (2460, 680), "#101522")
    for i, im in enumerate(images):
        combined.paste(im, (10 + i * 490, 20))
    combined.save(ROOT / "docs/mini-deck-preview.png")
    monitor_images = []
    fw.write("page", struct.pack("<I", 2))
    for detail in (4, 0, 1, 2, 3):
        fw.write("monitor_detail", struct.pack("<I", detail))
        fw.call("screen")
        monitor_images.append(fw.image.resize((480, 640), Image.Resampling.NEAREST))
    monitor = Image.new("RGB", (2460, 680), "#101522")
    for i, im in enumerate(monitor_images):
        monitor.paste(im, (10 + i * 490, 20))
    monitor.save(ROOT / "docs/mini-deck-monitor-preview.png")
    print("Saved docs/mini-deck-preview.png (ARM application rendering; simulated values)")


if __name__ == "__main__":
    if "--preview" in sys.argv:
        preview()
    else:
        unittest.main()
