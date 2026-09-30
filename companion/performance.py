"""Read-only NVIDIA utilization and foreground application's presented-frame rate.

PresentMon is a signed, hash-pinned console executable. No CSV capture is saved:
only one second of per-swap-chain intervals is retained in bounded memory.
"""

from collections import OrderedDict, deque
import csv
import ctypes as C
from ctypes import wintypes as W
import hashlib
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

import psutil
import winreg
from weather_service import Weather

PRESENTMON = Path(__file__).resolve().parents[1] / "tools/presentmon/PresentMon.exe"
PRESENTMON_SHA256 = "b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af"


class NvidiaGPU:
    def __init__(self):
        self.lib = None
        if os.name != "nt":
            return
        try:
            lib = C.WinDLL(
                str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/nvml.dll")
            )
            lib.nvmlInit_v2.argtypes = []
            lib.nvmlInit_v2.restype = C.c_int
            lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [C.c_uint, C.POINTER(C.c_void_p)]
            lib.nvmlDeviceGetHandleByIndex_v2.restype = C.c_int
            lib.nvmlDeviceGetUtilizationRates.argtypes = [C.c_void_p, C.c_void_p]
            lib.nvmlDeviceGetUtilizationRates.restype = C.c_int
            lib.nvmlShutdown.argtypes = []
            lib.nvmlShutdown.restype = C.c_int
            if lib.nvmlInit_v2() != 0:
                return
            self.handle = C.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, C.byref(self.handle)) != 0:
                lib.nvmlShutdown()
                return
            self.lib = lib
        except (OSError, AttributeError):
            pass

    def sample(self):
        if self.lib is None:
            return None
        values = (C.c_uint * 2)()
        if self.lib.nvmlDeviceGetUtilizationRates(self.handle, C.byref(values)) != 0:
            return None
        return min(100, int(values[0]))

    def details(self):
        result = dict(
            temp=None,
            fan=None,
            power=None,
            clock=None,
            vram_used=None,
            vram_total=None,
            model="GPU",
        )
        if not self.lib:
            return result
        for key, name, args in [
            ("temp", "nvmlDeviceGetTemperature", [0]),
            ("fan", "nvmlDeviceGetFanSpeed", []),
            ("power", "nvmlDeviceGetPowerUsage", []),
            ("clock", "nvmlDeviceGetClockInfo", [0]),
        ]:
            try:
                f = getattr(self.lib, name)
                f.argtypes = [C.c_void_p] + [C.c_uint] * len(args) + [C.c_void_p]
                f.restype = C.c_int
                value = C.c_uint()
                if f(self.handle, *args, C.byref(value)) == 0:
                    result[key] = value.value
            except AttributeError:
                pass
        try:
            name = C.create_string_buffer(96)
            f = self.lib.nvmlDeviceGetName
            f.argtypes = [C.c_void_p, C.c_void_p, C.c_uint]
            f.restype = C.c_int
            if f(self.handle, name, 96) == 0:
                result["model"] = (
                    name.value.decode("utf-8", errors="replace")
                    .replace("NVIDIA GeForce ", "")
                    .replace("NVIDIA ", "")
                )

            class Memory(C.Structure):
                _fields_ = [
                    ("total", C.c_ulonglong),
                    ("free", C.c_ulonglong),
                    ("used", C.c_ulonglong),
                ]

            m = Memory()
            f = self.lib.nvmlDeviceGetMemoryInfo
            f.argtypes = [C.c_void_p, C.c_void_p]
            f.restype = C.c_int
            if f(self.handle, C.byref(m)) == 0:
                result.update(vram_used=m.used, vram_total=m.total)
        except AttributeError:
            pass
        return result

    def close(self):
        if self.lib is not None:
            self.lib.nvmlShutdown()
            self.lib = None


class FrameRates:
    def __init__(self):
        self.chains = OrderedDict()
        self.lock = threading.Lock()

    def add(self, row, now=None):
        now = time.monotonic() if now is None else now
        try:
            pid = int(row["ProcessID"])
            stamp = float(row["TimeInSeconds"])
            interval = float(row["msBetweenPresents"])
            if not (math.isfinite(stamp) and math.isfinite(interval) and 0 < interval <= 10000):
                return
            key = (pid, row["SwapChainAddress"])
        except (KeyError, TypeError, ValueError):
            return
        with self.lock:
            frames = self.chains.setdefault(key, deque(maxlen=2000))
            self.chains.move_to_end(key)
            if frames and stamp < frames[-1][0]:
                frames.clear()
            frames.append((stamp, interval, now))
            while frames and frames[0][0] < stamp - 1:
                frames.popleft()
            while len(self.chains) > 128:
                self.chains.popitem(last=False)

    def sample(self, pid, now=None):
        now = time.monotonic() if now is None else now
        pids = {pid} if isinstance(pid, int) else set(pid)
        with self.lock:
            candidates = [
                frames
                for (process, _), frames in self.chains.items()
                if process in pids and frames and now - frames[-1][2] < 2
            ]
            if not candidates:
                return None
            frames = max(candidates, key=len)
            return min(9999, round(1000 * len(frames) / sum(f[1] for f in frames)))

    def details(self, pid, now=None):
        now = time.monotonic() if now is None else now
        pids = {pid} if isinstance(pid, int) else set(pid)
        with self.lock:
            candidates = [
                list(frames)
                for (process, _), frames in self.chains.items()
                if process in pids and frames and now - frames[-1][2] < 2
            ]
        if not candidates:
            return None, None
        intervals = sorted((f[1] for f in max(candidates, key=len)), reverse=True)
        count = max(1, math.ceil(len(intervals) * 0.01))
        return sum(intervals) / len(intervals), min(
            9999, round(1000 * count / sum(intervals[:count]))
        )


