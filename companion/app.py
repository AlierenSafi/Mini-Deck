"""Mini Deck desktop companion. Run with --dry-run to suppress PC actions."""

import argparse
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from actions import Actions
from icons import AssetWorker
from editor import Editor
from programmer import Programmer
from bridge import Bridge, Sampler, detect_port, ports
from performance import PerformanceMonitor
from game import GameController
from game_panel import GamePanel
from desktop import Desktop
from tray import Tray

ROOT = Path(__file__).resolve().parent
BG, CARD, TEXT, MUTED, ACCENT = "#101522", "#1b2435", "#edf3fa", "#94a4bc", "#35d4b3"


class App(Desktop):
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.actions = Actions(args.config, args.dry_run)
        self.messages = queue.Queue(maxsize=128)
        self.worker = None
        self.programmer = None
        self.programming = False
        self.exiting = False
        self.tray_events = queue.Queue()
        self.stop_event = threading.Event()
        root.title("Mini Deck | Kontrol merkezi" + (" | Önizleme" if args.preview else ""))
        root.iconbitmap(str(ROOT / "mini-deck.ico"))
        self.build_shell()
        self.append_log(
            "Deneme modu: bilgisayar komutları uygulanmaz."
            if args.dry_run
            else "Hazır. Bir slot seçerek düzenleyin; sürükleyerek yerini değiştirin."
        )
        self.layout = None
        self.asset_stop = threading.Event()
        self.asset_worker = AssetWorker(self.actions, self.emit, self.asset_stop)
        self.asset_worker.start()
        self.performance = PerformanceMonitor(self.emit)
        self.performance.start()
        self.game = GameController(self.performance, self.emit, args.dry_run)
        self.game.start()
        self.tray = Tray(ROOT / "mini-deck.ico", self.tray_events)
        self.tray.start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(50, self.pump)
        if args.preview:
            sample = Sampler()

            def preview_tick():
                self.show_metrics(sample.sample())
                self.root.after(250, preview_tick)

            self.state.set("Önizleme / bu bilgisayarın canlı verileri / seri port açılmadı")
            self.connect_button.configure(state="disabled")
            root.after(250, preview_tick)
        elif self.port.get():
            root.after(200, self.connect)

    def emit(self, kind, value):
        try:
            self.messages.put((kind, value), timeout=0.5)
        except queue.Full:
            pass

    def save_items(self, items):
        self.actions.replace(items)
        self.asset_worker.wake.set()
        self.sync_status.set("Kaydedildi · simgeler hazırlanıyor")
        self.append_log("Profil kaydedildi. Kart bağlantısı varsa otomatik aktarılacak.")

    def button(self, parent, text, command, bg=None, fg=None):
        bg = bg or CARD
        fg = fg or TEXT
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=ACCENT,
            activeforeground=BG,
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 10),
        )

    def refresh(self):
        self.port_box["values"] = [p.device for p in ports()]
        if not self.port.get():
            self.port.set(detect_port() or "")

    def show_programmer(self):
        if self.programmer and self.programmer.winfo_exists():
            self.programmer.lift()
            return
        self.programmer = Programmer(self)

    def connect(self):
        if self.programming:
            return
        if self.worker and self.worker.is_alive():
            self.append_log("Önce mevcut bağlantıyı durdurun.")
            return
        if not self.port.get().strip():
            messagebox.showinfo("Seri port", "Kartın COM portunu seçin.")
            return
        self.stop_event = threading.Event()
        self.worker = Bridge(
            self.port.get().strip(),
            self.actions,
            self.messages,
            self.stop_event,
            self.performance,
            self.game,
        )
        self.worker.layout = self.layout
        self.worker.start()

    def navigate(self, page, detail=0, bank=0):
        if not self.worker or not self.worker.is_alive():
            self.append_log("Kart ekranı değiştirilemedi: bağlantı yok.")
            return
        self.worker.navigate(page, detail, bank)

    def disconnect(self):
        self.stop_event.set()
        self.state.set("Bağlantı durduruluyor")
        for value in self.values:
            value.set("—")

    def run_action(self, index):
        try:
            self.append_log(self.actions.run(index))
        except (OSError, ValueError) as exc:
            self.append_log(f"Komut hatası: {exc}")

    def append_log(self, line):
        if hasattr(self, "toast"):
            self.toast.set(str(line)[:150])
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S  ") + str(line) + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 200:
            self.log.delete("1.0", "2.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def show_metrics(self, values):
        for var, value in zip(self.values[:2], (f"{values[0]}%", f"{values[1]}%")):
            var.set(value)

    def pump(self):
        while not self.tray_events.empty():
            action = self.tray_events.get_nowait()
            if not self.exiting:
                if action == "exit":
                    self.exit_app()
                else:
                    self.show_window()
                    if action == "error":
                        self.append_log("Sistem tepsisi başlatılamadı; pencere açık tutuldu.")
        for _ in range(128):
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "state":
                self.state.set(value)
                if "Mini Deck bağlı" not in value:
                    for var in self.values:
                        var.set("—")
            elif kind == "performance":
                self.values[2].set("—" if value["gpu"] is None else f"{value['gpu']}%")
                self.values[3].set("—" if value["fps"] is None else str(value["fps"]))
                self.performance_status.set(
                    f"FPS: {value['name']} · {value['status']} · Öndeki uygulama otomatik izlenir"
                )
            elif kind == "game":
                self.game_panel.update_state(value)
                self.update_home(value)
            elif kind in ("game_match", "game_discord"):
                pass
            elif kind == "metrics":
                self.show_metrics(value)
            elif kind == "diagnostics":
                if value[0]:
                    self.diagnostics.set(f"Bağlantıda {value[0]} alım hatası algılandı")
                elif not value[5]:
                    self.diagnostics.set(
                        "Dokunmatik ayarı yok: kartın iki tuşunu birlikte basılı tutun"
                    )
                else:
                    self.diagnostics.set(
                        "Dokunmatik hazır · KEY1: sayfa · KEY2: sonraki uygulama sayfası"
                    )
            elif kind == "sync":
                self.sync_status.set(value)
            elif kind == "layout":
                if value["revision"] == self.actions.revision:
                    self.layout = value
                    self.editor.update_layout(value)
                    self.update_quick()
                    if self.worker:
                        self.worker.layout = value
                    self.sync_status.set(
                        "Önizleme hazır"
                        if self.args.preview
                        else "Profil hazır · kartla eşitlenmesi bekleniyor"
                    )

            else:
                self.append_log(value)
        self.root.after(50, self.pump)

    def close(self):
        if self.exiting:
            return
        if self.ui_preferences["close_to_tray"] and not self.programming:
            if self.tray.ready.is_set():
                self.root.withdraw()
            else:
                messagebox.showinfo(
                    "Sistem tepsisi",
                    "Tepsi simgesi hazır değil. Pencere açık tutuldu; ayarlardan arka planda çalışma seçeneğini kapatarak çıkabilirsin.",
                    parent=self.root,
                )
            return
        self.exit_app()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def exit_app(self):
        if self.exiting:
            return
        self.show_window()
        if self.programming:
            messagebox.showinfo(
                "Yükleme sürüyor", "Kart yazılımı yüklenirken uygulama açık kalmalı."
            )
            return
        if not self.editor.confirm_discard():
            return
        self.exiting = True
        self.tray.stop()
        self.game.close()
        self.performance.close()
        self.asset_stop.set()
        self.stop_event.set()
        self.wait_close()

    def wait_close(self):
        if (
            (self.worker and self.worker.is_alive())
            or self.performance.is_alive()
            or self.game.is_alive()
        ):
            self.root.after(50, self.wait_close)
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Mini Deck Windows companion")
    parser.add_argument("--port", help="Örnek: COM7; belirtilmezse tek CP210x otomatik seçilir")
    parser.add_argument("--config", type=Path, default=ROOT / "actions.json")
    parser.add_argument(
        "--dry-run", action="store_true", help="Eylemleri uygulamak yerine günlüğe yaz"
    )
    parser.add_argument(
        "--preview", action="store_true", help="Seri port açmadan canlı PC verilerini göster"
    )
    args = parser.parse_args()
    root = tk.Tk()
    try:
        App(root, args)
    except (OSError, ValueError) as exc:
        messagebox.showerror("Mini Deck", str(exc))
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
