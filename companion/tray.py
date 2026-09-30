"""Windows tray loop; callbacks only enqueue commands, never touch Tk."""

import threading


class Tray:
    def __init__(self, path, events):
        self.path = path
        self.events = events
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.icon = None
        self.thread = threading.Thread(target=self.run, name="deck-tray", daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        try:
            import pystray
            from PIL import Image

            with Image.open(self.path) as image:
                art = image.convert("RGBA")
            self.icon = pystray.Icon(
                "AlierenMiniDeck",
                art,
                "Alieren Mini Deck",
                pystray.Menu(
                    pystray.MenuItem("Aç", lambda *_: self.events.put("open"), default=True),
                    pystray.MenuItem("Tamamen çık", lambda *_: self.events.put("exit")),
                ),
            )

            def setup(icon):
                try:
                    if self.stopping.is_set():
                        icon.stop()
                        return
                    icon.visible = True
                    self.ready.set()
                except Exception:
                    icon.stop()

            self.icon.run(setup=setup)
        except Exception:
            pass  # Tk displays a recoverable error; a window is never stranded hidden.
        finally:
            self.ready.clear()
            if not self.stopping.is_set():
                self.events.put("error")

    def stop(self):
        self.stopping.set()
        self.ready.clear()
        if self.icon:
            self.icon.stop()
