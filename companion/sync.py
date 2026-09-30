"""Acknowledged, restartable layout transfer. Commands remain higher priority."""

import secrets
import time
from icons import deck_label
from protocol import encode


# Advance the transfer only after acknowledgements; retries must never activate a partial profile.
class Sync:
    def __init__(self, layout, previous=None, version=5):
        self.revision = layout["revision"]
        self.layout = layout
        delta = version >= 6 and previous is not None
        self.jobs = [f'b,{self.revision},{previous["revision"]}' if delta else f"B,{self.revision}"]
        key = "themed_pixels" if version >= 6 and "themed_pixels" in layout else "pixels"
        chunk = 192 if version >= 6 else 64
        for index, item in enumerate(layout["items"]):
            if (
                delta
                and item == previous["items"][index]
                and layout[key][index] == previous.get(key, previous["pixels"])[index]
            ):
                continue
            enabled = item["type"] != "empty"
            self.jobs.append(f"L,{index},{int(enabled)},{deck_label(item)}")
            if enabled:
                pixels = layout[key][index]
                if len(pixels) != 4096:
                    raise ValueError("Simge 32x32 RGB565 olmalı.")
                self.jobs.extend(
                    f"I,{index},{offset//4},{pixels[offset:offset+chunk]}"
                    for offset in range(0, 4096, chunk)
                )
            self.jobs.append(f"F,{index}")
        self.jobs.append(f"Z,{self.revision}")
        self.index = 0
        self.token = secrets.randbelow(0x7FFFFFFE) + 1
        self.sent_at = None
        self.attempts = 0
        self.failed = False

    @property
    def done(self):
        return self.index == len(self.jobs)

    def acknowledge(self, body):
        parts = body.split(",")
        if (
            len(parts) != 3
            or parts[0] != "Y"
            or not all(v.isascii() and v.isdecimal() and len(v) <= 10 for v in parts[1:])
        ):
            return False
        token, result = map(int, parts[1:])
        if token != self.token or self.sent_at is None or result not in (0, 1):
            return False
        if not result:
            self.failed = True
            return True
        self.index += 1
        self.token = (self.token + 1) & 0xFFFFFFFF or 1
        self.sent_at = None
        self.attempts = 0
        return True

    def next_packet(self, now=None):
        now = time.monotonic() if now is None else now
        if self.done or self.failed:
            return None
        if self.sent_at is not None and now - self.sent_at < 0.3:
            return None
        if self.attempts >= 3:
            self.failed = True
            return None
        self.sent_at = now
        self.attempts += 1
        return encode(f"X,{self.token},{self.jobs[self.index]}")
