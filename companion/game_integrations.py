"""Optional official Discord RPC and PUBG API integrations, off until configured."""

import ctypes as C
from ctypes import wintypes as W
import json
import msvcrt
import queue
import struct
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pubg_reports import extract, aggregate, archive


def http_json(url, headers=None, form=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Yanıt çok büyük")
        return json.loads(raw)


def pubg_summary(config, cache=None, stop=None):
    cache = {} if cache is None else cache
    base = "https://api.pubg.com/shards/steam/"
    headers = {
        "Authorization": "Bearer " + config["pubg_key"],
        "Accept": "application/vnd.api+json",
    }
    player = http_json(
        base + "players?" + urllib.parse.urlencode({"filter[playerNames]": config["player"]}),
        headers,
    )
    players = player.get("data", [])
    if not players:
        raise ValueError("Oyuncu bulunamadı")
    matches = players[0]["relationships"]["matches"]["data"]
    if not matches:
        return None
    # Player match lists are unordered: inspect recent match timestamps, not list order.
    summaries = []
    for ref in matches:
        if stop and stop.is_set():
            return None
        if ref["id"] in cache:
            if cache[ref["id"]]:
                summaries.append(cache[ref["id"]])
            continue
        match = http_json(
            base + "matches/" + urllib.parse.quote(ref["id"], safe=""),
            {"Accept": headers["Accept"]},
        )
        cache[ref["id"]] = None
        summary = extract(match, players[0]["id"], ref["id"])
        cache[ref["id"]] = summary
        if summary:
            summaries.append(summary)
    current = {ref["id"] for ref in matches}
    for key in list(cache):
        if key not in current:
            del cache[key]
    return max(summaries, key=lambda m: m["created"]) if summaries else None


class MatchMonitor(threading.Thread):
    def __init__(self, settings, emit):
        super().__init__(daemon=True, name="deck-pubg")
        self.settings, self.emit = settings, emit
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.cache = {}
        self.player = ""
        self.last_request = 0
        self.latest = {
            "status": 0,
            "summary": None,
            "message": "Maç özeti için oyuncu adı ve API anahtarı gerekli.",
        }

    def run(self):
        while not self.stop_event.is_set():
            config = self.settings()
            if config["player"] and config["pubg_key"]:
                if self.stop_event.wait(max(0, 20 - (time.monotonic() - self.last_request))):
                    break
                self.last_request = time.monotonic()
                try:
                    if config["player"] != self.player:
                        self.cache.clear()
                        self.player = config["player"]
                    summary = pubg_summary(config, self.cache, self.stop_event)
                    self.latest = {
                        "status": 1 if summary else 3,
                        "summary": summary,
                        "message": (
                            "Son tamamlanan maç" if summary else "Son 14 günde maç bulunamadı"
                        ),
                        **aggregate(archive(config["player"], self.cache.values())),
                    }
                except Exception as exc:
                    self.latest = {
                        "status": 2,
                        "summary": None,
                        "message": f"PUBG verisi alınamadı ({type(exc).__name__}); ayarları kontrol edin.",
                    }
            else:
                self.latest = {
                    "status": 0,
                    "summary": None,
                    "message": "Maç özeti için oyuncu adı ve API anahtarı gerekli.",
                }
            self.emit("game_match", dict(self.latest))
            self.wake.wait(180)
            self.wake.clear()

    def close(self):
        self.stop_event.set()
        self.wake.set()


class PipeRPC:
    def __init__(self, client_id):
        self.pipe = None
        for index in range(10):
            try:
                self.pipe = open(r"\\?\pipe\discord-ipc-" + str(index), "r+b", buffering=0)
                break
            except OSError:
                pass
        if self.pipe is None:
            raise OSError("Discord IPC bulunamadı")
        self.peek = C.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
        self.peek.argtypes = [
            W.HANDLE,
            C.c_void_p,
            W.DWORD,
            C.c_void_p,
            C.POINTER(W.DWORD),
            C.c_void_p,
        ]
        self.peek.restype = W.BOOL
        self.buffer = bytearray()
        self.send({"v": 1, "client_id": client_id}, 0)
        if self.receive(3).get("evt") != "READY":
            self.close()
            raise ValueError("Discord RPC hazır değil")

    def send(self, payload, opcode=1):
        body = json.dumps(payload).encode("utf-8")
        self.pipe.write(struct.pack("<II", opcode, len(body)) + body)

    def receive(self, timeout=0.1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.buffer) >= 8:
                op, size = struct.unpack_from("<II", self.buffer)
                if size > 1024 * 1024:
                    raise ValueError("RPC çerçevesi çok büyük")
                if len(self.buffer) >= size + 8:
                    raw = bytes(self.buffer[8 : size + 8])
                    del self.buffer[: size + 8]
                    if op == 2:
                        raise OSError("Discord bağlantısı kapandı")
                    if op == 3:
                        self.pipe.write(struct.pack("<II", 4, len(raw)) + raw)
                        continue
                    if op == 4:
                        continue
                    return json.loads(raw)
            available = W.DWORD()
            if not self.peek(
                msvcrt.get_osfhandle(self.pipe.fileno()), None, 0, None, C.byref(available), None
            ):
                raise OSError("Discord bağlantısı kesildi")
            if available.value:
                self.buffer.extend(self.pipe.read(min(available.value, 65536)))
            else:
                time.sleep(0.01)
        raise TimeoutError("Discord yanıt vermedi")

    def request(self, cmd, args=None, callback=None, timeout=3, evt=None):
        nonce = uuid.uuid4().hex
        payload = {"cmd": cmd, "args": args or {}, "nonce": nonce}
        if evt:
            payload["evt"] = evt
        self.send(payload)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            packet = self.receive(max(0.01, deadline - time.monotonic()))
            if packet.get("nonce") == nonce:
                if packet.get("evt") == "ERROR":
                    raise ValueError("Discord RPC yetkisi/komutu reddedildi")
                return packet.get("data")
            if callback:
                callback(packet)
        raise TimeoutError("Discord komutu zaman aşımı")

    def close(self):
        if self.pipe:
            self.pipe.close()
            self.pipe = None


class DiscordMonitor(threading.Thread):
    def __init__(self, settings, persist, emit):
        super().__init__(daemon=True, name="deck-discord")
        self.settings, self.persist, self.emit = settings, persist, emit
        self.stop_event = threading.Event()
        self.authorize = threading.Event()
        self.commands = queue.Queue(maxsize=8)
        self.latest = {
            "status": 0,
            "members": [],
            "mic": None,
            "channel": "",
            "message": "Discord bağlantısı ayarlanmadı",
        }
        self.speakers = set()

    def event(self, packet):
        evt = packet.get("evt")
        data = packet.get("data") or {}
        uid = data.get("user_id")
        if evt == "SPEAKING_START":
            self.speakers.add(uid)
        elif evt == "SPEAKING_STOP":
            self.speakers.discard(uid)

    def toggle_mic(self):
        if self.latest["status"] != 1:
            raise ValueError("Discord yetkilendirmesi gerekli")
        done = threading.Event()
        result = []
        self.commands.put_nowait((done, result))
        if not done.wait(4):
            raise TimeoutError("Discord mikrofon komutu zaman aşımı")
        if result and result[0]:
            raise ValueError(result[0])

    def run(self):
        while not self.stop_event.is_set():
            config = self.settings()
            rpc = None
            try:
                if (
                    config.get("discord_mode", "bot") != "rpc"
                    or not config["client_id"]
                    or not (config["discord_token"] or self.authorize.is_set())
                ):
                    self.latest = {
                        "status": 0,
                        "members": [],
                        "mic": None,
                        "channel": "",
                        "message": "Discord bağlantısı ayarlanmadı",
                    }
                    self.stop_event.wait(0.5)
                    continue
                rpc = PipeRPC(config["client_id"])
                if self.authorize.is_set():
                    self.authorize.clear()
                    auth = rpc.request(
                        "AUTHORIZE",
                        {
                            "client_id": config["client_id"],
                            "scopes": ["rpc", "rpc.voice.read", "rpc.voice.write", "identify"],
                        },
                        timeout=60,
                    )
                    token = http_json(
                        "https://discord.com/api/oauth2/token",
                        form={
                            "client_id": config["client_id"],
                            "client_secret": config["client_secret"],
                            "grant_type": "authorization_code",
                            "code": auth["code"],
                        },
                    )
                    config["discord_token"] = token["access_token"]
                    config["discord_refresh"] = token.get("refresh_token", "")
                    self.persist(config)
                try:
                    rpc.request("AUTHENTICATE", {"access_token": config["discord_token"]})
                except ValueError:
                    if not config["discord_refresh"]:
                        raise
                    token = http_json(
                        "https://discord.com/api/oauth2/token",
                        form={
                            "client_id": config["client_id"],
                            "client_secret": config["client_secret"],
                            "grant_type": "refresh_token",
                            "refresh_token": config["discord_refresh"],
                        },
                    )
                    config["discord_token"] = token["access_token"]
                    config["discord_refresh"] = token.get(
                        "refresh_token", config["discord_refresh"]
                    )
                    self.persist(config)
                    rpc.request("AUTHENTICATE", {"access_token": config["discord_token"]})
                channel_id = None
                poll_at = 0
                while not self.stop_event.is_set():
                    if (
                        self.authorize.is_set()
                        or self.settings()["client_id"] != config["client_id"]
                        or self.settings().get("discord_mode", "bot") != "rpc"
                    ):
                        break
                    try:
                        done, result = self.commands.get_nowait()
                    except queue.Empty:
                        done = None
                    if done:
                        try:
                            voice = rpc.request("GET_VOICE_SETTINGS", callback=self.event)
                            rpc.request(
                                "SET_VOICE_SETTINGS", {"mute": not voice["mute"]}, self.event
                            )
                        except Exception:
                            result.append("Discord mikrofon komutu uygulanamadı")
                        finally:
                            done.set()
                    if time.monotonic() >= poll_at:
                        channel = (
                            rpc.request("GET_SELECTED_VOICE_CHANNEL", callback=self.event) or {}
                        )
                        voice = rpc.request("GET_VOICE_SETTINGS", callback=self.event)
                        new_id = channel.get("id")
                        if channel_id != new_id:
                            self.speakers.clear()
                            if channel_id:
                                for evt in ("SPEAKING_START", "SPEAKING_STOP"):
                                    rpc.request(
                                        "UNSUBSCRIBE",
                                        {"channel_id": channel_id},
                                        self.event,
                                        evt=evt,
                                    )
                            channel_id = new_id
                            if new_id:
                                for evt in ("SPEAKING_START", "SPEAKING_STOP"):
                                    rpc.request(
                                        "SUBSCRIBE", {"channel_id": new_id}, self.event, evt=evt
                                    )
                        members = []
                        for item in channel.get("voice_states", [])[:100]:
                            user = item.get("user", {})
                            state = item.get("voice_state", {})
                            members.append(
                                {
                                    "id": user.get("id"),
                                    "name": item.get("nick")
                                    or user.get("global_name")
                                    or user.get("username", "?"),
                                    "mute": bool(state.get("self_mute") or state.get("mute")),
                                    "deaf": bool(state.get("self_deaf") or state.get("deaf")),
                                    "speaking": user.get("id") in self.speakers,
                                }
                            )
                        self.latest = {
                            "status": 1,
                            "members": members,
                            "mic": bool(voice["mute"]),
                            "channel": channel.get("name", ""),
                            "message": channel.get("name") or "Ses kanalına bağlı değil",
                        }
                        self.emit("game_discord", dict(self.latest))
                        poll_at = time.monotonic() + 0.5
                    try:
                        self.event(rpc.receive(0.05))
                    except TimeoutError:
                        pass
            except Exception as exc:
                self.latest = {
                    "status": 2,
                    "members": [],
                    "mic": None,
                    "channel": "",
                    "message": f"Discord bağlantısı kurulamadı ({type(exc).__name__}); RPC iznini kontrol edin.",
                }
                self.emit("game_discord", dict(self.latest))
                self.stop_event.wait(5)
            finally:
                if rpc:
                    rpc.close()

    def close(self):
        self.stop_event.set()
