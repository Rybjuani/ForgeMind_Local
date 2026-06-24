"""Headless screenshot harness that pre-seeds a chat conversation
so the sidebar HISTORIAL rail shows up populated in screenshots.

Runs the same 6-screen capture as smoke_all_screens.py, but first
sends a couple of chat messages so the persisted chats/ dir has
content and the sidebar reflects it.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("MOCK_LLM", "1")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication

from app.ui_main import MainWindow
from app import auto_config, chat_history


def _seed_demo_chats() -> None:
    """Pre-populate chats/ with a couple of sample conversations
    so the sidebar HISTORIAL shows entries in screenshots."""
    chat_history.save_chat({
        "id": "20260623-201500",
        "title": "Comparar Gemma vs Qwen para código",
        "model": "Gemma 4 12B",
        "preset": "coding",
        "messages": [
            {"role": "user", "content": "¿Cuál modelo es mejor para auditar Python?", "ts": "2026-06-23T20:15:00"},
            {"role": "ai", "content": "Gemma 4 12B rinde mejor en código por...", "ts": "2026-06-23T20:15:02", "preset": "coding"},
        ],
    })
    chat_history.save_chat({
        "id": "20260624-093000",
        "title": "Resumen del paper de attention",
        "model": "Gemma 4 12B",
        "preset": "resumen",
        "messages": [
            {"role": "user", "content": "Resumí el paper 'Attention is all you need'", "ts": "2026-06-24T09:30:00"},
            {"role": "ai", "content": "El paper introduce el Transformer...", "ts": "2026-06-24T09:30:03", "preset": "resumen"},
        ],
    })
    chat_history.save_chat({
        "id": "20260624-141500",
        "title": "Traducir docs al inglés",
        "model": "Gemma 4 12B",
        "preset": "diario",
        "messages": [
            {"role": "user", "content": "Translate this paragraph to English", "ts": "2026-06-24T14:15:00"},
            {"role": "ai", "content": "Here is the translation...", "ts": "2026-06-24T14:15:02", "preset": "diario"},
        ],
    })


def main() -> int:
    _seed_demo_chats()

    app = QApplication(sys.argv)
    app.setApplicationName("ForgeMind Local")
    s = auto_config.first_run_setup(interactive=False)
    win = MainWindow(initial_settings=s)
    win._first_run_needs_setup = False
    win.resize(1440, 900)
    win.setFixedSize(1440, 900)
    win.show()
    app.processEvents()

    out_dir = Path("screenshots")
    out_dir.mkdir(exist_ok=True)

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
