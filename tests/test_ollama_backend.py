"""Tests para app.ollama_backend (mockeando urllib; sin daemon real)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.llama_backend import LlamaBackend  # noqa: F401 (uso implicito)
from app.model_config import ModelConfig
from app.ollama_backend import (
    DEFAULT_OLLAMA_URL,
    OllamaBackend,
    list_ollama_models,
    ollama_available,
)


def _http_response(status: int, payload):
    r = MagicMock()
    r.status = status
    body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
    if isinstance(body, str):
        body = body.encode("utf-8")
    r.read = MagicMock(return_value=body)
    # Para streaming (usado por generate_stream)
    r.__enter__ = MagicMock(return_value=r)
    r.__exit__ = MagicMock(return_value=False)
    r.close = MagicMock()
    # Si el codigo de test itera sobre `for raw in resp:`, hacer iterable
    r.__iter__ = MagicMock(return_value=iter([]))
    return r


class TestProbes:
    @patch("app.ollama_backend._http_json")
    def test_ollama_available_true(self, mock_http: MagicMock) -> None:
        mock_http.return_value = (200, {"models": []})
        assert ollama_available() is True

    @patch("app.ollama_backend._http_json")
    def test_ollama_available_false(self, mock_http: MagicMock) -> None:
        mock_http.return_value = (0, "connection refused")
        assert ollama_available() is False

    @patch("app.ollama_backend._http_json")
    def test_list_models(self, mock_http: MagicMock) -> None:
        mock_http.return_value = (200, {
            "models": [
                {"name": "gemma3:12b", "size": 8_000_000_000},
                {"name": "qwen3:14b", "size": 9_000_000_000},
            ]
        })
        models = list_ollama_models()
        assert len(models) == 2
        assert models[0]["name"] == "gemma3:12b"

    @patch("app.ollama_backend._http_json")
    def test_list_models_empty_on_error(self, mock_http: MagicMock) -> None:
        mock_http.return_value = (0, "boom")
        assert list_ollama_models() == []


class TestOllamaBackendMocked:
    """Backend con Ollama daemon disponible (mockeado)."""

    def _make_backend(self, name: str = "gemma3:12b") -> OllamaBackend:
        cfg = ModelConfig(name=name, backend_kind="ollama", ollama_url=DEFAULT_OLLAMA_URL)
        b = OllamaBackend(cfg)
        return b

    @patch("app.ollama_backend.ollama_available", return_value=True)
    @patch("app.ollama_backend.list_ollama_models")
    def test_start_ok(self, mock_list: MagicMock, mock_avail: MagicMock) -> None:
        mock_list.return_value = [{"name": "gemma3:12b"}, {"name": "qwen3:14b"}]
        b = self._make_backend("gemma3:12b")
        assert b.start() is True
        s = b.status()
        assert s["backend"] == "ollama"
        assert s["mock"] is False
        assert "gemma3:12b" in s["available_models"]

    @patch("app.ollama_backend.ollama_available", return_value=True)
    @patch("app.ollama_backend.list_ollama_models")
    def test_start_warns_missing_model(self, mock_list: MagicMock, mock_avail: MagicMock) -> None:
        mock_list.return_value = [{"name": "other-model"}]
        b = self._make_backend("nope")
        b.start()
        assert "no esta en Ollama" in (b.last_error or "")

    @patch("app.ollama_backend.ollama_available", return_value=False)
    def test_start_mock_when_no_daemon(self, mock_avail: MagicMock) -> None:
        b = self._make_backend()
        b.start()
        s = b.status()
        assert s["mock"] is True
        assert s["backend"] == "mock"

    @patch("app.ollama_backend.ollama_available", return_value=False)
    def test_generate_mock_does_not_raise(self, mock_avail: MagicMock) -> None:
        b = self._make_backend()
        b.start()
        out = b.generate("hola", "sos util")
        assert "[ollama-mock]" in out
        assert isinstance(out, str)

    @patch("app.ollama_backend.ollama_available", return_value=False)
    def test_generate_stream_mock_yields(self, mock_avail: MagicMock) -> None:
        b = self._make_backend()
        b.start()
        chunks = list(b.generate_stream("x", ""))
        assert len(chunks) == 1
        assert "[ollama-mock]" in chunks[0]

    @patch("app.ollama_backend.ollama_available", return_value=True)
    @patch("app.ollama_backend.list_ollama_models", return_value=[{"name": "gemma3:12b"}])
    @patch("app.ollama_backend._http_json")
    def test_generate_via_api(self, mock_http: MagicMock, mock_list: MagicMock,
                              mock_avail: MagicMock) -> None:
        mock_http.return_value = (200, {"response": "Hola desde Ollama", "done": True})
        b = self._make_backend("gemma3:12b")
        b.start()
        out = b.generate("ping", "sys")
        assert out == "Hola desde Ollama"

    @patch("app.ollama_backend.ollama_available", return_value=True)
    @patch("app.ollama_backend.list_ollama_models", return_value=[{"name": "gemma3:12b"}])
    @patch("app.ollama_backend.urllib.request.urlopen")
    def test_generate_stream_via_api(self, mock_urlopen: MagicMock,
                                     mock_list: MagicMock, mock_avail: MagicMock) -> None:
        # Simular NDJSON streaming
        ndjson_lines = [
            json.dumps({"response": "Hola "}),
            json.dumps({"response": "desde "}),
            json.dumps({"response": "Ollama", "done": True}),
        ]
        resp = MagicMock()
        resp.__iter__ = MagicMock(return_value=iter([ln.encode("utf-8") for ln in ndjson_lines]))
        resp.close = MagicMock()
        mock_urlopen.return_value = resp

        b = self._make_backend("gemma3:12b")
        b.start()
        chunks = list(b.generate_stream("ping", "sys"))
        assert "".join(chunks) == "Hola desde Ollama"
        resp.close.assert_called()

    @patch("app.ollama_backend.ollama_available", return_value=False)
    def test_status_shape_when_mock(self, mock_avail: MagicMock) -> None:
        b = self._make_backend()
        b.start()
        s = b.status()
        for k in ("backend", "mock", "running", "pid", "command", "exe",
                  "load_error", "ollama_url", "available_models"):
            assert k in s

    def test_stop_does_not_raise(self) -> None:
        b = self._make_backend()
        b.start()
        b.stop()  # sin proc activo, no raise

    def test_request_abort_safe_no_active_stream(self) -> None:
        b = self._make_backend()
        b.start()
        b.request_abort()  # sin stream activo, no raise


class TestBackendBaseContract:
    """OllamaBackend cumple el contrato BackendBase."""

    def test_is_backend_base(self) -> None:
        from app.backend_base import BackendBase
        b = OllamaBackend(ModelConfig(name="x", backend_kind="ollama"))
        assert isinstance(b, BackendBase)

    def test_default_stream_yields_generate(self) -> None:
        # El default en BackendBase.generate_stream yield lo de generate().
        # Aqui comprobamos que en OllamaBackend (override) tambien respeta el contrato:
        # nunca raise.
        b = OllamaBackend(ModelConfig(name="x", backend_kind="ollama"))
        b.start()  # cai a mock si daemon no esta
        # No raise
        for _ in b.generate_stream("q", "s"):
            pass