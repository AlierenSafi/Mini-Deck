"""Firmware recovery UI. The helper verifies the bundled image before any erase."""

import os
from firmware_package import validate
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

ROOT = Path(__file__).resolve().parents[1]
BG, CARD, TEXT, MUTED, ACCENT = "#101522", "#1b2435", "#edf3fa", "#94a4bc", "#35d4b3"


class Programmer(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.running = False
        self.events = queue.Queue()
        self.port = app.port.get().strip()
        self.title("Mini Deck | Karta yazılım yükle")
        self.geometry("690x510")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.transient(app.root)
        app.disconnect()
        tk.Label(
            self, text="Karta yazılım yükle", bg=BG, fg=TEXT, font=("Segoe UI", 20, "bold")
        ).pack(anchor="w", padx=24, pady=(20, 10))
        instructions = (
            "1. Kartı USB-COM girişinden bağla. USB gücünü kesme.\n"
            "2. ISP tuşuna basılı tut; RESET’e basıp bırak; ardından ISP’yi bırak.\n"
            "3. Aşağıdaki düğmeyle yüklemeyi başlat.\n\n"
            "Uygulamayla gelen Mini Deck yazılımı yüklenecek. Kayıtlı dokunmatik\n"
            "ayarı korunur; silinmiş kart yazılımı da bu yöntemle geri yüklenebilir."
        )
        tk.Label(
            self, text=instructions, justify="left", bg=BG, fg=MUTED, font=("Segoe UI", 10)
        ).pack(anchor="w", padx=24)
        try:
            package = validate()
            package_label = f"Güncel paket: v{package['version']} · SHA256 {package['sha256'][:12]}"
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            package_label = str(exc)
        tk.Label(self, text=package_label, bg=BG, fg=ACCENT, wraplength=635).pack(
            anchor="w", padx=24, pady=4
        )
        self.state = tk.StringVar(
            value=f'Hedef: {self.port or "COM portu seçilmedi"} · fiziksel tuş adımı bekleniyor'
        )
        tk.Label(
            self,
            textvariable=self.state,
            wraplength=635,
            bg=BG,
            fg=ACCENT,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=24, pady=12)
        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=24)
        self.log = tk.Text(
            self, height=7, bg=CARD, fg=MUTED, relief="flat", font=("Consolas", 9), state="disabled"
        )
        self.log.pack(fill="both", expand=True, padx=24, pady=12)
        self.start_button = tk.Button(
            self,
            text="Yüklemeyi başlat",
            command=self.start,
            bg=ACCENT,
            fg=BG,
            relief="flat",
            font=("Segoe UI", 11, "bold"),
            padx=20,
            pady=10,
        )
        self.start_button.pack(pady=(0, 18))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(60, self.pump)

    def start(self):
        if self.running:
            return
        if not self.port:
            messagebox.showerror(
                "COM portu", "Ana pencereden kartın COM portunu seçin.", parent=self
            )
            return
        if self.app.worker and self.app.worker.is_alive():
            self.state.set("Seri bağlantı kapatılıyor; birazdan tekrar başlatabilirsin.")
            return
        if self.app.args.preview or self.app.args.dry_run:
            self.state.set("Deneme/önizleme modunda karta yazma kapalı. Normal uygulamayı aç.")
            return
        self.running = True
        self.app.programming = True
        self.start_button.configure(state="disabled")
        self.state.set("Bağlanılıyor ve firmware paketi doğrulanıyor…")
        threading.Thread(target=self.upload, daemon=True, name="deck-programmer").start()

    def upload(self):
        try:
            command = [
                str(Path(sys.executable).with_name("python.exe")),
                "-u",
                str(ROOT / "tools/upgrade_deck.py"),
                "--port",
                self.port,
            ]
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            for line in process.stdout:
                self.events.put(("log", line.rstrip()))
            code = process.wait()
            self.events.put(("done", code == 0))
        except OSError as exc:
            self.events.put(("log", str(exc)))
            self.events.put(("done", False))

    def pump(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log.configure(state="normal")
                self.log.insert("end", str(value) + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
                match = re.search(r"Written and compared: (\d+)/(\d+)", value)
                if match:
                    self.progress["value"] = int(match[1]) * 90 / int(match[2])
                    self.state.set("Yazılım karta yazılıyor ve geri okunuyor…")
                elif "calibration" in value.lower():
                    self.state.set("Dokunmatik kalibrasyon kaydı işleniyor…")
                elif "CRC VERIFIED" in value:
                    self.progress["value"] = 100
            else:
                self.running = False
                self.app.programming = False
                self.start_button.configure(state="normal", text="Yeniden yükle")
                if value:
                    self.state.set("Yükleme ve tam imaj doğrulaması başarılı. Kart bağlanıyor.")
                    self.app.append_log("Firmware yüklendi ve CRC doğrulandı.")
                    self.app.connect()
                else:
                    self.state.set(
                        "Yükleme tamamlanamadı. Günlüğü kontrol et; ISP/RESET adımından sonra yeniden deneyebilirsin."
                    )
        if self.winfo_exists():
            self.after(60, self.pump)

    def close(self):
        if self.running:
            messagebox.showinfo(
                "Yükleme sürüyor",
                "Kart yazılırken bu pencere açık kalmalı. Tamamlanmasını bekleyin.",
                parent=self,
            )
            return
        self.app.programmer = None
        self.destroy()
