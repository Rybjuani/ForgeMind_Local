"""Tests para app.llama_backend (solo modo mock; no requiere binarios)."""

import os

import pytest

from app.llama_backend import _have_llama_cpp_binding, LlamaBackend
from app.model_config import ModelConfig


class TestMockBackend:
    def test_starts_without_executable(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        assert b.start() is True
        assert b.is_running() is True

    def test_generate_does_not_raise(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        b.start()
        out = b.generate("hola", "sys")
        assert isinstance(out, str)
        assert len(out) > 0
        # Mock debe etiquetar
        assert "[mock]" in out or "mock" in out.lower()

    def test_generate_stream_yields_chunks(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        b.start()
        chunks = list(b.generate_stream("hola", "sys"))
        assert len(chunks) >= 1
        out = "".join(chunks)
        assert len(out) > 0

    def test_stop_does_not_raise(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        b.start()
        b.stop()
        # Despues de stop, en mock start_time queda en None -> is_running False
        assert b.is_running() is False

    def test_status_has_expected_keys(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        b.start()
        s = b.status()
        for k in ("backend", "mock", "running", "pid", "command", "exe",
                  "load_error", "config"):
            assert k in s
        assert s["backend"] == "mock"
        assert s["mock"] is True
        assert s["running"] is True

    def test_request_abort_is_safe(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        b.start()
        # No debe raise aunque no haya proc activo
        b.request_abort()
        b.request_abort()  # idempotente

    def test_generate_with_empty_prompt(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        b.start()
        out = b.generate("")
        assert isinstance(out, str)

    def test_process_metrics_handles_no_proc(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        b.start()
        m = b.process_metrics()
        assert m["pid"] is None
        assert m["running"] is False

    def test_repeated_starts_idempotent(self) -> None:
        b = LlamaBackend(ModelConfig(name="mock"))
        assert b.start() is True
        # Segundo start en mock: True (no recrea nada)
        assert b.start() is True


class TestBindingProbe:
    def test_probe_returns_bool(self) -> None:
        v = _have_llama_cpp_binding()
        assert isinstance(v, bool)


class TestConfigSwitch:
    def test_backend_kind_cpu_vulkan(self) -> None:
        for mode in ("cpu", "vulkan"):
            c = ModelConfig(name="x", mode=mode, gpu_layers=8 if mode == "vulkan" else 0)
            b = LlamaBackend(c)
            b.start()
            assert b.is_running() is True  # mock fallback
            b.stop()