"""ForgeMind Local — PyQt6 desktop UI.

Faithful reproduction of the Claude-style desktop mockup:
  - Dark-only warm palette (#1a1918 + #d97757 accent, copper).
  - Frameless window with custom TitleBar (min/max/close + brand + status).
  - Collapsible Sidebar (brand + model card + new chat + nav + footer RAM/t/s).
  - 6 screens stacked: Chat / Modelo y backend / Rendimiento / Benchmark / Presets / GPU.
  - Floating Command Palette (Ctrl+K) — overlay + list with filter.
  - Toast notifications bottom-right.
  - All metrics / chat / presets / benchmark / GPU detection wired to the
    existing backends and modules (LlamaBackend, OllamaBackend, benchmark,
    presets, gpu_detect, metrics). Streaming chat uses GenerateRunner
    (QThread) so the UI never blocks.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .benchmark import (
    DEFAULT_PROMPTS_FILE,
    DEFAULT_RESULTS_DIR,
    compare_runs,
    list_runs,
    load_prompts,
    render_compare_markdown,
    run_benchmark,
    save_compare,
)
from .gpu_detect import system_summary
from .llama_backend import LlamaBackend
from .metrics import get_process_metrics, get_system_memory
from .model_config import ModelConfig
from .ollama_backend import DEFAULT_OLLAMA_URL, OllamaBackend
from .presets import PRESETS, default_preset, get_preset


# ---------------------------------------------------------------------------
# QSS — Claude desktop warm dark palette, mirrors the mockup exactly.
# ---------------------------------------------------------------------------

QSS = """
/* === Base / shared === */
* { font-family: "Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, system-ui, sans-serif; }
QMainWindow, #AppRoot, #TitleBar, #Sidebar, #MainArea, #ContentHost {
    background: #1a1918;
    color: #f5f4ee;
}
QWidget { color: #f5f4ee; font-size: 14px; }

QLabel { background: transparent; color: #f5f4ee; }
QLabel[role="muted"] { color: #a8a499; }
QLabel[role="dim"] { color: #787469; }
QLabel[role="accent"] { color: #d97757; }
QLabel[role="green"] { color: #8ab589; }
QLabel[role="amber"] { color: #d4a361; }
QLabel[role="rose"] { color: #d88a83; }

/* Serif headlines — Newsreader for editorial identity (mockup L40).
   Qt does NOT honor the generic `serif` keyword the way browsers do,
   so we list explicit fallbacks for Windows (Georgia), Linux
   (Liberation Serif / DejaVu Serif), and macOS (Times New Roman). */
QLabel[font-role="serif"] {
    font-family: "Newsreader", "Tiempos Text", Georgia, "Liberation Serif",
                 "DejaVu Serif", "Times New Roman", serif;
    letter-spacing: -0.01em;
}

QFrame[role="card"] {
    background: #282623;
    border: 1px solid #34312e;
    border-radius: 14px;
}
QFrame[role="card"]:hover { border-color: #444039; }

QFrame[role="metric-tile"] {
    background: #282623;
    border: 1px solid #34312e;
    border-radius: 10px;
}
QFrame[role="gpu-tile"] {
    background: #282623;
    border: 1px solid #34312e;
    border-radius: 10px;
}

QFrame[role="divider"] { background: #34312e; max-height: 1px; min-height: 1px; border: 0; }

/* === Titlebar === */
#TitleBar {
    background: #181715;
    border-bottom: 1px solid #34312e;
}
#TitleBar QLabel { color: #a8a499; }
#TitleBar QLabel#BrandLabel {
    color: #d8d4c8; font-size: 13px; font-weight: 500;
    font-family: "Newsreader", Georgia, "Liberation Serif", "DejaVu Serif",
                 "Times New Roman", serif; letter-spacing: -0.005em;
}
#TitleBar QLabel#StatusDot {
    background: #8ab589; border-radius: 3px;
    min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px;
}
#TitleBar QLabel#StatusDot[idle="true"] { background: #787469; }
#WinBtn {
    background: transparent;
    border: none;
    border-radius: 7px;
    width: 14px; height: 14px;
}
#WinBtn:hover { background: rgba(255,255,255,0.06); }
#WinMin { background: #febc2e; }
#WinMax { background: #28c840; }
#WinClose { background: #ff5f57; }

/* === Sidebar === */
#Sidebar {
    background: #211f1d;
    border-right: 1px solid #34312e;
}
#Sidebar QPushButton#SidebarCollapse {
    background: transparent; color: #a8a499; border: none;
    border-radius: 6px; padding: 0; min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px;
}
#Sidebar QPushButton#SidebarCollapse:hover { background: rgba(255,255,255,0.045); color: #f5f4ee; }

#BrandName {
    color: #f5f4ee; font-size: 15px; font-weight: 500;
    font-family: "Newsreader", Georgia, "Liberation Serif", "DejaVu Serif",
                 "Times New Roman", serif; letter-spacing: -0.01em;
}
#BrandTag { color: #787469; font-size: 10.5px; }

#ModelCard {
    background: #282623; border: 1px solid #34312e; border-radius: 10px;
}
#ModelCard:hover { border-color: #444039; background: #2f2d2a; cursor: pointer; }
#ModelCard QLabel#McName {
    color: #f5f4ee; font-size: 13.5px; font-weight: 500;
    font-family: "Newsreader", Georgia, "Liberation Serif", "DejaVu Serif",
                 "Times New Roman", serif; letter-spacing: -0.005em;
}
#ModelCard QLabel#McMeta { color: #a8a499; font-size: 11.5px; }

QPushButton#NewChat {
    background: #2f2d2a; color: #f5f4ee;
    border: 1px solid #444039; border-radius: 10px;
    padding: 8px 11px; font-weight: 500; text-align: left;
}
QPushButton#NewChat:hover { background: #383531; border-color: #564f47; }
QPushButton#NewChat:pressed { padding-top: 9px; padding-bottom: 7px; }

QLabel#NavSectionLabel {
    color: #787469; font-size: 10.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px; padding: 6px 10px 4px;
}

QPushButton#NavBtn {
    background: transparent; color: #d8d4c8; border: none;
    border-radius: 6px; padding: 7px 10px; text-align: left;
    font-size: 13px; font-weight: 450; letter-spacing: -0.005em;
    /* 3px accent left-bar via border (visible only when checked) */
    border-left: 3px solid transparent;
    margin-left: -3px;
}
QPushButton#NavBtn:hover { background: rgba(255,255,255,0.045); color: #f5f4ee; }
QPushButton#NavBtn:checked {
    background: rgba(255,255,255,0.075); color: #f5f4ee; font-weight: 500;
    border-left: 3px solid #d97757;
}
QPushButton#NavBtn:checked QLabel#NavIco { color: #d97757; }
QLabel#NavIco { color: #a8a499; }
QLabel#NavKbd {
    color: #787469; font-family: "JetBrains Mono", "Consolas", monospace;
    background: #151413; border: 1px solid #34312e; border-radius: 4px;
    font-size: 10px; padding: 1px 5px;
}

#SidebarFoot {
    background: transparent; border-top: 1px solid #34312e;
}
#FootRow { color: #a8a499; font-size: 11.5px; }
#FootRow QLabel#FootDot {
    background: #8ab589; border-radius: 3px; min-width: 6px; max-width: 6px;
    min-height: 6px; max-height: 6px;
}

/* === Header === (solid bg — Qt cannot do backdrop-filter blur) */
#Header {
    background: #282623;
    border-bottom: 1px solid #34312e;
}
#Header QLabel#BreadTitle {
    color: #f5f4ee; font-size: 15px; font-weight: 500;
    font-family: "Newsreader", Georgia, "Liberation Serif", "DejaVu Serif",
                 "Times New Roman", serif; letter-spacing: -0.01em;
}
#Header QLabel#BreadSub { color: #a8a499; font-size: 12px; }

QFrame#Chip {
    background: #282623; border: 1px solid #444039; border-radius: 999px;
}
QFrame#Chip:hover { background: #2f2d2a; border-color: #564f47; }
QFrame#Chip[accent="true"] {
    background: rgba(217,119,87,0.14); border: 1px solid rgba(217,119,87,0.34);
}
QLabel#ChipLabel { color: #d8d4c8; font-size: 11.5px; font-weight: 500; }
QFrame#Chip[accent="true"] QLabel#ChipLabel { color: #d97757; }
QLabel#ChipDot { background: #8ab589; border-radius: 3px; min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px; }
QFrame#Chip[accent="true"] QLabel#ChipDot { background: #d97757; }

/* === Generic input controls === */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #151413; color: #f5f4ee;
    border: 1px solid #444039; border-radius: 6px;
    padding: 8px 11px; selection-background-color: rgba(217,119,87,0.34);
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid rgba(217,119,87,0.34);
    background: #282623;
    /* glow approximation: a thicker accent-tinted border */
}
QPlainTextEdit, QTextEdit { font-family: "JetBrains Mono", "Consolas", "Courier New", monospace; font-size: 12.5px; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView {
    background: #2f2d2a; color: #f5f4ee;
    border: 1px solid #444039; border-radius: 6px;
    selection-background-color: rgba(217,119,87,0.20);
    outline: 0;
}
QComboBox::down-arrow { width: 10px; height: 10px; }

QSlider::groove:horizontal {
    background: #151413; height: 4px; border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #d97757; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #c5663f; }
QSlider::sub-page:horizontal { background: #151413; border-radius: 2px; }
/* slider value box (mockup L1121-1132) */
QLabel#SliderValue {
    color: #d8d4c8;
    background: #151413;
    border: 1px solid #34312e;
    border-radius: 4px;
    padding: 2px 8px;
    min-width: 60px;
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: 12.5px;
    qproperty-alignment: AlignCenter;
}

/* === Buttons (general) === */
QPushButton {
    background: #282623; color: #f5f4ee; border: 1px solid #444039;
    border-radius: 10px; padding: 6px 14px; min-height: 28px; font-size: 13px; font-weight: 500;
}
QPushButton:hover { background: #2f2d2a; border-color: #564f47; }
QPushButton:pressed { background: #383531; padding-top: 7px; padding-bottom: 5px; }
QPushButton:disabled { color: #787469; background: #211f1d; border-color: #34312e; }

QPushButton[primary="true"] {
    background: #d97757; color: #1f1e1d; border: none; font-weight: 500;
    /* inset top highlight (mockup L1159) — Qt cannot do inset shadow,
       so we approximate with a 1px gradient via border-image none; */
}
QPushButton[primary="true"]:hover { background: #c5663f; }
QPushButton[primary="true"]:pressed { background: #b1582e; padding-top: 7px; padding-bottom: 5px; }

QPushButton[ghost="true"] {
    background: transparent; color: #d8d4c8; border: none; font-weight: 500;
}
QPushButton[ghost="true"]:hover { background: rgba(255,255,255,0.045); color: #f5f4ee; }

QPushButton[danger="true"] {
    color: #d88a83; border-color: rgba(216,138,131,0.34); background: #282623;
}
QPushButton[danger="true"]:hover { background: rgba(216,138,131,0.14); }

/* === Status pill === (true pill shape per mockup) */
QFrame#StatusPill {
    background: rgba(138,181,137,0.14); border: 1px solid rgba(138,181,137,0.32);
    border-radius: 999px;
}
QFrame#StatusPill QLabel { color: #8ab589; font-size: 10.5px; font-weight: 500; background: transparent; }
QFrame#StatusPill QLabel#PillDot {
    background: #8ab589; border-radius: 3px;
    min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px;
}
QFrame#StatusPill[idle="true"] {
    background: #151413; border-color: #444039;
}
QFrame#StatusPill[idle="true"] QLabel { color: #a8a499; }
QFrame#StatusPill[idle="true"] QLabel#PillDot { background: #787469; }

/* === Chat screen === */
QScrollArea#ChatScroll { background: transparent; border: 0; }
QScrollArea#ChatScroll > QWidget > QWidget { background: transparent; }
QWidget#MessagesContainer { background: transparent; }

QWidget#MsgBubble { background: transparent; }
QLabel#MsgName { color: #a8a499; font-size: 12px; font-weight: 600; background: transparent; }
QLabel#MsgPreset {
    color: #d97757; background: rgba(217,119,87,0.14); border: 1px solid rgba(217,119,87,0.34);
    border-radius: 999px; font-size: 10.5px; font-weight: 500; padding: 1px 8px;
}
QLabel#MsgBody { color: #f5f4ee; font-size: 14.5px; line-height: 1.65; background: transparent; }
QLabel#MsgBody code, QLabel#MsgBody pre {
    font-family: "JetBrains Mono", "Consolas", monospace; font-size: 12.5px;
    background: #151413; color: #d8d4c8; border: 1px solid #34312e; border-radius: 4px;
}
QLabel#MsgMeta { color: #787469; font-family: "JetBrains Mono", "Consolas", monospace; font-size: 11px; background: transparent; }

QFrame#MsgAvatar {
    border-radius: 8px; min-width: 28px; max-width: 28px;
    min-height: 28px; max-height: 28px;
}
QFrame#MsgAvatar[role="user"] { background: #383531; border: 1px solid #444039; }
QFrame#MsgAvatar[role="ai"] { background: #d97757; }
QLabel#MsgAvatarLabel { color: #d8d4c8; font-size: 12px; font-weight: 600; background: transparent; }
QFrame#MsgAvatar[role="ai"] QLabel#MsgAvatarLabel { color: #1f1e1d; }

/* Composer */
QFrame#Composer {
    background: #2f2d2a; border: 1px solid #444039; border-radius: 20px;
}
QFrame#Composer:focus { border: 1px solid rgba(217,119,87,0.34); }
QFrame[composer-focused="true"] { border: 1px solid rgba(217,119,87,0.34); }
QPlainTextEdit#ComposerEdit {
    background: transparent; border: none; padding: 4px 6px;
    color: #f5f4ee; font-size: 14.5px;
}

QPushButton#PresetPill {
    background: #151413; border: 1px solid #34312e; border-radius: 999px;
    color: #d8d4c8; font-size: 12px; font-weight: 500; padding: 4px 10px;
}
QPushButton#PresetPill:hover { background: rgba(255,255,255,0.045); color: #f5f4ee; border-color: #444039; }

QPushButton#SendBtn {
    background: #d97757; color: #1f1e1d; border: none; border-radius: 6px;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
}
QPushButton#SendBtn:hover { background: #c5663f; }
QPushButton#SendBtn:pressed { background: #b1582e; padding-top: 1px; }
QPushButton#SendBtn:disabled { background: #564f47; color: #787469; }

QPushButton#ToolBtn {
    background: transparent; border: none; border-radius: 6px;
    color: #a8a499; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
}
QPushButton#ToolBtn:hover { background: rgba(255,255,255,0.045); color: #f5f4ee; }

/* === Preset card === */
QFrame#PresetCard {
    background: #282623; border: 1px solid #34312e; border-radius: 10px;
}
QFrame#PresetCard:hover { background: #2f2d2a; border-color: #444039; }
QFrame#PresetCard[active="true"] {
    background: rgba(217,119,87,0.14); border: 1px solid rgba(217,119,87,0.34);
}
QLabel#PresetTitle { color: #f5f4ee; font-size: 13.5px; font-weight: 500; }
QLabel#PresetDesc { color: #a8a499; font-size: 12px; }
QLabel#PresetParams {
    color: #787469; font-family: "JetBrains Mono", "Consolas", monospace; font-size: 10.5px;
}

/* === Log console === (rich-text colored log lines) */
QTextBrowser#LogConsole {
    background: #151413; color: #a8a499; border: 1px solid #34312e; border-radius: 10px;
    font-family: "JetBrains Mono", "Consolas", "Courier New", monospace; font-size: 11.5px;
    padding: 6px;
}
QTextBrowser#LogConsole QScrollBar:vertical { margin: 4px; }

/* === Run items === (selected state with accent left-bar per mockup L1370-1394) */
QListWidget#RunsList { background: transparent; border: none; outline: 0; }
QListWidget#RunsList::item {
    padding: 10px 12px; border-bottom: 1px solid #34312e;
    border-left: 3px solid transparent;
}
QListWidget#RunsList::item:hover { background: rgba(255,255,255,0.045); }
QListWidget#RunsList::item:selected {
    background: rgba(217,119,87,0.14);
    border-left: 3px solid #d97757;
    color: #f5f4ee;
}
QFrame#RunItem {
    background: transparent; border-bottom: 1px solid #34312e;
}
QFrame#RunItem:hover { background: rgba(255,255,255,0.045); }
QFrame#RunItem[selected="true"] {
    background: rgba(217,119,87,0.14);
    border-left: 3px solid #d97757;
}
QLabel#RunTitle { color: #f5f4ee; font-size: 13px; font-weight: 500; background: transparent; }
QLabel#RunMeta { color: #a8a499; font-size: 11.5px; background: transparent; }

/* === Command palette === */
QDialog#CmdPalette {
    background: #2f2d2a; border: 1px solid #444039; border-radius: 20px;
}
QLineEdit#CmdInput {
    background: transparent; border: none; padding: 14px 18px;
    color: #f5f4ee; font-size: 15px;
}
QListWidget#CmdList {
    background: transparent; border: none; outline: 0;
    color: #d8d4c8; font-size: 13.5px;
}
QListWidget#CmdList::item {
    padding: 9px 12px; border-radius: 10px; margin: 1px 6px;
}
QListWidget#CmdList::item:selected {
    background: rgba(255,255,255,0.075); color: #f5f4ee;
}
QListWidget#CmdList::item:hover {
    background: rgba(255,255,255,0.075); color: #f5f4ee;
}
/* command palette item layout (icon + label + kbd via custom widget) */
QListWidget#CmdList::item {
    padding: 0; margin: 1px 6px; border-radius: 10px;
}
QLabel#CmdItemIcon { background: transparent; }
QLabel#CmdItemLabel { color: #d8d4c8; font-size: 13.5px; background: transparent; }
QLabel#CmdItemKbd {
    color: #787469; font-family: "JetBrains Mono", "Consolas", monospace;
    background: #151413; border: 1px solid #34312e; border-radius: 4px;
    font-size: 10.5px; padding: 1px 5px;
}
QFrame#CmdFooterRow {
    background: transparent; border-top: 1px solid #34312e;
}
QLabel#CmdFooter {
    color: #787469; font-size: 11px; padding: 8px 14px;
    background: transparent;
}
QLabel#CmdFooterRight {
    color: #787469; font-size: 11px; padding: 8px 14px;
    background: transparent;
}
QFrame#CmdBackdrop { background: rgba(0,0,0,0.55); }

/* === Toast === */
QFrame#ToastBanner {
    background: #2f2d2a; border: 1px solid #444039; border-radius: 10px;
}
QLabel#ToastIcon {
    background: #8ab589; color: #2f2d2a; border-radius: 9px;
    min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px;
    font-weight: 700; qproperty-alignment: AlignCenter;
}
QLabel#ToastText { color: #f5f4ee; font-size: 13px; font-weight: 500; }

