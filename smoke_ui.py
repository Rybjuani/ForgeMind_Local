"""Headless smoke test: open the UI, grab a screenshot, no wizard.

This is for debugging the UI in dev without going through the
first-run flow. Run with: python smoke_ui.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Force mock so we never spawn llama-cli / Ollama
os.environ.setdefault("MOCK_LLM", "1")
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # headless: no real display

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from app.ui_main import MainWindow
from app import auto_config


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ForgeMind Local")
    s = auto_config.first_run_setup()
    win = MainWindow(initial_settings=s)
    win.resize(1280, 820)
    # Skip the first-run wizard for the screenshot (it would just
    # cover everything; this script is purely a visual smoke test).
    win._first_run_needs_setup = False
    win.show()

    out_dir = Path("screenshots")
    out_dir.mkdir(exist_ok=True)

    def grab_and_quit():
        # Give the layout one event loop tick
        app.processEvents()
        pixmap = win.grab()
        path = out_dir / "smoke-frameless.png"
        ok = pixmap.save(str(path), "PNG")
        print(f"window flags: {win.windowFlags()}")
        print(f"menu widget: {win.menuWidget()}")
        print(f"central: {win.centralWidget().objectName()}")
        print(f"titlebar: {win.titlebar.objectName()}")
        print(f"screenshot saved: {path} ok={ok} size={path.stat().st_size}")
        app.quit()

    QTimer.singleShot(400, grab_and_quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
