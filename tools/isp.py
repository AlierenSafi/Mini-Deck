"""LPC1768 ROM UART ISP, per NXP UM10360 chapter 32. Requires pyserial."""

import argparse
import binascii
import hashlib
import json
from pathlib import Path
import struct
import time
import serial

RAM = 0x10001000
PART_ID = 0x26013F37


def uudecode(line):
    # NXP ROM leaves nonzero pad bits in the final quartet; binascii rejects them.
    count = (line[0] - 32) & 63
    if not 1 <= count <= 45 or len(line) != 1 + ((count + 2) // 3) * 4:
        raise RuntimeError(f"Invalid UU line: {line!r}")
    decoded = bytearray()
    for i in range(1, len(line), 4):
        a, b, c, d = ((v - 32) & 63 for v in line[i : i + 4])
        decoded.extend(((a << 2) | (b >> 4), ((b << 4) | (c >> 2)) & 255, ((c << 6) | d) & 255))
    return decoded[:count]


class ISP:
    def __init__(self, port, baud):
        self.s = serial.Serial(port, baud, timeout=3, write_timeout=5)

    def line(self):
        data = self.s.readline()
        if not data.endswith(b"\n"):
            raise RuntimeError(f"ISP response timeout: {data!r}")
        return data.rstrip(b"\r\n")

    def send(self, text):
        self.s.write(text.encode("ascii") + b"\r\n")
        self.s.flush()

    def command(self, cmd):
        self.send(cmd)
        status = self.line()
        if status != b"0":
            raise RuntimeError(f"{cmd}: ISP status {status!r}")

    def sync(self):
        self.s.write(b"?")
        if self.line() != b"Synchronized":
            raise RuntimeError("Enter ISP: hold ISP, tap RESET, release ISP.")
        self.send("Synchronized")
        if b"OK" not in self.line():
            raise RuntimeError("Synchronization failed")
        self.send("12000")
        if b"OK" not in self.line():
            raise RuntimeError("Crystal frequency handshake failed")
        self.send("A 0")
        if not self.line().endswith(b"0"):
            raise RuntimeError("Cannot disable ISP echo")
        # Remain at the conservative autobaud rate for ROM RAM writes.

    def identify(self):
        self.command("J")
        part = int(self.line())
        if part != PART_ID:
            raise RuntimeError(f"Unexpected part 0x{part:08x}; expected LPC1768")
        print(f"LPC1768 confirmed: 0x{part:08X}", flush=True)

    def read(self, address, size):
        self.command(f"R {address} {size}")
        data = bytearray()
        while len(data) < size:
            block = bytearray()
            for _ in range(20):
                block.extend(uudecode(self.line()))
                if len(data) + len(block) >= size:
                    break
            checksum = int(self.line())
            if sum(block) != checksum:
                self.send("RESEND")
                raise RuntimeError("Read checksum mismatch; no flash modification attempted")
            self.send("OK")
            data.extend(block)
        if len(data) != size:
            raise RuntimeError("Unexpected read length")
        return bytes(data)

    def write_ram(self, address, data):
        self.command(f"W {address} {len(data)}")
        for start in range(0, len(data), 900):
            block = data[start : start + 900]
            for attempt in range(3):
                for i in range(0, len(block), 45):
                    self.s.write(
                        binascii.b2a_uu(block[i : i + 45], backtick=True).rstrip(b"\n") + b"\r\n"
                    )
                    self.s.flush()
                    time.sleep(0.01)  # ROM has no flow control; pace each encoded line.
                self.send(str(sum(block)))
                reply = self.line()
                if reply == b"OK":
                    break
                if reply != b"RESEND" or attempt == 2:
                    raise RuntimeError(f"RAM transfer failed: {reply!r}")

    def backup(self, path):
        path = Path(path)
        if path.exists():
            raise RuntimeError(f"Refusing to overwrite existing backup: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray()
        for addr in range(0, 512 * 1024, 4096):
            data.extend(self.read(addr, 4096))
            if addr % 65536 == 0:
                print(f"Backup {len(data) // 1024}/512 KiB", flush=True)
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "bytes": len(data),
                    "sha256": digest,
                    "part_id": hex(PART_ID),
                    "limitation": "First 1024 bytes are ISP ROM overlay, not original flash vectors; not a complete restorable image.",
                },
                indent=2,
            )
        )
        print(f"Backup saved: {path} SHA256={digest}", flush=True)

    def flash(self, path):
        data = Path(path).read_bytes()
        if not 0x400 <= len(data) <= 512 * 1024:
            raise ValueError("Image size outside LPC1768 limits")
        if sum(struct.unpack("<8I", data[:32])) & 0xFFFFFFFF:
            raise ValueError("Invalid LPC vector checksum")
        if struct.unpack_from("<I", data, 0x2FC)[0] != 0xFFFFFFFF:
            raise ValueError("CRP word must remain 0xffffffff")
        data += b"\xff" * (-len(data) % 4096)
        last = sector(len(data) - 1)
        # Prove RAM transfer works before erasing any sectors.
        self.write_ram(RAM, data[:256])
        if self.read(RAM, 256) != data[:256]:
            raise RuntimeError("RAM preflight readback failed; flash not erased")
        print("RAM preflight verified", flush=True)
        self.command("U 23130")
        self.command(f"P 0 {last}")
        self.command(f"E 0 {last}")
        for addr in range(0, len(data), 4096):
            block = data[addr : addr + 4096]
            self.write_ram(RAM, block)
            self.command(f"P {sector(addr)} {sector(addr)}")
            self.command(f"C {addr} {RAM} 4096")
            # Conservatively exclude the boot vector window while ROM is mapped.
            skip = 1024 if addr == 0 else 0
            self.command(f"M {addr+skip} {RAM+skip} {4096-skip}")
            print(f"Written and compared: {addr+4096}/{len(data)}", flush=True)
        readback = b"".join(self.read(a, 4096) for a in range(0, len(data), 4096))
        # ROM overlays the start of flash; independently check the entire image at runtime.
        if readback[1024:] != data[1024:]:
            raise RuntimeError("Full readback mismatch; leaving device in ISP")
        report = {
            "image": str(path),
            "verified_bytes": len(data) - 1024,
            "sha256": hashlib.sha256(data).hexdigest(),
            "verification": "Byte-for-byte flash readback passed from byte 1024; first 1024 require runtime full-image CRC32",
        }
        Path("build/flash-verification.json").write_text(json.dumps(report, indent=2))
        print(report, flush=True)

    def reset(self):
        # Thumb trampoline: LDR r0/literal; LDR r1/literal; STR; B .; literals.
        stub = bytes.fromhex("014802490160fee7") + struct.pack("<II", 0xE000ED0C, 0x05FA0004)
        self.command("U 23130")
        self.write_ram(RAM, stub)
        self.send(f"G {RAM} T")
        # The reset stub may reset UART before the trailing CR/LF is transmitted.
        # Read the success byte only, then switch immediately to application baud.
        status = self.s.read(1)
        if status != b"0":
            raise RuntimeError(f"GO/reset not acknowledged: {status!r}")
        self.s.baudrate = 115200


def sector(addr):
    return addr // 4096 if addr < 65536 else 16 + (addr - 65536) // 32768


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", default="COM7")
    p.add_argument("--resume", action="store_true", help="Already synchronized at --baud")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--backup")
    p.add_argument("--flash")
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()
    isp = ISP(args.port, args.baud)
    try:
        if not args.resume:
            isp.sync()
        isp.identify()
        if args.backup:
            isp.backup(args.backup)
        if args.flash:
            isp.flash(args.flash)
        if args.reset:
            isp.reset()
    finally:
        isp.s.close()


if __name__ == "__main__":
    main()
