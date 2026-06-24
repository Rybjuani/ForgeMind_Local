"""Deteccion basica de GPU AMD y disponibilidad de Vulkan en Windows.

NO afirma que Vulkan mejora nada. Solo reporta lo que encuentra.

Metodos:
  - WMI Win32_VideoController (via PowerShell) para nombres / AdapterRAM.
  - vulkaninfo (si esta instalado, parte del Vulkan SDK) -> bool.
  - ctypes.LoadLibrary("vulkan-1.dll") como ultima prueba barata.

Si algo falla, devuelve None/False. Nunca raise.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from typing import Any


# ------------------ GPU detection ------------------

def _run_ps(cmd: str, timeout: float = 6.0) -> str | None:
    """Ejecuta un bloque PowerShell y devuelve stdout. None si fallo."""
    try:
        # -NoProfile para no contaminar, -ExecutionPolicy Bypass para evitar prompt.
        full = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", cmd,
        ]
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout.strip()
        return None
    except Exception:
        return None


def detect_gpus() -> list[dict[str, Any]]:
    """Devuelve lista de GPUs via WMI. Vacio si nada."""
    ps_cmd = (
        "Get-WmiObject Win32_VideoController | "
        "Select-Object Name, AdapterRAM, DriverVersion, VideoProcessor | "
        "ConvertTo-Json -Compress"
    )
    raw = _run_ps(ps_cmd)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        out: list[dict[str, Any]] = []
        for g in data:
            out.append({
                "name": (g.get("Name") or "").strip(),
                "adapter_ram_bytes": int(g.get("AdapterRAM") or 0) or None,
                "driver_version": (g.get("DriverVersion") or "").strip() or None,
                "video_processor": (g.get("VideoProcessor") or "").strip() or None,
            })
        return out
    except Exception:
        return []


def detect_amd_gpu() -> dict[str, Any] | None:
    """Devuelve la primera GPU AMD detectada, o None."""
    for g in detect_gpus():
        name_lower = (g.get("name") or "").lower()
        if "amd" in name_lower or "radeon" in name_lower or "advanced micro devices" in name_lower:
            vram = g.get("adapter_ram_bytes") or 0
            return {
                "name": g["name"],
                "vram_bytes": vram,
                "vram_human": _human_bytes(vram) if vram else "?",
                "driver_version": g.get("driver_version"),
                "video_processor": g.get("video_processor"),
            }
    return None


# ------------------ Vulkan detection ------------------

def detect_vulkan_dll() -> bool:
    """Intenta cargar vulkan-1.dll. No garantiza un ICD usable, solo presencia."""
    try:
        ctypes.WinDLL("vulkan-1.dll")
        return True
    except OSError:
        return False


def detect_vulkaninfo() -> dict[str, Any] | None:
    """Si vulkaninfo esta en PATH, devuelve resumen. None si no."""
    exe = shutil.which("vulkaninfo") or shutil.which("vulkaninfo.exe")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--summary", "--json"],
                           capture_output=True, text=True, timeout=8)
        if r.returncode != 0:
            return None
        # En algunas versiones --json no existe; fallback a parsear texto
        try:
            import json as _json
            data = _json.loads(r.stdout)
            return {
                "available": True,
                "api_version": (data.get("VulkanAPIVersion") or ""),
                "driver_version": (data.get("driverVersion") or ""),
                "devices": [
                    {
                        "name": d.get("name"),
                        "api_version": d.get("apiVersion"),
                        "driver_version": d.get("driverVersion"),
                        "type": d.get("type"),
                    }
                    for d in (data.get("devices") or [])
                ],
            }
        except Exception:
            return {"available": True, "raw_summary": r.stdout[:2000]}
    except Exception:
        return None


def detect_vulkan() -> dict[str, Any]:
    """Resumen consolidado de Vulkan."""
    info = detect_vulkaninfo()
    dll_present = detect_vulkan_dll()
    available = bool(info) or dll_present
    return {
        "available": available,
        "vulkaninfo_installed": info is not None,
        "vulkan_dll_present": dll_present,
        "info": info,
    }


# ------------------ Resumen ------------------

def system_summary() -> dict[str, Any]:
    """Lo que la UI muestra en el panel AMD/Vulkan."""
    return {
        "gpus": detect_gpus(),
        "amd_gpu": detect_amd_gpu(),
        "vulkan": detect_vulkan(),
    }


def _human_bytes(n: float | int | None) -> str:
    if n is None or n == 0:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"