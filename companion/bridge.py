"""Serial bridge: 4 Hz telemetry, bounded framing, no action replay on reconnect."""

from collections import OrderedDict
import os
import queue
import threading
import time

import psutil
import serial
from serial.tools import list_ports

from protocol import Decoder, encode, parse_event
from sync import Sync
from monitor_wire import frames as monitor_frames


def ports():
    return list(list_ports.comports())


def detect_port():
    candidates = [p.device for p in ports() if p.vid == 0x10C4 and p.pid == 0xEA60]
    return candidates[0] if len(candidates) == 1 else None


class Sampler:
    def __init__(self):
        psutil.cpu_percent(None)  # First nonblocking sample is a baseline.
        self.network = psutil.net_io_counters()
        self.last = time.monotonic()
        self.disk = 0
        self.disk_due = 0

    def sample(self):
        now = time.monotonic()
        elapsed = max(now - self.last, 0.001)
        network = psutil.net_io_counters()
        down = max(0, network.bytes_recv - self.network.bytes_recv) / elapsed / 1024
        up = max(0, network.bytes_sent - self.network.bytes_sent) / elapsed / 1024
        self.network, self.last = network, now
        if now >= self.disk_due:
            try:
                self.disk = round(
                    psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").percent
                )
            except OSError:
                self.disk = 0
            self.disk_due = now + 5
        local = time.localtime()
        return (
            min(100, max(0, round(psutil.cpu_percent(None)))),
            min(100, max(0, round(psutil.virtual_memory().percent))),
            self.disk,
            min(999999, round(down)),
            min(999999, round(up)),
            local.tm_hour,
            local.tm_min,
        )


class EventHandler:
    def __init__(self, actions, emit):
        self.actions, self.emit = actions, emit
        self.seen = OrderedDict()

    def handle(self, body):
        event = parse_event(body)
        if event is None:
            return None
        seq, action, revision = event
        if seq not in self.seen:
            try:
                description = self.actions.run(action, revision)
                self.seen[seq] = 1
                self.emit("log", description)
            except (OSError, ValueError, KeyError, IndexError) as exc:
                self.seen[seq] = 0
                self.emit("log", f"Komut hatasi: {exc}")
            if len(self.seen) > 64:
                self.seen.popitem(last=False)
        return f"K,{seq},{self.seen[seq]}"