/* === Progress bar (loading bars) === (color variants per mockup L1296-1298) */
QProgressBar {
    background: #151413; border: 0; border-radius: 3px;
    min-height: 5px; max-height: 5px; text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #d97757; border-radius: 3px; }
QProgressBar[tone="green"]::chunk  { background: #8ab589; }
QProgressBar[tone="amber"]::chunk { background: #d4a361; }
QProgressBar[tone="blue"]::chunk  { background: #88a7c4; }
QProgressBar[tone="rose"]::chunk  { background: #d88a83; }

/* === StatusBar (hidden by default — mockup uses toasts only) === */
QStatusBar { background: #211f1d; color: #a8a499; max-height: 0; min-height: 0; }
QStatusBar QLabel { background: transparent; }

/* === Scrollbars === */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical {
    background: #444039; border-radius: 5px; min-height: 24px; margin: 3px;
}
QScrollBar::handle:vertical:hover { background: #564f47; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; background: transparent; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #444039; border-radius: 5px; min-width: 24px; margin: 3px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { height: 0; background: transparent; }

/* === Tooltips === */
QToolTip {
    background: #f5f4ee; color: #1a1918; border: 0;
    padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 500;
}

/* === Message action buttons (hover-revealed) === */
QFrame#MsgActions { background: transparent; }
QToolButton#MsgAction {
    background: transparent; border: 0; border-radius: 4px;
    padding: 4px; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;
}
QToolButton#MsgAction:hover { background: rgba(255,255,255,0.08); }

/* === Typing indicator === */
QFrame#TypingDot {
    background: #787469; border-radius: 3px;
    min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px;
}
QFrame#TypingDot[active="true"] { background: #d97757; }
"""


# ---------------------------------------------------------------------------
# Worker thread (kept from the original; same contract).
# ---------------------------------------------------------------------------

"""Small SVG-icon helper for ForgeMind.

The mockup uses inline SVG paths for nav / metric / brand / etc. icons.
PyQt6 has no native SVG support in QLabel, so we render the icon as a
tightly-cropped ``QIcon`` built from a tiny inline SVG payload. Falls
back to the supplied text glyph when ``QIcon`` cannot render the SVG
(very old Qt builds).
"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor


# 24x24 stroke-only icons from the mockup, kept verbatim.
_NAV_ICONS: dict[str, str] = {
    "chat": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 '
        '8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 '
        '8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>'
    ),
    "config": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0'
        'l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 '
        '1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0'
        ' 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 '
        '1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 '
        '2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 '
        '1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 '
        '1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 '
        '1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 '
        '0-1.51 1z"/></svg>'
    ),
    "metrics": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>'
    ),
    "benchmark": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 3v18h18"/>'
        '<path d="M7 14l4-4 4 4 5-5"/></svg>'
    ),
    "presets": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
        '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>'
    ),
    "gpu": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="2" y="6" width="20" height="12" rx="2"/>'
        '<path d="M6 10v4M10 10v4M14 10v4M18 10v4"/></svg>'
    ),
    "search": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
    ),
    "send": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="22" y1="2" x2="11" y2="13"/>'
        '<polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>'
    ),
    "trash": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="3 6 5 6 21 6"/>'
        '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4'
        'a2 2 0 0 1 2 2v2"/></svg>'
    ),
    "preset-dot": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="6 9 12 15 18 9"/></svg>'
    ),
    "cmd-icon": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
    ),
    "play": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polygon points="5 3 19 12 5 21 5 3"/></svg>'
    ),
    "stop": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="6" y="6" width="12" height="12" rx="1"/></svg>'
    ),
    "refresh": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="23 4 23 10 17 10"/>'
        '<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>'
    ),
    "check": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="20 6 9 17 4 12"/></svg>'
    ),
    "x": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="18" y1="6" x2="6" y2="18"/>'
        '<line x1="6" y1="6" x2="18" y2="18"/></svg>'
    ),
    "doc": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/></svg>'
    ),
    "menu": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="3" y1="6" x2="21" y2="6"/>'
        '<line x1="3" y1="12" x2="21" y2="12"/>'
        '<line x1="3" y1="18" x2="21" y2="18"/></svg>'
    ),
    "alert": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 '
        '0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
    ),
    "copy": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
    ),
    "regen": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="23 4 23 10 17 10"/>'
        '<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>'
    ),
    "compare": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="17 1 21 5 17 9"/>'
        '<path d="M3 11V9a4 4 0 0 1 4-4h14"/>'
        '<polyline points="7 23 3 19 7 15"/>'
        '<path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>'
    ),
    "save": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<polyline points="17 21 17 13 7 13 7 21"/>'
        '<polyline points="7 3 7 8 15 8"/></svg>'
    ),
    "folder": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9'
        'a2 2 0 0 1 2 2z"/></svg>'
    ),
    "package": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 '
        '8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>'
    ),
    "monitor": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/>'
        '<line x1="12" y1="17" x2="12" y2="21"/></svg>'
    ),
    "list": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="8" y1="6" x2="21" y2="6"/>'
        '<line x1="8" y1="12" x2="21" y2="12"/>'
        '<line x1="8" y1="18" x2="21" y2="18"/>'
        '<line x1="3" y1="6" x2="3.01" y2="6"/>'
        '<line x1="3" y1="12" x2="3.01" y2="12"/>'
        '<line x1="3" y1="18" x2="3.01" y2="18"/></svg>'
    ),
    "search-lg": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
    ),
    "ai": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/><path d="M9 13l2 2 4-4"/></svg>'
    ),
    "user": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
        '<circle cx="12" cy="7" r="4"/></svg>'
    ),
    "plus": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="12" y1="5" x2="12" y2="19"/>'
        '<line x1="5" y1="12" x2="19" y2="12"/></svg>'
    ),
    "chevron-left": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="15 18 9 12 15 6"/></svg>'
    ),
    "chevron-right": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="9 18 15 12 9 6"/></svg>'
    ),
    "activity": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>'
    ),
    "play-circle": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<polygon points="10 8 16 12 10 16 10 8"/></svg>'
    ),
    "book": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
        '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>'
    ),
}


