"""Tests para app.benchmark usando backend mock (no necesita modelo real)."""

import json
from pathlib import Path

import pytest

from app.benchmark import (
    DEFAULT_PROMPTS_FILE,
    DEFAULT_RESULTS_DIR,
    load_prompts,
    run_benchmark,
)
from app.llama_backend import LlamaBackend
from app.model_config import ModelConfig


@pytest.fixture
def mock_backend() -> LlamaBackend:
    b = LlamaBackend(ModelConfig(name="mock-model"))
    b.start()
    return b


class TestLoadPrompts:
    def test_default_file_loads(self, sample_prompts_path: Path) -> None:
        prompts = load_prompts(str(sample_prompts_path))
        assert len(prompts) >= 10
        for p in prompts:
            assert "key" in p
            assert "title" in p
            assert "prompt" in p

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_prompts(str(tmp_path / "nope.json")) == []

    def test_malformed_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{ this is not valid json", encoding="utf-8")
        assert load_prompts(str(p)) == []


class TestRunBenchmark:
    def test_produces_files(self, mock_backend: LlamaBackend, tmp_path: Path) -> None:
        prompts = load_prompts(str(Path(__file__).resolve().parent.parent / "benchmarks" / "prompts_es.json"))
        result = run_benchmark(
            mock_backend,
            prompts=prompts[:3],
            results_dir=str(tmp_path),
            label="unit-test",
        )
        files = sorted(tmp_path.iterdir())
        assert any(f.suffix == ".json" for f in files)
        assert any(f.suffix == ".md" for f in files)

    def test_result_schema(self, mock_backend: LlamaBackend, tmp_path: Path) -> None:
        prompts = load_prompts(str(Path(__file__).resolve().parent.parent / "benchmarks" / "prompts_es.json"))
        result = run_benchmark(
            mock_backend,
            prompts=prompts[:2],
            results_dir=str(tmp_path),
            label="schema-test",
        )
        assert result["schema_version"] == 1
        assert result["label"] == "schema-test"
        assert result["totals"]["prompts_run"] == 2
        assert "timestamp" in result
        assert result["backend"]["backend"] == "mock"
        assert result["backend"]["mock"] is True
        assert isinstance(result["items"], list)
        assert len(result["items"]) == 2
        for it in result["items"]:
            assert "key" in it
            assert "title" in it
            assert "prompt" in it
            assert "response" in it
            assert "metrics" in it
            assert "elapsed_sec" in it["metrics"]
            assert "char_count" in it["metrics"]

    def test_json_roundtrip(self, mock_backend: LlamaBackend, tmp_path: Path) -> None:
        prompts = load_prompts(str(Path(__file__).resolve().parent.parent / "benchmarks" / "prompts_es.json"))
        run_benchmark(
            mock_backend,
            prompts=prompts[:1],
            results_dir=str(tmp_path),
            label="roundtrip",
        )
        # El JSON mas reciente en tmp_path debe parsear
        jsons = sorted(tmp_path.glob("*.json"))
        assert jsons
        data = json.loads(jsons[-1].read_text(encoding="utf-8"))
        assert data["schema_version"] == 1
        assert len(data["items"]) == 1

    def test_peak_rss_safe_when_no_backend_proc(
        self, mock_backend: LlamaBackend, tmp_path: Path
    ) -> None:
        # Caso edge: backend es mock, por lo tanto no hay PID real -> rss_peak_proxy debe
        # ser 0 (no crashear con max() sobre secuencia vacia).
        prompts = load_prompts(str(Path(__file__).resolve().parent.parent / "benchmarks" / "prompts_es.json"))
        result = run_benchmark(
            mock_backend,
            prompts=prompts[:1],
            results_dir=str(tmp_path),
            label="rss-zero",
        )
        assert result["hardware"]["backend_rss_peak_proxy_bytes"] == 0

    def test_handles_default_paths(self, mock_backend: LlamaBackend, tmp_path: Path, monkeypatch) -> None:
        # Cargar prompts default sin pasar prompts ni prompts_file
        # El archivo default existe en el repo
        prompts = load_prompts(DEFAULT_PROMPTS_FILE)
        assert len(prompts) >= 10
        # Y los resultados van a DEFAULT_RESULTS_DIR (que existe por .gitkeep)
        result = run_benchmark(
            mock_backend,
            results_dir=str(tmp_path),
            label="default",
        )
        assert result["totals"]["prompts_run"] >= 10