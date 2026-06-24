"""Tests para app.model_config."""

import json
from pathlib import Path

import pytest

from app.model_config import (
    KNOWN_QUANTS,
    ModelConfig,
    detect_quant_from_filename,
    file_size_bytes,
    human_size,
)


class TestDetectQuant:
    @pytest.mark.parametrize("name,expected", [
        ("gemma-4-12b.Q4_K_M.gguf", "Q4_K_M"),
        ("Qwen3-14B.Q5_K_S.gguf", "Q5_K_S"),
        ("phi-4-14b.Q4_0.gguf", "Q4_0"),
        ("modelo.Q8_0.gguf", "Q8_0"),
        ("Llama-3.1-8B-Instruct.Q4_K_M.gguf", "Q4_K_M"),
        ("modelo.bin", ""),
        ("sin-extension", ""),
        ("", ""),
        ("Q2_K_small.gguf", "Q2_K"),
    ])
    def test_detect(self, name: str, expected: str) -> None:
        assert detect_quant_from_filename(name) == expected

    def test_all_known_quants_detectable(self) -> None:
        for q in KNOWN_QUANTS:
            assert detect_quant_from_filename(f"model.{q}.gguf") == q


class TestHumanSize:
    @pytest.mark.parametrize("n,expected_substring", [
        (0, "0.00 B"),
        (1023, "B"),
        (1024, "1.00 KB"),
        (1024 * 1024, "1.00 MB"),
        (1024 ** 3, "1.00 GB"),
        (8 * 1024 ** 3, "8.00 GB"),
    ])
    def test_sizes(self, n: int, expected_substring: str) -> None:
        assert expected_substring in human_size(n)


class TestFileSizeBytes:
    def test_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        assert file_size_bytes(str(p)) == 5

    def test_missing(self, tmp_path: Path) -> None:
        assert file_size_bytes(str(tmp_path / "nope")) == 0


class TestModelConfig:
    def test_defaults(self) -> None:
        c = ModelConfig()
        assert c.name == "modelo-sin-nombre"
        assert c.ctx_size == 4096
        assert c.mode == "cpu"
        assert c.gpu_layers == 0
        assert c.backend_kind == "llama_cli"
        assert not c.exists()

    def test_exists_missing(self, tmp_path: Path) -> None:
        c = ModelConfig(gguf_path=str(tmp_path / "no.gguf"))
        assert not c.exists()

    def test_exists_ok(self, tmp_path: Path) -> None:
        p = tmp_path / "model.Q4_K_M.gguf"
        p.write_bytes(b"x" * 100)
        c = ModelConfig(gguf_path=str(p))
        assert c.exists()
        assert c.size_bytes == 100
        assert c.quant == "Q4_K_M"
        assert "100.00" in c.size_human

    def test_to_from_dict_roundtrip(self) -> None:
        c = ModelConfig(
            name="gemma",
            gguf_path=r"C:\fake\model.Q4_K_M.gguf",
            ctx_size=8192,
            threads=12,
            temperature=0.3,
            top_p=0.9,
            repeat_penalty=1.05,
            mode="cpu",
            gpu_layers=0,
        )
        d = c.to_dict()
        assert d["name"] == "gemma"
        assert d["quant"] == "Q4_K_M"
        assert d["ctx_size"] == 8192
        c2 = ModelConfig.from_dict(d)
        assert c2.name == c.name
        assert c2.ctx_size == c.ctx_size
        assert c2.temperature == pytest.approx(c.temperature)

    def test_from_dict_ignores_unknown_keys(self) -> None:
        d = {"name": "x", "extra_unknown_key": 123}
        c = ModelConfig.from_dict(d)
        assert c.name == "x"


class TestExampleConfig:
    def test_models_example_loads(self, example_model_config_path: Path) -> None:
        data = json.loads(example_model_config_path.read_text(encoding="utf-8"))
        # No debe tener claves rotas (campos con tipos basicos)
        for key in ("name", "gguf_path", "ctx_size", "threads", "temperature",
                    "top_p", "repeat_penalty", "mode", "gpu_layers", "backend_kind"):
            assert key in data
        # debe parsear
        c = ModelConfig.from_dict(data)
        assert c.name == "Gemma 4 12B Q4_K_M"
        assert c.backend_kind == "llama_cli"