"""Location selection without blocking Tk or guessing ambiguous place names."""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from weather_service import load, save, search


def show(app):
    win = tk.Toplevel(app.root)
    win.title("Hava durumu")
    win.geometry("620x370")
    win.transient(app.root)
    panel = ttk.Frame(win, padding=20)
    panel.pack(fill="both", expand=True)
    config = load()
    enabled = tk.BooleanVar(value=config.get("enabled", False))
    ttk.Checkbutton(panel, text="Kartta hava durumunu göster", variable=enabled).pack(anchor="w")
    ttk.Label(panel, text="İl veya ilçe ara; sonuçlardan doğru konumu seç.").pack(
        anchor="w", pady=(16, 5)
    )
    query = tk.StringVar()
    ttk.Entry(panel, textvariable=query).pack(fill="x")
    choices = ttk.Combobox(panel, state="readonly")
    choices.pack(fill="x", pady=10)
    status = tk.StringVar(value="Kayıtlı konum: " + config.get("name", "Seçilmedi"))
    ttk.Label(panel, textvariable=status, wraplength=565).pack(anchor="w", pady=8)
    results = []
    messages = queue.Queue()

    def find():
        term = query.get()
        button.configure(state="disabled")
        status.set("Konumlar aranıyor…")

        def work():
            try:
                messages.put((search(term), None))
            except (OSError, ValueError, KeyError, TypeError):
                messages.put(([], "Arama yapılamadı. Bağlantını ve konum adını kontrol et."))

        threading.Thread(target=work, daemon=True).start()

    button = ttk.Button(panel, text="Konum ara", command=find)
    button.pack(anchor="w")

    def poll():
        if not win.winfo_exists():
            return
        try:
            values, error = messages.get_nowait()
            results[:] = values
            choices.set("")
            choices["values"] = [p["name"] for p in results]
            status.set(error or ("Konum seç." if results else "Sonuç bulunamadı."))
            button.configure(state="normal")
        except queue.Empty:
            pass
        win.after(100, poll)

    def commit():
        i = choices.current()
        selected = dict(results[i]) if i >= 0 else dict(config)
        if enabled.get() and not selected:
            messagebox.showinfo("Konum", "Önce arama sonucundan konum seç.", parent=win)
            return
        selected["enabled"] = enabled.get()
        try:
            save(selected)
        except OSError as exc:
            messagebox.showerror("Kaydedilemedi", str(exc), parent=win)
            return
        app.append_log("Hava durumu ayarı kaydedildi.")
        win.destroy()

    ttk.Button(panel, text="Kaydet", command=commit).pack(anchor="e", pady=10)
    ttk.Button(
        panel,
        text="Hava verisi: Open-Meteo.com (10 dakikada bir)",
        command=lambda: webbrowser.open("https://open-meteo.com/"),
    ).pack(anchor="w")
    win.after(100, poll)
