"""Backend llama.cpp.

Tres modos (segun ModelConfig.backend_kind):

  1) "llama_cli"   -> subprocess a llama-cli (MVP default; portable, sin build).
  2) "llama_server"-> subprocess a llama-server (HTTP local; recomendado si
                      se quiere reutilizar el modelo entre varias requests).
  3) "llama_cpp"   -> binding Python (opcional, requiere instalar
                      `llama-cpp-python`; NO es hard dependency).

Si nada esta disponible, arranca en modo MOCK y generate() devuelve una
respuesta etiquetada. Nunca raise desde generate().
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
import json
from threading import Lock, Thread
from typing import Any

from .backend_base import BackendBase
from .metrics import find_executable, get_process_metrics, peak_rss_self
from .model_config import ModelConfig


# ----------------------------- helpers -----------------------------

def _have_llama_cpp_binding() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def _which_or_path(name: str, override: str) -> str | None:
    if override and os.path.isfile(override):
        return override
    return find_executable(name)


def _build_cli_command(cfg: ModelConfig, exe: str, prompt: str, system: str) -> list[str]:
    """Arma el argv para llama-cli (-no-display, simple)."""
    cmd = [
        exe,
        "-m", cfg.gguf_path,
        "-c", str(cfg.ctx_size),
        "-t", str(cfg.threads),
        "-n", str(cfg.max_tokens),
        "--temp", f"{cfg.temperature:.3f}",
        "--top-p", f"{cfg.top_p:.3f}",
        "--repeat-penalty", f"{cfg.repeat_penalty:.3f}",
        "-p", (f"{system}\n\n{prompt}" if system else prompt),
        "--no-display-prompt",
        "-r", "</s>",
    ]
    if cfg.mode == "vulkan" and cfg.gpu_layers > 0:
        cmd += ["-ngl", str(cfg.gpu_layers)]
    elif cfg.mode == "vulkan":
        # 999 = offload todo lo posible al GPU (regla de llama.cpp)
        cmd += ["-ngl", "999"]
    cmd += list(cfg.extra_args)
    return cmd


def _build_server_command(cfg: ModelConfig, exe: str, port: int) -> list[str]:
    """Arma el argv para arrancar llama-server."""
    cmd = [
        exe,
        "-m", cfg.gguf_path,
        "-c", str(cfg.ctx_size),
        "-t", str(cfg.threads),
        "--port", str(port),
        "--host", "127.0.0.1",
    ]
    if cfg.mode == "vulkan" and cfg.gpu_layers > 0:
        cmd += ["-ngl", str(cfg.gpu_layers)]
    elif cfg.mode == "vulkan":
        cmd += ["-ngl", "999"]
    cmd += list(cfg.extra_args)
    return cmd


# ----------------------------- backend -----------------------------

class LlamaBackend(BackendBase):
    """Backend que envuelve llama.cpp. Modo mock como fallback."""

    def __init__(self, config: ModelConfig) -> None:
        super().__init__(config)
        self._lock = Lock()
        self._proc: subprocess.Popen | None = None
        self._server_port: int = 8081
        self._mock: bool = False
        self._backend_kind_active: str = "mock"  # lo que realmente se uso
        self._exe: str | None = None
        self._load_error: str | None = None
        self._binding = None  # instancia de llama_cpp.Llama si aplica
        self._start_time: float | None = None

    # ---------- resolucion de modo ----------

    def _resolve_mode(self) -> None:
        """Decide que modo usar segun config.backend_kind y disponibilidad."""
        # 1) binding Python (si lo pidio el usuario Y esta disponible)
        if self.config.backend_kind == "llama_cpp":
            if not self.config.exists():
                self._mock = True
                self._load_error = f"Modelo no existe: {self.config.gguf_path}"
                self._backend_kind_active = "mock"
                return
            if _have_llama_cpp_binding():
                try:
                    from llama_cpp import Llama  # type: ignore
                    self._binding = Llama(
                        model_path=self.config.gguf_path,
                        n_ctx=self.config.ctx_size,
                        n_threads=self.config.threads,
                        verbose=False,
                        n_gpu_layers=(self.config.gpu_layers if self.config.mode == "vulkan" else 0),
                    )
                    self._mock = False
                    self._backend_kind_active = "llama_cpp"
                    return
                except Exception as e:
                    self._load_error = f"llama_cpp binding fallo: {e}"
            else:
                self._load_error = "llama_cpp binding no instalado (pip install llama-cpp-python)"
            # cae a subprocess si esta disponible

        # 2) subprocess: server o cli
        if self.config.backend_kind in ("llama_server", "llama_cli"):
            exe_name = "llama-server" if self.config.backend_kind == "llama_server" else "llama-cli"
            override = (self.config.llama_server_path if self.config.backend_kind == "llama_server"
                        else self.config.llama_cli_path)
            exe = _which_or_path(exe_name, override)
            if exe and self.config.exists():
                self._exe = exe
                self._mock = False
                self._backend_kind_active = self.config.backend_kind
                return
            if not exe:
                self._load_error = (f"{exe_name} no encontrado en PATH "
                                    f"(configura {exe_name} en la UI o en settings)")
            if exe and not self.config.exists():
                self._load_error = f"Modelo no existe: {self.config.gguf_path}"

        # 3) fallback mock
        self._mock = True
        self._backend_kind_active = "mock"
        if not self._load_error:
            self._load_error = "No hay backend usable; operando en modo MOCK."

    # ---------- ciclo de vida ----------

    def start(self) -> bool:
        with self._lock:
            if self.is_running():
                return True
            self._resolve_mode()
            if self._mock or self._backend_kind_active == "mock":
                self._start_time = time.time()
                return True  # mock "arranca" siempre

            try:
                if self._backend_kind_active == "llama_cpp":
                    # ya cargado en _resolve_mode
                    self._start_time = time.time()
                    return True
                if self._backend_kind_active == "llama_server":
                    cmd = _build_server_command(self.config, self._exe, self._server_port)
                    self._proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                    self.last_command = " ".join(_quote(a) for a in cmd)
                    self.last_pid = self._proc.pid
                    # Esperar a que el server responda (max 30s)
                    if not self._wait_server_ready(timeout=30.0):
                        # si no responde, no abortamos: dejamos que UI lo muestre
                        self._load_error = (self._load_error or
                                            "Servidor no respondio en 30s")
                elif self._backend_kind_active == "llama_cli":
                    # En MVP, CLI arranca bajo demanda por request (no persistente).
                    # Marcamos "running" igual para que la UI habilite botones.
                    self.last_command = f"{self._exe} -m {self.config.gguf_path} ..."
                    self.last_pid = None
            except Exception as e:
                self._load_error = f"No se pudo arrancar: {e}"
                self._mock = True
                self._backend_kind_active = "mock"
                return False
            self._start_time = time.time()
            return True

    def stop(self) -> None:
        with self._lock:
            try:
                if self._proc is not None and self._proc.poll() is None:
                    if os.name == "nt":
                        try:
                            self._proc.terminate()
                        except Exception:
                            pass
                    else:
                        try:
                            self._proc.send_signal(signal.SIGTERM)
                        except Exception:
                            pass
                    try:
                        self._proc.wait(timeout=5)
                    except Exception:
                        try:
                            self._proc.kill()
                        except Exception:
                            pass
            finally:
                self._proc = None
                self.last_pid = None
                if self._binding is not None:
                    try:
                        del self._binding
                    except Exception:
                        pass
                    self._binding = None
                self._start_time = None

    def is_running(self) -> bool:
        if self._mock or self._backend_kind_active == "mock":
            return self._start_time is not None
        if self._binding is not None:
            return True
        if self._proc is None:
            return False
        return self._proc.poll() is None

    # ---------- inferencia ----------

    def generate(self, prompt: str, system: str = "") -> str:
        # Asegurar modo resuelto
        if self._backend_kind_active == "mock" and self._exe is None and self._binding is None:
            self._resolve_mode()

        # Mock
        if self._mock or self._backend_kind_active == "mock":
            return self._mock_response(prompt, system)

        # Binding Python
        if self._backend_kind_active == "llama_cpp" and self._binding is not None:
            try:
                full = (f"{system}\n\n{prompt}" if system else prompt)
                out = self._binding(
                    full,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    top_p=self.config.top_p,
                    repeat_penalty=self.config.repeat_penalty,
                    stop=["</s>", "Usuario:"],
                )
                return (out["choices"][0]["text"] or "").strip()
            except Exception as e:
                self._load_error = f"inference error: {e}"
                return self._mock_response(prompt, system)

        # Server HTTP
        if self._backend_kind_active == "llama_server":
            return self._generate_via_server(prompt, system)

        # llama-cli subprocess (one-shot)
        if self._backend_kind_active == "llama_cli" and self._exe is not None:
            return self._generate_via_cli(prompt, system)

        return self._mock_response(prompt, system)

    def _generate_via_cli(self, prompt: str, system: str) -> str:
        cmd = _build_cli_command(self.config, self._exe, prompt, system)
        self.last_command = " ".join(_quote(a) for a in cmd)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            out = (r.stdout or "").strip()
            if r.returncode != 0 and not out:
                self._load_error = f"llama-cli exit {r.returncode}: {(r.stderr or '')[:400]}"
                return self._mock_response(prompt, system)
            return out or self._mock_response(prompt, system)
        except subprocess.TimeoutExpired:
            self._load_error = "llama-cli timeout (>600s)"
            return self._mock_response(prompt, system)
        except Exception as e:
            self._load_error = f"llama-cli fallo: {e}"
            return self._mock_response(prompt, system)

    def _generate_via_server(self, prompt: str, system: str) -> str:
        url = f"http://127.0.0.1:{self._server_port}/completion"
        body = json.dumps({
            "prompt": (f"{system}\n\n{prompt}" if system else prompt),
            "n_predict": self.config.max_tokens,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "repeat_penalty": self.config.repeat_penalty,
            "stream": False,
            "stop": ["</s>", "Usuario:"],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return (data.get("content") or "").strip()
        except urllib.error.URLError as e:
            self._load_error = f"server unreachable: {e}"
            return self._mock_response(prompt, system)
        except Exception as e:
            self._load_error = f"server error: {e}"
            return self._mock_response(prompt, system)

    def _wait_server_ready(self, timeout: float = 30.0) -> bool:
        url = f"http://127.0.0.1:{self._server_port}/health"
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                with urllib.request.urlopen(url, timeout=1.5) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                time.sleep(0.4)
        return False

    # ---------- observabilidad ----------

    def status(self) -> dict[str, Any]:
        return {
            "backend": self._backend_kind_active,
            "mock": self._mock,
            "running": self.is_running(),
            "pid": self.last_pid,
            "command": self.last_command,
            "exe": self._exe,
            "load_error": self._load_error,
            "server_port": self._server_port if self._backend_kind_active == "llama_server" else None,
            "config": self.config.to_dict(),
        }

    def process_metrics(self) -> dict[str, Any]:
        if self._proc is not None and self._proc.pid:
            return get_process_metrics(self._proc.pid)
        return {"pid": None, "rss_bytes": None, "rss_human": "?", "cpu_percent": None, "running": False}

    @staticmethod
    def peak_rss_self() -> int | None:
        return peak_rss_self()

    # ---------- mock ----------

    def _mock_response(self, prompt: str, system: str) -> str:
        head = "[mock] "
        # Recortar prompt largo para que el mock no sea infinito
        preview = (prompt[:200] + "...") if len(prompt) > 200 else prompt
        return (f"{head}No hay backend de inferencia activo. "
                f"Configura llama-server / llama-cli en el panel Backend "
                f"y vuelve a intentar. "
                f"Prompt recibido ({len(prompt)} chars): {preview!r}")


def _quote(a: str) -> str:
    if " " in a or "\t" in a:
        return f'"{a}"'
    return a