def foreground_process():
    if os.name != "nt":
        return 0, "Uygulama yok"
    user = C.WinDLL("user32")
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = W.HWND
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    user.GetWindowThreadProcessId.restype = W.DWORD
    pid = W.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), C.byref(pid))
    try:
        return pid.value, psutil.Process(pid.value).name()
    except (psutil.Error, ValueError):
        return 0, "Uygulama yok"


# Keep OS sampling and PresentMon capture away from the Tk event loop.
class PerformanceMonitor(threading.Thread):
    def __init__(self, emit):
        super().__init__(daemon=True, name="deck-performance")
        self.emit = emit
        self.stop_event = threading.Event()
        self.frames = FrameRates()
        self.lock = threading.Lock()
        self.latest = {
            "gpu": None,
            "fps": None,
            "pid": 0,
            "name": "",
            "status": "Hazırlanıyor",
            "time": 0,
        }
        self.weather = Weather()
        self.process = None
        self.reader = None
        self.error = ""
        self.session = "MiniDeck-" + uuid.uuid4().hex

    def read_frames(self):
        try:
            # PresentMon emits a conventional CSV header followed by individual frames.
            for row in csv.DictReader(self.process.stdout):
                self.frames.add(row)
        except (OSError, ValueError, csv.Error):
            self.error = "FPS akışı okunamadı"

    def start_capture(self):
        try:
            if hashlib.sha256(PRESENTMON.read_bytes()).hexdigest() != PRESENTMON_SHA256:
                self.error = "FPS aracı bütünlük kontrolünü geçemedi"
                return
            self.process = subprocess.Popen(
                [
                    str(PRESENTMON),
                    "--output_stdout",
                    "--no_console_stats",
                    "--v1_metrics",
                    "--no_track_gpu",
                    "--no_track_input",
                    "--no_track_display",
                    "--session_name",
                    self.session,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.reader = threading.Thread(target=self.read_frames, daemon=True, name="deck-fps")
            self.reader.start()
        except OSError:
            self.error = "FPS ölçüm aracı açılamadı"

    def snapshot(self):
        with self.lock:
            result = dict(self.latest)
        if time.monotonic() - result["time"] > 2:
            result["gpu"] = result["fps"] = result["frametime"] = result["low"] = None
            result["sensors"] = {}
            result["weather"] = (255, 255, 1)
        return result

    def close(self):
        self.stop_event.set()
        self.weather.close()

    def run(self):
        gpu = NvidiaGPU()
        self.weather.start()
        cpu = "CPU"
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                cpu = (
                    winreg.QueryValueEx(key, "ProcessorNameString")[0]
                    .strip()
                    .replace("AMD ", "")
                    .replace("Intel(R) ", "")
                    .replace(" Core(TM)", " Core")
                )
                cpu = cpu.split(" 6-Core")[0].split(" @")[0]
        except OSError:
            pass
        sensors = {}
        sensor_due = 0
        try:
            self.start_capture()
            while not self.stop_event.is_set():
                pid, name = foreground_process()
                fps = self.frames.sample(pid)
                frametime, low = self.frames.details(pid)
                if fps is None and pid:
                    # Browsers render in a child GPU process rather than the window PID.
                    try:
                        family = [p.pid for p in psutil.Process(pid).children(recursive=True)]
                        fps = self.frames.sample(family)
                        frametime, low = self.frames.details(family)
                    except psutil.Error:
                        pass
                if self.process and self.process.poll() is not None:
                    fps = None
                    self.error = "FPS kaynağı durdu; ETW erişimini kontrol edin"
                if time.monotonic() >= sensor_due:
                    sensors = gpu.details()
                    ram = psutil.virtual_memory()
                    sensors.update(cpu_model=cpu, ram_used=ram.used, ram_total=ram.total)
                    sensor_due = time.monotonic() + 1
                result = {
                    "sensors": sensors,
                    "weather": self.weather.snapshot(),
                    "gpu": gpu.sample(),
                    "fps": fps,
                    "pid": pid,
                    "name": name,
                    "status": self.error
                    or ("Canlı FPS" if fps is not None else "Bu uygulamadan kare verisi alınmıyor"),
                    "time": time.monotonic(),
                    "frametime": frametime,
                    "low": low,
                }
                with self.lock:
                    self.latest = result
                self.emit("performance", result)
                self.stop_event.wait(0.25)
        finally:
            gpu.close()
            self.weather.close()
            if self.process:
                if self.process.poll() is None:
                    try:
                        subprocess.run(
                            [
                                str(PRESENTMON),
                                "--session_name",
                                self.session,
                                "--terminate_existing_session",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        )
                        self.process.wait(timeout=3)
                    except (OSError, subprocess.TimeoutExpired):
                        self.process.kill()
                        self.process.wait()
                if self.reader:
                    self.reader.join(timeout=2)
                self.process.stdout.close()
