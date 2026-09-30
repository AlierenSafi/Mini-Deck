"""Visual slot editor. Clicking selects; dragging swaps; testing is explicit."""

import json

import os

from pathlib import Path

import tkinter as tk

from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

from actions import empty_slot, SLOT_COUNT

from icons import deck_label, import_icon, installed_shortcuts

from profiles import export_profile, import_profile

BG, CARD, TEXT, MUTED, ACCENT = "#101522", "#1b2435", "#edf3fa", "#94a4bc", "#35d4b3"

TYPES = {
    "Uygulama": "launch",
    "Kısayol / dosya": "open",
    "Tuş kombinasyonu": "keys",
    "Windows Ayarları": "settings",
    "Boş slot": "empty",
}

REVERSE = {value: key for key, value in TYPES.items()}


class Editor(tk.Frame):

    def __init__(self, parent, app):

        super().__init__(parent, bg=BG)

        self.loaded = None
        self.app = app
        self.selected = 6
        self.bank = 1
        self.drag = None
        self.photos = {}
        self.layout = None
        self.custom_icon = ""

        self.columnconfigure(0, weight=1, uniform="editor")
        self.columnconfigure(1, weight=1, uniform="editor")
        self.rowconfigure(0, weight=1)

        left = tk.Frame(self, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 20))

        bar = tk.Frame(left, bg=BG)
        bar.pack(fill="x", pady=(0, 10))

        self.media = self.button(bar, "Medya · 6", lambda: self.switch(0))
        self.media.pack(side="left", padx=(0, 6))

        self.page_buttons = []

        for bank in range(1, 4):

            button = self.button(bar, f"Sayfa {bank}", lambda b=bank: self.switch(b))

            button.pack(side="left", padx=(0, 4))
            self.page_buttons.append(button)

        self.grid_frame = tk.Frame(left, bg=BG)
        self.grid_frame.pack(fill="both", expand=True)

        self.hint = tk.Label(
            left,
            text="Tıkla: düzenle   •   Sürükle: yer değiştir",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
        )

        self.hint.pack(anchor="w", pady=(8, 0))

        right = tk.Frame(self, bg=CARD, padx=16, pady=12)
        right.grid(row=0, column=1, sticky="nsew")

        self.title = tk.StringVar()
        tk.Label(
            right, textvariable=self.title, bg=CARD, fg=ACCENT, font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 6))

        names = tk.Frame(right, bg=CARD)
        names.pack(fill="x")

        left_name = tk.Frame(names, bg=CARD)
        left_name.pack(side="left", fill="x", expand=True, padx=(0, 8))

        right_name = tk.Frame(names, bg=CARD)
        right_name.pack(side="left", fill="x", expand=True)

        self.name = self.field(left_name, "Ad")

        self.label = self.field(right_name, "Kart etiketi · en fazla 10 karakter")

        tk.Label(right, text="Görev", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(
            anchor="w", pady=(5, 0)
        )

        self.kind = tk.StringVar()
        self.type_box = ttk.Combobox(
            right, textvariable=self.kind, values=list(TYPES), state="readonly"
        )
        self.type_box.pack(fill="x", pady=3)
        self.type_box.bind("<<ComboboxSelected>>", lambda e: self.type_changed())

        self.path_group = tk.Frame(right, bg=CARD)
        self.path_group.pack(fill="x")

        self.path = self.field(self.path_group, "Program / kısayol yolu")

        row = tk.Frame(self.path_group, bg=CARD)
        row.pack(fill="x", pady=(3, 0))

        self.browse_button = self.button(row, "Dosya seç", self.browse)
        self.browse_button.pack(side="left", padx=(0, 5))

        self.installed_button = self.button(row, "Uygulama listesi", self.choose_app)
        self.installed_button.pack(side="left")

        self.keys_group = tk.Frame(right, bg=CARD)
        self.keys_group.pack(fill="x")

        self.keys = self.field(self.keys_group, "Tuşlar · örnek CTRL+SHIFT+S")

        self.args_group = tk.Frame(right, bg=CARD)
        self.args_group.pack(fill="x")

        tk.Label(
            self.args_group,
            text="Başlatma seçenekleri · her satıra bir argüman",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(5, 0))

        self.arguments = tk.Text(
            self.args_group,
            height=2,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 9),
        )
        self.arguments.pack(fill="x", pady=3)

        self.icon_group = tk.Frame(right, bg=CARD)
        self.icon_group.pack(fill="x", pady=(5, 0))

        row = self.icon_group

        self.button(row, "Simge seç", self.choose_icon).pack(side="left", padx=(0, 5))

        self.button(row, "Otomatik simge", self.auto_icon).pack(side="left")

        self.icon_note = tk.StringVar()
        tk.Label(right, textvariable=self.icon_note, bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
            anchor="w", pady=3
        )

        row = tk.Frame(right, bg=CARD)
        row.pack(fill="x", pady=(7, 0))

        self.button(row, "Kaydet ve karta gönder", self.save, ACCENT, BG).pack(
            side="left", padx=(0, 5)
        )

        self.button(row, "Dene", self.test).pack(side="left")

        self.button(row, "Geri al", lambda: self.select(self.selected, force=True)).pack(
            side="left", padx=5
        )

        row = tk.Frame(right, bg=CARD)
        row.pack(fill="x", pady=(7, 0))

        self.button(row, "Slotu boşalt", self.clear).pack(side="left", padx=(0, 5))

        self.move_target = tk.StringVar(value="1")

        ttk.Combobox(
            row,
            textvariable=self.move_target,
            values=[str(i + 1) for i in range(SLOT_COUNT)],
            width=4,
            state="readonly",
        ).pack(side="left", padx=(0, 5))

        self.button(row, "Yer değiştir", self.move).pack(side="left")

        bottom = tk.Frame(self, bg=BG)
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        self.button(bottom, "Profili dışa aktar", self.export).pack(side="left", padx=(0, 7))

        self.button(bottom, "Profil içe aktar", self.restore).pack(side="left")

        self.render()
        self.select(6)

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
            padx=9,
            pady=7,
            cursor="hand2",
            font=("Segoe UI", 9),
        )

    def field(self, parent, label):

        tk.Label(parent, text=label, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(
            anchor="w", pady=(5, 0)
        )

        var = tk.StringVar()
        tk.Entry(
            parent,
            textvariable=var,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
        ).pack(fill="x", ipady=3, pady=2)

        return var

    def switch(self, bank):

        if not self.confirm_discard():
            return

        self.bank = bank
        self.render()
        self.select(bank * 6, force=True)

    def render(self):

        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.media.configure(
            bg=ACCENT if self.bank == 0 else CARD, fg=BG if self.bank == 0 else TEXT
        )

        for bank, button in enumerate(self.page_buttons, 1):

            button.configure(
                bg=ACCENT if self.bank == bank else CARD, fg=BG if self.bank == bank else TEXT
            )

        items = self.app.actions.items

        ids = range(self.bank * 6, self.bank * 6 + 6)

        for row in range(4):
            self.grid_frame.rowconfigure(row, weight=0)

        for col in range(2):
            self.grid_frame.columnconfigure(col, weight=1, uniform="slots")

        for i, index in enumerate(ids):

            item = items[index]

            frame = tk.Frame(
                self.grid_frame, bg=ACCENT if index == self.selected else CARD, padx=2, pady=2
            )

            frame.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0, 7), pady=(0, 7))

            self.grid_frame.rowconfigure(i // 2, weight=1)

            button = tk.Button(
                frame,
                text=f'{index+1:02d}  {item["name"][:25]}',
                image=self.photos.get(index),
                compound="top",
                wraplength=155,
                bg=CARD,
                fg=MUTED if item["type"] == "empty" else TEXT,
                activebackground="#29394f",
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                font=("Segoe UI", 10),
                padx=5,
                pady=10,
                cursor="hand2",
            )

            button.pack(fill="both", expand=True)
            button.slot_index = index

            button.bind("<ButtonPress-1>", lambda event, n=index: self.press(n))

            button.bind("<ButtonRelease-1>", self.release)

    def press(self, index):

        if self.select(index, redraw=False) is False:
            self.drag = None
            return

        self.drag = index

    def release(self, event):

        source = self.drag
        self.drag = None

        target = self.winfo_containing(event.x_root, event.y_root)

        destination = getattr(target, "slot_index", None)

        if source is not None and destination is not None and source != destination:

            self.swap(source, destination)

        else:
            self.render()

    def form_state(self):

        return (
            self.name.get(),
            self.label.get(),
            self.kind.get(),
            self.path.get(),
            self.keys.get(),
            self.arguments.get("1.0", "end-1c"),
            self.custom_icon,
        )

    def confirm_discard(self):

        if self.loaded is None or self.form_state() == self.loaded:
            return True

        answer = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklik", "Slot değişikliklerini kaydetmek ister misin?", parent=self
        )

        if answer is None:
            return False

        if answer:
            return bool(self.save())

        self.select(self.selected, force=True)
        return True

    def select(self, index, redraw=True, force=False):

        if not force and index != self.selected and not self.confirm_discard():
            return False

        self.selected = index
        item = self.app.actions.items[index]

        self.title.set(f"Slot {index+1:02d} · düzenle")

        self.name.set(item["name"])
        self.label.set(item.get("label") or deck_label(item))
        self.kind.set(REVERSE[item["type"]])

        self.path.set(
            item.get("argv", [""])[0] if item["type"] == "launch" else item.get("path", "")
        )

        self.keys.set("+".join(item.get("keys", [])))

        self.arguments.configure(state="normal")
        self.arguments.delete("1.0", "end")
        self.arguments.insert("1.0", "\n".join(item.get("argv", [])[1:]))

        self.custom_icon = item.get("icon", "")
        self.icon_note.set(
            "Özel simge seçili" if self.custom_icon else "Uygulamanın simgesi otomatik alınır"
        )

        self.type_changed()

        self.loaded = self.form_state()

        if redraw:
            self.render()

        return True

    def type_changed(self):

        enabled = TYPES.get(self.kind.get()) in ("launch", "open")

        self.browse_button.configure(state="normal" if enabled else "disabled")

        kind = TYPES.get(self.kind.get())

        self.arguments.configure(state="normal" if kind == "launch" else "disabled")

        for frame, visible in [
            (self.path_group, enabled),
            (self.keys_group, kind == "keys"),
            (self.args_group, kind == "launch"),
        ]:

            frame.pack_forget()

            if visible:
                frame.pack(fill="x", before=self.icon_group)

    def save(self):

        try:

            item = {
                "name": self.name.get().strip(),
                "label": self.label.get().strip(),
                "type": TYPES[self.kind.get()],
            }

            if self.custom_icon:
                item["icon"] = self.custom_icon

            if item["type"] == "launch":
                item["argv"] = [self.path.get().strip()] + self.arguments.get(
                    "1.0", "end-1c"
                ).splitlines()

            elif item["type"] == "open":
                item["path"] = self.path.get().strip()

            elif item["type"] == "keys":
                item["keys"] = [key.strip().upper() for key in self.keys.get().split("+")]

            items = self.app.actions.items
            items[self.selected] = item

            self.app.save_items(items)
            self.select(self.selected, force=True)
            return True

        except (ValueError, OSError, KeyError) as exc:

            messagebox.showerror("Slot kaydedilemedi", str(exc), parent=self)
            return False

    def swap(self, first, second):

        if not self.confirm_discard():
            return

        items = self.app.actions.items
        items[first], items[second] = items[second], items[first]

        try:
            self.app.save_items(items)

        except (ValueError, OSError) as exc:
            messagebox.showerror("Taşıma başarısız", str(exc), parent=self)
            return

        self.bank = second // 6
        self.select(second, force=True)

    def move(self):
        self.swap(self.selected, int(self.move_target.get()) - 1)

    def clear(self):

        if not messagebox.askyesno("Slotu boşalt", "Seçili slot boşaltılsın mı?", parent=self):
            return

        items = self.app.actions.items
        items[self.selected] = empty_slot()

        try:
            self.app.save_items(items)
            self.select(self.selected, force=True)

        except (ValueError, OSError) as exc:
            messagebox.showerror("Slot boşaltılamadı", str(exc), parent=self)

    def test(self):

        self.app.run_action(self.selected)

    def browse(self):

        path = filedialog.askopenfilename(
            parent=self,
            title="Uygulama veya kısayol seç",
            filetypes=[("Uygulama ve kısayollar", "*.exe *.lnk *.url"), ("Tüm dosyalar", "*.*")],
        )

        if path:
            self.set_app(Path(path).stem, path)

    def set_app(self, name, path):

        self.name.set(name[:80])
        self.label.set(deck_label({"name": name}))

        self.path.set(path)
        self.kind.set("Uygulama" if Path(path).suffix.lower() == ".exe" else "Kısayol / dosya")

        self.arguments.configure(state="normal")
        self.arguments.delete("1.0", "end")
        self.custom_icon = ""
        self.icon_note.set("Uygulamanın simgesi otomatik alınır")
        self.type_changed()

    def choose_app(self):
        from app_picker import AppPicker

        AppPicker(self)

    def choose_icon(self):

        path = filedialog.askopenfilename(
            parent=self,
            title="Slot simgesi seç",
            filetypes=[("Görsel", "*.png *.ico *.jpg *.jpeg *.bmp")],
        )

        if path:

            try:
                self.custom_icon = import_icon(path)
                self.icon_note.set("Özel simge seçildi · Kaydet ile uygula")

            except (OSError, ValueError) as exc:
                messagebox.showerror("Simge okunamadı", str(exc), parent=self)

    def auto_icon(self):
        self.custom_icon = ""
        self.icon_note.set("Otomatik simge · Kaydet ile uygula")

    def update_layout(self, layout):

        self.layout = layout

        self.photos = {}
        for i, im in enumerate(layout["images"]):
            item = layout["items"][i]
            if not item.get("icon") and item["type"] in ("keys", "settings"):
                tinted = Image.new("RGBA", im.size, self.app.palette["ACCENT"])
                tinted.putalpha(im.getchannel("A"))
                im = tinted
            self.photos[i] = ImageTk.PhotoImage(im.resize((48, 48), Image.Resampling.LANCZOS))

        self.render()

    def export(self):

        if not self.layout or self.layout["revision"] != self.app.actions.revision:

            messagebox.showinfo(
                "Simgeler hazırlanıyor", "Simgeler hazır olduğunda yeniden deneyin.", parent=self
            )
            return

        path = filedialog.asksaveasfilename(
            parent=self,
            title="Profil yedeği",
            defaultextension=".json",
            initialfile="mini-deck-profil.json",
            filetypes=[("Mini Deck profili", "*.json")],
        )

        if path:

            try:
                export_profile(path, self.app.actions.items, self.layout["images"])
                self.app.append_log("Profil, simgeleriyle birlikte dışa aktarıldı.")

            except OSError as exc:
                messagebox.showerror("Dışa aktarma başarısız", str(exc), parent=self)

    def restore(self):

        if not self.confirm_discard():
            return

        path = filedialog.askopenfilename(
            parent=self, title="Profil yükle", filetypes=[("Mini Deck profili", "*.json")]
        )

        if path:

            try:
                self.app.save_items(import_profile(path))
                self.select(self.selected, force=True)

            except (OSError, ValueError, KeyError) as exc:
                messagebox.showerror("Profil yüklenemedi", str(exc), parent=self)
