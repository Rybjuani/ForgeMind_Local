"""Tests para app.backend_base (interfaz abstracta)."""

from typing import Any, Iterator

import pytest

from app.backend_base import BackendBase
from app.model_config import ModelConfig


class _DummyBackend(BackendBase):
    """Backend minimo que respeta el contrato."""
    name = "dummy"

    def __init__(self, config: ModelConfig) -> None:
        super().__init__(config)
        self._running = False
        self.calls: list[tuple[str, str]] = []

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def generate(self, prompt: str, system: str = "") -> str:
        self.calls.append((prompt, system))
        return f"ECHO[{prompt[:20]}]"

    def status(self) -> dict[str, Any]:
        return {"running": self._running, "name": self.name}


class TestContract:
    def test_subclass_must_implement_abstract(self) -> None:
        class Incomplete(BackendBase):
            pass
        with pytest.raises(TypeError):
            Incomplete(ModelConfig())

    def test_start_stop_cycle(self) -> None:
        b = _DummyBackend(ModelConfig())
        assert not b.is_running()
        assert b.start() is True
        assert b.is_running()
        b.stop()
        assert not b.is_running()

    def test_generate_default_stream(self) -> None:
        b = _DummyBackend(ModelConfig())
        b.start()
        chunks = list(b.generate_stream("hola", "sys"))
        # Default implementation yield el generate() entero en 1 chunk
        assert chunks == ["ECHO[hola]"]

    def test_generate_records_call(self) -> None:
        b = _DummyBackend(ModelConfig())
        b.start()
        b.generate("pregunta", "contexto")
        assert b.calls == [("pregunta", "contexto")]

    def test_status_shape(self) -> None:
        b = _DummyBackend(ModelConfig())
        b.start()
        s = b.status()
        assert s["running"] is True
        assert s["name"] == "dummy"

    def test_repr_includes_class(self) -> None:
        b = _DummyBackend(ModelConfig())
        assert "_DummyBackend" in repr(b)