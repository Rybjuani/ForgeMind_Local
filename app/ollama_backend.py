"""Backend Ollama local (http://127.0.0.1:11434).

Ollama expone una API REST local. No requiere build ni Python binding:
solo el daemon de Ollama corriendo y un modelo descargado (`ollama pull`).

Endpoints usados:
  - GET  /api/tags                  -> lista modelos disponibles
  - POST /api/show {name}           -> info del modelo (sirve como health check)
  - POST /api/generate {model,prompt,stream,options}  -> {response} o NDJSON si stream

NO requiere ni .gguf ni llama.cpp. Pensado como backend secundario para
usar modelos que ya tenes descargados en Ollama.

Si Ollama no esta corriendo, el backend cae a modo MOCK sin raise.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

from .backend_base import BackendBase
from .model_config import ModelConfig


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


def _http_json(url: str, method: str = "GET", body: dict | None = None,
               timeout: float = 5.0) -> tuple[int, dict | str | None]:
    """Wrapper minimo sobre urllib. Devuelve (status, parsed_or_raw)."""
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw) if raw else None
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        return e.code, raw or None
    except Exception as e:
        return 0, str(e)


def list_ollama_models(base_url: str = DEFAULT_OLLAMA_URL,
                       timeout: float = 3.0) -> list[dict[str, Any]]:
    """Lista modelos disponibles en Ollama. Vacio si no responde."""
    status, data = _http_json(f"{base_url}/api/tags", timeout=timeout)
    if status != 200 or not isinstance(data, dict):
        return []
    return list(data.get("models") or [])


def ollama_available(base_url: str = DEFAULT_OLLAMA_URL,
                     timeout: float = 3.0) -> bool:
    """True si el daemon Ollama responde."""
    status, _ = _http_json(f"{base_url}/api/tags", timeout=timeout)
    return status == 200


class OllamaBackend(BackendBase):
    """Backend que habla con Ollama via HTTP. Modo mock si no responde."""

    name = "ollama"

    def __init__(self, config: ModelConfig) -> None:
        super().__init__(config)
        self.base_url: str = getattr(config, "ollama_url", "") or DEFAULT_OLLAMA_URL
        self._available: bool = False
        self._available_models: list[dict[str, Any]] = []
        self._active_resp: Any = None  # response HTTP del stream activo (para abort)

    # ---------- ciclo de vida ----------

    def start(self) -> bool:
        self._available = ollama_available(self.base_url)
        if not self._available:
            self.last_error = f"Ollama no responde en {self.base_url}"
            return True  # modo mock "arranca" siempre; is_running True
        self._available_models = list_ollama_models(self.base_url)
        # Verificar que el modelo pedido exista; si no, sugerimos el primero disponible
        wanted = self.config.name
        names = [m.get("name", "") for m in self._available_models]
        if wanted and wanted not in names and names:
            self.last_error = f"Modelo '{wanted}' no esta en Ollama. Disponibles: {names[:5]}"
        else:
            self.last_error = None
        self.last_command = f"Ollama @ {self.base_url} model={wanted}"
        return True

    def stop(self) -> None:
        # Ollama es externo: cierro stream activo si hay
        try:
            if self._active_resp is not None:
                self._active_resp.close()
        except Exception:
            pass
        self._active_resp = None

    def is_running(self) -> bool:
        # En Ollama, "running" significa que el daemon esta vivo.
        # No re-pingueamos cada vez (caro); confiamos en start().
        return True

    def request_abort(self) -> None:
        try:
            if self._active_resp is not None:
                self._active_resp.close()
                self._active_resp = None
        except Exception:
            pass

    # ---------- inferencia ----------

    def generate(self, prompt: str, system: str = "") -> str:
        if not self._available:
            return self._mock_response(prompt, system)
        body = {
            "model": self.config.name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "repeat_penalty": self.config.repeat_penalty,
                "num_predict": self.config.max_tokens,
                "num_ctx": self.config.ctx_size,
            },
        }
        if system:
            body["system"] = system
        status, data = _http_json(f"{self.base_url}/api/generate", method="POST",
                                  body=body, timeout=600.0)
        if status != 200 or not isinstance(data, dict):
            self.last_error = f"ollama generate status={status}: {data}"
            return self._mock_response(prompt, system)
        return (data.get("response") or "").strip()

    def generate_stream(self, prompt: str, system: str = "") -> Iterator[str]:
        if not self._available:
            yield self._mock_response(prompt, system)
            return
        body = {
            "model": self.config.name,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "repeat_penalty": self.config.repeat_penalty,
                "num_predict": self.config.max_tokens,
                "num_ctx": self.config.ctx_size,
            },
        }
        if system:
            body["system"] = system
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            self._active_resp = resp
            try:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    chunk = obj.get("response")
                    if chunk:
                        yield chunk
                    if obj.get("done"):
                        break
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
                self._active_resp = None
        except urllib.error.URLError as e:
            self.last_error = f"ollama stream unreachable: {e}"
        except Exception as e:
            self.last_error = f"ollama stream error: {e}"

    # ---------- observabilidad ----------

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.name if self._available else "mock",
            "mock": not self._available,
            "running": self._available,
            "pid": None,
            "command": self.last_command,
            "exe": None,
            "load_error": self.last_error,
            "ollama_url": self.base_url,
            "available_models": [m.get("name", "") for m in self._available_models],
        }

    def process_metrics(self) -> dict[str, Any]:
        # Ollama es un proceso externo; sin PID accesible desde aca.
        return {"pid": None, "rss_bytes": None, "rss_human": "?",
                "cpu_percent": None, "running": self._available}

    @staticmethod
    def peak_rss_self() -> int | None:
        from .metrics import peak_rss_self
        return peak_rss_self()

    # ---------- mock ----------

    def _mock_response(self, prompt: str, system: str) -> str:
        preview = (prompt[:160] + "...") if len(prompt) > 160 else prompt
        return (
            f"[ollama-mock] Ollama no esta corriendo en {self.base_url}. "
            f"Inicia el daemon (`ollama serve`) y descarga un modelo (`ollama pull gemma3:12b`). "
            f"Prompt ({len(prompt)} chars): {preview!r}"
        )