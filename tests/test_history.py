"""Tests para app.history."""

import json
from pathlib import Path

import pytest

from app.benchmark import load_run as load_run_via_benchmark
from app.history import (
    compare_runs,
    list_runs,
    load_run,
    render_compare_markdown,
    save_compare,
)


def _fake_run(label: str, prompt_results: list[dict], path: Path,
              model: str = "fake-model", backend: str = "mock") -> dict:
    """Genera un run.json completo en disco y devuelve el dict."""
    data = {
        "schema_version": 1,
        "timestamp": "2026-06-22T12:00:00",
        "label": label,
        "backend": {
            "backend": backend,
            "mock": backend == "mock",
            "config": {"name": model, "gguf_path": "C:\\fake.gguf",
                       "quant": "Q4_K_M", "size_human": "7.50 GB",
                       "ctx_size": 4096, "mode": "cpu", "gpu_layers": 0,
                       "threads": 8, "temperature": 0.7},
        },
        "totals": {"wall_time_sec": 1.5, "prompts_run": len(prompt_results)},
        "items": prompt_results,
        "notes": [],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


class TestListRuns:
    def test_empty_when_no_dir(self, tmp_path: Path) -> None:
        assert list_runs(tmp_path / "nonexistent") == []

    def test_empty_when_dir_empty(self, tmp_path: Path) -> None:
        assert list_runs(tmp_path) == []

    def test_finds_json_runs(self, tmp_path: Path) -> None:
        _fake_run("a", [], tmp_path / "a-20260101-000000.json")
        _fake_run("b", [], tmp_path / "b-20260102-000000.json")
        runs = list_runs(tmp_path)
        assert len(runs) == 2
        # Debe tener _raw con el contenido completo
        for r in runs:
            assert "_raw" in r
            assert "label" in r["_raw"]

    def test_skips_malformed(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{ not json", encoding="utf-8")
        _fake_run("ok", [], tmp_path / "ok-20260101-000000.json")
        runs = list_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0]["label"] == "ok"


class TestLoadRun:
    def test_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        _fake_run("x", [], p)
        loaded = load_run(p)
        assert loaded is not None
        assert loaded["label"] == "x"

    def test_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_run(tmp_path / "nope.json") is None

    def test_reexport_via_benchmark(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        _fake_run("x", [], p)
        # El re-export desde benchmark funciona: llamar la funcion retorna el mismo data.
        # No testeamos `is` / `__module__` / signature porque Python re-asigna
        # el nombre al importar (`from X import Y as Y`); eso es un detalle
        # del binding, no del comportamiento.
        assert load_run_via_benchmark(p)["label"] == "x"


class TestCompareRuns:
    def test_with_paths(self, tmp_path: Path) -> None:
        p1 = tmp_path / "r1-20260101-000000.json"
        p2 = tmp_path / "r2-20260102-000000.json"
        _fake_run("gemma", [
            {"key": "p1", "title": "P1", "prompt": "x", "response": "y",
             "metrics": {"elapsed_sec": 1.0, "char_count": 100,
                         "tokens_per_sec_proxy": 25.0, "first_token_sec": 0.1}},
        ], p1, model="gemma-4-12b")
        _fake_run("qwen", [
            {"key": "p1", "title": "P1", "prompt": "x", "response": "z",
             "metrics": {"elapsed_sec": 1.5, "char_count": 110,
                         "tokens_per_sec_proxy": 18.0, "first_token_sec": 0.2}},
        ], p2, model="qwen3-14b")
        cmp = compare_runs([str(p1), str(p2)])
        assert "gemma" in cmp["markdown"]
        assert "qwen" in cmp["markdown"]
        assert "p1" in cmp["per_prompt"]
        rows = cmp["per_prompt"]["p1"]
        assert len(rows) == 2
        # summary tiene 2 runs
        assert len(cmp["summary"]) == 2
        # avg_tps_proxy presente
        for s in cmp["summary"]:
            assert s["avg_tps_proxy"] is not None

    def test_with_dicts(self, tmp_path: Path) -> None:
        p = tmp_path / "r1.json"
        data = _fake_run("only", [
            {"key": "k", "title": "T", "prompt": "q", "response": "r",
             "metrics": {"elapsed_sec": 0.5, "char_count": 50,
                         "tokens_per_sec_proxy": 25.0, "first_token_sec": None}},
        ], p)
        # usar el _raw directo
        from app.history import list_runs
        runs = list_runs(tmp_path)
        assert len(runs) == 1
        cmp = compare_runs(runs)
        assert cmp["runs"]  # no vacio
        assert "only" in cmp["markdown"]

    def test_empty(self) -> None:
        cmp = compare_runs([])
        assert cmp["runs"] == []
        assert cmp["markdown"] == "(sin runs)"

    def test_corrupt_path_skipped(self, tmp_path: Path) -> None:
        # un path inexistente + un path valido -> solo cuenta el valido
        p = tmp_path / "ok.json"
        _fake_run("ok", [], p)
        cmp = compare_runs([str(tmp_path / "nope.json"), str(p)])
        assert len(cmp["summary"]) == 1


class TestSaveCompare:
    def test_writes_json_and_md(self, tmp_path: Path) -> None:
        p1 = tmp_path / "r1.json"
        _fake_run("a", [], p1)
        cmp = compare_runs([str(p1)])
        jp, mp = save_compare(cmp, results_dir=tmp_path)
        assert jp.exists()
        assert mp.exists()
        # ambos contienen el label
        assert "a" in jp.read_text(encoding="utf-8")
        assert "a" in mp.read_text(encoding="utf-8")

    def test_creates_dir_if_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "results"
        cmp = compare_runs([])
        jp, mp = save_compare(cmp, results_dir=target)
        assert jp.exists()
        assert mp.exists()


class TestRenderCompareMarkdown:
    def test_returns_string(self, tmp_path: Path) -> None:
        p = tmp_path / "r.json"
        _fake_run("x", [], p)
        cmp = compare_runs([str(p)])
        md = render_compare_markdown(cmp)
        assert isinstance(md, str)
        assert "# Comparativa" in md

    def test_empty(self) -> None:
        md = render_compare_markdown({})
        assert isinstance(md, str)