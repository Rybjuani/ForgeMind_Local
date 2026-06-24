"""Headless smoke test for all 6 screens.

Grabs a screenshot of each screen after switching to it. The first-run
wizard is suppressed and the backend is auto-started so the metrics
panel shows non-default values.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MOCK_LLM", "1")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication

from app.ui_main import MainWindow
from app import auto_config


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ForgeMind Local")
    s = auto_config.first_run_setup(interactive=False)
    win = MainWindow(initial_settings=s)
    win._first_run_needs_setup = False
    win.resize(1280, 820)
    win.show()

    out_dir = Path("screenshots")
    out_dir.mkdir(exist_ok=True)

    # The offscreen Qt platform ignores showMaximized() — set a fixed
    # large window size instead so the screenshot matches the mockup's
    # 1440x900 desktop reference.
    win.setFixedSize(1440, 900)
    win.show()
    app.processEvents()

    screens = [
        ("chat",      "01-chat"),
        ("config",    "02-config"),
        ("metrics",   "03-metrics"),
        ("benchmark", "04-benchmark"),
        ("presets",   "05-presets"),
        ("gpu",       "06-gpu"),
    ]

    def grab_one(i: int = 0):
        if i >= len(screens):
            print("All screenshots captured.")
            app.quit()
            return
        key, name = screens[i]
        win._switch_screen(key)
        app.processEvents()
        # give the layout one tick
        QTimer.singleShot(80, lambda: _snap(name, i))

    def _snap(name: str, i: int):
        pm = win.grab()
        path = out_dir / f"{name}.png"
        ok = pm.save(str(path), "PNG")
        print(f"  saved {path.name} ok={ok} size={path.stat().st_size if ok else 0}")
        QTimer.singleShot(20, lambda: grab_one(i + 1))

    QTimer.singleShot(150, lambda: grab_one(0))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
