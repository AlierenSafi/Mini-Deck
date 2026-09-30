"""Local, explicitly configured Windows actions. Serial data contains IDs only."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import threading
import copy
import zlib

KEYS = {
    "CTRL": 0x11,
    "ALT": 0x12,
    "SHIFT": 0x10,
    "WIN": 0x5B,
    "ESC": 0x1B,
    "ENTER": 0x0D,
    "SPACE": 0x20,
    "TAB": 0x09,
    "PREVIOUS": 0xB1,
    "PLAY": 0xB3,
    "NEXT": 0xB0,
    "VOLUME_DOWN": 0xAE,
    "MUTE": 0xAD,
    "VOLUME_UP": 0xAF,
}
KEYS.update({chr(c): c for c in range(65, 91)})
KEYS.update({str(c): 48 + c for c in range(10)})


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", INPUTUNION)]


def send_keys(names):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    send = user32.SendInput
    send.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    send.restype = wintypes.UINT
    codes = [KEYS[name] for name in names]
    events = []
    for code in codes:
        events.append(INPUT(type=1, ki=KEYBDINPUT(wVk=code)))
    for code in reversed(codes):
        events.append(INPUT(type=1, ki=KEYBDINPUT(wVk=code, dwFlags=2)))
    buffer = (INPUT * len(events))(*events)
    if send(len(events), buffer, ctypes.sizeof(INPUT)) != len(events):
        # Release our keys even if UIPI/focus conditions caused partial injection.
        releases = (INPUT * len(codes))(*events[len(codes) :])
        send(len(codes), releases, ctypes.sizeof(INPUT))
        raise OSError("Windows tus girisini kabul etmedi (yetki veya masaustu durumu).")


SLOT_COUNT = 24
KEYS.update({f"F{i}": 0x6F + i for i in range(1, 25)})


def empty_slot():
    return {"name": "Boş slot", "label": "BOS SLOT", "type": "empty"}


def normalize_config(value):
    if isinstance(value, dict) and value.get("version") in (2, 3):
        value = value.get("slots")
    if not isinstance(value, list) or len(value) not in (12, 18, SLOT_COUNT):
        raise ValueError(
            "Profil 24 slot içermeli: 6 medya + 18 uygulama. Eski 12/18 slotlu profiller de alınabilir."
        )
    items = copy.deepcopy(value)
    if len(items) < SLOT_COUNT:
        items.extend(empty_slot() for _ in range(SLOT_COUNT - len(items)))
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not 1 <= len(item["name"]) <= 80
        ):
            raise ValueError("Slot adı 1–80 karakter olmalı.")
        if not isinstance(item.get("label", ""), str) or len(item.get("label", "")) > 10:
            raise ValueError("Kart etiketi en fazla 10 karakter olmalı.")
        if not isinstance(item.get("icon", ""), str):
            raise ValueError("Simge yolu metin olmalı.")
        kind = item.get("type")
        if kind == "keys":
            keys = item.get("keys")
            if (
                not isinstance(keys, list)
                or not 1 <= len(keys) <= 4
                or any(not isinstance(k, str) or k not in KEYS for k in keys)
            ):
                raise ValueError("Geçersiz tuş dizisi. Örnek: CTRL+SHIFT+S")
        elif kind == "launch":
            argv = item.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or len(argv) > 32
                or any(not isinstance(a, str) or not a or len(a) > 4096 for a in argv)
            ):
                raise ValueError("Program ve argümanlar boş olmayan metinler olmalı.")
        elif kind == "open":
            if not isinstance(item.get("path"), str) or not item["path"]:
                raise ValueError("Uygulama kısayolu veya dosya seçilmeli.")
        elif kind not in ("settings", "empty"):
            raise ValueError("Bilinmeyen eylem türü.")
    return items


class Actions:
    def __init__(self, path, dry_run=False):
        self.path, self.dry_run = Path(path), dry_run
        # First launch creates a personal profile from portable, path-free defaults.
        # Exclusive creation avoids overwriting another application's saved profile.
        if not self.path.exists():
            sample = Path(__file__).with_name("actions.example.json").read_text(encoding="utf-8")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self.path.open("x", encoding="utf-8") as stream:
                    stream.write(sample)
            except FileExistsError:
                pass
        self.lock = threading.RLock()
        self._items = normalize_config(json.loads(self.path.read_text(encoding="utf-8-sig")))

    @property
    def items(self):
        with self.lock:
            return copy.deepcopy(self._items)

    @property
    def revision(self):
        with self.lock:
            data = json.dumps(
                self._items, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode()
            return zlib.crc32(data) or 1

    def snapshot(self):
        with self.lock:
            return self.revision, self.items

    def replace(self, value):
        items = normalize_config(value)
        encoded = json.dumps(items, ensure_ascii=False, indent=2)
        with self.lock:
            temp = self.path.with_suffix(".tmp")
            temp.write_text(encoded, encoding="utf-8")
            if self.path.exists():
                self.path.with_suffix(".json.bak").write_bytes(self.path.read_bytes())
            os.replace(temp, self.path)
            self._items = items

    def run(self, action, revision=None):
        with self.lock:
            if revision is not None and revision != self.revision:
                raise ValueError("Kart profili güncelleniyor; yeniden deneyin.")
            if not isinstance(action, int) or not 0 <= action < SLOT_COUNT:
                raise ValueError("Geçersiz slot.")
            item = copy.deepcopy(self._items[action])
        if item["type"] == "empty":
            raise ValueError("Bu slot boş.")
        if not self.dry_run:
            if os.name != "nt":
                raise OSError("Bu yardımcı uygulama Windows içindir.")
            if item["type"] == "keys":
                send_keys(item["keys"])
            elif item["type"] == "launch":
                subprocess.Popen(item["argv"], shell=False)
            elif item["type"] == "open":
                os.startfile(item["path"])
            else:
                os.startfile("ms-settings:")
        return ("DENEME: " if self.dry_run else "") + item["name"]
