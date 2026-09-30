"""Bounded CRC16-CCITT wire framing shared with the Cortex-M firmware."""

import binascii

MAX_FRAME = 256


def encode(body: str) -> bytes:
    raw = body.encode("ascii")
    if not raw or len(raw) > MAX_FRAME - 6 or any(c < 32 or c > 126 or c in b"@*" for c in raw):
        raise ValueError("Invalid frame body")
    return b"@" + raw + f"*{binascii.crc_hqx(raw, 0xffff):04X}\n".encode("ascii")


class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.active = False

    def feed(self, data: bytes):
        result = []
        for byte in data:
            if byte == 64:
                self.active = True
                self.buffer.clear()
            elif self.active:
                if byte == 13:
                    continue
                if byte == 10:
                    self.active = False
                    raw = bytes(self.buffer)
                    if len(raw) < 6 or raw[-5:-4] != b"*":
                        continue
                    try:
                        checksum = raw[-4:]
                        if any(c not in b"0123456789ABCDEF" for c in checksum):
                            continue
                        if binascii.crc_hqx(raw[:-5], 0xFFFF) == int(checksum, 16):
                            result.append(raw[:-5].decode("ascii"))
                    except (ValueError, UnicodeError):
                        continue
                elif byte < 32 or byte > 126 or len(self.buffer) >= MAX_FRAME - 1:
                    self.active = False
                    self.buffer.clear()
                else:
                    self.buffer.append(byte)
        return result


def parse_event(body: str):
    parts = body.split(",")
    if len(parts) != 4 or parts[0] != "E":
        return None
    if any(not part.isascii() or not part.isdecimal() or len(part) > 10 for part in parts[1:]):
        return None
    sequence, action, revision = map(int, parts[1:])
    if not 1 <= sequence <= 0xFFFFFFFF or not 0 <= action < 24 or not 1 <= revision <= 0xFFFFFFFF:
        return None
    return sequence, action, revision
