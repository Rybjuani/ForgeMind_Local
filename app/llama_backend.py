"""Backend llama.cpp.

Tres modos (segun ModelConfig.backend_kind):

  1) "llama_cli"   -> subprocess a llama-cli (MVP default; portable, sin build).
  2) "llama_server"-> subprocess a llama-server (HTTP local; recomendado si
                      se quiere reutilizar el modelo entre varias requests).
  3) "llama_cpp"   -> binding Python (opcional, requiere instalar
                      `llama-cpp-python`; NO es hard dependency).

Si nada esta disponible, arranca en modo MOCK y generate() devuelve una
respuesta etiquetada. Nunca raise desde generate() ni generate_stream().
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
from typing import Any, Iterator

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
        self._active_proc: subprocess.Popen | None = None  # proc de generate_stream en curso
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
        # 0) Demo mode (MOCK_LLM=1): short-circuit to mock so the UI
        # shows "Activo" + Gemma 4 12B without spawning any subprocess.
        # The DemoModelConfig.exists() lies and returns True so the
        # config screen displays OK status, but we never actually try
        # to invoke llama-cli with a fake path.
        if getattr(self.config, "is_demo", False):
            self._mock = True
            self._backend_kind_active = "mock"
            self._load_error = None
            return
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
            # Abortar generacion en curso primero
            for p in (self._proc, self._active_proc):
                if p is not None and p.poll() is None:
                    try:
                        if os.name == "nt":
                            p.terminate()
                        else:
                            p.send_signal(signal.SIGTERM)
                    except Exception:
                        pass
            try:
                for p in (self._proc, self._active_proc):
                    if p is not None:
                        try:
                            p.wait(timeout=3)
                        except Exception:
                            try:
                                p.kill()
                            except Exception:
                                pass
            finally:
                self._proc = None
                self._active_proc = None
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

    def generate_stream(self, prompt: str, system: str = "") -> Iterator[str]:
        """Yield chunks de texto conforme se producen. NO raise.

        Cada chunk es un string (puede ser multi-linea si el backend asi emite).
        El caller es responsable de medir first_token_sec al recibir el primer yield.
        """
        if self._backend_kind_active == "mock" and self._exe is None and self._binding is None:
            self._resolve_mode()

        # Mock -> yield todo junto
        if self._mock or self._backend_kind_active == "mock":
            yield self._mock_response(prompt, system)
            return

        # llama-cli subprocess streaming
        if self._backend_kind_active == "llama_cli" and self._exe is not None:
            yield from self._stream_via_cli(prompt, system)
            return

        # llama-server HTTP streaming
        if self._backend_kind_active == "llama_server":
            yield from self._stream_via_server(prompt, system)
            return

        # binding Python con stream=True si lo soporta
        if self._backend_kind_active == "llama_cpp" and self._binding is not None:
            try:
                full = (f"{system}\n\n{prompt}" if system else prompt)
                stream = self._binding(
                    full,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    top_p=self.config.top_p,
                    repeat_penalty=self.config.repeat_penalty,
                    stop=["</s>", "Usuario:"],
                    stream=True,
                )
                for chunk in stream:
                    piece = chunk.get("choices", [{}])[0].get("text") or ""
                    if piece:
                        yield piece
            except TypeError:
                # El binding no acepta stream=True -> fallback a generate()
                yield self.generate(prompt, system)
            except Exception as e:
                self._load_error = f"stream error: {e}"
                yield self._mock_response(prompt, system)
            return

        yield self._mock_response(prompt, system)

    def request_abort(self) -> None:
        """Pide abortar la generacion en curso. No raise. Best-effort."""
        with self._lock:
            proc = self._active_proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGTERM)
        except Exception as e:
            self._load_error = f"abort failed: {e}"

    # ---------- streaming interno ----------

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

    # ---------- streaming interno ----------

    def _stream_via_cli(self, prompt: str, system: str) -> Iterator[str]:
        """Stream output from a one-shot llama-cli subprocess.

        On Windows, ``subprocess.Popen`` with a pipe *and* line buffering
        frequently buffers the entire output until the process exits,
        which kills our streaming UX. We work around that with a
        dedicated reader thread that drains the pipe into a queue.
        """
        cmd = _build_cli_command(self.config, self._exe, prompt, system)
        self.last_command = " ".join(_quote(a) for a in cmd)
        self.last_pid = None
        import queue as _queue
        from threading import Thread

        try:
            # Binary mode + explicit decode is the most reliable way to
            # stream on Windows. text=True + bufsize=1 ends up buffering
            # the entire output until the process exits.
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
            self._active_proc = proc
            self.last_pid = proc.pid

            q: _queue.Queue[str | None] = _queue.Queue(maxsize=10_000)

            def _reader() -> None:
                assert proc.stdout is not None
                try:
                    # Read in larger chunks for throughput; the queue
                    # hands the consumer a steady stream of bytes that
                    # the consumer assembles into lines.
                    while True:
                        chunk = proc.stdout.read(4096)
                        if not chunk:
                            q.put(None)
                            return
                        try:
                            q.put(chunk.decode("utf-8", errors="replace"))
                        except Exception:
                            q.put("?")
                except Exception:
                    q.put(None)

            t = Thread(target=_reader, daemon=True)
            t.start()

            # Line-prefixes that are llama.cpp's own UI/log text, not
            # model output. We skip them so the chat stays clean.
            noise_prefixes = (
                "llama_",
                "llm_load",
                "system_info:",
                "load:",
                "load_tensors:",
                "load_backend:",
                "load_model:",
                "init:",
                "sampler chain:",
                "sampler seed:",
                "sampler params:",
                "generate:",
                "main:",
                "== Running in interactive",
                "==",
                "- Press Ctrl+C",
                "- Press Return",
                "- To return control",
                "- If you want to submit",
                "- Not using system message",
                "> EOF by user",
                "llama_perf_",
                "top_k =",
                "top_p =",
                "min_p =",
                "xtc_",
                "typical_p =",
                "top_n_sigma =",
                "temp =",
                "mirostat",
                "repeat_last_n",
                "frequency_penalty",
                "presence_penalty",
                "dry_multiplier",
                "dry_base",
                "dry_allowed",
                "dry_penalty_last_n",
                "Reverse prompt:",
                "sampling:",
                "model ",
                "n_keep =",
                "common:",
                "common_perf",
                "print_info:",
                "interactive",
                "build:",
                "WARNING:",
                "warning:",
                "error:",
                "log:",
                "common_init_from_params:",
                "*** User-specified prompt",
            )

            buf = ""
            saw_chat_boundary = False
            while True:
                try:
                    item = q.get(timeout=600)
                except _queue.Empty:
                    break
                if item is None:
                    # EOF
                    break
                buf += item
                # Normalize line endings: llama.cpp uses \r in some places
                # (e.g. model loading progress), \n in others. Treat both
                # as line terminators.
                buf = buf.replace("\r\n", "\n").replace("\r", "\n")
                # Drop leading run of dots+spaces (loading progress lines
                # that never end with a newline because of buffering)
                while len(buf) > 0 and buf[0] in (".", " "):
                    buf = buf[1:]
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    s = line.lstrip()
                    if not s:
                        continue
                    if any(s.startswith(p) for p in noise_prefixes):
                        continue
                    # Skip chat-template tokens (Qwen2.5, Llama-3, etc.)
                    # The model sometimes "leaks" a few turns of its
                    # training data right before producing the real
                    # response. We drop those lines but DO NOT break —
                    # the actual response comes after them.
                    if "<|im_start|>" in s or "<|im_end|>" in s:
                        continue
                    if s.strip() in {"1>", "2>", ">"}:
                        continue
                    yield s + "\n"
                if saw_chat_boundary:
                    break
                # Interruption is handled at the consumer (GenerateRunner)
                # level — LlamaBackend itself is not a QThread.

            # Flush any remaining partial line
            if buf.strip() and not saw_chat_boundary:
                s = buf.lstrip()
                if (
                    s
                    and not any(s.startswith(p) for p in noise_prefixes)
                    and "<|im_start|>" not in s
                    and "<|im_end|>" not in s
                    and s.strip() not in {"1>", "2>", ">"}
                ):
                    yield s + "\n"

            ret = proc.wait()
            if ret != 0 and not saw_chat_boundary:
                self._load_error = f"llama-cli exit {ret}"
        except subprocess.TimeoutExpired:
            self._load_error = "llama-cli timeout (>600s)"
        except Exception as e:
            self._load_error = f"llama-cli stream fallo: {e}"
        finally:
            self._active_proc = None

    def _stream_via_server(self, prompt: str, system: str) -> Iterator[str]:
        url = f"http://127.0.0.1:{self._server_port}/completion"
        body = json.dumps({
            "prompt": (f"{system}\n\n{prompt}" if system else prompt),
            "n_predict": self.config.max_tokens,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "repeat_penalty": self.config.repeat_penalty,
            "stream": True,
            "stop": ["</s>", "Usuario:"],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            try:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    # llama-server emite JSON lines o "data: {...}" (SSE)
                    payload = line
                    if line.startswith("data:"):
                        payload = line[len("data:"):].strip()
                    if payload in ("[DONE]", ""):
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        # Texto plano -> emitir tal cual
                        yield payload + "\n"
                        continue
                    chunk = obj.get("content")
                    if chunk:
                        yield chunk
                    if obj.get("stop"):
                        break
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
        except urllib.error.URLError as e:
            self._load_error = f"server unreachable: {e}"
        except Exception as e:
            self._load_error = f"server stream error: {e}"

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