"""Tests para app.chat_history (persistencia de conversaciones).

Cubre: new_chat_id, derive_title, save_chat, list_chats, load_chat,
delete_chat — usando un tmp_path como config_dir para no tocar el
filesystem real del proyecto.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import chat_history


@pytest.fixture(autouse=True)
def _isolated_chats_dir(tmp_path: Path, monkeypatch):
    """Redirect chats_dir() to a tmp_path so tests don't pollute repo."""
    monkeypatch.setattr(chat_history, "chats_dir", lambda: tmp_path / "chats")
    (tmp_path / "chats").mkdir(parents=True, exist_ok=True)
    yield


class TestNewChatId:
    def test_new_chat_id_is_string(self):
        cid = chat_history.new_chat_id()
        assert isinstance(cid, str)
        assert len(cid) == 15  # YYYYMMDD-HHMMSS

    def test_new_chat_id_format(self):
        cid = chat_history.new_chat_id()
        # YYYYMMDD-HHMMSS  →  8 digits, dash, 6 digits
        parts = cid.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 8
        assert len(parts[1]) == 6
        assert parts[0].isdigit()
        assert parts[1].isdigit()


class TestDeriveTitle:
    def test_short_text_unchanged(self):
        assert chat_history.derive_title("Hola") == "Hola"

    def test_long_text_truncated_with_ellipsis(self):
        text = "Esta es una pregunta muy larga que supera los cuarenta caracteres facilmente"
        title = chat_history.derive_title(text)
        assert title.endswith("...")
        assert len(title) <= 40

    def test_whitespace_collapsed(self):
        text = "Hola\n\n  mundo\tcon   espacios"
        title = chat_history.derive_title(text)
        assert "  " not in title
        assert "\n" not in title

    def test_empty_returns_placeholder(self):
        assert chat_history.derive_title("") == "(nueva conversacion)"


class TestSaveChat:
    def test_save_creates_json_file(self):
        cid = chat_history.new_chat_id()
        conv = {
            "id": cid,
            "messages": [
                {"role": "user", "content": "Hola"},
                {"role": "ai", "content": "Hola!"},
            ],
        }
        path = chat_history.save_chat(conv)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["id"] == cid
        assert len(data["messages"]) == 2
        assert "created_at" in data
        assert "updated_at" in data

    def test_save_assigns_title_from_first_user_message(self):
        conv = {
            "id": chat_history.new_chat_id(),
            "messages": [
                {"role": "user", "content": "¿Cómo auditar código?"},
                {"role": "ai", "content": "..."},
            ],
        }
        chat_history.save_chat(conv)
        chats = chat_history.list_chats()
        assert len(chats) == 1
        assert "auditar" in chats[0]["title"].lower()

    def test_save_preserves_existing_title(self):
        conv = {
            "id": chat_history.new_chat_id(),
            "title": "Mi conversación custom",
            "messages": [{"role": "user", "content": "Hola"}],
        }
        chat_history.save_chat(conv)
        chats = chat_history.list_chats()
        assert chats[0]["title"] == "Mi conversación custom"

    def test_save_generates_id_if_missing(self):
        conv = {"messages": [{"role": "user", "content": "test"}]}
        path = chat_history.save_chat(conv)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "id" in data
        assert len(data["id"]) == 15


class TestListChats:
    def test_empty_returns_empty_list(self):
        assert chat_history.list_chats() == []

    def test_lists_multiple_chats_sorted_by_updated_at(self):
        # Save 3 chats with different timestamps
        for i in range(3):
            conv = {
                "id": f"2026010{i+1}-120000",
                "title": f"Chat {i+1}",
                "messages": [{"role": "user", "content": f"msg {i+1}"}],
            }
            chat_history.save_chat(conv)
        chats = chat_history.list_chats()
        assert len(chats) == 3
        # Most recent first (sorted by updated_at desc)
        # All saves happen "now", so they should be in the order we
        # saved them (which is increasing). List returns reverse.
        titles = [c["title"] for c in chats]
        assert "Chat 1" in titles
        assert "Chat 2" in titles
        assert "Chat 3" in titles

    def test_list_respects_limit(self):
        for i in range(10):
            conv = {
                "id": f"2026010{i+1}-120000",
                "title": f"Chat {i+1}",
                "messages": [{"role": "user", "content": f"msg {i+1}"}],
            }
            chat_history.save_chat(conv)
        chats = chat_history.list_chats(limit=5)
        assert len(chats) == 5

    def test_list_includes_metadata(self):
        conv = {
            "id": chat_history.new_chat_id(),
            "title": "Test chat",
            "model": "Gemma 4 12B",
            "preset": "diario",
            "messages": [
                {"role": "user", "content": "Hola"},
                {"role": "ai", "content": "Hola!"},
            ],
        }
        chat_history.save_chat(conv)
        chats = chat_history.list_chats()
        assert len(chats) == 1
        c = chats[0]
        assert c["title"] == "Test chat"
        assert c["model"] == "Gemma 4 12B"
        assert c["preset"] == "diario"
        assert c["message_count"] == 2
        assert "path" in c


class TestLoadChat:
    def test_load_existing_chat(self):
        conv = {
            "id": "20260624-153022",
            "title": "Hola",
            "messages": [{"role": "user", "content": "Hola"}],
        }
        chat_history.save_chat(conv)
        loaded = chat_history.load_chat("20260624-153022")
        assert loaded is not None
        assert loaded["title"] == "Hola"
        assert len(loaded["messages"]) == 1

    def test_load_nonexistent_returns_none(self):
        assert chat_history.load_chat("no-existe") is None


class TestDeleteChat:
    def test_delete_existing(self):
        conv = {
            "id": "20260624-160000",
            "messages": [{"role": "user", "content": "x"}],
        }
        chat_history.save_chat(conv)
        assert chat_history.delete_chat("20260624-160000") is True
        assert chat_history.load_chat("20260624-160000") is None

    def test_delete_nonexistent_returns_false(self):
        assert chat_history.delete_chat("no-existe") is False


class TestRoundTrip:
    def test_save_then_load_preserves_messages(self):
        original = {
            "id": chat_history.new_chat_id(),
            "title": "Round trip",
            "model": "Test",
            "preset": "coding",
            "messages": [
                {"role": "user", "content": "Pregunta 1", "ts": "2026-01-01T10:00:00"},
                {"role": "ai", "content": "Respuesta 1", "ts": "2026-01-01T10:00:01", "preset": "coding"},
                {"role": "user", "content": "Pregunta 2", "ts": "2026-01-01T10:01:00"},
                {"role": "ai", "content": "Respuesta 2", "ts": "2026-01-01T10:01:02", "preset": "coding"},
            ],
        }
        chat_history.save_chat(original)
        loaded = chat_history.load_chat(original["id"])
        assert loaded is not None
        assert loaded["messages"] == original["messages"]
        assert loaded["title"] == "Round trip"
        assert loaded["model"] == "Test"
        assert loaded["preset"] == "coding"