def _paint_svg_to_pixmap(svg_payload: str, color: str, size: int) -> QPixmap:
    """Render an SVG string into a QPixmap of the given size.

    Qt's QPixmap can load SVG via QPainter + QPicture (QtSvg is not in
    our wheelhouse), so we go straight to QPainter drawing the SVG
    through QSvgRenderer when available; on builds without QtSvg we
    fall back to a transparent pixmap with the right size — the
    caller can still show a label glyph alongside the icon.
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    try:
        from PyQt6.QtSvg import QSvgRenderer  # type: ignore
        from PyQt6.QtCore import QByteArray
        renderer = QSvgRenderer(QByteArray(svg_payload.encode("utf-8")))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()
    except Exception:
        # No QtSvg — paint a tiny dot as visual fallback.
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, size - 4, size - 4)
        painter.end()
    return pm


def svg_pixmap(name: str, *, color: str = "#a8a499", size: int = 17) -> QPixmap:
    """Return a QPixmap of an icon by name. Unknown names -> empty pixmap."""
    tmpl = _NAV_ICONS.get(name)
    if not tmpl:
        return QPixmap()
    return _paint_svg_to_pixmap(tmpl.format(c=color), color, size)


def svg_icon(name: str, *, color: str = "#a8a499", size: int = 17) -> QIcon:
    """Convenience wrapper returning a QIcon."""
    return QIcon(svg_pixmap(name, color=color, size=size))


def svg_label(parent, name: str, *, color: str = "#a8a499", size: int = 17):
    """Return a fixed-size QLabel that displays the named SVG icon."""
    from PyQt6.QtWidgets import QLabel
    lbl = QLabel(parent)
    lbl.setFixedSize(size, size)
    lbl.setPixmap(svg_pixmap(name, color=color, size=size))
    return lbl


# ---------------------------------------------------------------------------
# Bundled Newsreader font (variable TTF, ~440 KB)
# Loaded once at module import so every QLabel/QFont using the
# "Newsreader" family resolves to this bundled copy on any platform
# (Linux dev box, Windows end-user, macOS build). Without this, the
# QSS `font-family: "Newsreader", Georgia, serif` chain falls through
# to a generic sans on machines that don't have Newsreader installed.
# ---------------------------------------------------------------------------

def _load_bundled_fonts() -> None:
    from pathlib import Path
    try:
        from PyQt6.QtGui import QFontDatabase
        from PyQt6.QtWidgets import QApplication
        # QApplication must exist before addApplicationFont.
        if QApplication.instance() is None:
            return
        fonts_dir = Path(__file__).parent / "assets" / "fonts"
        if not fonts_dir.is_dir():
            return
        for ttf in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(ttf))
    except Exception:
        # Font loading is best-effort — the UI must still run if it fails.
        pass


class GenerateRunner(QThread):
    """Streams `token` per chunk and `finished` at the end with metrics."""

    token = pyqtSignal(str)
    finished = pyqtSignal(str, dict)
    failed = pyqtSignal(str)

    def __init__(self, backend: Any, prompt: str, system: str,
                 max_tokens_override: int | None = None) -> None:
        super().__init__()
        self._backend = backend
        self._prompt = prompt
        self._system = system
        self._override = max_tokens_override

    def run(self) -> None:
        old_max = self._backend.config.max_tokens
        if self._override is not None:
            self._backend.config.max_tokens = self._override
        try:
            t0 = time.perf_counter()
            first_token_sec: float | None = None
            chunks: list[str] = []
            try:
                for chunk in self._backend.generate_stream(self._prompt, self._system):
                    if first_token_sec is None and chunk:
                        first_token_sec = time.perf_counter() - t0
                    if chunk:
                        chunks.append(chunk)
                        self.token.emit(chunk)
                    if self.isInterruptionRequested():
                        try:
                            self._backend.request_abort()
                        except Exception:
                            pass
                        break
                out = "".join(chunks)
                elapsed = time.perf_counter() - t0
                m = {
                    "elapsed_sec": round(elapsed, 3),
                    "char_count": len(out),
                    "tokens_per_sec_proxy": round((len(out) / 4.0) / elapsed, 3) if elapsed > 0 else None,
                    "first_token_sec": round(first_token_sec, 3) if first_token_sec is not None else None,
                    "error": None,
                }
                self.finished.emit(out, m)
            except Exception as e:  # noqa: BLE001
                self.failed.emit(str(e))
        finally:
            self._backend.config.max_tokens = old_max


# ---------------------------------------------------------------------------
# DownloadRunner — QThread wrapper around app.downloader
# ---------------------------------------------------------------------------

class DownloadRunner(QThread):
    """Runs install_starter_kit() in a background thread.

    Emits progress as ``(key, done_bytes, total_bytes)`` and a
    final ``(success: bool, result: dict)`` when done.
    """

    progress = pyqtSignal(str, int, int)   # key, done, total
    stage    = pyqtSignal(str)             # human-readable stage label
    finished_ok = pyqtSignal(dict)         # result dict from install_starter_kit
    failed  = pyqtSignal(str)              # error message

    def __init__(self, config_dir: Path, variant: str = "cpu") -> None:
        super().__init__()
        self._config_dir = config_dir
        self._variant = variant

    def run(self) -> None:
        try:
            from . import downloader
            self.stage.emit("Buscando binarios…")
            def _on_progress(key: str, done: int, total: int) -> None:
                # Throttled internally by the downloader
                self.progress.emit(key, done, total)
            self.stage.emit("Descargando llama.cpp…")
            result = downloader.install_starter_kit(
                self._config_dir, variant=self._variant, progress=_on_progress,
            )
            self.stage.emit("Finalizando…")
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _have_llama_cpp_binding() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def _set_kv_row(row: QFrame, key: str, value: str, *, accent: str | None = None) -> None:
    k = row.findChild(QLabel, "k")
    v = row.findChild(QLabel, "v")
    if k: k.setText(key)
    if v:
        v.setText(value)
        # Update the value's color inline (the dynamic property alone
        # wouldn't override the stylesheet set in _kv_row).
        color = {"accent": "#d97757", "green": "#8ab589", "amber": "#d4a361"}.get(accent or "", "#f5f4ee")
        v.setStyleSheet(
            f"color: {color}; font-weight: 500; font-size: 13px; "
            "background: transparent; border: 0;"
        )
        v.setProperty("role", accent)


# ---------------------------------------------------------------------------
# TitleBar (window chrome — min/max/close + brand + status)
# ---------------------------------------------------------------------------

class TitleBar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(38)
        # Forward drag events to the top-level window (frameless).
        # The MainWindow installs a custom mouse handler that moves
        # the window by the mouse delta.

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        # --- LEFT: brand (mark + name) — matches the mockup where the
        # brand sits on the LEFT of the titlebar and the win controls
        # are on the RIGHT.
        brand = QLabel("ForgeMind Local", self)
        brand.setObjectName("BrandLabel")
        brand_mark = svg_label(self, "ai", color="#1f1e1d", size=18)
        brand_mark.setStyleSheet(
            "background: #d97757; border-radius: 5px; padding: 1px;"
        )
        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        brand_row.addWidget(brand_mark)
        brand_row.addWidget(brand)
        layout.addLayout(brand_row)

        layout.addStretch(1)

        # --- CENTER: model status (with green dot indicator) ---
        self.status_model = QLabel("(sin modelo)", self)
        layout.addWidget(self.status_model)
        sep = QLabel("·", self)
        layout.addWidget(sep)
        # green status dot (mockup L1760)
        self.status_dot = QLabel(self)
        self.status_dot.setObjectName("StatusDot")
        self.status_dot.setProperty("idle", "true")
        layout.addWidget(self.status_dot)
        sep2 = QLabel("·", self)
        layout.addWidget(sep2)
        self.status_backend = QLabel("", self)
        layout.addWidget(self.status_backend)

        layout.addStretch(1)

        # --- RIGHT: traffic-light win controls (min / max / close) ---
        for cls, tooltip in (("WinMin", "Minimizar"),
                             ("WinMax", "Maximizar"),
                             ("WinClose", "Cerrar")):
            btn = QPushButton(self)
            btn.setObjectName(cls)
            btn.setFixedSize(14, 14)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            layout.addWidget(btn)

    def set_status(self, model_text: str, backend_text: str,
                   running: bool = False) -> None:
        self.status_model.setText(model_text)
        self.status_backend.setText(backend_text)
        # Toggle the status dot color via dynamic property
        self.status_dot.setProperty("idle", "false" if running else "true")
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)


# ---------------------------------------------------------------------------
# Toast banner (bottom-right floating notification)
# ---------------------------------------------------------------------------

class ToastBanner(QFrame):
    """A floating toast notification anchored bottom-right of its parent."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ToastBanner")
        self.setFixedHeight(40)
        self.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 14, 0)
        layout.setSpacing(9)
        self.icon = QLabel("✓", self)
        self.icon.setObjectName("ToastIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon)
        self.text_lbl = QLabel("", self)
        self.text_lbl.setObjectName("ToastText")
        layout.addWidget(self.text_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._anim: QPropertyAnimation | None = None

    def show_message(self, msg: str, msec: int = 2000) -> None:
        self.text_lbl.setText(msg)
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(msec)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if not parent:
            return
        margin = 24
        self.adjustSize()
        size = self.sizeHint()
        geo = parent.geometry()
        x = geo.width() - size.width() - margin
        y = geo.height() - size.height() - margin
        self.move(max(0, x), max(0, y))


# ---------------------------------------------------------------------------
# Command palette (Ctrl+K)
# ---------------------------------------------------------------------------

@dataclass
class _CmdItem:
    cmd: str          # "goto" | "new-chat" | "start-backend" | "stop-backend" | "run-benchmark" | "apply-model"
    label: str
    screen: str | None = None
    icon: str = ""       # SVG icon name (resolved via svg_pixmap)
    shortcut: str = ""


class CommandPalette(QDialog):
    """Frameless top-anchored dialog with input + filterable command list."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("CmdPalette")
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self.commands: list[_CmdItem] = []
        self._build_commands()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Input row
        input_row = QHBoxLayout()
        input_row.setContentsMargins(18, 14, 18, 14)
        input_row.setSpacing(10)
        search_icon = svg_label(self, "search", color="#a8a499", size=17)
        input_row.addWidget(search_icon)
        self.input = QLineEdit(self)
        self.input.setObjectName("CmdInput")
        self.input.setPlaceholderText("Buscar pantallas, acciones…")
        self.input.textChanged.connect(self._filter)
        self.input.returnPressed.connect(self._activate_selected)
        input_row.addWidget(self.input, 1)
        esc = QLabel("ESC", self)
        esc.setObjectName("CmdItemKbd")
        input_row.addWidget(esc)
        outer.addLayout(input_row)

        # List
        self.listw = QListWidget(self)
        self.listw.setObjectName("CmdList")
        self.listw.itemActivated.connect(self._activate_item)
        self.listw.itemClicked.connect(self._activate_item)
        outer.addWidget(self.listw, 1)

        # Footer (two-column row: left hint + right brand text per mockup L2348)
        footer_row = QFrame(self)
        footer_row.setObjectName("CmdFooterRow")
        f_lay = QHBoxLayout(footer_row)
        f_lay.setContentsMargins(0, 0, 0, 0)
        f_lay.setSpacing(0)
        footer_left = QLabel("↑↓ navegar · Enter ejecutar", footer_row)
        footer_left.setObjectName("CmdFooter")
        f_lay.addWidget(footer_left, 1)
        footer_right = QLabel("ForgeMind Local · 100% offline", footer_row)
        footer_right.setObjectName("CmdFooterRight")
        footer_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        f_lay.addWidget(footer_right)
        outer.addWidget(footer_row)

        self._populate()
        self.setFixedSize(560, 480)

    def _build_commands(self) -> None:
        # icons are SVG names resolved via svg_pixmap (no more emoji glyphs)
        self.commands = [
            _CmdItem("goto", "Ir a Chat", "chat", "chat", "G C"),
            _CmdItem("goto", "Ir a Modelo y backend", "config", "config", "G M"),
            _CmdItem("goto", "Ir a Rendimiento", "metrics", "activity", "G P"),
            _CmdItem("goto", "Ir a Benchmark", "benchmark", "benchmark", "G B"),
            _CmdItem("goto", "Ir a Presets", "presets", "book", "G R"),
            _CmdItem("goto", "Ir a GPU / Vulkan", "gpu", "gpu", "G G"),
            _CmdItem("new-chat", "Nueva conversación", None, "plus", ""),
            _CmdItem("start-backend", "Iniciar modelo", None, "play", ""),
            _CmdItem("stop-backend", "Detener modelo", None, "stop", ""),
            _CmdItem("run-benchmark", "Correr benchmark", None, "play-circle", ""),
            _CmdItem("apply-model", "Aplicar config al backend", None, "check", ""),
        ]

    def _populate(self) -> None:
        self.listw.clear()
        for c in self.commands:
            # Build a custom item widget: [SVG icon] [label] [stretch] [kbd]
            w = QWidget(self.listw)
            w.setObjectName("CmdItemWidget")
            lay = QHBoxLayout(w)
            lay.setContentsMargins(12, 6, 12, 6)
            lay.setSpacing(11)
            ico_lbl = svg_label(w, c.icon or "search", color="#a8a499", size=17)
            ico_lbl.setObjectName("CmdItemIcon")
            lay.addWidget(ico_lbl)
            text_lbl = QLabel(c.label, w)
            text_lbl.setObjectName("CmdItemLabel")
            lay.addWidget(text_lbl, 1)
            if c.shortcut:
                kbd_lbl = QLabel(c.shortcut, w)
                kbd_lbl.setObjectName("CmdItemKbd")
                lay.addWidget(kbd_lbl)
            item = QListWidgetItem(self.listw)
            item.setSizeHint(w.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, c)
            self.listw.addItem(item)
            self.listw.setItemWidget(item, w)
        if self.listw.count():
            self.listw.setCurrentRow(0)

    def _filter(self, q: str) -> None:
        q = (q or "").lower().strip()
        first = -1
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            c: _CmdItem = item.data(Qt.ItemDataRole.UserRole)
            match = (not q) or (q in c.label.lower())
            item.setHidden(not match)
            if match and first == -1:
                first = i
        if first >= 0:
            self.listw.setCurrentRow(first)

    def move_selection(self, delta: int) -> None:
        rows = [i for i in range(self.listw.count()) if not self.listw.item(i).isHidden()]
        if not rows:
            return
        cur = self.listw.currentRow()
        if cur in rows:
            idx = rows.index(cur)
        else:
            idx = 0
        nxt = rows[(idx + delta) % len(rows)]
        self.listw.setCurrentRow(nxt)

    def _activate_selected(self) -> None:
        item = self.listw.currentItem()
        if item:
            self._activate_item(item)

    def _activate_item(self, item: QListWidgetItem) -> None:
        c: _CmdItem = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        win = self.parent()
        if win and hasattr(win, "_exec_command"):
            win._exec_command(c)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
        elif e.key() == Qt.Key.Key_Down:
            self.move_selection(1)
        elif e.key() == Qt.Key.Key_Up:
            self.move_selection(-1)
        else:
            super().keyPressEvent(e)

    def show_at(self) -> None:
        win = self.parent()
        if not win:
            self.show()
            return
        w, h = 560, 480
        geo = win.geometry()
        x = geo.x() + (geo.width() - w) // 2
        y = geo.y() + int(geo.height() * 0.14)
        self.move(max(0, x), max(0, y))
        self.input.clear()
        self._populate()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()


# ---------------------------------------------------------------------------
# Sidebar (brand + collapse + model card + new chat + nav + footer)
# ---------------------------------------------------------------------------

class Sidebar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(260)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Brand row ---
        top = QHBoxLayout()
        top.setContentsMargins(12, 0, 8, 0)
        top.setSpacing(10)
        brand_box = QHBoxLayout()
        brand_box.setSpacing(10)
        # Brand mark — orange rounded square with the checkmark SVG icon
        # (replaces the previous "✓" text glyph with the mockup's exact icon).
        mark = QFrame(self)
        mark.setFixedSize(28, 28)
        mark.setStyleSheet("background: #d97757; border-radius: 8px;")
        mark_lay = QVBoxLayout(mark)
        mark_lay.setContentsMargins(0, 0, 0, 0)
        mark_lbl = svg_label(mark, "ai", color="#1f1e1d", size=15)
        mark_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_lbl.setStyleSheet("background: transparent;")
        mark_lay.addWidget(mark_lbl)
        brand_box.addWidget(mark)
        bcol = QVBoxLayout()
        bcol.setContentsMargins(0, 0, 0, 0)
        bcol.setSpacing(0)
        bname = QLabel("ForgeMind", self)
        bname.setObjectName("BrandName")
        btag = QLabel("Local LLM lab", self)
        btag.setObjectName("BrandTag")
        bcol.addWidget(bname)
        bcol.addWidget(btag)
        brand_box.addLayout(bcol)
        top.addLayout(brand_box, 1)

        # collapse button: SVG chevron-left (mockup L1788 — points LEFT when expanded)
        self.collapse_btn = QPushButton(self)
        self.collapse_btn.setObjectName("SidebarCollapse")
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.setFixedSize(30, 30)
        chev = svg_label(self.collapse_btn, "chevron-left", color="#a8a499", size=16)
        chev_wrap = QHBoxLayout(self.collapse_btn)
        chev_wrap.setContentsMargins(0, 0, 0, 0)
        chev_wrap.addWidget(chev, 0, Qt.AlignmentFlag.AlignCenter)
        self.collapse_btn._chev = chev
        top.addWidget(self.collapse_btn)

        # expand button (chevron-right) — shown only when sidebar is collapsed
        self.expand_btn = QPushButton(self)
        self.expand_btn.setObjectName("SidebarCollapse")
        self.expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_btn.setFixedSize(30, 30)
        exp_ico = svg_label(self.expand_btn, "chevron-right", color="#a8a499", size=16)
        exp_lay = QHBoxLayout(self.expand_btn)
        exp_lay.setContentsMargins(0, 0, 0, 0)
        exp_lay.addWidget(exp_ico, 0, Qt.AlignmentFlag.AlignCenter)
        self.expand_btn.hide()
        top.addWidget(self.expand_btn)
        root.addLayout(top)

        # --- Model card ---
        self.model_card = QFrame(self)
        self.model_card.setObjectName("ModelCard")
        self.model_card.setCursor(Qt.CursorShape.PointingHandCursor)
        mc_lay = QVBoxLayout(self.model_card)
        mc_lay.setContentsMargins(12, 10, 12, 10)
        mc_lay.setSpacing(6)
        self.mc_pill = QFrame(self.model_card)
        self.mc_pill.setObjectName("StatusPill")
        self.mc_pill.setProperty("idle", "true")
        pill_lay = QHBoxLayout(self.mc_pill)
        pill_lay.setContentsMargins(8, 2, 8, 2)
        pill_lay.setSpacing(6)
        pill_dot = QLabel(self.mc_pill)
        pill_dot.setObjectName("PillDot")
        pill_lay.addWidget(pill_dot)
        pill_text = QLabel("Detenido", self.mc_pill)
        pill_lay.addWidget(pill_text)
        pill_lay.addStretch(1)
        mc_lay.addWidget(self.mc_pill)

        self.mc_name = QLabel("(sin modelo)", self.model_card)
        self.mc_name.setObjectName("McName")
        mc_lay.addWidget(self.mc_name)

        self.mc_meta = QLabel("", self.model_card)
        self.mc_meta.setObjectName("McMeta")
        mc_lay.addWidget(self.mc_meta)

        mc_wrap = QHBoxLayout()
        mc_wrap.setContentsMargins(10, 6, 10, 10)
        mc_wrap.addWidget(self.model_card)
        root.addLayout(mc_wrap)

        # --- Body (new chat + nav) ---
        body = QVBoxLayout()
        body.setContentsMargins(10, 4, 10, 10)
        body.setSpacing(6)

        self.new_chat_btn = QPushButton(self)
        self.new_chat_btn.setObjectName("NewChat")
        self.new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        nc_row = QHBoxLayout(self.new_chat_btn)
        nc_row.setContentsMargins(11, 0, 11, 0)
        nc_row.setSpacing(10)
        # Mockup L1819: new-chat uses a "+" plus icon (orange), not a paper-plane
        nc_ico = svg_label(self.new_chat_btn, "plus", color="#d97757", size=14)
        nc_ico.setObjectName("NewChatIco")
        nc_row.addWidget(nc_ico)
        self.new_chat_lbl = QLabel("Nueva conversación", self.new_chat_btn)
        self.new_chat_lbl.setStyleSheet("color: #f5f4ee; font-size: 13px; font-weight: 500; background: transparent; border: 0;")
        nc_row.addWidget(self.new_chat_lbl, 1)
        body.addWidget(self.new_chat_btn)

        nav_label = QLabel("Workspace", self)
        nav_label.setObjectName("NavSectionLabel")
        body.addWidget(nav_label)

        self.nav_buttons: dict[str, QPushButton] = {}
        # (key, label, icon name, kbd) — icons are real SVG paths from the
        # mockup (no more emoji glyphs).
        nav_items = [
            ("chat",      "Chat",           "chat",      "G C"),
            ("config",    "Modelo y backend", "config",   "G M"),
            ("metrics",   "Rendimiento",    "metrics",   "G P"),
            ("benchmark", "Benchmark",      "benchmark", "G B"),
            ("presets",   "Presets",        "presets",   "G R"),
            ("gpu",       "GPU / Vulkan",   "gpu",       "G G"),
        ]
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(1)
        for key, label, icon, kbd in nav_items:
            btn = self._make_nav_btn(key, label, icon, kbd)
            self.nav_layout.addWidget(btn)
            self.nav_buttons[key] = btn
        body.addLayout(self.nav_layout)
        body.addStretch(1)
        root.addLayout(body, 1)

        # --- Footer (RAM / t/s) ---
        foot = QFrame(self)
        foot.setObjectName("SidebarFoot")
        foot_lay = QVBoxLayout(foot)
        foot_lay.setContentsMargins(8, 8, 8, 8)
        foot_lay.setSpacing(4)
        self.foot_row = QHBoxLayout()
        self.foot_row.setContentsMargins(0, 0, 0, 0)
        self.foot_dot = QLabel("", self)
        self.foot_dot.setObjectName("FootDot")
        self.foot_text = QLabel("RAM — · — t/s", self)
        self.foot_text.setObjectName("FootRow")
        self.foot_row.addWidget(self.foot_dot)
        self.foot_row.addWidget(self.foot_text)
        self.foot_row.addStretch(1)
        foot_lay.addLayout(self.foot_row)
        root.addWidget(foot)

    def _make_nav_btn(self, key: str, label: str, icon: str, kbd: str) -> QPushButton:
        """Build a nav button with a real SVG icon (no emoji).

        The active state is driven by ``Qt.CheckState.Checked``; the
        ``NavBtn:checked`` selector flips both the icon colour and the
        optional accent indicator on the left.
        """
        btn = QPushButton(self)
        btn.setObjectName("NavBtn")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setProperty("screen", key)
        lay = QHBoxLayout(btn)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(11)
        # Icon — set initially; the ``NavBtn:checked QLabel#NavIco``
        # selector re-tints to accent (#d97757) when active.
        ico = svg_label(btn, icon, color="#a8a499", size=17)
        ico.setObjectName("NavIco")
        lay.addWidget(ico)
        lbl = QLabel(label, btn)
        lbl.setObjectName("NavLabel")
        lay.addWidget(lbl, 1)
        kbd_lbl = QLabel(kbd, btn)
        kbd_lbl.setObjectName("NavKbd")
        lay.addWidget(kbd_lbl)
        return btn

    def set_active(self, screen: str) -> None:
        """Mark the active nav button and re-tint its SVG icon.

        ``svg_label`` bakes the colour into the QPixmap at construction
        time, so we have to swap the icon pixmap here whenever the
        active screen changes — the QSS ``:checked`` selector alone
        cannot repaint a QPixmap.
        """
        for k, b in self.nav_buttons.items():
            is_active = (k == screen)
            b.setChecked(is_active)
            ico = b.findChild(QLabel, "NavIco")
            if ico is not None:
                color = "#d97757" if is_active else "#a8a499"
                ico.setPixmap(svg_pixmap(b.property("screen") or "chat",
                                         color=color, size=17))

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed:
            self.setFixedWidth(60)
            for k, b in self.nav_buttons.items():
                # hide label and kbd, center the icon
                lbl = b.findChild(QLabel, "NavLabel")
                kbd = b.findChild(QLabel, "NavKbd")
                if lbl: lbl.hide()
                if kbd: kbd.hide()
            self.model_card.hide()
            self.foot_text.hide()
            self.findChild(QLabel, "BrandName").hide()
            self.findChild(QLabel, "BrandTag").hide()
            self.collapse_btn.hide()
            self.expand_btn.show()
            # collapse new-chat label too
            if hasattr(self, "new_chat_lbl"):
                self.new_chat_lbl.hide()
        else:
            self.setFixedWidth(260)
            for b in self.nav_buttons.values():
                lbl = b.findChild(QLabel, "NavLabel")
                kbd = b.findChild(QLabel, "NavKbd")
                if lbl: lbl.show()
                if kbd: kbd.show()
            self.model_card.show()
            self.foot_text.show()
            self.findChild(QLabel, "BrandName").show()
            self.findChild(QLabel, "BrandTag").show()
            self.collapse_btn.show()
            self.expand_btn.hide()
            if hasattr(self, "new_chat_lbl"):
                self.new_chat_lbl.show()

    def set_model_card(self, *, name: str, quant: str, size_human: str,
                       ctx_size: int, running: bool) -> None:
        if name:
            self.mc_name.setText(name)
        else:
            self.mc_name.setText("(sin modelo)")
        meta_bits = []
        if quant: meta_bits.append(quant)
        if size_human: meta_bits.append(f"<b>{size_human}</b>")
        if ctx_size: meta_bits.append(f"<b>{ctx_size}</b> ctx")
        self.mc_meta.setText(" · ".join(meta_bits))
        # pill
        if running:
            self.mc_pill.setProperty("idle", "false")
            for lbl in self.mc_pill.findChildren(QLabel):
                if lbl.objectName() != "PillDot":
                    lbl.setText("Activo")
        else:
            self.mc_pill.setProperty("idle", "true")
            for lbl in self.mc_pill.findChildren(QLabel):
                if lbl.objectName() != "PillDot":
                    lbl.setText("Detenido")
        # re-polish (dynamic property)
        self.mc_pill.style().unpolish(self.mc_pill)
        self.mc_pill.style().polish(self.mc_pill)

    def set_foot_metrics(self, ram_gb: float | None, tps: float | None) -> None:
        ram_s = f"{ram_gb:.2f}" if ram_gb is not None else "—"
        tps_s = f"{tps:.1f}" if tps is not None else "—"
        self.foot_text.setText(f"RAM {ram_s} / 16 GB · {tps_s} t/s")


# ---------------------------------------------------------------------------
# Reusable widgets
# ---------------------------------------------------------------------------

class MetricTile(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("")  # we use the role=metric-tile selector
        self.setProperty("role", "metric-tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        self.lbl = QLabel(label.upper(), self)
        self.lbl.setProperty("role", "dim")
        self.lbl.setStyleSheet("font-size: 10.5px; font-weight: 600; letter-spacing: 1px; color: #787469;")
        lay.addWidget(self.lbl)
        self.val = QLabel("—", self)
        # Mockup L1256-1262: 24px Newsreader serif, weight 500, letter-spacing -0.02em
        self.val.setStyleSheet(
            "color: #f5f4ee; font-size: 24px; font-weight: 500; "
            "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; letter-spacing: -0.02em; "
            "background: transparent; border: 0;"
        )
        lay.addWidget(self.val)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.sub = QLabel("", self)
        self.sub.setProperty("role", "muted")
        self.sub.setStyleSheet("color: #a8a499; font-size: 11.5px;")
        lay.addWidget(self.sub)
        lay.addStretch(1)

    def set_value(self, value: str, *, unit: str = "", bar_pct: int | None = None, sub: str = "") -> None:
        if unit:
            self.val.setText(f"{value} <span style='font-size:13px;color:#a8a499;font-family:\"Inter\",sans-serif;letter-spacing:0'>{unit}</span>")
        else:
            self.val.setText(value)
        if bar_pct is not None:
            self.bar.setValue(max(0, min(100, bar_pct)))
        self.sub.setText(sub)


class GPUTile(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "gpu-tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(6)
        self.lbl = QLabel(label.upper(), self)
        self.lbl.setStyleSheet("color: #787469; font-size: 10.5px; font-weight: 600; letter-spacing: 1px;")
        lay.addWidget(self.lbl)
        self.val = QLabel("—", self)
        # Mockup L1500-1505: 17px Newsreader serif, weight 500
        self.val.setStyleSheet(
            "color: #f5f4ee; font-size: 17px; font-weight: 500; "
            "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; "
            "background: transparent; border: 0;"
        )
        lay.addWidget(self.val)
        self.sub = QLabel("", self)
        self.sub.setStyleSheet("color: #a8a499; font-size: 11.5px;")
        lay.addWidget(self.sub)


def _kv_row(key: str, value: str, *, accent: str | None = None) -> QFrame:
    row = QFrame()
    row.setStyleSheet("background: transparent; border-bottom: 1px solid #34312e;")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 9, 0, 9)
    lay.setSpacing(12)
    k = QLabel(key, row)
    k.setObjectName("k")
    k.setStyleSheet("color: #a8a499; font-family: 'JetBrains Mono', monospace; font-size: 12px; background: transparent; border: 0;")
    lay.addWidget(k, 1)
    v = QLabel(value, row)
    v.setObjectName("v")
    color = {"accent": "#d97757", "green": "#8ab589", "amber": "#d4a361"}.get(accent or "", "#f5f4ee")
    v.setStyleSheet(f"color: {color}; font-weight: 500; font-size: 13px; background: transparent; border: 0;")
    v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    v.setWordWrap(True)
    lay.addWidget(v, 1)
    return row


def _h3(title: str, icon: str = "") -> QLabel:
    """Card title. ``icon`` may be either an emoji glyph (legacy) or a
    recognized SVG name (resolved by the caller via _card()).
    The label uses Newsreader serif (mockup L1012-1015)."""
    h = QLabel(title)
    h.setProperty("font-role", "serif")
    h.setStyleSheet(
        "color: #f5f4ee; font-size: 16px; font-weight: 500; "
        "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; letter-spacing: -0.01em; "
        "background: transparent; border: 0;"
    )
    return h


def _h3_with_icon(title: str, svg_name: str) -> QWidget:
    """Card title row with a real SVG icon next to the serif headline."""
    row = QWidget()
    row.setStyleSheet("background: transparent; border: 0;")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    ico = svg_label(row, svg_name, color="#d97757", size=18)
    ico.setStyleSheet("background: transparent; border: 0;")
    lay.addWidget(ico, 0, Qt.AlignmentFlag.AlignVCenter)
    h = QLabel(title)
    h.setStyleSheet(
        "color: #f5f4ee; font-size: 16px; font-weight: 500; "
        "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; letter-spacing: -0.01em; "
        "background: transparent; border: 0;"
    )
    lay.addWidget(h, 1, Qt.AlignmentFlag.AlignVCenter)
    return row


def _p(text: str, *, dim: bool = False) -> QLabel:
    p = QLabel(text)
    p.setWordWrap(True)
    p.setStyleSheet(
        f"color: {'#a8a499' if dim else '#d8d4c8'}; font-size: 13px; background: transparent; border: 0;"
        + (" margin-left: 28px;" if dim else "")
    )
    return p


def _card(title: str, icon: str, desc: str = "") -> tuple[QFrame, QVBoxLayout]:
    """Card factory. ``icon`` is an SVG name (resolved via _h3_with_icon).

    Falls back to the old emoji behavior if the name is not in _NAV_ICONS.
    """
    f = QFrame()
    f.setProperty("role", "card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(22, 22, 22, 22)
    lay.setSpacing(10)
    if icon and icon in _NAV_ICONS:
        lay.addWidget(_h3_with_icon(title, icon))
    else:
        lay.addWidget(_h3(title, icon))
    if desc:
        lay.addWidget(_p(desc, dim=True))
    return f, lay


def _icon_button(label: str, svg_name: str, *, primary: bool = False,
                 ghost: bool = False, danger: bool = False) -> QPushButton:
    """Button with an SVG icon + label (replaces emoji-prefixed text)."""
    btn = QPushButton()
    if primary:
        btn.setProperty("primary", True)
    if ghost:
        btn.setProperty("ghost", True)
    if danger:
        btn.setProperty("danger", True)
    lay = QHBoxLayout(btn)
    lay.setContentsMargins(14, 0, 14, 0)
    lay.setSpacing(8)
    icon_color = "#1f1e1d" if primary else ("#d88a83" if danger else "#d97757")
    ico = svg_label(btn, svg_name, color=icon_color, size=14)
    ico.setStyleSheet("background: transparent; border: 0;")
    lay.addWidget(ico, 0, Qt.AlignmentFlag.AlignVCenter)
    lbl = QLabel(label, btn)
    lbl.setStyleSheet(
        f"color: {'#1f1e1d' if primary else '#f5f4ee'}; "
        "font-size: 13px; font-weight: 500; background: transparent; border: 0;"
    )
    lay.addWidget(lbl, 1, Qt.AlignmentFlag.AlignVCenter)
    lay.addStretch(1)
    return btn


# ---------------------------------------------------------------------------
# Screen 1: Chat
# ---------------------------------------------------------------------------

class ChatScreen(QWidget):
    """Streaming chat with preset pill + composer + message bubbles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_preset_key: str = "diario"
        self._pending_meta: dict[str, Any] | None = None
        self._messages_dom: list[dict[str, Any]] = []  # role, label, html

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Messages area ---
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("ChatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.msgs_container = QWidget()
        self.msgs_container.setObjectName("MessagesContainer")
        # Wrap messages in a centered container so we can cap the max-width
        # to 820px (mockup L636) on wide screens.
        self.msgs_layout = QVBoxLayout(self.msgs_container)
        self.msgs_layout.setContentsMargins(24, 24, 24, 16)
        self.msgs_layout.setSpacing(22)
        self.msgs_layout.addStretch(1)
        self.scroll.setWidget(self.msgs_container)
        # Center the messages container with a horizontal stretch on each side
        # so the content stays capped at ~820px even when the window is wide.
        scroll_outer = QHBoxLayout()
        scroll_outer.setContentsMargins(0, 0, 0, 0)
        scroll_outer.setSpacing(0)
        scroll_outer.addStretch(1)
        scroll_outer.addWidget(self.scroll, 0)
        scroll_outer.addStretch(1)
        # We can't easily add a stretch around a QScrollArea that owns its
        # own widget — instead, cap the scroll's max width and let the
        # parent layout center it.
        self.scroll.setMaximumWidth(820)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.scroll, 1)

        # --- Composer (also capped at 820px) ---
        composer_outer = QHBoxLayout()
        composer_outer.setContentsMargins(0, 0, 0, 0)
        composer_outer.setSpacing(0)
        composer_outer.addStretch(1)
        composer_wrap = QFrame(self)
        composer_wrap.setMaximumWidth(820)
        composer_wrap.setStyleSheet("background: transparent; border: 0;")
        composer_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        cw_lay = QVBoxLayout(composer_wrap)
        cw_lay.setContentsMargins(0, 8, 0, 16)
        cw_lay.setSpacing(8)

        comp = QFrame(composer_wrap)
        comp.setObjectName("Composer")
        comp_lay = QVBoxLayout(comp)
        comp_lay.setContentsMargins(12, 10, 12, 8)
        comp_lay.setSpacing(4)
        self._composer_frame = comp
        self.edit = QPlainTextEdit(comp)
        self.edit.setObjectName("ComposerEdit")
        self.edit.setPlaceholderText("Escribí tu prompt… (Enter para enviar)")
        # Auto-grow: min 56, max 200 — set via _on_text_changed
        self.edit.setFixedHeight(56)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        comp_lay.addWidget(self.edit)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        # preset pill: orange dot + label + chevron (matches the mockup)
        self.preset_pill = QPushButton(comp)
        self.preset_pill.setObjectName("PresetPill")
        self.preset_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        pp_row = QHBoxLayout(self.preset_pill)
        pp_row.setContentsMargins(9, 0, 10, 0)
        pp_row.setSpacing(6)
        pp_dot = QFrame(self.preset_pill)
        pp_dot.setFixedSize(6, 6)
        pp_dot.setStyleSheet("background: #d97757; border-radius: 3px; border: 0;")
        pp_row.addWidget(pp_dot)
        self.preset_pill_label = QLabel("Diario", self.preset_pill)
        self.preset_pill_label.setStyleSheet(
            "color: #d8d4c8; font-size: 12px; font-weight: 500; background: transparent; border: 0;"
        )
        pp_row.addWidget(self.preset_pill_label)
        pp_chev = svg_label(self.preset_pill, "preset-dot", color="#787469", size=12)
        pp_row.addWidget(pp_chev)
        bar.addWidget(self.preset_pill)
        # clear btn (trash SVG icon, no more emoji glyph)
        self.clear_btn = QPushButton(comp)
        self.clear_btn.setObjectName("ToolBtn")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setToolTip("Limpiar conversación")
        self.clear_btn.setFixedSize(30, 30)
        cl_lay = QHBoxLayout(self.clear_btn)
        cl_lay.setContentsMargins(0, 0, 0, 0)
        cl_lay.addWidget(svg_label(self.clear_btn, "trash", color="#a8a499", size=15),
                         0, Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self.clear_btn)
        bar.addStretch(1)
        # send btn: paper-plane SVG (no more ➤ glyph)
        self.send_btn = QPushButton(comp)
        self.send_btn.setObjectName("SendBtn")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setToolTip("Enviar (Enter)")
        self.send_btn.setFixedSize(32, 32)
        sb_lay = QHBoxLayout(self.send_btn)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.addWidget(svg_label(self.send_btn, "send", color="#1f1e1d", size=15),
                         0, Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self.send_btn)
        comp_lay.addLayout(bar)
        cw_lay.addWidget(comp)

        # Hint — kbd-styled chips (mockup L924-934)
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 0, 0)
        hint_row.setSpacing(6)
        hint_row.addStretch(1)
        for k, t in [("Enter", "enviar"),
                     ("Shift+Enter", "nueva línea"),
                     ("Ctrl+K", "comandos")]:
            kbd = QLabel(k, self)
            kbd.setStyleSheet(
                "color: #787469; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; "
                "background: #151413; border: 1px solid #34312e; border-radius: 4px; "
                "padding: 1px 5px;"
            )
            hint_row.addWidget(kbd)
            txt = QLabel(t, self)
            txt.setStyleSheet("color: #787469; font-size: 11px; background: transparent; border: 0;")
            hint_row.addWidget(txt)
        hint_row.addStretch(1)
        cw_lay.addLayout(hint_row)
        composer_outer.addWidget(composer_wrap, 0)
        composer_outer.addStretch(1)
        root.addLayout(composer_outer)

        # Seed the initial greeting (matches mockup exactly).
        self._add_message(
            "ai",
            self._preset_label("diario"),
            "<p>¡Hola! Soy <b>ForgeMind Local</b>. Estoy corriendo 100% en tu máquina, sin nube ni claves. "
            "Puedo ayudarte a:</p>"
            "<ul><li>Comparar modelos GGUF (Gemma, Qwen3, Phi-4…)</li>"
            "<li>Medir tokens/s, RAM y latencia real</li>"
            "<li>Probar 10 prompts en español con el benchmark</li></ul>"
            "<p>Empezá escribiendo abajo o elegí una sugerencia.</p>",
            meta={"first_token": "1.2", "tps": "18.4", "chars": "312"},
        )

    # ---- public API ----

    def cycle_preset(self) -> None:
        keys = [p.key for p in PRESETS]
        idx = keys.index(self._current_preset_key) if self._current_preset_key in keys else 0
        self.set_preset(keys[(idx + 1) % len(keys)])

    def set_preset(self, key: str) -> None:
        for p in PRESETS:
            if p.key == key:
                self._current_preset_key = key
                # Update the pill label, keep dot + chevron intact
                if hasattr(self, "preset_pill_label"):
                    self.preset_pill_label.setText(p.label)
                else:
                    self.preset_pill.setText(f"●  {p.label}  ▾")
                return

    def current_preset(self) -> str:
        return self._current_preset_key

    def current_prompt(self) -> str:
        return self.edit.toPlainText().strip()

    def clear_input(self) -> None:
        self.edit.clear()

    def clear_messages(self) -> None:
        # remove all msg bubble widgets (preserve stretch at end)
        while self.msgs_layout.count() > 1:
            item = self.msgs_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def add_user_message(self, text: str) -> None:
        self._add_message("user", "Tú", _html_escape(text), meta=None)

    def add_streaming_ai_message(self, preset_key: str) -> None:
        """Create an empty AI message bubble (will be filled by append_stream)."""
        self._add_message("ai", self._preset_label(preset_key), "", meta=None)

    def append_stream(self, chunk: str) -> None:
        if not chunk:
            return
        if not self._messages_dom or self._messages_dom[-1].get("role") != "ai":
            return
        meta = self._messages_dom[-1]
        meta["body"] = (meta.get("body") or "") + chunk
        body_lbl: QLabel = meta["body_label"]
        bubble = meta.get("bubble")
        # On first chunk: hide the typing indicator and reveal the body label
        if bubble is not None and getattr(bubble, "_typing", None) is not None:
            typing = bubble._typing
            if hasattr(typing, "_dot_timer"):
                typing._dot_timer.stop()
            typing.hide()
            typing.deleteLater()
            bubble._typing = None
            body_lbl.show()
        body_lbl.setText(meta["body"])
        QApplication.processEvents()
        self._scroll_to_bottom()

    def finalize_stream(self, meta_dict: dict[str, Any]) -> None:
        if not self._messages_dom or self._messages_dom[-1].get("role") != "ai":
            return
        meta = self._messages_dom[-1]
        meta_lbl: QLabel = meta["meta_label"]
        first = meta_dict.get("first_token_sec")
        tps = meta_dict.get("tokens_per_sec_proxy")
        chars = meta_dict.get("char_count")
        meta_lbl.setText(
            f"1er token: {first:.3f}s  ·  {tps:.2f} t/s  ·  {chars} chars"
            if first is not None and tps is not None else
            f"{chars} chars"
        )

    def append_error(self, msg: str) -> None:
        self._add_message("ai", self._preset_label(self._current_preset_key),
                          f"<p style='color:#d88a83'>[error] {_html_escape(msg)}</p>", meta=None)

    # ---- internals ----

    def _preset_label(self, key: str) -> str:
        for p in PRESETS:
            if p.key == key:
                return p.label
        return "Diario"

    def _add_message(self, role: str, name: str, body_html: str, meta: dict[str, Any] | None) -> None:
        bubble = QFrame(self.msgs_container)
        bubble.setObjectName("MsgBubble")
        bubble.setStyleSheet("background: transparent; border: 0;")
        blay = QHBoxLayout(bubble)
        blay.setContentsMargins(0, 0, 0, 0)
        blay.setSpacing(14)
        blay.setAlignment(Qt.AlignmentFlag.AlignTop)

        avatar = QFrame(bubble)
        avatar.setProperty("role", role)
        avatar.setObjectName("MsgAvatar")
        al = QVBoxLayout(avatar)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)
        # Avatar SVG icon (mockup L1891, L2508): user = person, ai = checkmark-doc
        av_icon_name = "user" if role == "user" else "ai"
        av_color = "#d8d4c8" if role == "user" else "#1f1e1d"
        a_lbl = svg_label(avatar, av_icon_name, color=av_color, size=15)
        a_lbl.setObjectName("MsgAvatarLabel")
        a_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        a_lbl.setStyleSheet("background: transparent; border: 0;")
        al.addWidget(a_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        blay.addWidget(avatar)

        content = QFrame(bubble)
        content.setStyleSheet("background: transparent; border: 0;")
        clay = QVBoxLayout(content)
        clay.setContentsMargins(0, 2, 0, 0)
        clay.setSpacing(4)

        # name row (with optional preset pill on the right + action buttons)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        n = QLabel(name, content)
        n.setObjectName("MsgName")
        name_row.addWidget(n)
        if role == "ai":
            mp = QLabel(f"Preset: {name}", content)
            mp.setObjectName("MsgPreset")
            name_row.addWidget(mp)
        name_row.addStretch(1)
        # Message action buttons (mockup L1911-1914, L2555-2558): copy + regenerate
        actions = QFrame(content)
        actions.setObjectName("MsgActions")
        actions.setStyleSheet("background: transparent; border: 0;")
        actions_lay = QHBoxLayout(actions)
        actions_lay.setContentsMargins(0, 0, 0, 0)
        actions_lay.setSpacing(2)
        copy_btn = QToolButton(actions)
        copy_btn.setObjectName("MsgAction")
        copy_btn.setIcon(svg_icon("copy", color="#a8a499", size=14))
        copy_btn.setIconSize(QSize(14, 14))
        copy_btn.setToolTip("Copiar respuesta")
        actions_lay.addWidget(copy_btn)
        if role == "ai":
            regen_btn = QToolButton(actions)
            regen_btn.setObjectName("MsgAction")
            regen_btn.setIcon(svg_icon("regen", color="#a8a499", size=14))
            regen_btn.setIconSize(QSize(14, 14))
            regen_btn.setToolTip("Regenerar respuesta")
            actions_lay.addWidget(regen_btn)
            regen_btn.clicked.connect(lambda: self._on_regen_action(bubble))
        copy_btn.clicked.connect(lambda: self._on_copy_action(bubble))
        # Hover-reveal: hide by default, show on bubble enter
        actions.setVisible(False)
        bubble._actions = actions
        # Override enter/leave on the bubble to toggle visibility
        _orig_enter = bubble.enterEvent
        _orig_leave = bubble.leaveEvent
        def _enter(ev):
            actions.setVisible(True)
            if _orig_enter: _orig_enter(ev)
        def _leave(ev):
            actions.setVisible(False)
            if _orig_leave: _orig_leave(ev)
        bubble.enterEvent = _enter
        bubble.leaveEvent = _leave
        name_row.addWidget(actions)
        clay.addLayout(name_row)

        # body — for AI streaming with no body yet, show typing indicator
        if role == "ai" and not body_html:
            body_lbl = QLabel("", content)
            body_lbl.setObjectName("MsgBody")
            body_lbl.setWordWrap(True)
            body_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body_lbl.setTextFormat(Qt.TextFormat.RichText)
            # Build typing indicator (3 dots) as the bubble content until first chunk
            typing = QFrame(content)
            typing.setObjectName("TypingIndicator")
            typing_lay = QHBoxLayout(typing)
            typing_lay.setContentsMargins(0, 0, 0, 0)
            typing_lay.setSpacing(4)
            dots = []
            for _ in range(3):
                d = QFrame(typing)
                d.setObjectName("TypingDot")
                d.setFixedSize(6, 6)
                typing_lay.addWidget(d)
                dots.append(d)
            typing._dots = dots
            typing._dot_idx = 0
            typing._dot_timer = QTimer(typing)
            typing._dot_timer.timeout.connect(lambda: self._tick_typing(typing))
            typing._dot_timer.start(380)
            # Replace the body label with the typing widget visually
            clay.addWidget(typing)
            clay.addWidget(body_lbl)
            body_lbl.hide()
            bubble._typing = typing
        else:
            body_lbl = QLabel(body_html or "<span style='color:#787469'>…</span>", content)
            body_lbl.setObjectName("MsgBody")
            body_lbl.setWordWrap(True)
            body_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body_lbl.setTextFormat(Qt.TextFormat.RichText)
            clay.addWidget(body_lbl)
            bubble._typing = None

        # meta (only for AI)
        meta_lbl = QLabel("", content)
        meta_lbl.setObjectName("MsgMeta")
        if meta is not None:
            meta_lbl.setText(
                f"1er token: {meta.get('first_token','?')}s  ·  "
                f"{meta.get('tps','?')} t/s  ·  {meta.get('chars','?')} chars"
            )
        clay.addWidget(meta_lbl)

        blay.addWidget(content, 1)
        # Insert before the final stretch
        self.msgs_layout.insertWidget(self.msgs_layout.count() - 1, bubble)

        self._messages_dom.append({
            "role": role,
            "name": name,
            "body": body_html,
            "body_label": body_lbl,
            "meta_label": meta_lbl,
            "bubble": bubble,
        })
        self._scroll_to_bottom()

    def _tick_typing(self, typing: QFrame) -> None:
        """Advance the typing indicator: highlight one dot at a time."""
        dots = getattr(typing, "_dots", None) or []
        if not dots:
            return
        idx = getattr(typing, "_dot_idx", 0)
        for i, d in enumerate(dots):
            d.setProperty("active", "true" if i == idx else "false")
            d.style().unpolish(d)
            d.style().polish(d)
        typing._dot_idx = (idx + 1) % len(dots)

    def _on_copy_action(self, bubble: QFrame) -> None:
        """Copy the body text of the given bubble to the clipboard."""
        # find the body label
        body_lbl = bubble.findChild(QLabel, "MsgBody")
        if body_lbl is None:
            return
        text = body_lbl.text()
        # strip HTML tags for clipboard
        import re
        plain = re.sub(r"<[^>]+>", "", text)
        QApplication.clipboard().setText(plain)

    def _on_regen_action(self, bubble: QFrame) -> None:
        """Trigger a regenerate of the last user prompt."""
        win = self.window()
        if win is not None and hasattr(win, "_on_regen_last"):
            win._on_regen_last(bubble)

    def _scroll_to_bottom(self) -> None:
        QApplication.processEvents()
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# Screen 2: Config (Modelo + Backend + Log console, three cards)
# ---------------------------------------------------------------------------

class ConfigScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend_ref: Any = None  # injected from MainWindow

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 48)
        root.setSpacing(16)

        # --- Card 1: Modelo GGUF ---
        card_model, m_lay = _card("Modelo GGUF", "package",
                                   "Seleccioná el archivo .gguf y los parámetros de inferencia.")
        form1 = QGridLayout()
        form1.setHorizontalSpacing(16)
        form1.setVerticalSpacing(12)

        form1.addWidget(_make_field_label("Archivo .gguf"), 0, 0, 1, 2)
        gguf_row = QHBoxLayout()
        self.in_gguf_path = QLineEdit()
        self.in_gguf_path.setPlaceholderText("C:\\ruta\\a\\modelo.Q4_K_M.gguf")
        gguf_row.addWidget(self.in_gguf_path, 1)
        self.btn_pick_gguf = QPushButton("Elegir")
        gguf_row.addWidget(self.btn_pick_gguf)
        self.btn_auto_gguf = QPushButton("Auto-detectar")
        self.btn_auto_gguf.setProperty("ghost", True)
        gguf_row.addWidget(self.btn_auto_gguf)
        form1.addLayout(gguf_row, 1, 0, 1, 2)
        self.lbl_gguf_info = QLabel("Cuant: ? · Tamaño: ?")
        self.lbl_gguf_info.setStyleSheet("color: #787469; font-family: 'JetBrains Mono', monospace; font-size: 11px; background: transparent; border: 0;")
        form1.addWidget(self.lbl_gguf_info, 2, 0, 1, 2)

        form1.addWidget(_make_field_label("Nombre amigable"), 3, 0)
        self.in_name = QLineEdit("modelo-sin-nombre")
        form1.addWidget(self.in_name, 3, 1)

        form1.addWidget(_make_field_label("Contexto (tokens)"), 4, 0)
        self.sb_ctx = QSpinBox(); self.sb_ctx.setRange(256, 32768); self.sb_ctx.setValue(4096); self.sb_ctx.setSingleStep(256)
        form1.addWidget(self.sb_ctx, 4, 1)

        form1.addWidget(_make_field_label("Threads CPU"), 5, 0)
        self.sb_threads = QSpinBox(); self.sb_threads.setRange(1, 64); self.sb_threads.setValue(8)
        form1.addWidget(self.sb_threads, 5, 1)

        form1.addWidget(_make_field_label("Max tokens respuesta"), 6, 0)
        self.sb_max = QSpinBox(); self.sb_max.setRange(16, 8192); self.sb_max.setValue(512); self.sb_max.setSingleStep(32)
        form1.addWidget(self.sb_max, 6, 1)

        # Sliders row: temp / top_p / repeat penalty (with inline accent value + value box)
        self.lbl_temp_field = _make_field_label("Temperatura")
        form1.addWidget(self.lbl_temp_field, 7, 0)
        temp_row = QHBoxLayout()
        self.slider_temp = QSlider(Qt.Orientation.Horizontal); self.slider_temp.setRange(0, 200); self.slider_temp.setValue(70)
        self.lbl_temp_val = QLabel("0.70")
        self.lbl_temp_val.setObjectName("SliderValue")
        temp_row.addWidget(self.slider_temp, 1)
        temp_row.addWidget(self.lbl_temp_val)
        form1.addLayout(temp_row, 7, 1)

        self.lbl_topp_field = _make_field_label("Top-p")
        form1.addWidget(self.lbl_topp_field, 8, 0)
        topp_row = QHBoxLayout()
        self.slider_topp = QSlider(Qt.Orientation.Horizontal); self.slider_topp.setRange(0, 100); self.slider_topp.setValue(95)
        self.lbl_topp_val = QLabel("0.95")
        self.lbl_topp_val.setObjectName("SliderValue")
        topp_row.addWidget(self.slider_topp, 1)
        topp_row.addWidget(self.lbl_topp_val)
        form1.addLayout(topp_row, 8, 1)

        self.lbl_rep_field = _make_field_label("Repeat penalty")
        form1.addWidget(self.lbl_rep_field, 9, 0)
        rep_row = QHBoxLayout()
        self.slider_rep = QSlider(Qt.Orientation.Horizontal); self.slider_rep.setRange(50, 200); self.slider_rep.setValue(110)
        self.lbl_rep_val = QLabel("1.10")
        self.lbl_rep_val.setObjectName("SliderValue")
        rep_row.addWidget(self.slider_rep, 1)
        rep_row.addWidget(self.lbl_rep_val)
        form1.addLayout(rep_row, 9, 1)
        m_lay.addLayout(form1)

        apply_row = QHBoxLayout()
        self.btn_apply_model = _icon_button("Aplicar config al backend", "check", primary=True)
        apply_row.addWidget(self.btn_apply_model)
        self.btn_refresh_info = QPushButton("Refrescar info")
        self.btn_refresh_info.setProperty("ghost", True)
        apply_row.addWidget(self.btn_refresh_info)
        apply_row.addStretch(1)
        m_lay.addLayout(apply_row)

        root.addWidget(card_model)

        # --- Card 2: Backend ---
        card_be, b_lay = _card("Backend", "monitor",
                                "Elegí cómo correr el modelo. Recomendado: <code>llama-cli</code>.")
        form2 = QGridLayout()
        form2.setHorizontalSpacing(16)
        form2.setVerticalSpacing(12)
        form2.addWidget(_make_field_label("Tipo de backend"), 0, 0, 1, 2)
        self.cmb_backend_kind = QComboBox()
        # Mockup L2033-2038: descriptive labels (keep the bare key as item data
        # so the existing logic still works).
        for key, desc in [
            ("llama_cli",   "llama-cli (subprocess, default)"),
            ("llama_server","llama-server (HTTP local)"),
            ("llama_cpp",   "llama-cpp binding Python"),
            ("ollama",      "ollama (servicio externo)"),
        ]:
            self.cmb_backend_kind.addItem(desc, key)
        form2.addWidget(self.cmb_backend_kind, 1, 0, 1, 2)
        form2.addWidget(_make_field_label("llama-cli path"), 2, 0)
        self.in_llama_cli = QLineEdit()
        self.in_llama_cli.setPlaceholderText("(vacío = auto-detectar en PATH)")
        self.in_llama_cli_btn = QPushButton("Auto-detectar")
        self.in_llama_cli_btn.setProperty("ghost", True)
        cli_row = QHBoxLayout()
        cli_row.addWidget(self.in_llama_cli, 1)
        cli_row.addWidget(self.in_llama_cli_btn)
        form2.addLayout(cli_row, 2, 1)
        form2.addWidget(_make_field_label("llama-server path"), 3, 0)
        self.in_llama_server = QLineEdit()
        self.in_llama_server.setPlaceholderText("(vacío = auto-detectar en PATH)")
        self.in_llama_server_btn = QPushButton("Auto-detectar")
        self.in_llama_server_btn.setProperty("ghost", True)
        srv_row = QHBoxLayout()
        srv_row.addWidget(self.in_llama_server, 1)
        srv_row.addWidget(self.in_llama_server_btn)
        form2.addLayout(srv_row, 3, 1)
        form2.addWidget(_make_field_label("Modo de cómputo"), 4, 0)
        self.cmb_mode = QComboBox(); self.cmb_mode.addItems(["cpu", "vulkan"])
        form2.addWidget(self.cmb_mode, 4, 1)
        form2.addWidget(_make_field_label("GPU layers (0 = off)"), 5, 0)
        self.sb_gpu_layers = QSpinBox(); self.sb_gpu_layers.setRange(0, 999); self.sb_gpu_layers.setValue(0)
        form2.addWidget(self.sb_gpu_layers, 5, 1)
        form2.addWidget(_make_field_label("Ollama URL"), 6, 0)
        self.in_ollama_url = QLineEdit(DEFAULT_OLLAMA_URL)
        form2.addWidget(self.in_ollama_url, 6, 1)
        b_lay.addLayout(form2)

        be_row = QHBoxLayout()
        self.btn_test_backend = _icon_button("Probar backend", "search-lg")
        be_row.addWidget(self.btn_test_backend)
        self.btn_start_backend = _icon_button("Iniciar modelo", "play", primary=True)
        be_row.addWidget(self.btn_start_backend)
        self.btn_stop_backend = _icon_button("Detener", "stop", danger=True)
        be_row.addWidget(self.btn_stop_backend)
        be_row.addStretch(1)
        b_lay.addLayout(be_row)
        root.addWidget(card_be)

        # --- Card 3: Log console ---
        card_log, l_lay = _card("Log del backend", "doc", "")
        self.log_console = QTextBrowser()
        self.log_console.setObjectName("LogConsole")
        self.log_console.setOpenExternalLinks(False)
        self.log_console.setReadOnly(True)
        # QTextBrowser has no MaximumBlockCount; cap via documentMaximumBlockCount
        try:
            self.log_console.document().setMaximumBlockCount(2000)
        except Exception:
            pass
        l_lay.addWidget(self.log_console)
        root.addWidget(card_log, 1)

        # wire sliders to value labels (both inline field label + value box)
        self.slider_temp.valueChanged.connect(lambda v: self._on_slider_changed("temp", v))
        self.slider_topp.valueChanged.connect(lambda v: self._on_slider_changed("topp", v))
        self.slider_rep.valueChanged.connect(lambda v: self._on_slider_changed("rep", v))
        # initial sync
        self._on_slider_changed("temp", self.slider_temp.value())
        self._on_slider_changed("topp", self.slider_topp.value())
        self._on_slider_changed("rep", self.slider_rep.value())

    # ---- helpers ----

    def _on_slider_changed(self, which: str, v: int) -> None:
        # Field labels are UPPERCASE per mockup (Qt QSS doesn't support text-transform).
        if which == "temp":
            val = f"{v/100:.2f}"
            self.lbl_temp_val.setText(val)
            self.lbl_temp_field.setText(f"TEMPERATURA  ·  <span style='color:#d97757;font-family:\"JetBrains Mono\",monospace;font-weight:500'>{val}</span>")
        elif which == "topp":
            val = f"{v/100:.2f}"
            self.lbl_topp_val.setText(val)
            self.lbl_topp_field.setText(f"TOP-P  ·  <span style='color:#d97757;font-family:\"JetBrains Mono\",monospace;font-weight:500'>{val}</span>")
        elif which == "rep":
            val = f"{v/100:.2f}"
            self.lbl_rep_val.setText(val)
            self.lbl_rep_field.setText(f"REPEAT PENALTY  ·  <span style='color:#d97757;font-family:\"JetBrains Mono\",monospace;font-weight:500'>{val}</span>")

    def log(self, msg: str, *, level: str = "info") -> None:
        """Append a log line. ``level`` is one of: info / ok / warn / err.

        Color codes per mockup L1322-1340.
        """
        ts = time.strftime("%H:%M:%S")
        color = {
            "info": "#a8a499",
            "ok":   "#8ab589",
            "warn": "#d4a361",
            "err":  "#d88a83",
        }.get(level, "#a8a499")
        # QTextBrowser accepts HTML
        line = (
            f"<span style='color:#787469'>[{ts}]</span> "
            f"<span style='color:{color}'>{_html_escape(msg)}</span>"
        )
        self.log_console.append(line)

    def gather_model_config(self) -> ModelConfig:
        # backend_kind comes from the combo's user data (the bare key)
        backend_kind = self.cmb_backend_kind.currentData() or "llama_cli"
        return ModelConfig(
            name=self.in_name.text().strip() or "modelo-sin-nombre",
            gguf_path=self.in_gguf_path.text().strip(),
            ctx_size=int(self.sb_ctx.value()),
            threads=int(self.sb_threads.value()),
            max_tokens=int(self.sb_max.value()),
            temperature=float(self.slider_temp.value()) / 100,
            top_p=float(self.slider_topp.value()) / 100,
            repeat_penalty=float(self.slider_rep.value()) / 100,
            mode=self.cmb_mode.currentText(),
            gpu_layers=int(self.sb_gpu_layers.value()),
            backend_kind=backend_kind,
            llama_cli_path=self.in_llama_cli.text().strip(),
            llama_server_path=self.in_llama_server.text().strip(),
            ollama_url=self.in_ollama_url.text().strip() or DEFAULT_OLLAMA_URL,
        )

    def apply_to_widgets(self, cfg: ModelConfig) -> None:
        self.in_name.setText(cfg.name)
        self.in_gguf_path.setText(cfg.gguf_path)
        self.sb_ctx.setValue(cfg.ctx_size)
        self.sb_threads.setValue(cfg.threads)
        self.sb_max.setValue(cfg.max_tokens)
        self.slider_temp.setValue(int(cfg.temperature * 100))
        self.slider_topp.setValue(int(cfg.top_p * 100))
        self.slider_rep.setValue(int(cfg.repeat_penalty * 100))
        self.cmb_mode.setCurrentText(cfg.mode)
        self.sb_gpu_layers.setValue(cfg.gpu_layers)
        # find the combo index whose data matches cfg.backend_kind
        for i in range(self.cmb_backend_kind.count()):
            if self.cmb_backend_kind.itemData(i) == cfg.backend_kind:
                self.cmb_backend_kind.setCurrentIndex(i)
                break
        self.in_llama_cli.setText(cfg.llama_cli_path)
        self.in_llama_server.setText(cfg.llama_server_path)
        self.in_ollama_url.setText(cfg.ollama_url or DEFAULT_OLLAMA_URL)

    def refresh_gguf_info(self) -> None:
        cfg = ModelConfig(gguf_path=self.in_gguf_path.text().strip())
        if not cfg.gguf_path:
            self.lbl_gguf_info.setText("Cuant: ? · Tamaño: ?")
            return
        if not cfg.exists():
            self.lbl_gguf_info.setText(f"Ruta no existe")
            return
        self.lbl_gguf_info.setText(f"Cuant: {cfg.quant or '?'} · Tamaño: {cfg.size_human}")


