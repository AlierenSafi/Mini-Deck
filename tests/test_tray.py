import json
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from app import App
from desktop import load_preferences, save_preferences
from tray import Tray


class TrayTests(unittest.TestCase):
    def app(self, enabled=True):
        app = object.__new__(App)
        app.root = Mock()
        app.tray = Mock()
        app.exiting = False
        app.programming = False
        app.ui_preferences = {"close_to_tray": enabled}
        app.tray.ready.is_set.return_value = True
        app.editor = Mock()
        app.editor.confirm_discard.return_value = True
        app.game = Mock()
        app.performance = Mock()
        app.asset_stop = Mock()
        app.stop_event = Mock()
        app.wait_close = Mock()
        return app

    def test_hide_preserves_services_and_unsaved_form(self):
        app = self.app()
        app.close()
        app.root.withdraw.assert_called_once()
        app.game.close.assert_not_called()
        app.performance.close.assert_not_called()
        app.editor.confirm_discard.assert_not_called()
        app.stop_event.set.assert_not_called()

    def test_disabled_option_really_exits_and_stops_tray(self):
        app = self.app(False)
        app.close()
        app.tray.stop.assert_called_once()
        app.game.close.assert_called_once()
        app.stop_event.set.assert_called_once()
        app.root.withdraw.assert_not_called()
        self.assertTrue(app.exiting)
        app.close()
        app.game.close.assert_called_once()

    def test_explicit_exit_bypasses_setting_but_respects_cancel_and_upload(self):
        app = self.app()
        app.editor.confirm_discard.return_value = False
        app.exit_app()
        app.tray.stop.assert_not_called()
        app.root.deiconify.assert_called_once()
        app.programming = True
        with patch("app.messagebox.showinfo"):
            app.exit_app()
        app.game.close.assert_not_called()
        self.assertFalse(app.exiting)
        app.programming = False
        app.editor.confirm_discard.return_value = True
        app.exit_app()
        self.assertTrue(app.exiting)

    def test_missing_tray_never_hides_window(self):
        app = self.app()
        app.tray.ready.is_set.return_value = False
        with patch("app.messagebox.showinfo"):
            app.close()
        app.root.withdraw.assert_not_called()
        app.game.close.assert_not_called()

    def test_preferences_migrate_and_disabled_setting_survives_theme_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui.json"
            path.write_text(json.dumps({"theme": "Sıcak Taş"}), encoding="utf-8")
            self.assertTrue(load_preferences(path)["close_to_tray"])
            pref = load_preferences(path)
            pref["close_to_tray"] = False
            save_preferences(path, pref)
            updated = {**load_preferences(path), "theme": "Grafit & Mint"}
            save_preferences(path, updated)
            self.assertFalse(load_preferences(path)["close_to_tray"])

    @unittest.skipUnless(sys.platform == "win32", "Windows tray integration")
    def test_real_windows_icon_starts_and_stops(self):
        events = queue.Queue()
        tray = Tray(ROOT / "companion/mini-deck.ico", events)
        tray.start()
        try:
            self.assertTrue(tray.ready.wait(5), "Native tray did not become ready")
        finally:
            tray.stop()
            tray.thread.join(5)
        self.assertFalse(tray.thread.is_alive())
        self.assertTrue(events.empty())
