"""Smoke test end-to-end sin UI: backend mock + benchmark + presets + load/save config."""

import json
from pathlib import Path

import pytest

from app.benchmark import run_benchmark
from app.llama_backend import LlamaBackend
from app.model_config import ModelConfig
from app.presets import get_preset


class TestEndToEnd:
    def test_full_prompts_run_succeeds(self, tmp_path: Path) -> None:
        # Backend mock + todos los prompts del repo
        b = LlamaBackend(ModelConfig(name="e2e"))
        b.start()
        assert b.is_running()
        out = b.generate("hola", "sys")
        assert isinstance(out, str)
        # Correr benchmark minimo
        result = run_benchmark(
            b,
            prompts=[
                {"key": "p1", "title": "P1", "prompt": "ping", "system": ""},
                {"key": "p2", "title": "P2", "prompt": "pong", "system": "sos util"},
            ],
            results_dir=str(tmp_path),
            label="e2e",
        )
        assert result["totals"]["prompts_run"] == 2
        # Streaming debe dar chunks
        chunks = list(b.generate_stream("ping", "sos util"))
        assert all(isinstance(c, str) for c in chunks)
        # No debe haber raise

    def test_config_roundtrip_with_presets(self, tmp_path: Path) -> None:
        cfg = ModelConfig(
            name="test",
            gguf_path="C:\\fake\\model.Q4_K_M.gguf",
            ctx_size=2048,
            threads=4,
            temperature=0.5,
            mode="cpu",
        )
        data = cfg.to_dict()
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        loaded = ModelConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
        assert loaded.name == "test"
        assert loaded.ctx_size == 2048
        # Preset sugerido para coding tiene temp baja
        p = get_preset("coding")
        assert p is not None
        assert p.temperature < 0.5

    def test_main_module_imports(self) -> None:
        # Verifica que el entry point se puede importar
        from app import main as m
        assert hasattr(m, "main")
        assert hasattr(m, "_print_env_summary")
        assert callable(m.main)