def _make_field_label(text: str) -> QLabel:
    # Mockup L1055-1059: field-label uses `text-transform: uppercase`.
    # Qt QSS does NOT support text-transform, so we uppercase in Python.
    l = QLabel(text.upper())
    l.setStyleSheet(
        "color: #a8a499; font-size: 11.5px; font-weight: 500; "
        "letter-spacing: 0.06em; background: transparent; border: 0;"
    )
    return l


# ---------------------------------------------------------------------------
# Screen 3: Metrics
# ---------------------------------------------------------------------------

class MetricsScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 48)
        root.setSpacing(16)

        card, lay = _card("Rendimiento en vivo", "activity",
                          "Métricas del backend activo y del sistema. Click en Refrescar para actualizar.")
        self.tiles_row = QHBoxLayout()
        self.tiles_row.setSpacing(12)
        self.tile_rss = MetricTile("RSS proceso")
        self.tile_rss.bar.setProperty("tone", "amber")
        self.tile_tps = MetricTile("Tokens/s")
        self.tile_tps.bar.setProperty("tone", "green")
        self.tile_first = MetricTile("1er token")
        self.tile_first.bar.setProperty("tone", "blue")
        self.tile_ram = MetricTile("RAM disponible")
        self.tile_ram.bar.setProperty("tone", "amber")
        for t in (self.tile_rss, self.tile_tps, self.tile_first, self.tile_ram):
            # Re-polish so tone::chunk applies
            t.bar.style().unpolish(t.bar)
            t.bar.style().polish(t.bar)
            self.tiles_row.addWidget(t, 1)
        lay.addLayout(self.tiles_row)

        btn_row = QHBoxLayout()
        self.btn_refresh = _icon_button("Refrescar ahora", "refresh", primary=True)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        root.addWidget(card)

        # KV list card
        kv_card, kv_lay = _card("Detalle de la última corrida", "search-lg", "")
        self.kv_rows: list[QFrame] = []
        for _ in range(8):
            row = _kv_row("?", "?")
            self.kv_rows.append(row)
            kv_lay.addWidget(row)
        kv_lay.addStretch(1)
        root.addWidget(kv_card, 1)

    def refresh(self, *, rss_gb: float | None, tps: float | None,
                first_token: float | None, ram_avail_gb: float | None,
                cfg: ModelConfig, running: bool, status: dict) -> None:
        self.tile_rss.set_value(f"{rss_gb:.2f}" if rss_gb is not None else "—", unit="GB",
                                bar_pct=int((rss_gb or 0) / 16 * 100),
                                sub="De 16 GB totales.")
        self.tile_tps.set_value(f"{tps:.1f}" if tps is not None else "—", unit="t/s",
                                bar_pct=int((tps or 0) / 40 * 100),
                                sub="Proxy (chars/4 ÷ elapsed).")
        self.tile_first.set_value(f"{first_token:.2f}" if first_token is not None else "—", unit="s",
                                   bar_pct=int((first_token or 0) / 4 * 100),
                                   sub="Latencia a primer chunk.")
        self.tile_ram.set_value(f"{ram_avail_gb:.2f}" if ram_avail_gb is not None else "—", unit="GB",
                                bar_pct=int((ram_avail_gb or 0) / 16 * 100),
                                sub="Tras cargar el modelo.")

        rows = [
            ("modelo_disco", cfg.size_human or "?", None),
            ("ctx_configurado", str(cfg.ctx_size), None),
            ("elapsed_sec", f"{status.get('_last_generate',{}).get('elapsed_sec','—')}", "accent"),
            ("char_count", str(status.get('_last_generate',{}).get('char_count','—')), None),
            ("tokens_per_sec", f"{tps:.1f}" if tps else "—", "green"),
            ("first_token_sec", f"{first_token:.3f}" if first_token else "—", "accent"),
            ("cpu_vulkan", f"{cfg.mode} · gpu_layers={cfg.gpu_layers}", None),
            ("estado", "ACTIVO" if running else "DETENIDO", "green" if running else None),
        ]
        for row, (k, v, accent) in zip(self.kv_rows, rows):
            _set_kv_row(row, k, str(v), accent=accent)


