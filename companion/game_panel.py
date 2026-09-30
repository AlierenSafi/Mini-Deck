"""Desktop game controls and account setup. No credentials are displayed in logs."""

import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

BG, CARD, TEXT, MUTED, ACCENT = "#101522", "#1b2435", "#edf3fa", "#94a4bc", "#35d4b3"


class GamePanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG, padx=16, pady=12)
        self.app = app
        self.heading = tk.StringVar(value="PUBG + DISCORD")
        tk.Label(
            self, textvariable=self.heading, font=("Segoe UI", 20, "bold"), bg=BG, fg=TEXT
        ).pack(anchor="w")
        tk.Label(
            self, text="Ses kontrolü, takımın ve canlı performans tek yerde.", bg=BG, fg=MUTED
        ).pack(anchor="w", pady=(0, 10))
        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x")
        for name, page, detail in [
            ("Kartta PUBG", 3, 0),
            ("Takım", 3, 1),
            ("Son maç", 3, 2),
            ("İzleme", 2, 4),
        ]:
            app.button(nav, name, lambda p=page, d=detail: app.navigate(p, d)).pack(
                side="left", padx=(0, 6)
            )
        app.button(nav, "Bağlantı ayarları", self.settings).pack(side="right")
        reports = tk.Frame(self, bg=BG)
        reports.pack(fill="x", pady=(6, 0))
        for title, detail in [
            ("Takım sonuçları 1", 4),
            ("Takım sonuçları 2", 5),
            ("Bugün", 6),
            ("Son 10 maç", 7),
        ]:
            app.button(reports, title, lambda d=detail: app.navigate(3, d)).pack(
                side="left", padx=(0, 6)
            )
        app.button(reports, "PC raporları", self.show_reports).pack(side="right")
        self.report_window = None
        self.last_match = {}
        self.summary = tk.StringVar(value="Oyun verileri hazırlanıyor")
        tk.Label(self, textvariable=self.summary, font=("Segoe UI", 12), bg=BG, fg=ACCENT).pack(
            anchor="w", pady=12
        )
        grid = tk.Frame(self, bg=BG)
        grid.pack(fill="x")
        self.buttons = []
        for i, title in enumerate(
            ("Mikrofon", "Discord sesi", "Ses −", "Ses +", "Ayak Sesi", "Akıcılık grafiği")
        ):
            grid.columnconfigure(i % 3, weight=1)
            command = (lambda: app.navigate(3, 3)) if i == 5 else (lambda a=i: app.game.submit(a))
            button = app.button(grid, title, command)
            button.configure(font=("Segoe UI", 12, "bold"), pady=15)
            button.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            self.buttons.append(button)
        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="both", expand=True, pady=(12, 0))
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=1)
        self.team = tk.StringVar(value="Takım isimleri için Discord bağlantısı gerekli.")
        self.match = tk.StringVar(value="Son maç özeti için PUBG API ayarlarını girin.")
        for i, (title, var) in enumerate(
            (("SES ODASI", self.team), ("SON TAMAMLANAN MAÇ", self.match))
        ):
            box = tk.Frame(bottom, bg=CARD, padx=16, pady=12)
            box.grid(row=0, column=i, sticky="nsew", padx=4)
            tk.Label(box, text=title, bg=CARD, fg=ACCENT, font=("Segoe UI", 10, "bold")).pack(
                anchor="w"
            )
            tk.Label(
                box,
                textvariable=var,
                bg=CARD,
                fg=TEXT,
                justify="left",
                anchor="nw",
                wraplength=360,
                font=("Segoe UI", 10),
            ).pack(anchor="w", pady=8)

    def update_state(self, value):
        d = value["discord"]
        m = value["match"]
        f = self.app.performance.snapshot()
        fps = "—" if f["fps"] is None else str(f["fps"])
        ms = "—" if value["frametime"] is None else f"{value['frametime']:.1f}"
        low = "—" if value["low"] is None else str(value["low"])
        self.summary.set(
            f"FPS {fps}   ·   Kare süresi {ms} ms   ·   %1 düşük (1 sn) {low}   ·   Oturum {value['minutes']} dk"
        )
        self.heading.set("PUBG • OYUNDA" if value["active"] else "PUBG + DISCORD")
        mic = "Durum bilinmiyor" if d["mic"] is None else "Kapalı" if d["mic"] else "Açık"
        sound = (
            "Ses oturumu bekleniyor"
            if value["volume"] is None
            else "Sessiz" if value["muted"] else f"%{value['volume']}"
        )
        self.buttons[0].configure(text="Mikrofon\n" + mic)
        self.buttons[1].configure(text="Discord sesi\n" + sound)
        self.buttons[4].configure(
            text="Ayak Sesi\n" + ("Açık · %20 sınır" if value["focus"] else "Normal ses"),
            bg=ACCENT if value["focus"] else CARD,
            fg=BG if value["focus"] else TEXT,
        )
        rows = [d["message"]]
        if d.get("source") == "bot" and d["status"] == 1:
            rows.append("Katılımcılar / sessiz durumu · konuşan kişi algılanmaz")
        for person in d["members"][:8]:
            rows.append(
                person["name"]
                + " · Mikrofon "
                + ("kapalı" if person["mute"] else "açık")
                + " · Kulaklık "
                + ("kapalı" if person.get("deaf") else "açık")
            )
        if len(d["members"]) > 8:
            rows.append(f"+{len(d['members'])-8} kişi · kartta Sonraki 4")
        self.team.set("\n".join(rows))
        self.last_match = m
        if self.report_window and self.report_window.winfo_exists():
            self.refresh_report()
        summary = m["summary"]
        self.match.set(
            (
                f"{summary['kills']} öldürme    {summary['damage']} hasar\nSıralama: {summary['rank']}\n{summary['created']}"
                if summary
                else m["message"]
            )
        )

    def show_reports(self):
        if self.report_window and self.report_window.winfo_exists():
            self.report_window.lift()
            return
        self.report_window = tk.Toplevel(self)
        self.report_window.title("PUBG · Maç raporları")
        self.report_window.geometry("760x650")
        self.report_window.configure(bg=BG)
        self.report_text = tk.StringVar()
        tk.Label(
            self.report_window,
            textvariable=self.report_text,
            bg=BG,
            fg=TEXT,
            justify="left",
            font=("Consolas", 12),
            anchor="nw",
        ).pack(fill="both", expand=True, padx=20, pady=20)
        self.refresh_report()

    def refresh_report(self):
        m = self.last_match
        s = m.get("summary") or {}
        d = m.get("daily", {})
        rows = ["SON MAÇ TAKIMI  ·  Öldürme / Asist / Hasar", ""]
        for p in s.get("team", []):
            rows.append(f"{p['name'][:24]:24} {p['kills']:3} / {p['assists']:3} / {p['damage']:5}")
        rows += [
            "",
            f"BUGÜN · {d.get('date','')} · bilgisayarın yerel saati",
            f"{d.get('matches',0)} maç · {d.get('wins',0)} zafer · {d.get('kills',0)} öldürme",
            f"{d.get('assists',0)} asist · {d.get('damage',0)} hasar",
            "",
            "SON 10 MAÇ · yeni → eski",
            "Tarih (UTC)         K    A    Hasar  Sıra",
        ]
        for p in m.get("history", []):
            rows.append(
                f"{p['created'][:16].replace('T',' ')}  {p['kills']:3}  {p.get('assists',0):3}  {p['damage']:5}  {p['rank']:3}"
            )
        if m.get("status") != 1:
            rows = [m.get("message", "Veri bekleniyor")]
        self.report_text.set("\n".join(rows))

    def settings(self):
        app = self.app
        config = app.game.settings()
        win = tk.Toplevel(self)
        win.title("Oyun paneli · bağlantı ayarları")
        win.configure(bg=BG)
        win.geometry("780x790")
        win.transient(app.root)
        shell = tk.Frame(win, bg=BG, padx=22, pady=18)
        shell.pack(fill="both", expand=True)
        tk.Label(
            shell, text="OYUN PANELİ AYARLARI", bg=BG, fg=TEXT, font=("Segoe UI", 17, "bold")
        ).pack(anchor="w")
        auto = tk.BooleanVar(value=config["auto_switch"])
        tk.Checkbutton(
            shell,
            text="PUBG öne geldiğinde kartta oyun panelini aç",
            variable=auto,
            bg=BG,
            fg=TEXT,
            selectcolor=CARD,
            activebackground=BG,
        ).pack(anchor="w", pady=8)
        form = tk.Frame(shell, bg=BG)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        variables = {}
        for i, (key, label) in enumerate(
            (
                ("mic_keys", "Discord mikrofon kısayolu"),
                ("player", "PUBG oyuncu adı (Steam)"),
                ("pubg_key", "PUBG API anahtarı"),
                ("client_id", "Discord Application ID (davet için)"),
                ("bot_token", "Discord BOT TOKEN"),
                ("voice_channel", "Ses kanalı bağlantısı veya ID"),
                ("discord_user_id", "Kendi hesabın (mikrofon göstergesi)"),
            )
        ):
            tk.Label(form, text=label, bg=BG, fg=MUTED).grid(row=i, column=0, sticky="w", pady=7)
            var = tk.StringVar(value=config[key])
            variables[key] = var
            tk.Entry(
                form,
                textvariable=var,
                show="•" if key in ("pubg_key", "bot_token") else "",
                bg=CARD,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                font=("Segoe UI", 11),
            ).grid(row=i, column=1, sticky="ew", padx=(16, 0), ipady=5)

        def select_self():
            members = app.game.snapshot()["discord"]["members"]
            if not members:
                messagebox.showinfo(
                    "Ses odası",
                    "Önce Discord ses kanalına katıl ve bot bağlantısının hazır olmasını bekle.",
                    parent=win,
                )
                return
            picker = tk.Toplevel(win)
            picker.title("Ses odasından kendimi seç")
            picker.configure(bg=BG)
            picker.transient(win)
            tk.Label(picker, text="Kendi Discord hesabını seç", bg=BG, fg=TEXT).pack(
                padx=20, pady=12
            )
            choices = ttk.Combobox(
                picker,
                state="readonly",
                width=45,
                values=[m["name"] + " · " + str(m["id"]) for m in members],
            )
            choices.pack(padx=20, pady=8)

            def choose():
                index = choices.current()
                if index < 0:
                    return
                variables["discord_user_id"].set(str(members[index]["id"]))
                picker.destroy()

            app.button(picker, "Bu benim", choose).pack(pady=12)

        app.button(shell, "Ses odasından kendimi seç", select_self).pack(anchor="w", pady=6)
        explanation = (
            "Bot Token ve ses kanalı bağlantısını gir. Kanal bağlantısı: ses kanalına sağ tık → "
            "Kanal Bağlantısını Kopyala. Davet için Application ID kullanılır.\n\n"
            "Mikrofon göstergesi için “Ses odasından kendimi seç” ile hesabını seç ve Kaydet’e bas. "
            "Göstergeler gerçek Discord durumunu yansıtır. Kulaklık simgesi Discord sağırlaştırma "
            "durumudur, fiziksel cihazın güç durumu değildir.\n\n"
            "Bot için Kanalı Görüntüle izni yeterlidir; özel intent gerekmez. Bot ses kanalına "
            "katılmaz ve konuşan kişiyi algılamaz. Anahtarlar Windows hesabına özel şifrelenir. "
            "Bot Token, Client Secret ile aynı değildir."
        )
        tk.Label(
            shell,
            text=explanation,
            wraplength=690,
            justify="left",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(fill="x", pady=14)

        def save():
            latest = app.game.settings()
            latest.update({k: v.get().strip() for k, v in variables.items()})
            latest["auto_switch"] = auto.get()
            latest["discord_mode"] = "bot"
            if latest["client_id"] != config["client_id"]:
                latest["discord_token"] = latest["discord_refresh"] = ""
            try:
                app.game.save(latest)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Ayarlar", str(exc), parent=win)
                return False
            app.append_log("Oyun paneli ayarları kaydedildi.")
            return True

        def invite():
            application_id = variables["client_id"].get().strip()
            if (
                not application_id.isascii()
                or not application_id.isdigit()
                or not 0 < int(application_id) < 2**64
            ):
                messagebox.showinfo(
                    "Bot daveti",
                    "General Information sayfasındaki Application ID değerini girin.",
                    parent=win,
                )
                return
            webbrowser.open(
                "https://discord.com/oauth2/authorize?client_id="
                + application_id
                + "&scope=bot&permissions=1024"
            )

        row = tk.Frame(shell, bg=BG)
        row.pack(fill="x", pady=4)
        app.button(row, "Kaydet", lambda: win.destroy() if save() else None, ACCENT, BG).pack(
            side="left"
        )
        app.button(row, "Botu sunucuya ekle", invite).pack(side="left", padx=6)
        app.button(row, "PUBG API", lambda: webbrowser.open("https://developer.pubg.com/")).pack(
            side="right"
        )
        app.button(
            row,
            "Discord geliştirici",
            lambda: webbrowser.open("https://discord.com/developers/applications"),
        ).pack(side="right", padx=6)
