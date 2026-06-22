"""Configuracion de un modelo GGUF para una corrida."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any


# Cuantizaciones tipicas que se ven en filenames GGUF. No exhaustivo.
KNOWN_QUANTS = (
    "Q2_K", "Q3_K_S", "Q3_K_M", "Q3_K_L",
    "Q4_0", "Q4_1", "Q4_K_S", "Q4_K_M",
    "Q5_0", "Q5_1", "Q5_K_S", "Q5_K_M",
    "Q6_K", "Q8_0",
    "F16", "F32",
)


def detect_quant_from_filename(path: str) -> str:
    """Devuelve la cuantizacion si el filename la incluye; '' si no."""
    name = os.path.basename(path).upper()
    # Orden importante: chequear Q4_K_M antes que Q4_0 etc.
    for q in sorted(KNOWN_QUANTS, key=len, reverse=True):
        if q in name:
            return q
    return ""


def file_size_bytes(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def human_size(num_bytes: int) -> str:
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


@dataclass
class ModelConfig:
    """Una configuracion completa para arrancar un modelo en el backend."""

    # Identidad
    name: str = "modelo-sin-nombre"
    gguf_path: str = ""

    # Inferencia
    ctx_size: int = 4096
    threads: int = 8
    temperature: float = 0.7
    top_p: float = 0.95
    repeat_penalty: float = 1.1
    max_tokens: int = 512

    # Backend / modo
    # mode: "cpu" | "vulkan" (vulkan = experimental, offload GPU)
    mode: str = "cpu"
    gpu_layers: int = 0

    # Backend kind:
    #   "llama_cli"   -> subprocess a llama-cli (recomendado MVP, portable)
    #   "llama_server"-> subprocess a llama-server (HTTP local)
    #   "llama_cpp"   -> binding Python (opcional, requiere build)
    backend_kind: str = "llama_cli"

    # Ruta al ejecutable de llama.cpp. Si vacio, lo busca en PATH.
    llama_cli_path: str = ""
    llama_server_path: str = ""

    # Extras opcionales
    extra_args: list[str] = field(default_factory=list)

    # ----- Derivados -----

    @property
    def quant(self) -> str:
        return detect_quant_from_filename(self.gguf_path)

    @property
    def size_bytes(self) -> int:
        return file_size_bytes(self.gguf_path)

    @property
    def size_human(self) -> str:
        return human_size(self.size_bytes)

    def exists(self) -> bool:
        return bool(self.gguf_path) and os.path.isfile(self.gguf_path)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["quant"] = self.quant
        d["size_bytes"] = self.size_bytes
        d["size_human"] = self.size_human
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        # Tomar solo campos conocidos para no romper con claves extra
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})