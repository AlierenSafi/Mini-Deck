"""Searchable local application picker; catalog and icon work stays off Tk's thread."""

import queue
import threading
from pathlib import Path
from functools import lru_cache
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk
from icons import installed_shortcuts, get_icon, fallback_icon


class AppPicker(tk.Toplevel):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.app = editor.app
        self.p = self.app.palette
        self.title("Uygulama seç · Mini Deck")
        self.geometry("720x570")
        self.minsize(580, 460)
        self.transient(self.app.root)
        x = max(0, self.app.root.winfo_rootx() + (self.app.root.winfo_width() - 720) // 2)
        y = max(0, self.app.root.winfo_rooty() + (self.app.root.winfo_height() - 570) // 2)
        self.geometry(f"720x570+{x}+{y}")
        self.bind("<Escape>", lambda e: self.close())
        self.configure(bg=self.p["BG"])
        self.rows = []
        self.visible = []
        self.images = {}
        self.requests = set()
        self.events = queue.Queue()
        self.closed = False
        self.protocol("WM_DELETE_WINDOW", self.close)
        tk.Label(
            self,
            text="Slota bir uygulama ekle",
            font=("Segoe UI", 18, "bold"),
            bg=self.p["BG"],
            fg=self.p["TEXT"],
        ).pack(anchor="w", padx=20, pady=(18, 5))
        tk.Label(
            self,
            text="Başlat menüsü, masaüstü ve Steam oyunlarında ara.",
            bg=self.p["BG"],
            fg=self.p["MUTED"],
        ).pack(anchor="w", padx=20)
        row = tk.Frame(self, bg=self.p["BG"])
        row.pack(fill="x", padx=20, pady=12)
        self.query = tk.StringVar()
        entry = tk.Entry(
            row,
            textvariable=self.query,
            bg=self.p["CARD"],
            fg=self.p["TEXT"],
            insertbackground=self.p["TEXT"],
            relief="flat",
            font=("Segoe UI", 12),
        )
        entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.kind = tk.StringVar(value="Tümü")
        ttk.Combobox(
            row,
            textvariable=self.kind,
            values=["Tümü", "Steam", "Uygulamalar"],
            state="readonly",
            width=13,
        ).pack(side="right", padx=(12, 0))
        listing = tk.Frame(self, bg=self.p["BG"])
        listing.pack(fill="both", expand=True, padx=20)
        self.tree = ttk.Treeview(
            listing, columns=("source",), show="tree headings", height=12, selectmode="browse"
        )
        self.tree.heading("#0", text="Uygulama")
        self.tree.heading("source", text="Kaynak")
        self.tree.column("#0", width=410)
        self.tree.column("source", width=100, stretch=False)
        scroll = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        self.status = tk.StringVar(value="Uygulamalar bulunuyor…")
        tk.Label(self, textvariable=self.status, bg=self.p["BG"], fg=self.p["MUTED"]).pack(
            anchor="w", padx=20, pady=8
        )
        row = tk.Frame(self, bg=self.p["BG"])
        row.pack(fill="x", padx=20, pady=(0, 16))
        self.app.button(row, "Dosyadan seç…", self.browse).pack(side="left")
        self.app.button(row, "Slota ekle", self.choose, self.p["ACCENT"], self.p["BG"]).pack(
            side="right"
        )
        self.query.trace_add("write", lambda *_: self.filter())
        self.kind.trace_add("write", lambda *_: self.filter())
        self.tree.bind("<Double-Button-1>", lambda e: self.choose())
        self.tree.bind("<Return>", lambda e: self.choose())
        self.tree.bind("<<TreeviewSelect>>", self.selection)

        def catalog():
            try:
                self.events.put(("catalog", installed_shortcuts()))
            except OSError as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=catalog, daemon=True).start()
        self.after(60, self.pump)
        entry.focus_set()

    @staticmethod
    @lru_cache(maxsize=2048)
    def source(path):
        if path.startswith("steam://"):
            return "Steam"
        if path.lower().endswith(".url"):
            try:
                if (
                    "url=steam://"
                    in Path(path).read_text(encoding="utf-8-sig", errors="replace").lower()
                ):
                    return "Steam"
            except OSError:
                pass
        return "Uygulama"

    def filter(self):
        term = self.query.get().casefold()
        kind = self.kind.get()
        self.visible = [
            r
            for r in self.rows
            if term in r[0].casefold()
            and (kind == "Tümü" or (self.source(r[1]) == "Steam") == (kind == "Steam"))
        ]
        self.tree.delete(*self.tree.get_children())
        for i, (name, path) in enumerate(self.visible):
            self.tree.insert(
                "",
                "end",
                iid=str(i),
                text="  " + name,
                values=(self.source(path),),
                image=self.images.get(path, ""),
            )
        self.status.set(f"{len(self.visible)} sonuç · çift tıklayarak seç")
        if self.visible:
            self.tree.selection_set("0")
        self.load_icons(self.visible[:32])

    def load_icons(self, rows):
        todo = [r for r in rows if r[1] not in self.requests]
        self.requests.update(p for _, p in todo)
        if not todo:
            return

        def work():
            for name, path in todo:
                if self.closed:
                    return
                item = {"type": "open", "path": path, "name": name}
                try:
                    im = get_icon(item)
                except Exception:
                    im = fallback_icon(item)
                self.events.put(("icon", (path, im)))

        threading.Thread(target=work, daemon=True).start()

    def selection(self, event=None):
        selected = self.tree.selection()
        if selected:
            self.load_icons([self.visible[int(selected[0])]])

    def pump(self):
        if self.closed:
            return
        for _ in range(16):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "catalog":
                self.rows = data
                self.filter()
            elif kind == "error":
                self.status.set(data)
            else:
                path, im = data
                self.images[path] = ImageTk.PhotoImage(
                    im.resize((24, 24), Image.Resampling.LANCZOS)
                )
                for i, (_, p) in enumerate(self.visible):
                    if p == path:
                        self.tree.item(str(i), image=self.images[path])
        if self.visible:
            start = int(self.tree.yview()[0] * len(self.visible))
            self.load_icons(self.visible[start : start + 24])
        self.after(60, self.pump)

    def choose(self):
        selected = self.tree.selection()
        if not selected:
            return
        self.editor.set_app(*self.visible[int(selected[0])])
        self.close()

    def browse(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("Uygulama / kısayol", "*.exe *.lnk *.url"), ("Tüm dosyalar", "*.*")],
        )
        if path:
            from pathlib import Path

            self.editor.set_app(Path(path).stem, path)
            self.close()

    def close(self):
        self.closed = True
        self.destroy()