# Only this worker owns the serial connection; UI requests arrive through queues.
class Bridge(threading.Thread):
    def __init__(self, port, actions, messages, stop_event, performance=None, game=None):
        super().__init__(daemon=True, name="mini-deck-serial")
        self.port, self.actions, self.messages, self.stop_event = (
            port,
            actions,
            messages,
            stop_event,
        )
        self.layout = None
        self.performance = performance
        self.game = game
        self.navigation = queue.Queue(maxsize=8)

    def navigate(self, page, detail=0, bank=0):
        try:
            self.navigation.put_nowait((page, detail, bank))
        except queue.Full:
            self.emit("log", "Ekran komutu kuyruğu dolu")

    def emit(self, kind, value):
        try:
            self.messages.put_nowait((kind, value))
        except queue.Full:
            try:
                self.messages.get_nowait()
            except queue.Empty:
                pass
            try:
                self.messages.put_nowait((kind, value))
            except queue.Full:
                pass

    def serve(self, connection):
        decoder, handler, sampler = Decoder(), EventHandler(self.actions, self.emit), Sampler()
        ready = False
        sensor_index = 0
        version = 0
        nav_pending = None
        nav_sequence = 0
        game_text_index = 0
        report_index = 0
        next_sample = time.monotonic() + 0.25
        next_query = time.monotonic() + 0.5
        last_board = time.monotonic()
        sync = None
        synced_revision = 0
        previous_layout = None
        retry_after = 0
        last_progress = -1
        sync_started = 0
        self.emit("state", f"{self.port} açık / kart bekleniyor")
        while not self.stop_event.is_set():
            data = connection.read(min(max(connection.in_waiting, 1), 512))
            for body in decoder.feed(data):
                now = time.monotonic()
                if body in ("R,3", "R,4", "R,5", "R,6", "R,7", "R,8", "R,9", "R,10"):
                    version = int(body.split(",")[1])
                    handler.seen.clear()
                    sync = None
                    synced_revision = 0
                    previous_layout = None
                    if self.game:
                        self.game.reset_events()
                    ready = True
                    last_board = now
                    self.emit("state", f"{self.port} / Mini Deck bağlı")
                elif body in ("R,1", "R,2"):
                    ready = False
                    sync = None
                    handler.seen.clear()
                    self.emit("state", "Kartta eski sürüm var; v3 firmware yükleyin.")
                elif body.startswith("D,"):
                    fields = body.split(",")
                    if (
                        len(fields) == 7
                        and all(p.isascii() and p.isdecimal() and len(p) <= 10 for p in fields[1:])
                        and fields[3] in ("3", "4", "5", "6", "7", "8", "9", "10")
                    ):
                        version = int(fields[3])
                        ready = True
                        last_board = now
                        self.emit("diagnostics", tuple(map(int, fields[1:])))
                        self.emit("state", f"{self.port} / Mini Deck bağlı")
                    elif len(fields) in (3, 7):
                        ready = False
                        sync = None
                        handler.seen.clear()
                        self.emit("state", "Kartta eski sürüm var; v3 firmware yükleyin.")
                elif body.startswith("Y,") and sync:
                    if sync.acknowledge(body):
                        last_board = now
                        progress = sync.index * 100 // len(sync.jobs)
                        if progress != last_progress:
                            self.emit("sync", f"Slotlar karta aktarılıyor: %{progress}")
                            last_progress = progress
                        if sync.done:
                            synced_revision = sync.revision
                            previous_layout = sync.layout
                            sync = None
                            self.emit("sync", f"Kartla eşitlendi · {now-sync_started:.1f} sn")
                elif ready and body.startswith("H,"):
                    if nav_pending and body == f"H,{nav_pending[0]},1":
                        self.emit("log", "Kart ekranı değiştirildi.")
                        nav_pending = None
                elif ready and version >= 4 and body.startswith("J,") and self.game:
                    parts = body.split(",")
                    if len(parts) == 3 and all(
                        p.isascii() and p.isdecimal() and len(p) <= 10 for p in parts[1:]
                    ):
                        seq, action = map(int, parts[1:])
                        if 0 < seq <= 0xFFFFFFFF and not self.game.submit(action, seq):
                            connection.write(encode(f"K,{seq},0"))
                elif ready:
                    reply = handler.handle(body)
                    if reply:
                        last_board = now
                        connection.write(encode(reply))
            now = time.monotonic()
            if self.game:
                for _ in range(8):
                    try:
                        seq, result = self.game.replies.get_nowait()
                    except queue.Empty:
                        break
                    if ready:
                        connection.write(encode(f"K,{seq},{result}"))
            if nav_pending and now >= nav_pending[2]:
                seq, payload, due, attempt = nav_pending
                if attempt >= 3 or not ready:
                    self.emit("log", "Kart ekran komutunu onaylamadı.")
                    nav_pending = None
                else:
                    connection.write(encode(payload))
                    nav_pending = (seq, payload, now + 0.5, attempt + 1)
            if nav_pending is None:
                try:
                    page, detail, bank = self.navigation.get_nowait()
                except queue.Empty:
                    pass
                else:
                    if not ready or version < 4:
                        self.emit("log", "Ekran geçişi için bağlı v4 kart gerekli.")
                    elif page == 3 and detail >= 4 and version < 5:
                        self.emit("log", "PUBG raporları için v5 firmware yükleyin.")
                    else:
                        nav_sequence += 1
                        payload = f"W,{nav_sequence},{page},{detail},{bank}"
                        connection.write(encode(payload))
                        nav_pending = (nav_sequence, payload, now + 0.5, 1)
            if ready and now - last_board > 3:
                ready = False
                sync = None
                synced_revision = 0
                previous_layout = None
                self.emit("state", "Kart yanıt vermiyor / yeniden bağlantı bekleniyor")
            if ready and now >= next_sample:
                values = sampler.sample()
                if self.performance:
                    perf = self.performance.snapshot()
                    gpu = perf["gpu"] if perf["gpu"] is not None else 101
                    fps = perf["fps"] if perf["fps"] is not None else 10000
                    connection.write(encode(f'T,{gpu},{fps},{perf["pid"]}'))
                    if version >= 9:
                        extra = monitor_frames(perf)
                        connection.write(encode(extra[sensor_index % len(extra)]))
                        sensor_index += 1
                if self.game and version >= 4:
                    frames = self.game.frames(version=version)
                    connection.write(encode(frames[0]))
                    connection.write(encode(frames[1]))
                    connection.write(encode(frames[2 + game_text_index]))
                    game_text_index = (game_text_index + 1) % 6
                    if version >= 5 and len(frames) > 8:
                        for _ in range(4):
                            connection.write(encode(frames[8 + report_index % (len(frames) - 8)]))
                            report_index += 1
                connection.write(encode("M," + ",".join(map(str, values))))
                self.emit("metrics", values)
                next_sample = now + 0.25
            if now >= next_query:
                connection.write(encode("Q"))
                next_query = now + 1
            layout = self.layout
            if ready and layout and layout["revision"] == self.actions.revision:
                if (
                    sync is None and synced_revision != layout["revision"] and now >= retry_after
                ) or (sync and sync.revision != layout["revision"]):
                    sync = Sync(
                        layout, previous=previous_layout if sync is None else None, version=version
                    )
                    last_progress = -1
                    sync_started = now
                if sync:
                    packet = sync.next_packet(now)
                    if packet:
                        connection.write(packet)
                    if sync.failed:
                        self.emit("sync", "Aktarım yeniden denenecek")
                        sync = None
                        previous_layout = None
                        retry_after = now + 2

    def run(self):
        while not self.stop_event.is_set():
            connection = None
            try:
                connection = serial.Serial()
                connection.port = self.port
                connection.baudrate = 115200
                connection.timeout = 0.005
                connection.write_timeout = 0.2
                connection.dtr = False
                connection.rts = False
                connection.open()
                connection.reset_input_buffer()
                self.serve(connection)
            except (serial.SerialException, OSError) as exc:
                self.emit("state", f"Baglanti bekleniyor: {self.port}")
                self.emit("log", str(exc))
            finally:
                if connection and connection.is_open:
                    connection.close()
            self.stop_event.wait(1)
        self.emit("state", "Baglanti durduruldu")