# ---------------------------------------------------------------------------
# Screen 4: Benchmark (form + splitter history)
# ---------------------------------------------------------------------------

class BenchmarkScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected_paths: set[str] = set()
        self._last_compare: dict[str, Any] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 48)
        root.setSpacing(16)

        # Card 1: run benchmark
        card, lay = _card("Benchmark local", "benchmark",
                          "10 prompts fijos en español. Mismos prompts → misma base para comparar modelos.")
        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.addWidget(_make_field_label("Archivo de prompts"), 0, 0)
        self.in_prompts_file = QLineEdit(DEFAULT_PROMPTS_FILE)
        form.addWidget(self.in_prompts_file, 0, 1)
        form.addWidget(_make_field_label("Etiqueta"), 1, 0)
        self.in_label = QLineEdit("gemma4-12b-q4km")
        form.addWidget(self.in_label, 1, 1)
        lay.addLayout(form)

        run_row = QHBoxLayout()
        self.btn_run = _icon_button("Correr benchmark", "play", primary=True)
        run_row.addWidget(self.btn_run)
        self.btn_open = _icon_button("Abrir carpeta resultados", "folder", ghost=True)
        run_row.addWidget(self.btn_open)
        run_row.addStretch(1)
        lay.addLayout(run_row)
        root.addWidget(card)

        # Card 2: History + detail
        hist_card, hist_lay = _card("Historial y comparativa", "list",
                                     "Ctrl+click para seleccionar 2 o más corridas y comparar.")
        # header row (mockup L2197-2201): "Corridas" label + refresh icon-btn on same row)
        header_row = QHBoxLayout()
        runs_header = QLabel("Corridas")
        runs_header.setStyleSheet("color: #a8a499; font-size: 11.5px; font-weight: 600; background: transparent; border: 0;")
        header_row.addWidget(runs_header)
        header_row.addStretch(1)
        self.btn_refresh_runs = QPushButton(hist_card)
        self.btn_refresh_runs.setObjectName("ToolBtn")
        self.btn_refresh_runs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_runs.setFixedSize(30, 30)
        ref_lay = QHBoxLayout(self.btn_refresh_runs)
        ref_lay.setContentsMargins(0, 0, 0, 0)
        ref_lay.addWidget(svg_label(self.btn_refresh_runs, "refresh", color="#a8a499", size=15),
                          0, Qt.AlignmentFlag.AlignCenter)
        header_row.addWidget(self.btn_refresh_runs)
        hist_lay.addLayout(header_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # left: list of runs (object name set so the QSS item:selected with left-bar applies)
        self.runs_widget = QFrame()
        self.runs_widget.setStyleSheet("background: #282623; border: 1px solid #34312e; border-radius: 10px;")
        runs_lay = QVBoxLayout(self.runs_widget)
        runs_lay.setContentsMargins(0, 0, 0, 0)
        runs_lay.setSpacing(0)
        self.runs_list = QListWidget()
        self.runs_list.setObjectName("RunsList")
        self.runs_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.runs_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.runs_list.itemDoubleClicked.connect(self._on_run_double_clicked)
        runs_lay.addWidget(self.runs_list, 1)
        splitter.addWidget(self.runs_widget)

        # right: detail
        self.detail_widget = QFrame()
        self.detail_widget.setStyleSheet("background: #282623; border: 1px solid #34312e; border-radius: 10px;")
        detail_lay = QVBoxLayout(self.detail_widget)
        detail_lay.setContentsMargins(18, 14, 18, 14)
        detail_lay.setSpacing(10)
        self.detail_title = QLabel("Selecciona una corrida")
        # Mockup L1404-1405: 15px Newsreader serif headline
        self.detail_title.setStyleSheet(
            "color: #f5f4ee; font-size: 15px; font-weight: 500; "
            "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; letter-spacing: -0.01em; "
            "background: transparent; border: 0;"
        )
        detail_lay.addWidget(self.detail_title)
        # Mockup L1395-1428: styled compare-table via QTableWidget
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(5)
        self.detail_table.setHorizontalHeaderLabels(["#", "Título", "elapsed (s)", "t/s (proxy)", "chars"])
        self.detail_table.horizontalHeader().setStretchLastSection(False)
        self.detail_table.horizontalHeader().setDefaultSectionSize(120)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.detail_table.setAlternatingRowColors(False)
        self.detail_table.setShowGrid(False)
        self.detail_table.setStyleSheet(
            """
            QTableWidget {
                background: transparent; border: 0; color: #d8d4c8;
                font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 12px;
            }
            QTableWidget::item { padding: 6px 8px; border-bottom: 1px solid #34312e; }
            QTableWidget::item:hover { background: rgba(255,255,255,0.045); }
            QHeaderView::section {
                color: #a8a499; font-family: 'Inter', sans-serif; font-size: 11.5px;
                font-weight: 600; padding: 6px 8px; background: transparent; border: 0;
                border-bottom: 1px solid #34312e; text-transform: uppercase;
            }
            QTableWidget::item[winner="true"] { color: #8ab589; font-weight: 600; }
            """
        )
        detail_lay.addWidget(self.detail_table, 1)
        cmp_row = QHBoxLayout()
        self.btn_compare = _icon_button("Comparar seleccionados", "compare")
        cmp_row.addWidget(self.btn_compare)
        self.btn_save_compare = _icon_button("Guardar comparación", "save", ghost=True)
        self.btn_save_compare.setEnabled(False)
        cmp_row.addWidget(self.btn_save_compare)
        cmp_row.addStretch(1)
        detail_lay.addLayout(cmp_row)
        splitter.addWidget(self.detail_widget)
        splitter.setSizes([320, 700])
        hist_lay.addWidget(splitter, 1)
        root.addWidget(hist_card, 1)

    def _on_selection_changed(self) -> None:
        items = self.runs_list.selectedItems()
        if len(items) == 1:
            item = items[0]
            path = item.data(1)  # see _reload_runs
            if path:
                self._show_run_detail(path)
        else:
            self.detail_title.setText(f"{len(items)} corridas seleccionadas")
            self.detail_table.setRowCount(0)

    def _on_run_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(1)
        if path:
            self._show_run_detail(path)

    def _populate_table(self, rows: list[tuple[str, str, str, str]],
                        *, title: str, highlight_best_tps: bool = False) -> None:
        """Populate the compare-table with the given rows.

        Each row = (idx, title, elapsed, tps, chars). When ``highlight_best_tps``
        is True, the row with the highest t/s is marked as winner (green).
        """
        self.detail_title.setText(title)
        self.detail_table.setRowCount(len(rows))
        best_idx = -1
        if highlight_best_tps and rows:
            best_val = -1.0
            for i, (_, _, _, tps, _) in enumerate(rows):
                try:
                    v = float(tps)
                    if v > best_val:
                        best_val = v
                        best_idx = i
                except (ValueError, TypeError):
                    pass
        for i, (idx, t, elapsed, tps, chars) in enumerate(rows):
            cells = [idx, t, str(elapsed), str(tps), str(chars)]
            for col, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if col == 0:
                    item.setForeground(QColor("#787469"))
                if col in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if highlight_best_tps and i == best_idx:
                    item.setData(Qt.ItemDataRole.UserRole, "winner")
                    # apply the winner attribute via style (Qt item property)
                self.detail_table.setItem(i, col, item)
        self.detail_table.resizeColumnsToContents()
        if self.detail_table.columnWidth(1) > 320:
            self.detail_table.setColumnWidth(1, 320)

    def _show_run_detail(self, path: str) -> None:
        run = load_run(path) if path else None
        if not run:
            self.detail_table.setRowCount(1)
            self.detail_table.setItem(0, 0, QTableWidgetItem("(no se pudo cargar)"))
            return
        be = run.get("backend") or {}
        cfg = be.get("config") or {}
        items = run.get("items") or []
        rows = []
        for i, it in enumerate(items, 1):
            m = it.get("metrics") or {}
            tps = m.get("tokens_per_sec_proxy")
            tps_s = f"{tps:.2f}" if isinstance(tps, (int, float)) else "-"
            rows.append((str(i), it.get("title") or "", m.get("elapsed_sec") or "-", tps_s, m.get("char_count") or "-"))
        title = f"{run.get('label')} · {run.get('timestamp','')[:16]}"
        # Show summary line as a one-row above the table is not trivial with
        # QTableWidget — instead we encode the metadata in the title.
        wall = (run.get("totals") or {}).get("wall_time_sec")
        sub = f"  ·  wall {wall}s · backend {be.get('backend')}"
        self._populate_table(rows, title=title + sub)

    def _reload_runs(self, results_dir: str) -> None:
        self.runs_list.clear()
        runs = list_runs(results_dir)
        for r in runs:
            ts_short = (r.get("timestamp") or "").split("T")[-1][:8]
            date = (r.get("timestamp") or "").split("T")[0]
            label = r.get("label") or "?"
            quant = r.get("quant") or "?"
            size = r.get("size_human") or "?"
            display = f"{label}\n{quant} · {size} · {date} {ts_short}"
            it = QListWidgetItem(display)
            it.setData(1, r.get("path"))
            self.runs_list.addItem(it)

    def _selected_paths(self) -> list[str]:
        out: list[str] = []
        for it in self.runs_list.selectedItems():
            p = it.data(1)
            if p:
                out.append(p)
        return out

    def do_compare(self, results_dir: str) -> None:
        paths = self._selected_paths()
        if len(paths) < 2:
            QMessageBox.information(None, "Comparar corridas",
                                    "Selecciona 2 o más corridas (Ctrl+click).")
            return
        cmp_data = compare_runs(paths)
        if not cmp_data:
            self.detail_table.setRowCount(1)
            self.detail_table.setItem(0, 0, QTableWidgetItem("(no se pudo comparar)"))
            self.btn_save_compare.setEnabled(False)
            return
        self._last_compare = cmp_data
        # Render the compare as a table: each row = one prompt, columns = run labels
        runs = cmp_data.get("runs", [])
        items_per_run = [r.get("items") or [] for r in runs]
        max_items = max((len(items) for items in items_per_run), default=0)
        self.detail_table.setColumnCount(1 + len(runs))
        headers = ["# / Prompt"] + [r.get("label") or r.get("timestamp", "?") for r in runs]
        self.detail_table.setHorizontalHeaderLabels(headers)
        self.detail_table.setRowCount(max_items)
        for i in range(max_items):
            # Row header: prompt title (from the first run that has it)
            title = ""
            for items in items_per_run:
                if i < len(items) and items[i].get("title"):
                    title = items[i]["title"]
                    break
            self.detail_table.setItem(i, 0, QTableWidgetItem(f"{i+1} · {title}"))
            for j, items in enumerate(items_per_run, start=1):
                if i < len(items):
                    m = items[i].get("metrics") or {}
                    tps = m.get("tokens_per_sec_proxy")
                    tps_s = f"{tps:.2f}" if isinstance(tps, (int, float)) else "-"
                    cell = QTableWidgetItem(f"{tps_s} t/s")
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.detail_table.setItem(i, j, cell)
                else:
                    self.detail_table.setItem(i, j, QTableWidgetItem("-"))
        self.detail_title.setText(f"Comparación · {len(runs)} corridas")
        self.btn_save_compare.setEnabled(True)

    def do_save_compare(self, results_dir: str) -> None:
        if not self._last_compare:
            QMessageBox.information(None, "Guardar", "Primero corré 'Comparar seleccionados'.")
            return
        try:
            _, mp = save_compare(self._last_compare, results_dir=results_dir)
        except Exception as e:
            QMessageBox.warning(None, "Guardar", f"Error: {e}")
            return
        self.btn_save_compare.setEnabled(False)
        self._reload_runs(results_dir)

    def render_summary(self, r: dict[str, Any]) -> None:
        be = r.get("backend") or {}
        cfg = be.get("config") or {}
        items = r.get("items") or []
        # Restore the 5-column layout (was overwritten by do_compare)
        self.detail_table.setColumnCount(5)
        self.detail_table.setHorizontalHeaderLabels(["#", "Título", "elapsed (s)", "t/s (proxy)", "chars"])
        rows = []
        for i, it in enumerate(items, 1):
            m = it.get("metrics") or {}
            tps = m.get("tokens_per_sec_proxy")
            tps_s = f"{tps:.2f}" if isinstance(tps, (int, float)) else "-"
            rows.append((str(i), it.get("title") or "", m.get("elapsed_sec") or "-", tps_s, m.get("char_count") or "-"))
        wall = (r.get("totals") or {}).get("wall_time_sec")
        title = f"{r.get('label')} · benchmark reciente  ·  wall {wall}s · backend {be.get('backend')}"
        self._populate_table(rows, title=title)


# ---------------------------------------------------------------------------
# Screen 5: Presets (7 cards)
# ---------------------------------------------------------------------------

class PresetsScreen(QWidget):
    on_picked = pyqtSignal(str)  # preset key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 48)
        root.setSpacing(16)

        card, lay = _card("Presets de uso", "book",
                          "Contexto breve y consistente. La calidad real depende del modelo + cuantización + parámetros.")
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)
        lay.addLayout(self.grid)
        self._cards: dict[str, QFrame] = {}
        self._populate()
        root.addWidget(card, 1)

    def _populate(self) -> None:
        for i, p in enumerate(PRESETS):
            row, col = divmod(i, 2)
            card = QFrame()
            card.setObjectName("PresetCard")
            card.setProperty("active", "false")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            clay = QVBoxLayout(card)
            clay.setContentsMargins(16, 14, 16, 14)
            clay.setSpacing(6)
            title = QLabel(p.label, card)
            title.setObjectName("PresetTitle")
            clay.addWidget(title)
            # Mockup L2396-2402: short marketing description (not the full system prompt)
            desc_text = p.desc if p.desc else p.system[:140] + ("…" if len(p.system) > 140 else "")
            desc = QLabel(desc_text, card)
            desc.setObjectName("PresetDesc")
            desc.setWordWrap(True)
            clay.addWidget(desc)
            params_row = QHBoxLayout()
            for txt in (f"temp {p.temperature}", f"top_p {p.top_p}", f"max {p.max_tokens}"):
                pl = QLabel(txt, card)
                pl.setObjectName("PresetParams")
                pl.setStyleSheet("color: #787469; background: #151413; border: 1px solid #34312e; border-radius: 4px; padding: 1px 6px; font-family: 'JetBrains Mono', monospace; font-size: 10.5px;")
                params_row.addWidget(pl)
            params_row.addStretch(1)
            clay.addLayout(params_row)
            card.mousePressEvent = self._make_click(p.key)
            self._cards[p.key] = card
            self.grid.addWidget(card, row, col)

    def _make_click(self, key: str):
        def handler(ev):
            self.on_picked.emit(key)
        return handler

    def set_active(self, key: str) -> None:
        for k, c in self._cards.items():
            c.setProperty("active", "true" if k == key else "false")
            c.style().unpolish(c); c.style().polish(c)


