"""Game controller: bounded command queue, fresh telemetry, optional account integrations."""

from collections import OrderedDict
import copy
import queue
import threading
import time
import unicodedata

from actions import send_keys
from game_audio import DiscordAudio
import game_config
from game_integrations import DiscordMonitor, MatchMonitor
from discord_bot import BotMonitor
from pubg_reports import report_lines


def lcd_label(text, width=22):
    text = str(text).replace("ı", "i")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()
    return "".join(c if c.isalnum() or c in " -." else " " for c in text)[:width].ljust(width)


# Aggregate independent services and deduplicate board commands before executing them.
class GameController(threading.Thread):
    def __init__(self, performance, emit, dry_run=False):
        super().__init__(daemon=True, name="deck-game")
        self.performance, self.emit, self.dry_run = performance, emit, dry_run
        self.lock = threading.RLock()
        try:
            self.config = game_config.load()
        except (OSError, ValueError):
            self.config = dict(game_config.DEFAULTS)
            emit("log", "Oyun ayarları okunamadı; ayarlar penceresinden yeniden kaydedin.")
        self.stop_event = threading.Event()
        self.commands = queue.Queue(maxsize=16)
        self.replies = queue.Queue(maxsize=32)
        self.seen = OrderedDict()
        self.epoch = 0
        self.team_offset = 0
        self.latest = {
            "volume": None,
            "muted": None,
            "focus": False,
            "active": False,
            "minutes": 0,
            "frametime": None,
            "low": None,
            "time": 0,
        }
        self.discord = DiscordMonitor(self.settings, self.save, emit)
        self.matches = MatchMonitor(self.settings, emit)
        self.bot = BotMonitor(self.settings, emit)

    def settings(self):
        with self.lock:
            return dict(self.config)

    def save(self, config):
        with self.lock:
            game_config.save(config)
            self.config = dict(config)
        self.matches.wake.set()

    def reset_events(self):
        with self.lock:
            self.epoch += 1
            self.seen.clear()

    def submit(self, action, seq=0):
        if action not in range(7):
            return False
        with self.lock:
            if seq and seq in self.seen:
                result = self.seen[seq]
                if result is not None:
                    try:
                        self.replies.put_nowait((seq, result))
                    except queue.Full:
                        pass
                return True
            try:
                self.commands.put_nowait((self.epoch, seq, action))
            except queue.Full:
                return False
            if seq:
                self.seen[seq] = None
                while len(self.seen) > 64:
                    self.seen.popitem(last=False)
        return True

    def snapshot(self):
        with self.lock:
            result = dict(self.latest)
        result["discord"] = copy.deepcopy(
            self.bot.latest
            if self.settings().get("discord_mode", "bot") == "bot"
            else self.discord.latest
        )
        result["match"] = copy.deepcopy(self.matches.latest)
        if time.monotonic() - result["time"] > 2:
            result.update(volume=None, muted=None, frametime=None, low=None)
        return result

    def frames(self, version=7):
        value = self.snapshot()
        dc = value["discord"]
        match = value["match"]
        summary = match["summary"] or {}
        config = self.settings()
        active = int(value["active"] and config["auto_switch"])
        integer = lambda n, missing: missing if n is None else int(n)
        fields = [
            active,
            integer(value["volume"], 101),
            integer(value["muted"], 2),
            integer(dc["mic"], 2),
            int(value["focus"]),
            min(999, value["minutes"]),
            min(9999, round(value["frametime"])) if value["frametime"] is not None else 10000,
        ]
        result = ["G," + ",".join(map(str, fields))]
        fields = [
            dc["status"],
            match["status"],
            min(999, summary.get("kills", 0)),
            min(99999, summary.get("damage", 0)),
            min(999, summary.get("rank", 0)),
            integer(value["low"], 10000),
            int(bool(config["mic_keys"])),
        ]
        result.append("U," + ",".join(map(str, fields)))
        members = dc["members"]
        offset = self.team_offset if self.team_offset < len(members) else 0
        for i in range(4):
            member = members[offset + i] if offset + i < len(members) else None
            state = (
                (2 if member.get("mute") else 1 if member.get("speaking") else 0) if member else 3
            )
            if member and member.get("deaf"):
                state = (5 if member.get("mute") else 4) if version >= 8 else 2
            result.append(f"N,{i},{state}," + lcd_label(member["name"] if member else ""))
        result.append(
            "N,4,0,"
            + lcd_label(
                dc["channel"] or ("DISCORD IZNI GEREKLI" if dc["status"] != 1 else "SES KANALI YOK")
            )
        )
        result.append(
            "N,5,0,"
            + lcd_label(
                (summary.get("created", "")[:16].replace("T", " ") + " UTC") if summary else ""
            )
        )
        for page, rows in enumerate(report_lines(match)):
            for row, text in enumerate(rows):
                result.append(f"P,{page},{row}," + lcd_label(text, 18))
        recent = list(reversed(match.get("history", []))) if match.get("status") == 1 else []
        for i in range(10):
            result.append(f"B,{i},{min(999,recent[i]['kills']) if i<len(recent) else 1000}")
        return result

    def run(self):
        import comtypes

        comtypes.CoInitialize()
        audio = DiscordAudio()
        started = None
        last_game_seen = 0
        self.discord.start()
        self.matches.start()
        self.bot.start()
        try:
            while not self.stop_event.is_set():
                try:
                    epoch, seq, action = self.commands.get_nowait()
                except queue.Empty:
                    action = None
                if action is not None:
                    okay = 0
                    try:
                        if epoch != self.epoch:
                            continue
                        if self.dry_run:
                            message = f"Deneme: oyun komutu {action}"
                        elif action == 0:
                            if (
                                self.settings().get("discord_mode", "bot") == "rpc"
                                and self.discord.latest["status"] == 1
                            ):
                                self.discord.toggle_mic()
                            elif self.settings()["mic_keys"]:
                                send_keys(
                                    self.settings()["mic_keys"].upper().replace(" ", "").split("+")
                                )
                            else:
                                raise ValueError(
                                    "Mikrofon için Discord bağlantısı veya eşleşen kısayol gerekli."
                                )
                            message = "Discord mikrofon komutu gönderildi."
                        elif action == 5:
                            count = len(self.snapshot()["discord"]["members"])
                            self.team_offset = (
                                (self.team_offset + 4) if self.team_offset + 4 < count else 0
                            )
                            message = "Sonraki takım üyeleri"
                        elif action == 6:
                            self.matches.wake.set()
                            message = "Maç özeti yenilemesi istendi."
                        else:
                            message = audio.command(action)
                        okay = 1
                    except Exception as exc:
                        message = (
                            str(exc)
                            if isinstance(exc, ValueError)
                            else f"Oyun komutu başarısız ({type(exc).__name__})"
                        )
                    self.emit("log", message)
                    if seq and epoch == self.epoch:
                        with self.lock:
                            self.seen[seq] = okay
                        try:
                            self.replies.put_nowait((seq, okay))
                        except queue.Full:
                            pass
                perf = self.performance.snapshot()
                now = time.monotonic()
                active = perf["name"].lower() in ("tslgame.exe", "pubg.exe")
                if active:
                    if started is None:
                        started = now
                    last_game_seen = now
                # Alt-tab preserves the session for five minutes; closing the companion resets it.
                if started is not None and now - last_game_seen > 300:
                    started = None
                try:
                    volume, muted = audio.sample()
                except Exception:
                    volume, muted = None, None
                value = {
                    "volume": volume,
                    "muted": muted,
                    "focus": audio.focus,
                    "active": active,
                    "minutes": int((now - started) / 60) if started is not None else 0,
                    "frametime": perf.get("frametime"),
                    "low": perf.get("low"),
                    "time": now,
                }
                with self.lock:
                    self.latest = value
                self.emit("game", self.snapshot())
                self.stop_event.wait(0.25)
        finally:
            try:
                if audio.focus:
                    audio.restore()
            except Exception:
                self.emit(
                    "log",
                    "Discord ses seviyesi geri yüklenemedi; Windows ses karıştırıcısını kontrol edin.",
                )
            self.discord.close()
            self.matches.close()
            self.bot.close()
            self.bot.join(timeout=4)
            comtypes.CoUninitialize()

    def close(self):
        self.stop_event.set()
        self.discord.close()
        self.matches.close()
        self.bot.close()
