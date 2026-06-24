"""Tests para app.presets."""

import pytest

from app.presets import PRESETS, build_prompt, default_preset, get_preset


class TestPresets:
    def test_minimum_seven(self) -> None:
        assert len(PRESETS) >= 7

    def test_unique_keys(self) -> None:
        keys = [p.key for p in PRESETS]
        assert len(set(keys)) == len(keys)

    @pytest.mark.parametrize("key", [
        "diario", "coding", "auditoria", "resumen", "razonamiento",
        "espanol_claro", "prompt_largo",
    ])
    def test_required_presets_present(self, key: str) -> None:
        p = get_preset(key)
        assert p is not None
        assert p.label
        assert p.system
        assert 0.0 <= p.temperature <= 2.0
        assert 0.0 < p.top_p <= 1.0
        assert p.max_tokens > 0

    def test_unknown_returns_none(self) -> None:
        assert get_preset("nope_xyz") is None

    def test_default_is_preset(self) -> None:
        d = default_preset()
        assert d in PRESETS


class TestBuildPrompt:
    def test_no_system(self) -> None:
        out = build_prompt("hola")
        assert "Usuario: hola" in out
        assert "Asistente:" in out

    def test_with_system(self) -> None:
        out = build_prompt("hola", "Sos util.")
        assert "Sos util." in out
        assert "Usuario: hola" in out

    def test_includes_marker_for_response(self) -> None:
        # El "Asistente:" final es el marker donde el modelo empieza a generar
        out = build_prompt("q", "s")
        assert out.rstrip().endswith("Asistente:")