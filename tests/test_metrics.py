"""Tests para app.metrics."""

import time

import pytest

from app.metrics import (
    _human_bytes,
    find_executable,
    get_process_metrics,
    get_system_memory,
    measure_inference,
    peak_rss_self,
)


class TestHumanBytes:
    @pytest.mark.parametrize("n,expected_substring", [
        (0, "0.00 B"),
        (1024, "1.00 KB"),
        (1024 ** 3, "1.00 GB"),
    ])
    def test_format(self, n: int, expected_substring: str) -> None:
        assert expected_substring in _human_bytes(n)

    def test_none(self) -> None:
        assert _human_bytes(None) == "?"


class TestSystemMemory:
    def test_returns_dict_with_expected_keys(self) -> None:
        m = get_system_memory()
        for k in ("total_bytes", "available_bytes", "used_bytes", "total_human", "available_human", "used_human"):
            assert k in m
        # No podemos asumir valor exacto, pero los *_human son strings no vacios o "?"
        for k in ("total_human", "available_human", "used_human"):
            assert isinstance(m[k], str)


class TestProcessMetrics:
    def test_none_pid_safe(self) -> None:
        m = get_process_metrics(None)
        assert m["pid"] is None
        assert m["rss_bytes"] is None
        assert m["running"] is False

    def test_self_pid(self) -> None:
        import os
        m = get_process_metrics(os.getpid())
        assert m["pid"] == os.getpid()
        assert m["running"] is True


class TestMeasureInference:
    def test_basic(self) -> None:
        def fn(p: str, s: str = "") -> str:
            time.sleep(0.01)
            return "x" * 400

        m = measure_inference(fn, "hola", "sys")
        assert m["error"] is None
        assert m["char_count"] == 400
        assert m["elapsed_sec"] >= 0.01
        # 400 chars / 4 = 100 tokens, / elapsed -> positivo
        assert m["tokens_per_sec_proxy"] is not None
        assert m["tokens_per_sec_proxy"] > 0

    def test_error_captured(self) -> None:
        def fn(p: str, s: str = "") -> str:
            raise ValueError("boom")

        m = measure_inference(fn, "x")
        assert m["error"] is not None
        assert "boom" in m["error"]
        assert m["char_count"] == 0


class TestPeakRssSelf:
    def test_returns_int_or_none(self) -> None:
        v = peak_rss_self()
        assert v is None or isinstance(v, int)
        if v is not None:
            assert v > 0


class TestFindExecutable:
    def test_python_resolves(self) -> None:
        # Python siempre esta en PATH en el test runner
        p = find_executable("python") or find_executable("python.exe")
        assert p is not None
        assert p.lower().endswith(("python", "python.exe"))

    def test_nonexistent(self) -> None:
        assert find_executable("definitely_not_a_real_binary_xyz123") is None