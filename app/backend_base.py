"""Interfaz abstracta para backends de inferencia.

Cualquier backend (llama.cpp subprocess, llama-server HTTP, binding Python,
Ollama, LM Studio, mock) implementa este contrato.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator

from .model_config import ModelConfig


class BackendBase(ABC):
    """Contrato minimo que el resto de la app puede asumir."""

    name: str = "base"

    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self.last_command: str = ""
        self.last_pid: int | None = None
        self.last_error: str | None = None

    # ----- Ciclo de vida -----

    @abstractmethod
    def start(self) -> bool:
        """Inicia el backend (proceso / carga modelo). Devuelve True si arranco OK."""

    @abstractmethod
    def stop(self) -> None:
        """Detiene el backend. No debe raise."""

    @abstractmethod
    def is_running(self) -> bool:
        """True si el backend esta vivo y listo para generar."""

    # ----- Inferencia -----

    @abstractmethod
    def generate(self, prompt: str, system: str = "") -> str:
        """Genera respuesta. NO debe raise. Devuelve mock-labelled en caso de fallo."""

    def generate_stream(self, prompt: str, system: str = "") -> Iterator[str]:
        """Default: yield todo el resultado de generate() en un solo chunk.

        Los backends que soporten streaming real deben override.
        """
        yield self.generate(prompt, system)

    # ----- Observabilidad -----

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Estado serializable para mostrar en UI."""

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} backend={self.name} running={self.is_running()}>"