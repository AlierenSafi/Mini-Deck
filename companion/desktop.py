"""Compact desktop shell; transport, profiles and game services remain independent."""

from collections import deque
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from editor import Editor
from game_panel import GamePanel
from bridge import detect_port, ports
from firmware_package import validate

THEMES = {
    "Grafit & Mint": dict(
        BG="#171c20", CARD="#262e33", TEXT="#e4e9e6", MUTED="#a1afac", ACCENT="#80c9b0"
    ),
    "Sıcak Taş": dict(
        BG="#ddd8ce", CARD="#ece8df", TEXT="#303734", MUTED="#626963", ACCENT="#496f61"
    ),
}
LEGACY = dict(BG="#101522", CARD="#1b2435", TEXT="#edf3fa", MUTED="#94a4bc", ACCENT="#35d4b3")


def load_preferences(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {
            "theme": data.get("theme") if data.get("theme") in THEMES else "Grafit & Mint",
            "close_to_tray": (
                data.get("close_to_tray") if type(data.get("close_to_tray")) is bool else True
            ),
        }
    except (OSError, ValueError, AttributeError):
        return {"theme": "Grafit & Mint", "close_to_tray": True}


def save_preferences(path, data):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


class Desktop:
    def build_shell(self):
        self.ui_path = self.args.config.with_name("desktop-settings.json")
        self.ui_preferences = load_preferences(self.ui_path)
        self.palette = THEMES[self.ui_preferences["theme"]]
        self.graphs = []
        self.history = [deque(maxlen=60) for _ in range(4)]
        self.current_page = ""
        self.nav_buttons = {}
        self.pages = {}
        self.quick_buttons = []
        self.root.geometry("1180x780")
        self.root.minsize(1080, 720)
        self.root.configure(bg=LEGACY["BG"])
        self.root.option_add("*Font", ("Segoe UI", 10))
        self.state = tk.StringVar(value="Kart bağlantısı bekleniyor")
        self.sync_status = tk.StringVar(value="Simgeler hazırlanıyor")
        self.performance_status = tk.StringVar(value="Performans kaynağı hazırlanıyor")
        self.diagnostics = tk.StringVar(value="Kart durum bilgisi bekleniyor")
        self.values = [tk.StringVar(value="—") for _ in range(4)]
        self.port = tk.StringVar(value=self.args.port or detect_port() or "")
        self.sidebar = tk.Frame(self.root, bg=LEGACY["CARD"], width=182, padx=14, pady=18)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.label(self.sidebar, "A·", 28, bold=True, card=True).pack(anchor="w")
        self.label(self.sidebar, "ALIEREN", 16, bold=True, card=True).pack(anchor="w")
        self.label(self.sidebar, "MINI DECK", 9, muted=True, card=True).pack(
            anchor="w", pady=(0, 26)
        )
        for key, title in [
            ("home", "⌂   Kontrol merkezi"),
            ("slots", "▦   Slotlar"),
            ("monitor", "▥   İzleme"),
            ("game", "◈   PUBG + Discord"),
            ("settings", "⚙   Ayarlar"),
        ]:
            b = self.button(self.sidebar, title, lambda k=key: self.show_page(k))
            b.configure(anchor="w", pady=12)
            b.pack(fill="x", pady=3)
            self.nav_buttons[key] = b
        self.button(self.sidebar, "Karta yazılım yükle", self.show_programmer).pack(
            side="bottom", fill="x", pady=(8, 0)
        )
        self.button(self.sidebar, "USB / Kart", lambda: self.show_page("device")).pack(
            side="bottom", fill="x"
        )
        self.main = tk.Frame(self.root, bg=LEGACY["BG"], padx=20, pady=16)
        self.main.pack(side="left", fill="both", expand=True)
        top = tk.Frame(self.main, bg=LEGACY["BG"])
        top.pack(fill="x", pady=(0, 12))
        self.page_title = tk.StringVar(value="Kontrol merkezi")
        self.label(top, self.page_title, 21, bold=True).pack(side="left")
        status = tk.Frame(top, bg=LEGACY["BG"])
        status.pack(side="right")
        self.label(status, self.state, 9, muted=True).pack(anchor="e")
        self.label(status, self.sync_status, 9, muted=True).pack(anchor="e")
        # Pack the footer before the expanding body: controls remain visible on resize.
        bottom = tk.Frame(self.main, bg=LEGACY["BG"])
        bottom.pack(side="bottom", fill="x")
        self.toast = tk.StringVar(value="Bir slot seçerek düzenleyebilirsin.")
        self.label(bottom, self.toast, 9, muted=True, wraplength=790).pack(anchor="w", pady=(6, 0))
        self.log = tk.Text(
            bottom,
            height=4,
            bg=LEGACY["CARD"],
            fg=LEGACY["MUTED"],
            relief="flat",
            state="disabled",
            font=("Consolas", 9),
        )
        self.log_visible = False
        remote = tk.Frame(bottom, bg=LEGACY["BG"])
        remote.pack(fill="x", pady=(10, 0))
        self.label(remote, "Kart ekranı", 9, muted=True).pack(side="left", padx=(0, 8))
        self.remote = tk.StringVar(value="Slot 1")
        ttk.Combobox(
            remote,
            textvariable=self.remote,
            values=["Medya", "Slot 1", "Slot 2", "Slot 3", "İzleme", "PUBG"],
            state="readonly",
            width=13,
        ).pack(side="left")
        self.button(remote, "Kartta göster", self.remote_show).pack(side="left", padx=8)
        self.button(remote, "Günlük ▾", self.toggle_log).pack(side="right")
        self.body = tk.Frame(self.main, bg=LEGACY["BG"])
        self.body.pack(fill="both", expand=True)
        for name in ("home", "slots", "monitor", "game", "settings", "device"):
            self.pages[name] = tk.Frame(self.body, bg=LEGACY["BG"])
        self.editor = Editor(self.pages["slots"], self)
        self.editor.pack(fill="both", expand=True)
        self.game_panel = GamePanel(self.pages["game"], self)
        self.game_panel.pack(fill="both", expand=True)
        self.build_home()
        self.build_monitor()
        self.build_settings()
        self.build_device()
        self.root.bind("<Map>", self.theme_mapped, add="+")
        self.apply_theme(self.ui_preferences["theme"], persist=False)
        self.show_page("home")
        self.root.after(500, self.graph_tick)

    def label(self, parent, text, size=10, bold=False, muted=False, card=False, **kw):
        return tk.Label(
            parent,
            **({"textvariable": text} if isinstance(text, tk.Variable) else {"text": text}),
            bg=LEGACY["CARD" if card else "BG"],
            fg=LEGACY["MUTED" if muted else "TEXT"],
            font=("Segoe UI", size, "bold" if bold else "normal"),
            anchor="w",
            justify="left",
            **kw,
        )

    def panel(self, parent):
        return tk.Frame(parent, bg=LEGACY["CARD"], padx=14, pady=12)

    def metric_cards(self, parent, big=False):
        row = tk.Frame(parent, bg=LEGACY["BG"])
        row.pack(fill="both" if big else "x", expand=big)
        for i, name in enumerate(("CPU", "RAM", "GPU", "FPS")):
            box = self.panel(row)
            box.grid(
                row=i // 2 if big else 0, column=i % 2 if big else i, sticky="nsew", padx=4, pady=4
            )
            row.columnconfigure(i % 2 if big else i, weight=1, uniform="metrics")
            row.rowconfigure(i // 2 if big else 0, weight=1)
            self.label(box, name, 10, muted=True, card=True).pack(anchor="w")
            self.label(box, self.values[i], 26 if big else 21, bold=True, card=True).pack(
                anchor="w"
            )
            canvas = tk.Canvas(
                box, height=110 if big else 26, bg=LEGACY["CARD"], highlightthickness=0
            )
            canvas.pack(fill="both", expand=True)
            self.graphs.append((canvas, i))

    def build_home(self):
        home = self.pages["home"]
        self.metric_cards(home)
        middle = tk.Frame(home, bg=LEGACY["BG"])
        middle.pack(fill="both", expand=True, pady=10)
        middle.columnconfigure(0, weight=1, uniform="home")
        middle.columnconfigure(1, weight=1, uniform="home")
        middle.rowconfigure(0, weight=1)
        discord = self.panel(middle)
        discord.grid(row=0, column=0, sticky="nsew", padx=(4, 6))
        self.label(discord, "Discord · Ses odası", 13, bold=True, card=True).pack(anchor="w")
        self.room = tk.StringVar(value="Discord bağlantısı bekleniyor")
        self.label(discord, self.room, 10, card=True, wraplength=365).pack(
            fill="both", expand=True, pady=10
        )
        controls = tk.Frame(discord, bg=LEGACY["CARD"])
        controls.pack(fill="x")
        self.mic = self.button(controls, "Mikrofon · —", lambda: self.game.submit(0))
        self.mic.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.sound = self.button(controls, "Discord sesi · —", lambda: self.game.submit(1))
        self.sound.pack(side="left", fill="x", expand=True)
        vol = tk.Frame(discord, bg=LEGACY["CARD"])
        vol.pack(fill="x", pady=(6, 0))
        self.button(vol, "Ses −", lambda: self.game.submit(2)).pack(side="left")
        self.volume = tk.StringVar(value="—")
        self.label(vol, self.volume, 10, card=True).pack(side="left", padx=12)
        self.button(vol, "Ses +", lambda: self.game.submit(3)).pack(side="left")
        match = self.panel(middle)
        match.grid(row=0, column=1, sticky="nsew", padx=(6, 4))
        self.label(match, "Son tamamlanan maç", 13, bold=True, card=True).pack(anchor="w")
        self.match_note = tk.StringVar(value="Maç sonrası veri · PUBG bağlantısı bekleniyor")
        self.label(match, self.match_note, 9, muted=True, card=True, wraplength=365).pack(
            anchor="w", pady=(4, 8)
        )
        self.match_table = ttk.Treeview(
            match,
            columns=("player", "kills", "assists", "damage"),
            show="headings",
            height=4,
            selectmode="none",
        )
        for col, title, w in [
            ("player", "Oyuncu", 130),
            ("kills", "Öldürme", 62),
            ("assists", "Asist", 48),
            ("damage", "Hasar", 62),
        ]:
            self.match_table.heading(col, text=title)
            self.match_table.column(
                col,
                width=w,
                minwidth=40,
                stretch=col == "player",
                anchor="w" if col == "player" else "center",
            )
        self.match_table.pack(fill="both", expand=True)
        self.button(match, "Tüm raporlar →", self.game_panel.show_reports).pack(
            anchor="e", pady=(6, 0)
        )
        quick = self.panel(home)
        quick.pack(fill="x", padx=4)
        head = tk.Frame(quick, bg=LEGACY["CARD"])
        head.pack(fill="x")
        self.label(head, "Hızlı erişim", 12, bold=True, card=True).pack(side="left")
        self.button(head, "Slotları düzenle →", lambda: self.show_page("slots")).pack(side="right")
        keys = tk.Frame(quick, bg=LEGACY["CARD"])
        keys.pack(fill="x", pady=(5, 0))
        for i in range(6):
            keys.columnconfigure(i, weight=1, uniform="quick")
            b = self.button(keys, "—", lambda n=i + 6: self.run_action(n))
            b.configure(wraplength=110, padx=3, pady=5, compound="top", font=("Segoe UI", 9))
            b.grid(row=0, column=i, sticky="nsew", padx=3)
            self.quick_buttons.append(b)

    def build_monitor(self):
        parent = self.pages["monitor"]
        self.label(parent, self.performance_status, 9, muted=True, wraplength=820).pack(
            anchor="w", pady=(0, 12)
        )
        self.metric_cards(parent, True)
        self.label(
            parent, "Son 30 saniye · FPS, öndeki oyun / uygulamadan alınır.", 9, muted=True
        ).pack(anchor="w", pady=10)

    def build_settings(self):
        parent = self.pages["settings"]
        box = self.panel(parent)
        box.pack(fill="x", pady=(0, 12))
        self.label(box, "Görünüm", 15, bold=True, card=True).pack(anchor="w")
        self.label(
            box, "Tema anında uygulanır ve sonraki açılış için saklanır.", 10, muted=True, card=True
        ).pack(anchor="w", pady=8)
        self.theme_var = tk.StringVar(value=self.ui_preferences["theme"])
        for name in THEMES:
            tk.Radiobutton(
                box,
                text=name,
                variable=self.theme_var,
                value=name,
                command=lambda: self.apply_theme(self.theme_var.get()),
                bg=LEGACY["CARD"],
                fg=LEGACY["TEXT"],
                selectcolor=LEGACY["BG"],
                activebackground=LEGACY["CARD"],
                padx=8,
                pady=10,
            ).pack(anchor="w")
        self.label(box, "PC teması kartın temasından bağımsızdır.", 9, muted=True, card=True).pack(
            anchor="w", pady=6
        )
        self.tray_var = tk.BooleanVar(value=self.ui_preferences["close_to_tray"])
        tk.Checkbutton(
            box,
            text="Kapatınca sistem tepsisinde çalışmaya devam et",
            variable=self.tray_var,
            command=self.save_tray_preference,
            bg=LEGACY["CARD"],
            fg=LEGACY["TEXT"],
            selectcolor=LEGACY["BG"],
            activebackground=LEGACY["CARD"],
        ).pack(anchor="w", pady=4)
        box = self.panel(parent)
        box.pack(fill="x", pady=(0, 12))
        self.label(box, "PUBG ve Discord", 14, bold=True, card=True).pack(anchor="w")
        self.label(
            box,
            "Hesap bağlantıları, mikrofon kısayolu ve otomatik oyun geçişi.",
            10,
            muted=True,
            card=True,
        ).pack(anchor="w", pady=8)
        self.button(box, "Bağlantı ayarlarını aç", self.game_panel.settings).pack(anchor="w")
        box = self.panel(parent)
        box.pack(fill="x")
        self.label(box, "Profil ve hava durumu", 14, bold=True, card=True).pack(anchor="w")
        row = tk.Frame(box, bg=LEGACY["CARD"])
        row.pack(fill="x", pady=8)
        self.button(row, "Dışa aktar", self.editor.export).pack(side="left", padx=(0, 8))
        self.button(row, "İçe aktar", self.editor.restore).pack(side="left")
        from weather_panel import show as weather_settings

        self.button(row, "Hava durumu konumu", lambda: weather_settings(self)).pack(side="right")

    def build_device(self):
        parent = self.pages["device"]
        box = self.panel(parent)
        box.pack(fill="x")
        self.label(box, "Kart bağlantısı", 15, bold=True, card=True).pack(anchor="w", pady=(0, 12))
        row = tk.Frame(box, bg=LEGACY["CARD"])
        row.pack(fill="x")
        self.port_box = ttk.Combobox(
            row, textvariable=self.port, values=[p.device for p in ports()], width=14
        )
        self.port_box.pack(side="left")
        self.button(row, "Yenile", self.refresh).pack(side="left", padx=8)
        self.connect_button = self.button(
            row, "Bağlan", self.connect, LEGACY["ACCENT"], LEGACY["BG"]
        )
        self.connect_button.pack(side="left")
        self.button(row, "Bağlantıyı kes", self.disconnect).pack(side="left", padx=8)
        self.label(box, self.state, 10, card=True).pack(anchor="w", pady=12)
        self.label(box, self.diagnostics, 10, muted=True, card=True, wraplength=800).pack(
            anchor="w"
        )
        box = self.panel(parent)
        box.pack(fill="x", pady=12)
        self.label(box, "Kart yazılımı", 15, bold=True, card=True).pack(anchor="w")
        try:
            info = validate()
            status = f"Güncel paket · v{info['version']} · {info['image_bytes']:,} bayt\nYüklemeden önce bütünlük ve kaynak kontrolü yapılır."
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            status = str(exc)
        self.label(box, status, 10, muted=True, card=True, wraplength=780).pack(anchor="w", pady=12)
        self.button(box, "Karta yazılım yükle", self.show_programmer).pack(anchor="w")

    def show_page(self, name):
        if self.current_page == "slots" and name != "slots" and not self.editor.confirm_discard():
            return
        for frame in self.pages.values():
            frame.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.current_page = name
        self.page_title.set(
            dict(
                home="Kontrol merkezi",
                slots="Slot düzenleyici",
                monitor="Canlı izleme",
                game="PUBG + Discord",
                settings="Ayarlar",
                device="USB / Kart",
            )[name]
        )
        for key, b in self.nav_buttons.items():
            b.configure(
                bg=self.palette["ACCENT" if key == name else "CARD"],
                fg=self.palette["BG" if key == name else "TEXT"],
            )

    def remote_show(self):
        choices = {
            "Medya": (0, 0, 0),
            "Slot 1": (1, 0, 0),
            "Slot 2": (1, 0, 1),
            "Slot 3": (1, 0, 2),
            "İzleme": (2, 4, 0),
            "PUBG": (3, 0, 0),
        }
        self.navigate(*choices[self.remote.get()])

    def toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log.pack(fill="x", pady=6)
        else:
            self.log.pack_forget()

    def update_home(self, value):
        d = value["discord"]
        m = value["match"]
        members = d.get("members", [])
        names = [
            p["name"]
            + " · Mikrofon "
            + ("kapalı" if p["mute"] else "açık")
            + " / Kulaklık "
            + ("kapalı" if p.get("deaf") else "açık")
            for p in members[:4]
        ]
        if len(members) > 4:
            names.append(f"+{len(members)-4} kişi · Oyun sayfasında")
        self.room.set("\n".join(names) or d["message"])
        self.mic.configure(
            text="Mikrofon · " + ("—" if d["mic"] is None else "Kapalı" if d["mic"] else "Açık")
        )
        self.sound.configure(
            text="Discord sesi · "
            + ("—" if value["volume"] is None else "Kapalı" if value["muted"] else "Açık")
        )
        self.volume.set("—" if value["volume"] is None else f"%{value['volume']}")
        s = m.get("summary") if m.get("status") == 1 else None
        self.match_note.set(
            "Maç sonrası veri · " + s["created"][:16].replace("T", " ") + " UTC"
            if s
            else m.get("message", "Veri bekleniyor")
        )
        rows = [
            (p["name"], p["kills"], p["assists"], p["damage"]) for p in (s or {}).get("team", [])
        ]
        if rows != getattr(self, "home_rows", None):
            for item in self.match_table.get_children():
                self.match_table.delete(item)
            for row in rows:
                self.match_table.insert("", "end", values=row)
            self.home_rows = rows

    def update_quick(self):
        for i, b in enumerate(self.quick_buttons):
            item = self.actions.items[i + 6]
            b.configure(
                text=item["name"],
                image=self.editor.photos.get(i + 6, ""),
                state="disabled" if item["type"] == "empty" else "normal",
            )

    def graph_tick(self):
        for i, var in enumerate(self.values):
            try:
                v = float(var.get().rstrip("%"))
            except ValueError:
                v = None
            self.history[i].append(v)
        for canvas, i in self.graphs:
            if not canvas.winfo_ismapped():
                continue
            canvas.delete("all")
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            samples = list(self.history[i])
            maximum = max([100 if i < 3 else 60] + [v for v in samples if v is not None])
            run = []
            for j, v in enumerate(samples):
                if v is None:
                    if len(run) >= 4:
                        canvas.create_line(*run, fill=self.palette["ACCENT"], width=2)
                    run = []
                else:
                    run.extend((4 + j * (w - 8) / 59, h - 4 - v / max(1, maximum) * (h - 8)))
            if len(run) >= 4:
                canvas.create_line(*run, fill=self.palette["ACCENT"], width=2)
        self.root.after(500, self.graph_tick)

    def theme_widget(self, widget):
        mapping = {
            value: role for palette in [LEGACY, *THEMES.values()] for role, value in palette.items()
        }
        mapping["#29394f"] = "ACCENT"
        for option in (
            "background",
            "foreground",
            "activebackground",
            "activeforeground",
            "insertbackground",
            "selectcolor",
            "disabledforeground",
            "highlightbackground",
        ):
            try:
                value = widget.cget(option)
                if value in mapping:
                    widget.configure(**{option: self.palette[mapping[value]]})
            except tk.TclError:
                pass

    def theme_mapped(self, event):
        self.theme_widget(event.widget)

    def save_tray_preference(self):
        updated = {**self.ui_preferences, "close_to_tray": self.tray_var.get()}
        try:
            save_preferences(self.ui_path, updated)
        except OSError as exc:
            self.tray_var.set(self.ui_preferences["close_to_tray"])
            messagebox.showerror("Ayar kaydedilemedi", str(exc), parent=self.root)
            return
        self.ui_preferences = updated
        self.append_log(
            "Kapatma düğmesi uygulamayı sistem tepsisine gizler."
            if updated["close_to_tray"]
            else "Kapatma düğmesi uygulamadan tamamen çıkar."
        )

    def apply_theme(self, name, persist=True):
        updated = {**self.ui_preferences, "theme": name}
        if persist:
            try:
                save_preferences(self.ui_path, updated)
            except OSError as exc:
                messagebox.showerror("Tema kaydedilemedi", str(exc), parent=self.root)
                return
        self.palette = THEMES[name]
        self.ui_preferences = updated
        for module in ("app", "__main__", "editor", "game_panel", "programmer"):
            if module in sys.modules:
                for key, val in self.palette.items():
                    setattr(sys.modules[module], key, val)

        def walk(w):
            self.theme_widget(w)
            for c in w.winfo_children():
                walk(c)

        walk(self.root)
        p = self.palette
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground=p["CARD"],
            background=p["CARD"],
            foreground=p["TEXT"],
            arrowcolor=p["TEXT"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", p["CARD"])],
            foreground=[("readonly", p["TEXT"])],
            selectbackground=[("readonly", p["CARD"])],
            selectforeground=[("readonly", p["TEXT"])],
        )
        style.configure(
            "Treeview",
            background=p["CARD"],
            fieldbackground=p["CARD"],
            foreground=p["TEXT"],
            rowheight=27,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading", background=p["BG"], foreground=p["MUTED"], relief="flat"
        )
        style.map(
            "Treeview", background=[("selected", p["ACCENT"])], foreground=[("selected", p["BG"])]
        )
        if self.current_page:
            for key, b in self.nav_buttons.items():
                b.configure(
                    bg=p["ACCENT" if key == self.current_page else "CARD"],
                    fg=p["BG" if key == self.current_page else "TEXT"],
                )
        if self.editor.layout:
            self.editor.update_layout(self.editor.layout)
            self.update_quick()
        if persist:
            self.append_log(f"{name} teması kaydedildi.")