# ---------------------------------------------------------------------------
# Screen 6: GPU / Vulkan
# ---------------------------------------------------------------------------

class GPUScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 48)
        root.setSpacing(16)

        # GPU tiles card
        card, lay = _card("GPU y Vulkan", "gpu",
                          "Detección automática de hardware. Vulkan NO cambia la inteligencia del modelo.")
        self.tiles_row = QHBoxLayout()
        self.tiles_row.setSpacing(12)
        self.tile_gpu = GPUTile("GPU detectada")
        self.tile_dll = GPUTile("vulkan-1.dll")
        self.tile_vk = GPUTile("Vulkan disponible")
        for t in (self.tile_gpu, self.tile_dll, self.tile_vk):
            self.tiles_row.addWidget(t, 1)
        lay.addLayout(self.tiles_row)

        btn_row = QHBoxLayout()
        self.btn_redetect = _icon_button("Re-detectar", "refresh", primary=True)
        btn_row.addWidget(self.btn_redetect)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        root.addWidget(card)

        # Warnings card
        warn_card, wlay = _card("Avisos importantes", "alert", "")
        wlay.addWidget(_p("Vulkan / GPU offload es <b>experimental</b> en AMD Radeon RX550 4 GB. "
                           "Si falla, volvé a CPU — no rompe la app."))
        wlay.addWidget(_p("La calidad de la respuesta depende del <b>modelo + cuantización + parámetros</b>, "
                           "no del backend. Vulkan solo afecta velocidad."))
        wlay.addWidget(_p("Para RX550 con 4 GB VRAM, se recomienda <code>gpu_layers=0</code> (CPU puro) "
                           "o como máximo <code>gpu_layers=10</code> para modelos Q4 de 7B-12B."))
        root.addWidget(warn_card, 1)

    def refresh(self, summary: dict[str, Any]) -> None:
        gpus = summary.get("gpus") or []
        if gpus:
            g = gpus[0]
            vram = (g.get("adapter_ram_bytes") or 0) / (1024 ** 3)
            self.tile_gpu.val.setText(g.get("name") or "—")
            sub = f"VRAM: {vram:.2f} GB" if vram else "VRAM: ?"
            if g.get("driver_version"):
                sub += f" · Driver {g['driver_version']}"
            self.tile_gpu.sub.setText(sub)
        else:
            self.tile_gpu.val.setText("(ninguna)")
            self.tile_gpu.sub.setText("")

        vk = summary.get("vulkan") or {}
        if vk.get("vulkan_dll_present"):
            self.tile_dll.val.setText("Presente")
            self.tile_dll.val.setStyleSheet(
                "color: #8ab589; font-size: 17px; font-weight: 500; "
                "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; background: transparent; border: 0;"
            )
            self.tile_dll.sub.setText("C:\\Windows\\System32\\vulkan-1.dll")
        else:
            self.tile_dll.val.setText("Ausente")
            self.tile_dll.val.setStyleSheet(
                "color: #d88a83; font-size: 17px; font-weight: 500; "
                "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; background: transparent; border: 0;"
            )
            self.tile_dll.sub.setText("")

        avail = vk.get("available")
        if avail:
            self.tile_vk.val.setText("Sí")
            self.tile_vk.val.setStyleSheet(
                "color: #8ab589; font-size: 17px; font-weight: 500; "
                "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; background: transparent; border: 0;"
            )
        else:
            self.tile_vk.val.setText("No")
            self.tile_vk.val.setStyleSheet(
                "color: #d4a361; font-size: 17px; font-weight: 500; "
                "font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; background: transparent; border: 0;"
            )
        info = vk.get("info") or {}
        sub_bits = []
        if info.get("api_version"):
            sub_bits.append(f"API {info['api_version']}")
        if info.get("driver_version"):
            sub_bits.append(f"Driver {info['driver_version']}")
        if vk.get("vulkaninfo_installed") is not None:
            sub_bits.append(f"vulkaninfo: {'instalado' if vk.get('vulkaninfo_installed') else 'no'}")
        self.tile_vk.sub.setText(" · ".join(sub_bits) or "(sin info)")


