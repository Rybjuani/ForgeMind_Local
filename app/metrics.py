"""Metricas de rendimiento: RAM, CPU, latencia, tokens/s.

Pensado para correr dentro del mismo proceso Python que la UI.
Si psutil no esta instalado, devuelve None en vez de romper.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any


def _have_psutil() -> bool:
    try:
        import psutil  # noqa: F401
        return True
    except Exception:
        return False


def get_system_memory() -> dict[str, Any]:
    """RAM total / disponible / usada del sistema en bytes."""
    if not _have_psutil():
        return {"total_bytes": None, "available_bytes": None, "used_bytes": None,
                "total_human": "?", "available_human": "?", "used_human": "?"}
    import psutil
    vm = psutil.virtual_memory()
    return {
        "total_bytes": vm.total,
        "available_bytes": vm.available,
        "used_bytes": vm.used,
        "percent": vm.percent,
        "total_human": _human_bytes(vm.total),
        "available_human": _human_bytes(vm.available),
        "used_human": _human_bytes(vm.used),
    }


def get_process_metrics(pid: int | None) -> dict[str, Any]:
    """RSS / CPU% / status de un PID externo (el backend)."""
    if pid is None or not _have_psutil():
        return {"pid": pid, "rss_bytes": None, "cpu_percent": None,
                "rss_human": "?", "running": False}
    import psutil
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            rss = p.memory_info().rss
            cpu = p.cpu_percent(interval=0.0)
            return {
                "pid": pid,
                "rss_bytes": rss,
                "rss_human": _human_bytes(rss),
                "cpu_percent": cpu,
                "running": p.is_running(),
            }
    except Exception as e:
        return {"pid": pid, "rss_bytes": None, "cpu_percent": None,
                "rss_human": "?", "running": False, "error": str(e)}


def peak_rss_self() -> int | None:
    """Peak RSS del proceso actual (donde corre la UI). None si no disponible."""
    if not _have_psutil():
        return None
    import psutil
    try:
        p = psutil.Process(os.getpid())
        info = p.memory_info()
        # peak_wss es Linux/macOS; en Windows psutil expone peak_working_set_size
        peak = getattr(info, "peak_wss", 0) or 0
        if not peak:
            peak = getattr(info, "peak_working_set_size", 0) or 0
        return peak or info.rss
    except Exception:
        return None


def measure_inference(callable_, prompt: str, *args, **kwargs) -> dict[str, Any]:
    """Cronometra una llamada de inferencia y aproxima tokens/s.

    Proxy: 1 token ~= 4 chars (orden de magnitud, no exacto).
    Devuelve dict listo para guardar en JSON.
    """
    t0 = time.perf_counter()
    error: str | None = None
    try:
        out = callable_(prompt, *args, **kwargs)
        if not isinstance(out, str):
            out = str(out)
    except Exception as e:  # el callable no deberia raise, pero por si acaso
        out = ""
        error = str(e)
    elapsed = time.perf_counter() - t0
    char_count = len(out)
    tps = (char_count / 4.0) / elapsed if elapsed > 0 else None
    return {
        "elapsed_sec": round(elapsed, 3),
        "char_count": char_count,
        "tokens_per_sec_proxy": round(tps, 3) if tps is not None else None,
        "first_token_sec": None,  # requiere streaming, pendiente MVP
        "error": error,
    }


# ------------------ Helpers ------------------

def _human_bytes(n: float | int | None) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


def find_executable(name: str) -> str | None:
    """Busca un ejecutable (con .exe en Windows)."""
    return shutil.which(name) or shutil.which(name + ".exe")