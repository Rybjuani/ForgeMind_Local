"""Tests for the first-run auto-configuration helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import auto_config


@pytest.fixture
def isolated_config(monkeypatch, tmp_path: Path) -> Path:
    """Point FORGEMIND_HOME at tmp_path so we never touch the user's real config."""
    monkeypatch.setenv("FORGEMIND_HOME", str(tmp_path))
    # Reset the module-level cache so the new HOME is honoured.
    auto_config._BIN_SEARCH_DIRS.clear()
    auto_config._GGUF_SEARCH_DIRS.clear()
    return tmp_path


def test_config_dir_creates_dir(isolated_config: Path) -> None:
    d = auto_config.config_dir()
    assert d == isolated_config
    assert d.is_dir()


def test_settings_path_is_settings_json(isolated_config: Path) -> None:
    p = auto_config.settings_path()
    assert p == isolated_config / "settings.json"


def test_first_run_creates_settings(isolated_config: Path) -> None:
    settings = auto_config.first_run_setup()
    p = auto_config.settings_path()
    assert p.is_file()
    assert settings["schema_version"] == 1
    assert "model" in settings
    # The first-run must always create a `models/` subfolder
    assert (isolated_config / "models").is_dir()
    assert (isolated_config / "bin").is_dir()
    assert (isolated_config / "results").is_dir()


def test_first_run_idempotent(isolated_config: Path) -> None:
    s1 = auto_config.first_run_setup()
    p = auto_config.settings_path()
    mtime_before = p.stat().st_mtime
    s2 = auto_config.first_run_setup()
    # The file is NOT rewritten on the second call
    assert p.stat().st_mtime == mtime_before
    assert s1["model"] == s2["model"]


def test_save_and_load_roundtrip(isolated_config: Path) -> None:
    auto_config.first_run_setup()
    s = auto_config.load_settings()
    s["model"]["name"] = "test-model"
    s["ui"]["auto_start_backend"] = True
    auto_config.save_settings(s)
    s2 = auto_config.load_settings()
    assert s2["model"]["name"] == "test-model"
    assert s2["ui"]["auto_start_backend"] is True


def test_load_handles_corrupt_json(isolated_config: Path) -> None:
    p = auto_config.settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    s = auto_config.load_settings()
    # Falls back to defaults; never raises
    assert s["schema_version"] == 1


def test_merge_defaults_preserves_unknown_keys(isolated_config: Path) -> None:
    data = {"model": {"name": "x"}, "custom": 42}
    out = auto_config._merge_defaults(data, auto_config._DEFAULT_SETTINGS)
    assert out["custom"] == 42
    assert out["model"]["name"] == "x"
    assert out["model"]["ctx_size"] == 4096  # default kept


def test_find_llama_cli_returns_none_when_absent(
    isolated_config: Path, monkeypatch
) -> None:
    # Empty PATH, no candidate dirs contain llama-cli.
    monkeypatch.setenv("PATH", "")
    assert auto_config.find_llama_cli() is None


def test_find_llama_cli_finds_in_config_dir(
    isolated_config: Path, monkeypatch
) -> None:
    fake = isolated_config / "llama-cli.exe"
    fake.write_bytes(b"fake")
    monkeypatch.setenv("PATH", "")
    found = auto_config.find_llama_cli()
    assert found == str(fake)


def test_find_gguf_finds_models_subdir(
    isolated_config: Path, monkeypatch
) -> None:
    models = isolated_config / "models"
    models.mkdir(parents=True, exist_ok=True)
    g = models / "gemma-4-12b.Q4_K_M.gguf"
    g.write_bytes(b"GGUF")
    # Block the standard user dirs so we only see the test one
    monkeypatch.setattr(auto_config, "_GGUF_SEARCH_DIRS", [models])
    auto_config._BIN_SEARCH_DIRS.clear()
    auto_config._GGUF_SEARCH_DIRS.clear()
    monkeypatch.setattr(auto_config, "_GGUF_SEARCH_DIRS", [models])
    found = auto_config.find_gguf()
    assert found == str(g.resolve())


def test_find_gguf_all_returns_sorted(isolated_config: Path, monkeypatch) -> None:
    models = isolated_config / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "b.gguf").write_bytes(b"x")
    (models / "a.gguf").write_bytes(b"x")
    auto_config._GGUF_SEARCH_DIRS.clear()
    monkeypatch.setattr(auto_config, "_GGUF_SEARCH_DIRS", [models])
    out = auto_config.find_gguf_all()
    assert [Path(p).name for p in out] == ["a.gguf", "b.gguf"]


def test_describe_environment_lists_paths(isolated_config: Path) -> None:
    s = auto_config.first_run_setup()
    desc = auto_config.describe_environment(s)
    assert "Config dir" in desc
    assert "llama-cli" in desc
    assert "Model" in desc