# ---------------------------------------------------------------------------
# Main window — TitleBar + Sidebar + Stacked screens
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    SCREENS = ["chat", "config", "metrics", "benchmark", "presets", "gpu"]

    def __init__(self, initial_settings: dict[str, Any] | None = None) -> None:
        """Build the main window.

        ``initial_settings`` is the dict produced by
        :func:`app.auto_config.first_run_setup` — it contains every
        auto-detected path (llama-cli, llama-server, .gguf) plus the
        last known inference params. When provided we hydrate the
        Config screen from it and (if the user opted-in) auto-start
        the backend so the user can chat immediately.
        """
        # Frameless: no native Windows titlebar, no native menubar.
        # We use a fully custom TitleBar (38 px) with traffic-light
        # buttons (min/max/close), matching the mockup's "Claude
        # desktop" visual DNA. We keep the window on the taskbar via
        # the Window flag override below.
        super().__init__()
        self.setWindowTitle("ForgeMind Local")
        self.resize(1180, 800)
        # Use FramelessWindowHint but keep system menu available
        # (alt+space) and the taskbar entry. Hint: WindowStaysOnTopHint
        # is intentionally NOT used.
        from PyQt6.QtCore import Qt as _Qt
        self.setWindowFlags(
            _Qt.WindowType.Window
            | _Qt.WindowType.FramelessWindowHint
        )
        # Apply the global QSS to the QApplication so all selectors
        # (#BrandName, #Header, #Chip, QFrame[role="card"], etc.) take
        # effect. Without this the QSS defined above is dead code.
        app = QApplication.instance()
        # Load bundled fonts (Newsreader) BEFORE applying the QSS so the
        # serif font-family resolves to the bundled copy on every platform.
        _load_bundled_fonts()
        if app is not None:
            app.setStyleSheet(QSS)
        # Allow Aero-snap on Windows when user drags to screen edge.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # Drag state for the frameless titlebar
        self._drag_pos: tuple[int, int] | None = None
        self._resize_edge: int = 0  # bitmask: 1=L, 2=R, 4=T, 8=B
        # Background download runner (used by the first-run wizard).
        # Declared up-front so Pyright doesn't complain when the
        # wizard creates and connects to it.
        self._download_runner: DownloadRunner | None = None

        # --- Hydrate from settings (or fall back to defaults) ---
        from . import auto_config
        self._auto_config = auto_config
        if initial_settings is None:
            initial_settings = auto_config.load_settings()
        self._settings = auto_config._merge_defaults(
            initial_settings, auto_config._DEFAULT_SETTINGS,
        )
        cfg_dict = self._settings["model"]
        initial_model_cfg = ModelConfig(
            name=cfg_dict.get("name") or "modelo-sin-nombre",
            gguf_path=cfg_dict.get("gguf_path") or "",
            ctx_size=int(cfg_dict.get("ctx_size") or 4096),
            threads=int(cfg_dict.get("threads") or 8),
            max_tokens=int(cfg_dict.get("max_tokens") or 512),
            temperature=float(cfg_dict.get("temperature") or 0.7),
            top_p=float(cfg_dict.get("top_p") or 0.95),
            repeat_penalty=float(cfg_dict.get("repeat_penalty") or 1.1),
            mode=str(cfg_dict.get("mode") or "cpu"),
            gpu_layers=int(cfg_dict.get("gpu_layers") or 0),
            backend_kind=str(cfg_dict.get("backend_kind") or "llama_cli"),
            llama_cli_path=cfg_dict.get("llama_cli_path") or "",
            llama_server_path=cfg_dict.get("llama_server_path") or "",
            ollama_url=cfg_dict.get("ollama_url") or DEFAULT_OLLAMA_URL,
        )

        # Backend (LlamaBackend with the hydrated ModelConfig)
        self.backend = self._make_backend(initial_model_cfg)
        self._chat_history: list[dict[str, str]] = []
        self._current_runner: GenerateRunner | None = None
        self._last_metrics: dict[str, Any] = {}
        self._sidebar_collapsed = False

        # First-run UX: detect whether we auto-found everything or
        # whether the user needs to point us at a model / llama-cli.
        self._first_run_needs_setup = (
            not initial_model_cfg.gguf_path
            or not (initial_model_cfg.llama_cli_path or auto_config.find_llama_cli())
        )
        # True when settings.json did NOT exist before __init__ ran —
        # i.e. this is the very first launch and we just wrote it.
        self._first_run_was_just_run = not auto_config.settings_path().exists()

        # --- Build UI ---
        # NOTE: no native QMenuBar — the mockup uses a fully custom
        # chrome (frameless window + custom TitleBar with traffic-
        # light buttons). The "Archivo/Ayuda" actions live in the
        # Command Palette instead (Ctrl+K → "Guardar configuración",
        # "Salir", etc.).
        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.titlebar = TitleBar()
        v.addWidget(self.titlebar)

        # --- Wire the traffic-light win controls (min/max/close) ---
        # They live on the titlebar (created above) but the actions
        # apply to this QMainWindow, so we connect them here.
        win_min = self.titlebar.findChild(QPushButton, "WinMin")
        win_max = self.titlebar.findChild(QPushButton, "WinMax")
        win_close = self.titlebar.findChild(QPushButton, "WinClose")
        if win_min is not None:
            win_min.clicked.connect(self.showMinimized)
        if win_max is not None:
            win_max.clicked.connect(self._toggle_maximized)
        if win_close is not None:
            win_close.clicked.connect(self.close)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        v.addLayout(body, 1)

        # Sidebar
        self.sidebar = Sidebar()
        body.addWidget(self.sidebar)

        # Main area
        self.main_area = QFrame()
        self.main_area.setStyleSheet("background: #1a1918; border: 0;")
        ma_lay = QVBoxLayout(self.main_area)
        ma_lay.setContentsMargins(0, 0, 0, 0)
        ma_lay.setSpacing(0)
        body.addWidget(self.main_area, 1)

        # Header
        self.header = QFrame()
        self.header.setObjectName("Header")
        self.header.setFixedHeight(52)
        h_lay = QHBoxLayout(self.header)
        h_lay.setContentsMargins(16, 0, 16, 0)
        h_lay.setSpacing(12)
        h_left = QHBoxLayout()
        h_left.setSpacing(10)
        self.bread_title = QLabel("Chat", self.header)
        self.bread_title.setObjectName("BreadTitle")
        h_left.addWidget(self.bread_title)
        self.bread_sep = QLabel("·", self.header)
        self.bread_sep.setStyleSheet("color: #787469; background: transparent; border: 0;")
        h_left.addWidget(self.bread_sep)
        self.bread_sub = QLabel("Streaming on-device · primera respuesta en 1.2s", self.header)
        self.bread_sub.setObjectName("BreadSub")
        h_left.addWidget(self.bread_sub)
        h_left.addStretch(1)
        h_lay.addLayout(h_left, 1)

        # Header right: chips + cmdk
        h_right = QHBoxLayout()
        h_right.setSpacing(6)
        self.chip_model = self._make_chip("Gemma 4 12B", accent=True)
        self.chip_backend = self._make_chip("llama-cli", accent=False)
        h_right.addWidget(self.chip_model)
        h_right.addWidget(self.chip_backend)
        self.btn_cmdk = QPushButton(self.header)
        self.btn_cmdk.setObjectName("ToolBtn")
        self.btn_cmdk.setToolTip("Paleta de comandos (Ctrl+K)")
        self.btn_cmdk.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cmdk.setFixedSize(30, 30)
        cmdk_lay = QHBoxLayout(self.btn_cmdk)
        cmdk_lay.setContentsMargins(0, 0, 0, 0)
        cmdk_lay.addWidget(svg_label(self.btn_cmdk, "search", color="#a8a499", size=16),
                           0, Qt.AlignmentFlag.AlignCenter)
        h_right.addWidget(self.btn_cmdk)
        h_lay.addLayout(h_right)
        ma_lay.addWidget(self.header)

        # Stacked content
        self.stack = QStackedWidget()
        self.chat_screen = ChatScreen()
        self.config_screen = ConfigScreen()
        self.metrics_screen = MetricsScreen()
        self.bench_screen = BenchmarkScreen()
        self.presets_screen = PresetsScreen()
        self.gpu_screen = GPUScreen()
        for s in (self.chat_screen, self.config_screen, self.metrics_screen,
                  self.bench_screen, self.presets_screen, self.gpu_screen):
            self.stack.addWidget(s)
        ma_lay.addWidget(self.stack, 1)

        # Toast
        self.toast = ToastBanner(root)

        # Command palette (lazy)
        self._palette: CommandPalette | None = None

        # --- Wire signals ---
        self._wire_sidebar()
        self._wire_chat()
        self._wire_config()
        self._wire_metrics()
        self._wire_bench()
        self._wire_presets()
        self._wire_gpu()
        self._wire_header()

        # Initial state
        self._switch_screen("chat")
        self.refresh_sidebar_model_card()
        self.refresh_metrics()
        self.refresh_gpu()
        self.refresh_status_chips()
        self.refresh_bench_runs()
        # Hide the native QStatusBar — the mockup uses only toasts + the sidebar
        # footer for status feedback (no bottom status bar).
        self.statusBar().setVisible(False)

        # Restore default config widgets
        self.config_screen.apply_to_widgets(self.backend.config)

        # --- Auto-start backend if settings asked for it ---
        # We do this AFTER the UI is built so refresh_*() have targets.
        ui_settings = self._settings.get("ui", {}) if isinstance(self._settings, dict) else {}
        if ui_settings.get("auto_start_backend") and not self._first_run_needs_setup:
            QTimer.singleShot(150, self._auto_start_backend)

        # --- First-run wizard (only on the very first launch) ---
        if self._first_run_needs_setup:
            QTimer.singleShot(250, self._show_first_run_wizard)

        # Start a periodic timer to refresh metrics + foot
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(2500)

    # ---------- Frameless window: drag + double-click on titlebar ----------
    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            tb = getattr(self, "titlebar", None)
            if tb is not None and tb.underMouse():
                self._drag_pos = (
                    event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if (
            self._drag_pos is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        # Double-click on titlebar = toggle maximize (Claude desktop style)
        tb = getattr(self, "titlebar", None)
        if tb is not None and tb.underMouse():
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        # Keep the titlebar's status in sync when window is minimized
        # or restored. (No-op for now; placeholder for future use.)
        super().changeEvent(event)

    # ---------- factory ----------
    def _make_backend(self, config: ModelConfig):
        try:
            if config.backend_kind == "ollama":
                return OllamaBackend(config)
        except Exception:
            pass
        return LlamaBackend(config)

    # ---------- menu ----------
    # NOTE: QMenuBar removed. The mockup uses a fully frameless window
    # with a custom TitleBar (38 px) and traffic-light buttons. The
    # "Archivo/Ayuda" actions live in the Command Palette (Ctrl+K):
    #   - "Guardar configuración"  → guarda settings.json
    #   - "Cargar configuración"   → carga settings.json desde disco
    #   - "Salir"                  → cierra la app
    #   - "Acerca de…"             → muestra info de versión

    # ---------- helpers ----------
    def _make_chip(self, text: str, *, accent: bool) -> QFrame:
        chip = QFrame()
        chip.setObjectName("Chip")
        chip.setProperty("accent", "true" if accent else "false")
        chip.setFixedHeight(26)
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(9, 0, 10, 0)
        lay.setSpacing(6)
        dot = QLabel(chip)
        dot.setObjectName("ChipDot")
        lay.addWidget(dot)
        lbl = QLabel(text, chip)
        lbl.setObjectName("ChipLabel")
        lay.addWidget(lbl)
        return chip

    def set_chip_text(self, chip: QFrame, text: str) -> None:
        for c in chip.findChildren(QLabel):
            if c.objectName() == "ChipLabel":
                c.setText(text)
                return

    def _show_toast(self, msg: str, msec: int = 2000) -> None:
        self.toast.show_message(msg, msec)

    # ---------- wiring ----------
    def _wire_sidebar(self) -> None:
        for key, btn in self.sidebar.nav_buttons.items():
            btn.clicked.connect(lambda _, k=key: self._switch_screen(k))
        self.sidebar.new_chat_btn.clicked.connect(self._on_new_chat)
        self.sidebar.model_card.mousePressEvent = lambda ev: self._switch_screen("config")
        self.sidebar.collapse_btn.clicked.connect(self._toggle_sidebar)
        self.sidebar.expand_btn.clicked.connect(self._toggle_sidebar)

    def _wire_chat(self) -> None:
        cs = self.chat_screen
        cs.send_btn.clicked.connect(self._on_send_chat)
        cs.clear_btn.clicked.connect(self._on_clear_chat)
        cs.preset_pill.clicked.connect(self._on_cycle_preset)
        cs.edit.textChanged.connect(self._on_composer_text_changed)
        # enter to send
        cs.edit.installEventFilter(self)

    def _wire_config(self) -> None:
        cs = self.config_screen
        cs.btn_pick_gguf.clicked.connect(self._on_pick_gguf)
        cs.btn_auto_gguf.clicked.connect(self._on_auto_detect_gguf)
        cs.in_llama_cli_btn.clicked.connect(self._on_auto_detect_cli)
        cs.in_llama_server_btn.clicked.connect(self._on_auto_detect_server)
        cs.btn_apply_model.clicked.connect(self._on_apply_model)
        cs.btn_refresh_info.clicked.connect(cs.refresh_gguf_info)
        cs.btn_test_backend.clicked.connect(self._on_test_backend)
        cs.btn_start_backend.clicked.connect(self._on_start_backend)
        cs.btn_stop_backend.clicked.connect(self._on_stop_backend)
        cs.in_gguf_path.textChanged.connect(cs.refresh_gguf_info)
        # Use currentData to receive the bare backend key (not the descriptive text)
        cs.cmb_backend_kind.currentIndexChanged.connect(
            lambda i: self._on_backend_kind_changed(cs.cmb_backend_kind.itemData(i) or "llama_cli")
        )

    def _wire_metrics(self) -> None:
        self.metrics_screen.btn_refresh.clicked.connect(self.refresh_metrics)

    def _wire_bench(self) -> None:
        bs = self.bench_screen
        bs.btn_run.clicked.connect(self._on_run_benchmark)
        bs.btn_open.clicked.connect(self._on_open_results)
        bs.btn_refresh_runs.clicked.connect(self.refresh_bench_runs)
        bs.btn_compare.clicked.connect(lambda: bs.do_compare(DEFAULT_RESULTS_DIR))
        bs.btn_save_compare.clicked.connect(lambda: bs.do_save_compare(DEFAULT_RESULTS_DIR))

    def _wire_presets(self) -> None:
        self.presets_screen.on_picked.connect(self._on_pick_preset_from_screen)

    def _wire_gpu(self) -> None:
        self.gpu_screen.btn_redetect.clicked.connect(self.refresh_gpu)

    def _wire_header(self) -> None:
        self.btn_cmdk.clicked.connect(self._open_palette)

    # ---------- keyboard shortcuts ----------
    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is self.chat_screen.edit and ev.type() == ev.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self._on_send_chat()
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if (e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)) and \
                e.key() == Qt.Key.Key_K:
            self._open_palette()
            return
        # vim-style G+letter when palette is closed
        if self._palette is None or not self._palette.isVisible():
            if e.key() == Qt.Key.Key_G and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self._await_next_key()
                return
        super().keyPressEvent(e)

    def _await_next_key(self) -> None:
        """Wait for the next keystroke (up to 1.2s) and use it as a G-prefix shortcut.

        The one-shot ``_GOnce`` event filter is installed on the
        QApplication and removes itself on the first KeyPress — that
        guarantees a single capture without leaking the filter or
        depending on a flag the timer can never reset cleanly.
        """
        app = QApplication.instance()
        if app is None:
            return
        # Disarm any previous (stale) filter first.
        prev = getattr(self, "_g_filter_obj", None)
        if prev is not None:
            try:
                app.removeEventFilter(prev)
            except Exception:
                pass
            self._g_filter_obj = None

        # Map modifier-free letter key → screen.
        m = {
            Qt.Key.Key_C: "chat", Qt.Key.Key_M: "config",
            Qt.Key.Key_P: "metrics", Qt.Key.Key_B: "benchmark",
            Qt.Key.Key_R: "presets", Qt.Key.Key_G: "gpu",
        }
        outer = self

        class _GOnce(QObject):
            def eventFilter(s, obj, ev):  # noqa: N802
                if ev.type() == ev.Type.KeyPress:
                    screen = m.get(ev.key())
                    if screen:
                        outer._switch_screen(screen)
                    # Always remove after first key — either matched or not.
                    QApplication.instance().removeEventFilter(s)
                    outer._g_filter_obj = None
                    return True
                return False

        self._g_filter_obj = _GOnce()
        app.installEventFilter(self._g_filter_obj)
        # Safety net: if no key arrives within 1.2 s, drop the filter.
        QTimer.singleShot(1200, self._disarm_g_filter)

    def _disarm_g_filter(self) -> None:
        obj = getattr(self, "_g_filter_obj", None)
        if obj is None:
            return
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(obj)
            except Exception:
                pass
        self._g_filter_obj = None

    def _toggle_maximized(self) -> None:
        """Toggle between normal and maximized window state."""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ---------- screen switching ----------
    def _switch_screen(self, screen_id: str) -> None:
        idx = self.SCREENS.index(screen_id)
        self.stack.setCurrentIndex(idx)
        self.sidebar.set_active(screen_id)
        titles = {
            "chat": ("Chat", "Streaming on-device · primera respuesta en 1.2s"),
            "config": ("Modelo y backend", "Configuración del GGUF y del runner"),
            "metrics": ("Rendimiento", "RAM, tokens/s y latencia en vivo"),
            "benchmark": ("Benchmark", "10 prompts ES · historial y comparativa"),
            "presets": ("Presets", "Contextos de uso y parámetros sugeridos"),
            "gpu": ("GPU / Vulkan", "Detección AMD y heurística Vulkan"),
        }
        t, s = titles.get(screen_id, ("", ""))
        self.bread_title.setText(t)
        self.bread_sub.setText(s)
        if screen_id == "metrics":
            self.refresh_metrics()
        elif screen_id == "benchmark":
            self.refresh_bench_runs()

    def _toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        self.sidebar.set_collapsed(self._sidebar_collapsed)

    # ---------- chat ----------
    def _on_send_chat(self) -> None:
        prompt_text = self.chat_screen.current_prompt()
        if not prompt_text:
            self._show_toast("Escribí una pregunta primero")
            return
        if not self.backend.is_running():
            ok = self.backend.start()
            self.config_screen.log(f"start() -> {ok}", level="ok" if ok else "err")
            self.refresh_sidebar_model_card()
            self.refresh_status_chips()
            if not ok:
                QMessageBox.warning(self, "Backend",
                                    "No se pudo arrancar el backend. Revisa Modelo y backend.")
                return
        preset = get_preset(self.chat_screen.current_preset()) or default_preset()
        self.chat_screen.add_user_message(prompt_text)
        self.chat_screen.clear_input()
        self._run_chat_stream(prompt_text, preset.system, preset.max_tokens)

    def _run_chat_stream(self, prompt: str, system: str, max_tokens: int) -> None:
        self.chat_screen.send_btn.setEnabled(False)
        self.chat_screen.add_streaming_ai_message(self.chat_screen.current_preset())
        runner = GenerateRunner(self.backend, prompt, system, max_tokens_override=max_tokens)
        runner.token.connect(self.chat_screen.append_stream)
        runner.finished.connect(self._on_chat_finished)
        runner.failed.connect(self._on_chat_failed)
        runner.finished.connect(runner.deleteLater)
        runner.failed.connect(runner.deleteLater)
        self._current_runner = runner
        runner.start()

    def _on_chat_finished(self, out: str, metrics: dict[str, Any]) -> None:
        self.chat_screen.finalize_stream(metrics)
        self.chat_screen.send_btn.setEnabled(True)
        self._last_metrics = metrics
        self._current_runner = None
        self.refresh_metrics()
        self.refresh_sidebar_model_card()
        self.refresh_status_chips()

    def _on_chat_failed(self, err: str) -> None:
        self.chat_screen.append_error(err)
        self.chat_screen.send_btn.setEnabled(True)
        self._current_runner = None

    def _on_clear_chat(self) -> None:
        self.chat_screen.clear_messages()
        self._show_toast("Conversación limpiada")

    def _on_new_chat(self) -> None:
        self.chat_screen.clear_messages()
        self._switch_screen("chat")
        self._show_toast("Nueva conversación")

    def _on_cycle_preset(self) -> None:
        self.chat_screen.cycle_preset()
        self.presets_screen.set_active(self.chat_screen.current_preset())
        preset = get_preset(self.chat_screen.current_preset())
        if preset:
            self._show_toast(f"Preset: {preset.label}")

    def _on_composer_text_changed(self) -> None:
        # Auto-grow: just rely on QPlainTextEdit's natural sizing + fixed height range.
        pass

    # ---------- config / backend ----------
    def _on_pick_gguf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir modelo GGUF",
                                              "", "GGUF (*.gguf);;Todos (*.*)")
        if path:
            self.config_screen.in_gguf_path.setText(path)

    def _on_auto_detect_gguf(self) -> None:
        """Scan standard locations for any .gguf and let the user pick one.

        If exactly one model is found, use it directly. If multiple,
        show a selection dialog. If none, show a friendly hint with
        the model dirs that were searched.
        """
        from . import auto_config
        ggufs = auto_config.find_gguf_all()
        if not ggufs:
            QMessageBox.information(
                self, "Auto-detectar .gguf",
                "No se encontraron modelos .gguf en las rutas estándar:\n\n"
                "  · <config_dir>\\models\n"
                "  · C:\\modelos\n"
                "  · C:\\models\n"
                "  · %USERPROFILE%\\models\n\n"
                "Tip: copiá tu .gguf a la carpeta models junto al .exe, "
                "o usá 'Elegir' para seleccionarlo manualmente.",
            )
            return
        if len(ggufs) == 1:
            self.config_screen.in_gguf_path.setText(ggufs[0])
            self.config_screen.refresh_gguf_info()
            self._show_toast("Modelo detectado y aplicado")
            return
        # Multiple — show a picker
        pick, ok = QInputDialog.getItem(
            self, "Auto-detectar .gguf",
            f"Se encontraron {len(ggufs)} modelos. Elegí uno:",
            ggufs, 0, False,
        )
        if ok and pick:
            self.config_screen.in_gguf_path.setText(pick)
            self.config_screen.refresh_gguf_info()
            self._show_toast("Modelo seleccionado")

    def _on_auto_detect_cli(self) -> None:
        from . import auto_config
        hit = auto_config.find_llama_cli()
        if hit:
            self.config_screen.in_llama_cli.setText(hit)
            self._show_toast(f"llama-cli: {Path(hit).name}")
        else:
            QMessageBox.information(
                self, "Auto-detectar llama-cli",
                "No se encontró llama-cli en PATH ni en rutas estándar.\n\n"
                "Opciones:\n"
                "  · Instalá llama.cpp y agregá la carpeta al PATH\n"
                "  · O apuntá al .exe con el campo 'llama-cli path'",
            )

    def _on_auto_detect_server(self) -> None:
        from . import auto_config
        hit = auto_config.find_llama_server()
        if hit:
            self.config_screen.in_llama_server.setText(hit)
            self._show_toast(f"llama-server: {Path(hit).name}")
        else:
            self._show_toast("llama-server no encontrado (opcional)")

    def _on_apply_model(self) -> None:
        new_cfg = self.config_screen.gather_model_config()
        if self.backend.is_running():
            self.backend.stop()
        self.backend = self._make_backend(new_cfg)
        ok = self.backend.start()
        self.config_screen.log(f"start() -> {ok}", level="ok" if ok else "err")
        self.refresh_sidebar_model_card()
        self.refresh_status_chips()
        self.refresh_metrics()
        self._save_settings()  # persist every config change to settings.json
        self._show_toast(f"Config aplicada · {new_cfg.name}")

    def _save_settings(self) -> Path:
        """Persist the current in-memory settings back to settings.json.

        Called whenever the user applies a model config, toggles
        ``auto_start_backend``, or runs the first-run wizard. The on-
        disk file is the source of truth, so we always re-derive from
        the live widgets — never keep a stale copy in memory.
        """
        cfg = self.config_screen.gather_model_config()
        ui_cfg = dict(self._settings.get("ui") or {})
        ui_cfg["auto_start_backend"] = bool(
            self._settings.get("ui", {}).get("auto_start_backend", False)
        )
        # If the auto-start checkbox exists in the wizard UI, sync it too
        if hasattr(self, "_wizard_autostart_cb"):
            ui_cfg["auto_start_backend"] = bool(self._wizard_autostart_cb.isChecked())
        self._settings = self._auto_config._merge_defaults(
            {
                "model": {
                    "name": cfg.name,
                    "gguf_path": cfg.gguf_path,
                    "ctx_size": cfg.ctx_size,
                    "threads": cfg.threads,
                    "temperature": cfg.temperature,
                    "top_p": cfg.top_p,
                    "repeat_penalty": cfg.repeat_penalty,
                    "max_tokens": cfg.max_tokens,
                    "mode": cfg.mode,
                    "gpu_layers": cfg.gpu_layers,
                    "backend_kind": cfg.backend_kind,
                    "llama_cli_path": cfg.llama_cli_path,
                    "llama_server_path": cfg.llama_server_path,
                    "ollama_url": cfg.ollama_url,
                },
                "ui": ui_cfg,
                "paths": dict(self._settings.get("paths") or {}),
            },
            self._auto_config._DEFAULT_SETTINGS,
        )
        return self._auto_config.save_settings(self._settings)

    def _auto_start_backend(self) -> None:
        """Best-effort auto-start of the backend on launch.

        Used when ``ui.auto_start_backend`` is true AND a model +
        llama-cli are present. Errors are surfaced as a toast; never
        crashes the UI.
        """
        cfg = self.backend.config
        if not cfg.exists() and cfg.backend_kind != "ollama":
            self._show_toast("No se encontró el .gguf — abrí Modelo y backend")
            return
        ok = self.backend.start()
        self.config_screen.log(f"auto-start() -> {ok}", level="ok" if ok else "err")
        self.refresh_sidebar_model_card()
        self.refresh_metrics()
        self.refresh_status_chips()
        self._show_toast(
            "Modelo iniciado" if ok else "Falló el auto-start — revisá el backend"
        )

    def _show_first_run_wizard(self) -> None:
        """Show the in-app wizard when nothing was auto-detected.

        The wizard gives the user several options:
          1. ``Descargar modelo starter`` — pulls llama.cpp + a small
             Qwen2.5-1.5B GGUF (~1.2 GB) in the background, then
             re-detects and closes the wizard.
          2. ``Elegir manualmente`` — file dialog to pick a .gguf.
          3. ``Re-auto-detectar`` — re-scan standard locations in
             case the user just dropped files in.
          4. ``Modo mock`` — closes the wizard so the user can
             browse the UI without a model.

        It's a friendly dialog, not a blocker: closing it (X) lands
        the user back on the chat with the auto-detected values
        that *were* found filled in.
        """
        from . import auto_config, downloader as _downloader
        dlg = QDialog(self)
        dlg.setWindowTitle("ForgeMind · Primer arranque")
        dlg.setObjectName("WizardDialog")
        dlg.setModal(True)
        dlg.resize(600, 540)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(12)

        # Title
        title = QLabel("¡Bienvenido a ForgeMind Local!")
        title.setStyleSheet(
            "color: #f5f4ee; font-family: 'Newsreader', Georgia, 'Liberation Serif', 'DejaVu Serif', 'Times New Roman', serif; "
            "font-size: 22px; font-weight: 500; background: transparent; border: 0;"
        )
        v.addWidget(title)

        sub = QLabel(
            "No encontramos un modelo ni llama-cli. Te dejamos tres caminos:\n"
            "  1. Descargamos un kit starter (llama.cpp + Qwen2.5-1.5B Q4_K_M, ~1.2 GB).\n"
            "  2. Elegís un .gguf que ya tengas en disco.\n"
            "  3. Explorás la UI en modo mock (sin modelo).\n\n"
            "Tu PC, tus datos, sin nube."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(
            "color: #d8d4c8; font-size: 13px; line-height: 1.6; "
            "background: transparent; border: 0;"
        )
        v.addWidget(sub)

        # --- Detection report (collapsed by default) ---
        ggufs = auto_config.find_gguf_all()
        cli = auto_config.find_llama_cli()
        srv = auto_config.find_llama_server()

        report = QLabel()
        report.setWordWrap(True)
        report.setTextFormat(Qt.TextFormat.RichText)
        report.setStyleSheet(
            "color: #d8d4c8; font-family: 'JetBrains Mono', Consolas, monospace; "
            "font-size: 12px; background: #151413; border: 1px solid #34312e; "
            "border-radius: 8px; padding: 10px 14px;"
        )
        cfg_dir = auto_config.config_dir()
        gguf_lines = (
            "<br>".join(f"&nbsp;&nbsp;• {g}" for g in ggufs[:5])
            if ggufs else
            "&nbsp;&nbsp;<span style=\"color:#d88a83\">ninguno</span>"
        )
        cli_html = cli or '<span style="color:#d88a83">NO encontrado</span>'
        srv_html = srv or '<span style="color:#787469">NO encontrado</span>'
        report_text = (
            f"<b>Config dir:</b> {cfg_dir}<br>"
            f"<b>llama-cli:</b> {cli_html}<br>"
            f"<b>llama-server:</b> {srv_html}<br>"
            f"<b>.gguf encontrados ({len(ggufs)}):</b><br>{gguf_lines}"
        )
        report.setText(report_text)
        v.addWidget(report)

        # --- Download progress widget (hidden until download starts) ---
        self._wizard_progress = QProgressBar()
        self._wizard_progress.setRange(0, 0)  # indeterminate until first chunk
        self._wizard_progress.setVisible(False)
        self._wizard_progress.setFixedHeight(8)
        self._wizard_progress.setStyleSheet(
            "QProgressBar { background: #211f1d; border: 1px solid #34312e; "
            "border-radius: 4px; } "
            "QProgressBar::chunk { background: #d97757; border-radius: 4px; }"
        )
        v.addWidget(self._wizard_progress)

        self._wizard_stage = QLabel("")
        self._wizard_stage.setStyleSheet(
            "color: #a8a499; font-size: 11.5px; "
            "background: transparent; border: 0;"
        )
        self._wizard_stage.setVisible(False)
        v.addWidget(self._wizard_stage)

        # --- Auto-start checkbox ---
        self._wizard_autostart_cb = QCheckBox(
            "Iniciar el modelo automáticamente al abrir la app"
        )
        self._wizard_autostart_cb.setChecked(
            bool(self._settings.get("ui", {}).get("auto_start_backend", False))
        )
        self._wizard_autostart_cb.setStyleSheet(
            "color: #d8d4c8; font-size: 13px; background: transparent; border: 0;"
        )
        v.addWidget(self._wizard_autostart_cb)

        v.addStretch(1)

        # --- Buttons (the order matches the suggested user journey) ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        # Helper: open the models folder in Explorer
        def _open_models_dir():
            target = cfg_dir / "models"
            target.mkdir(parents=True, exist_ok=True)
            try:
                if os.name == "nt":
                    os.startfile(str(target.resolve()))  # type: ignore[attr-defined]
                else:
                    QMessageBox.information(
                        self, "Carpeta de modelos", f"Modelos en: {target}"
                    )
            except Exception as e:
                QMessageBox.warning(self, "Abrir carpeta", f"No se pudo abrir: {e}")

        b_models = QPushButton("Abrir carpeta models/")
        b_models.setProperty("ghost", True)
        b_models.clicked.connect(_open_models_dir)
        btn_row.addWidget(b_models)

        b_redetect = QPushButton("Re-auto-detectar")
        b_redetect.setProperty("ghost", True)
        def _redetect_and_reopen():
            dlg.accept()
            self._settings = self._auto_config.first_run_setup(interactive=False)
            QTimer.singleShot(100, self._show_first_run_wizard)
        b_redetect.clicked.connect(_redetect_and_reopen)
        btn_row.addWidget(b_redetect)

        btn_row.addStretch(1)

        b_mock = QPushButton("Modo mock")
        b_mock.setProperty("ghost", True)
        b_mock.clicked.connect(dlg.reject)
        btn_row.addWidget(b_mock)

        # Secondary: file picker (user has their own .gguf)
        b_pick = QPushButton("Elegir .gguf…")
        b_pick.setProperty("ghost", True)
        def _pick_gguf():
            path, _ = QFileDialog.getOpenFileName(
                self, "Elegir modelo GGUF", "", "GGUF (*.gguf);;Todos (*.*)"
            )
            if path:
                self.config_screen.in_gguf_path.setText(path)
                self.config_screen.refresh_gguf_info()
                self._save_settings()
                dlg.accept()
        b_pick.clicked.connect(_pick_gguf)
        btn_row.addWidget(b_pick)

        # Primary: download the starter kit
        b_download = QPushButton("Descargar modelo starter")
        b_download.setProperty("primary", True)
        def _start_download():
            from pathlib import Path
            # Disable all action buttons so we don't get concurrent downloads
            for b in (b_pick, b_redetect, b_mock, b_models, b_download):
                b.setEnabled(False)
            b_download.setText("Descargando…")
            self._wizard_progress.setVisible(True)
            self._wizard_stage.setVisible(True)
            self._wizard_progress.setRange(0, 0)  # indeterminate
            self._wizard_stage.setText("Iniciando descarga…")

            cfg = auto_config.config_dir()
            self._download_runner = DownloadRunner(cfg, variant="cpu")

            def _on_progress(key: str, done: int, total: int):
                if total > 0 and self._wizard_progress.maximum() != total:
                    self._wizard_progress.setRange(0, total)
                self._wizard_progress.setValue(done)
                pct = (done / total * 100) if total > 0 else 0
                size = _downloader.human_bytes(done)
                total_size = _downloader.human_bytes(total) if total > 0 else "?"
                label = {
                    "llama_cpp_cpu": "llama.cpp (CPU)",
                    "llama_cpp_vulkan": "llama.cpp (Vulkan)",
                    "qwen_15b_q4": "Qwen2.5-1.5B Q4_K_M",
                    "llama_1b_q4": "Llama-3.2-1B Q4_K_M",
                }.get(key, key)
                self._wizard_stage.setText(
                    f"{label} — {size} / {total_size} ({pct:.1f}%)"
                )

            def _on_finished(result: dict):
                self._wizard_progress.setRange(0, 1)
                self._wizard_progress.setValue(1)
                llama = result.get("llama_cli", "?")
                model = result.get("model", "?")
                self._wizard_stage.setText(
                    f"Listo — llama-cli={Path(llama).name} · modelo={Path(model).name}"
                )
                # Persist and re-hydrate everything
                self._settings = self._auto_config.first_run_setup(interactive=False)
                self.backend = self._make_backend(
                    ModelConfig(
                        gguf_path=self._settings["model"].get("gguf_path", ""),
                        name=self._settings["model"].get("name", "modelo-sin-nombre"),
                        backend_kind=self._settings["model"].get("backend_kind", "llama_cli"),
                        llama_cli_path=self._settings["model"].get("llama_cli_path", ""),
                        llama_server_path=self._settings["model"].get("llama_server_path", ""),
                    )
                )
                self.config_screen.apply_to_widgets(self.backend.config)
                self.refresh_sidebar_model_card()
                self.refresh_metrics()
                self.refresh_status_chips()
                QTimer.singleShot(700, dlg.accept)

            def _on_failed(err: str):
                self._wizard_progress.setRange(0, 1)
                self._wizard_progress.setValue(0)
                self._wizard_stage.setText(f"Error: {err}")
                for b in (b_pick, b_redetect, b_mock, b_models, b_download):
                    b.setEnabled(True)
                b_download.setText("Reintentar descarga")

            self._download_runner.progress.connect(_on_progress)
            self._download_runner.finished_ok.connect(_on_finished)
            self._download_runner.failed.connect(_on_failed)
            self._download_runner.start()
        b_download.clicked.connect(_start_download)
        btn_row.addWidget(b_download)

        v.addLayout(btn_row)

        # Persist the auto-start checkbox choice regardless of how
        # the wizard is closed.
        dlg.finished.connect(lambda *_: self._save_settings())

        dlg.exec()
        self._wizard_autostart_cb = None  # free reference

    def _on_test_backend(self) -> None:
        cfg = self.backend.config
        cfg.llama_cli_path = self.config_screen.in_llama_cli.text().strip()
        cfg.llama_server_path = self.config_screen.in_llama_server.text().strip()
        from .metrics import find_executable
        ok_cli = find_executable("llama-cli") or find_executable("llama-cli.exe") or (
            cfg.llama_cli_path and os.path.isfile(cfg.llama_cli_path))
        ok_srv = find_executable("llama-server") or find_executable("llama-server.exe") or (
            cfg.llama_server_path and os.path.isfile(cfg.llama_server_path))
        msgs = [
            f"llama-cli: {'OK' if ok_cli else 'NO encontrado'}",
            f"llama-server: {'OK' if ok_srv else 'NO encontrado'}",
            f"llama_cpp binding: {'OK' if _have_llama_cpp_binding() else 'NO instalado'}",
            f"Modelo existe: {'OK' if cfg.exists() else 'falta'}",
        ]
        for m in msgs:
            self.config_screen.log(m)
        QMessageBox.information(self, "Probar backend", "\n".join(msgs))

    def _on_start_backend(self) -> None:
        cfg = self.backend.config
        cfg.llama_cli_path = self.config_screen.in_llama_cli.text().strip()
        cfg.llama_server_path = self.config_screen.in_llama_server.text().strip()
        cfg.backend_kind = self.config_screen.cmb_backend_kind.currentData() or "llama_cli"
        if not cfg.exists() and cfg.backend_kind != "mock" and cfg.backend_kind != "ollama":
            QMessageBox.warning(self, "Modelo", "Ruta al .gguf inválida.")
            return
        ok = self.backend.start()
        self.config_screen.log(f"start() -> {ok}", level="ok" if ok else "err")
        self.refresh_sidebar_model_card()
        self.refresh_metrics()
        self.refresh_status_chips()
        self._show_toast("Iniciando modelo…")

    def _on_stop_backend(self) -> None:
        self.backend.stop()
        self.config_screen.log("stop()")
        self.refresh_sidebar_model_card()
        self.refresh_metrics()
        self.refresh_status_chips()
        self._show_toast("Backend detenido")

    def _on_backend_kind_changed(self, kind: str) -> None:
        cfg = self.backend.config
        cfg.backend_kind = kind
        cfg.llama_cli_path = self.config_screen.in_llama_cli.text().strip()
        cfg.llama_server_path = self.config_screen.in_llama_server.text().strip()
        cfg.ollama_url = self.config_screen.in_ollama_url.text().strip()
        if (kind == "ollama" and not isinstance(self.backend, OllamaBackend)) or \
           (kind != "ollama" and isinstance(self.backend, OllamaBackend)):
            try:
                self.backend.stop()
            except Exception:
                pass
            self.backend = self._make_backend(cfg)
        self.config_screen.log(f"backend_kind -> {kind}")
        self.refresh_status_chips()

    # ---------- metrics ----------
    def refresh_metrics(self) -> None:
        try:
            pm = self.backend.process_metrics()
            rss_gb = (pm.get("rss_bytes") or 0) / (1024 ** 3) if pm.get("rss_bytes") else None
        except Exception:
            rss_gb = None
        sys_mem = get_system_memory()
        ram_avail_gb = (sys_mem.get("available_bytes") or 0) / (1024 ** 3) if sys_mem.get("available_bytes") else None
        tps = (self._last_metrics.get("tokens_per_sec_proxy")
               if isinstance(self._last_metrics.get("tokens_per_sec_proxy"), (int, float)) else None)
        first = (self._last_metrics.get("first_token_sec")
                 if isinstance(self._last_metrics.get("first_token_sec"), (int, float)) else None)
        status = self.backend.status() or {}
        status["_last_generate"] = self._last_metrics
        self.metrics_screen.refresh(
            rss_gb=rss_gb,
            tps=tps,
            first_token=first,
            ram_avail_gb=ram_avail_gb,
            cfg=self.backend.config,
            running=self.backend.is_running(),
            status=status,
        )
        # also update sidebar foot
        self.sidebar.set_foot_metrics(rss_gb, tps)

    # ---------- presets ----------
    def _on_pick_preset_from_screen(self, key: str) -> None:
        self.chat_screen.set_preset(key)
        self.presets_screen.set_active(key)
        preset = get_preset(key)
        if preset:
            self._show_toast(f"Preset: {preset.label}")
        self._switch_screen("chat")

    # ---------- benchmark ----------
    def _on_run_benchmark(self) -> None:
        if not self.backend.is_running():
            ok = self.backend.start()
            self.refresh_sidebar_model_card()
            if not ok:
                QMessageBox.warning(self, "Benchmark", "No se pudo arrancar el backend.")
                return
        prompts = load_prompts(self.bench_screen.in_prompts_file.text().strip() or DEFAULT_PROMPTS_FILE)
        if not prompts:
            QMessageBox.warning(self, "Benchmark",
                                f"No hay prompts en {self.bench_screen.in_prompts_file.text()}.")
            return
        self._show_toast("Benchmark iniciado · 10 prompts")
        QApplication.processEvents()
        result = run_benchmark(
            backend=self.backend,
            prompts=prompts,
            results_dir=DEFAULT_RESULTS_DIR,
            label=self.bench_screen.in_label.text().strip() or "bench",
        )
        self.bench_screen.render_summary(result)
        self.config_screen.log(f"benchmark listo: {result['label']}")
        self.refresh_bench_runs()
        self._show_toast(f"Benchmark listo: {result['label']}")

    def _on_open_results(self) -> None:
        d = DEFAULT_RESULTS_DIR
        Path(d).mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(Path(d).resolve()))  # type: ignore[attr-defined]
            else:
                QMessageBox.information(self, "Resultados", f"Resultados en: {d}")
        except Exception as e:
            QMessageBox.warning(self, "Abrir carpeta", f"No se pudo abrir: {e}")

    def refresh_bench_runs(self) -> None:
        self.bench_screen._reload_runs(DEFAULT_RESULTS_DIR)

    # ---------- gpu ----------
    def refresh_gpu(self) -> None:
        try:
            summary = system_summary()
        except Exception as e:
            summary = {"gpus": [], "amd_gpu": None, "vulkan": {}}
        self.gpu_screen.refresh(summary)

    # ---------- sidebar / chips ----------
    def refresh_sidebar_model_card(self) -> None:
        cfg = self.backend.config
        self.sidebar.set_model_card(
            name=cfg.name or "",
            quant=cfg.quant or "",
            size_human=cfg.size_human or "",
            ctx_size=cfg.ctx_size,
            running=self.backend.is_running(),
        )

    def refresh_status_chips(self) -> None:
        cfg = self.backend.config
        # chip model: name or "sin modelo"
        chip_name = cfg.name if cfg.name and cfg.name != "modelo-sin-nombre" else "(sin modelo)"
        self.set_chip_text(self.chip_model, chip_name)
        # chip backend — show the friendly hyphenated form (mockup L1768)
        backend_kind = cfg.backend_kind or "llama_cli"
        friendly = {
            "llama_cli": "llama-cli",
            "llama_server": "llama-server",
            "llama_cpp": "llama-cpp",
            "ollama": "ollama",
        }.get(backend_kind, backend_kind)
        self.set_chip_text(self.chip_backend, friendly)
        # titlebar (also pass running state so the green dot reflects it)
        if cfg.size_human and cfg.quant:
            self.titlebar.set_status(
                f"{cfg.name} · {cfg.quant} · {cfg.size_human}",
                f"{friendly} {('activo' if self.backend.is_running() else 'detenido')}",
                running=self.backend.is_running(),
            )
        else:
            self.titlebar.set_status(
                "(sin modelo)", friendly,
                running=self.backend.is_running(),
            )

    # ---------- command palette ----------
    def _open_palette(self) -> None:
        if self._palette is None:
            self._palette = CommandPalette(self)
        self._palette.show_at()

    def _exec_command(self, cmd: _CmdItem) -> None:
        if cmd.cmd == "goto" and cmd.screen:
            self._switch_screen(cmd.screen)
            self._show_toast(cmd.label)
        elif cmd.cmd == "new-chat":
            self._on_new_chat()
        elif cmd.cmd == "start-backend":
            self._on_start_backend()
        elif cmd.cmd == "stop-backend":
            self._on_stop_backend()
        elif cmd.cmd == "run-benchmark":
            self._switch_screen("benchmark")
            self._on_run_benchmark()
        elif cmd.cmd == "apply-model":
            self._switch_screen("config")
            QTimer.singleShot(150, self._on_apply_model)
        else:
            self._show_toast(cmd.label)

    # ---------- config load/save ----------
    def _on_save_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Guardar configuración",
                                              "", "JSON (*.json)")
        if not path:
            return
        data = self.config_screen.gather_model_config().to_dict()
        data["backend_kind"] = self.config_screen.cmb_backend_kind.currentData() or "llama_cli"
        data["llama_cli_path"] = self.config_screen.in_llama_cli.text().strip()
        data["llama_server_path"] = self.config_screen.in_llama_server.text().strip()
        data["ollama_url"] = self.config_screen.in_ollama_url.text().strip()
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.config_screen.log(f"config guardada en {path}", level="ok")
        self._show_toast(f"Config guardada: {path}")

    def _on_load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cargar configuración",
                                              "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.warning(self, "Cargar config", f"JSON inválido: {e}")
            return
        self.config_screen.apply_to_widgets(ModelConfig.from_dict(data))
        self.config_screen.refresh_gguf_info()
        self.config_screen.log(f"config cargada de {path}", level="ok")
        self._show_toast(f"Config cargada: {path}")

    def _on_about(self) -> None:
        QMessageBox.information(
            self, "Acerca de ForgeMind Local",
            "ForgeMind Local v0.3\n\n"
            "App desktop para comparar modelos GGUF locales en Windows.\n"
            "Backend: llama.cpp (llama-cli / llama-server / binding) · Ollama opcional.\n"
            "Sin cloud. Sin CUDA. Vulkan = experimental en AMD."
        )

    # ---------- timer / lifecycle ----------
    def _on_tick(self) -> None:
        try:
            pm = self.backend.process_metrics()
            rss_gb = (pm.get("rss_bytes") or 0) / (1024 ** 3) if pm.get("rss_bytes") else None
        except Exception:
            rss_gb = None
        self.sidebar.set_foot_metrics(rss_gb, self._last_metrics.get("tokens_per_sec_proxy"))

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self._current_runner is not None and self._current_runner.isRunning():
                self._current_runner.requestInterruption()
        except Exception:
            pass
        try:
            self.backend.stop()
        except Exception:
            pass
        try:
            self._timer.stop()
        except Exception:
            pass
        super().closeEvent(event)


# To keep `from PyQt6.QtCore import QObject` working for the one-shot filter.
from PyQt6.QtCore import QObject  # noqa: E402
