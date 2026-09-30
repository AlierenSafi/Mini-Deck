"""User settings; API credentials encrypted for the current Windows account."""

import ctypes as C
from ctypes import wintypes as W
import base64
import json
from pathlib import Path

PATH = Path(__file__).with_name("game-settings.json")
DEFAULTS = {
    "auto_switch": True,
    "mic_keys": "",
    "player": "",
    "platform": "steam",
    "client_id": "",
    "pubg_key": "",
    "client_secret": "",
    "discord_token": "",
    "discord_refresh": "",
    "discord_mode": "bot",
    "bot_token": "",
    "voice_channel": "",
    "discord_user_id": "",
}
SECRETS = ("pubg_key", "client_secret", "discord_token", "discord_refresh", "bot_token")


def protect(value, decrypt=False):
    class Blob(C.Structure):
        _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_ubyte))]

    raw = base64.b64decode(value) if decrypt else value.encode("utf-8")
    data = (C.c_ubyte * len(raw)).from_buffer_copy(raw)
    source, output = Blob(len(raw), data), Blob()
    api = C.WinDLL("crypt32", use_last_error=True)
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    fn.argtypes = [
        C.POINTER(Blob),
        C.c_void_p,
        C.c_void_p,
        C.c_void_p,
        C.c_void_p,
        W.DWORD,
        C.POINTER(Blob),
    ]
    fn.restype = W.BOOL
    if not fn(C.byref(source), None, None, None, None, 1, C.byref(output)):
        raise OSError("Windows kimlik bilgisi şifrelemesi başarısız")
    try:
        result = C.string_at(output.data, output.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        kernel = C.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [C.c_void_p]
        kernel.LocalFree(output.data)


def load(path=PATH):
    result = dict(DEFAULTS)
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        for key in DEFAULTS:
            if key in stored:
                result[key] = (
                    protect(stored[key], True) if key in SECRETS and stored[key] else stored[key]
                )
    return result


# Persist credentials through the module encryption path; never log the plaintext values.
def save(config, path=PATH):
    from actions import KEYS

    keys = config["mic_keys"].upper().replace(" ", "").split("+") if config["mic_keys"] else []
    if len(keys) > 4 or any(k not in KEYS for k in keys):
        raise ValueError("Mikrofon kısayolu geçersiz; örnek CTRL+ALT+F10")
    from urllib.parse import urlparse

    channel = config.get("voice_channel", "").strip()
    if channel.startswith("https://"):
        parsed = urlparse(channel)
        parts = parsed.path.strip("/").split("/")
        if (
            parsed.hostname not in ("discord.com", "canary.discord.com", "ptb.discord.com")
            or len(parts) != 3
            or parts[0] != "channels"
            or not parts[1].isascii()
            or not parts[1].isdigit()
        ):
            raise ValueError(
                "Ses kanalına sağ tıklayıp Kanal Bağlantısını Kopyala seçeneğini kullanın."
            )
        channel = parts[2]
    for name, value in (
        ("Ses kanalı", channel),
        ("Discord kullanıcı kimliği", config.get("discord_user_id", "")),
    ):
        if value and (not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**64):
            raise ValueError(
                name + " geçersiz; ad değil sayısal kimlik veya kanal bağlantısı kullanın."
            )
    config["voice_channel"] = channel
    if config.get("discord_mode", "bot") not in ("bot", "rpc"):
        raise ValueError("Discord bağlantı türü geçersiz")
    stored = {k: config.get(k, DEFAULTS[k]) for k in DEFAULTS}
    for key in SECRETS:
        if stored[key]:
            stored[key] = protect(stored[key])
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
