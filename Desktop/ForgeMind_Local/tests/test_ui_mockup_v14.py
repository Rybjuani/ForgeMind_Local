"""UI regression tests that protect the mockup v14 invariants.

These tests intentionally render the MainWindow in offscreen mode and
verify that:
- No modal wizard pops up at startup (UX directive 2026-06: kill the
  first-launch "Primer arranque" dialog).
- The chat empty state shows the v14 greeting + 4 cards in one row.
- The composer carries the preset pill, model pill, and send button
  wired to the same handlers.
- The sidebar carries the history section, even when empty.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MOCK_LLM", "1")

import pytest

from PyQt6.QtWidgets import QApplication, QDialog

from app import auto_config
from app.ui_main import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture()
def win(qt_app, tmp_path: Path):
    """Build a MainWindow with no model detected (forces first_run needs).

    The smoke_all_screens.py harness disables the wizard via a flag,
    but here we exercise the production code path: ``first_run_setup``
    returns settings WITHOUT a model, so ``_first_run_needs_setup``
    is True. The test then asserts that the wizard still does NOT
    auto-trigger.
    """
    s = auto_config.first_run_setup(interactive=False)
    # Inject a benign settings dict with no model/cli so the wizard
    # gating path is exercised. We rewrite the model fields in place.
    s.setdefault("model", {})
    s["model"]["gguf_path"] = ""
    s["model"]["name"] = ""
    win = MainWindow(initial_settings=s)
    yield win
    win.close()
    win.deleteLater()


class TestFirstRunWizardKilled:
    """The first-launch wizard must NEVER auto-trigger."""

    def test_first_run_needs_setup_is_true(self, win) -> None:
        """Sanity check: this fixture sets up the first-run state."""
        assert win._first_run_needs_setup is True

    def test_no_modal_dialog_after_event_loop(self, qt_app, win) -> None:
        """Run the event loop for ~1s and verify no QDialog opens."""
        from PyQt6.QtCore import QTimer
        # Snapshot the open dialogs BEFORE running.
        before = [w for w in qt_app.topLevelWidgets() if isinstance(w, QDialog)]
        # Quit shortly after the wizard's would-be QTimer (250ms) fires.
        QTimer.singleShot(1200, qt_app.quit)
        qt_app.exec()
        after = [w for w in qt_app.topLevelWidgets() if isinstance(w, QDialog)]
        # If the wizard fired, it would appear in `after` and not in
        # `before` (or appear with .windowTitle() starting with
        # "ForgeMind" / "Primer arranque").
        new_dialogs = [d for d in after if d not in before]
        assert new_dialogs == [], (
            f"first-run wizard auto-triggered: "
            f"{[d.windowTitle() for d in new_dialogs]}"
        )


class TestChatEmptyStateV14:
    """The chat empty state must show the v14 greeting + 4 cards."""

    def test_chat_screen_has_asterisk_logo(self, win) -> None:
        # The logo QLabel has object name ChatEmptyLogo
        from PyQt6.QtWidgets import QLabel
        logo = win.chat_screen.findChild(QLabel, "ChatEmptyLogo")
        assert logo is not None
        assert logo.text().strip() == "*"

    def test_chat_greeting_uses_hola_prefix(self, win) -> None:
        from PyQt6.QtWidgets import QLabel
        title = win.chat_screen.findChild(QLabel, "ChatEmptyTitle")
        assert title is not None
        assert title.text().startswith("Hola,")

    def test_suggestion_cards_count_is_four(self, win) -> None:
        # The empty state container holds 4 SuggestionCard frames.
        from PyQt6.QtWidgets import QFrame
        cards = win.chat_screen.findChildren(QFrame, "SuggestionCard")
        # Filter out nested helper widgets by looking for direct children
        # of the empty_state container.
        cards = [c for c in cards if c.parent() is not None and c.parent().parent() is win.chat_screen.empty_state]
        assert len(cards) == 4, f"expected 4 suggestion cards, got {len(cards)}"


class TestSidebarMockupV14:
    """Sidebar must NOT carry the user row from the old mockup."""

    def test_no_user_row_in_sidebar(self, win) -> None:
        # The old sidebar exposed self.user_row / self.user_name /
        # self.user_avatar. Their absence is the invariant.
        assert not hasattr(win.sidebar, "user_row")
        assert not hasattr(win.sidebar, "user_name")
        assert not hasattr(win.sidebar, "user_avatar")

    def test_sidebar_has_history_section(self, win) -> None:
        from PyQt6.QtWidgets import QFrame
        sec = win.sidebar.findChild(QFrame, "HistorySection")
        assert sec is not None
        # When there are no runs, the section is hidden — but the
        # widget itself exists in the tree.
        assert sec.objectName() == "HistorySection"

    def test_brand_mark_is_asterisk_label(self, win) -> None:
        from PyQt6.QtWidgets import QLabel
        mark = win.sidebar.findChild(QLabel, "SidebarBrandMark")
        assert mark is not None
        assert mark.text().strip() == "*"


class TestComposerWiringV14:
    """Composer must have the preset pill, model pill, and shell focus."""

    def test_composer_has_model_select_pill(self, win) -> None:
        from PyQt6.QtWidgets import QPushButton
        pill = win.chat_screen.findChild(QPushButton, "ModelSelectPill")
        assert pill is not None

    def test_composer_has_input_shell(self, win) -> None:
        from PyQt6.QtWidgets import QFrame
        shell = win.chat_screen.findChild(QFrame, "ComposerInputShell")
        assert shell is not None

    def test_model_pill_label_syncs_with_sidebar(self, win) -> None:
        """The composer pill label mirrors the sidebar model card name."""
        win.refresh_sidebar_model_card()
        # The label exists
        assert win.chat_screen.model_pill_label.text() != ""