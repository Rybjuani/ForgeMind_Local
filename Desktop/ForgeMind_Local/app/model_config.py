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
    #   "ollama"      -> daemon Ollama externo via HTTP (no requiere llama.cpp)
    backend_kind: str = "llama_cli"

    # Ruta al ejecutable de llama.cpp. Si vacio, lo busca en PATH.
    llama_cli_path: str = ""
    llama_server_path: str = ""

    # URL del daemon Ollama. Solo aplica si backend_kind == "ollama".
    ollama_url: str = ""

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

    @property
    def pretty_name(self) -> str:
        """Human-friendly model name derived from the GGUF filename.

        Converts patterns like ``qwen2.5-1.5b-instruct-q4_k_m.gguf``
        into ``Qwen 2.5 1.5B Instruct`` (drops the quant suffix, adds
        spaces, capitalises family names + size tokens). Used by the
        sidebar model card and the chat composer pill so the UI shows
        a readable name instead of a slug.

        Falls back to the raw stem (title-cased) if no family pattern
        matches.
        """
        from pathlib import Path
        import re
        if not self.gguf_path:
            return ""
        stem = Path(self.gguf_path).stem
        # Drop the quant suffix (Q4_K_M, Q5_K_M, Q8_0, ...) and the
        # optional trailing dash / underscore.
        stem = re.sub(
            r"[-_. ]?(Q\d+_K_(?:M|S|L)|Q\d+_0|F16|F32|Q\d+_K|IQ\d+_[A-Z]+)$",
            "",
            stem,
            flags=re.IGNORECASE,
        ).strip("-_ ")
        # Family dictionary (lowercase -> display name).
        FAMILIES_RAW = (
            "qwen|llama|gemma|phi|mistral|mixtral|deepseek|"
            "codellama|starcoder|nemotron|yi|orca|falcon|vicuna|wizardlm|"
            "openhermes|zephyr|smollm|internlm|baichuan|"
            "command-r|dbrx|stablelm|solar|llava"
        )
        FAMILIES = {
            "qwen": "Qwen", "llama": "Llama", "gemma": "Gemma",
            "phi": "Phi", "mistral": "Mistral", "mixtral": "Mixtral",
            "deepseek": "DeepSeek", "codellama": "CodeLlama",
            "starcoder": "StarCoder", "nemotron": "Nemotron",
            "yi": "Yi", "orca": "Orca", "falcon": "Falcon",
            "vicuna": "Vicuna", "wizardlm": "WizardLM",
            "openhermes": "OpenHermes", "zephyr": "Zephyr",
            "smollm": "SmolLM", "internlm": "InternLM",
            "baichuan": "Baichuan", "command-r": "Command-R",
            "dbrx": "DBRX", "stablelm": "StableLM",
            "solar": "Solar", "llava": "LLaVA",
        }
        # Compound / dash-separated family names (multi-token lookups).
        COMPOUND_FAMILIES = {
            "nous hermes": "Nous Hermes",
            "gpt oss": "GPT-OSS",
            "qwen2 vl": "Qwen2-VL",
            "code llama": "CodeLlama",
            "open hermes": "OpenHermes",
            "command r": "Command-R",
        }
        SUB_VARIANTS = ("chat", "instruct", "base", "it")
        # Skip tokens (e.g. "mini", "4k", "v0.3" version tags, "xB" expert
        # count). These should never be confused with the size token.
        SKIP_TOKENS = {"mini", "4k", "8k", "32k", "x"}

        def _match_size(t: str) -> tuple[str, int] | None:
            """Return (size_str, priority) or None.

            Priority is HIGHER for more specific patterns. We always
            pick the highest-priority match, so an explicit "9b" beats
            a bare "2" version number, and "8x7b" beats a bare "8".
            """
            mm = re.match(r"^(\d+(?:\.\d+)?)([Bb])$", t)
            if mm:
                return f"{mm.group(1)}B", 30
            # Mixtral-style "8x7b" → "8x7B".
            mm = re.match(r"^(\d+)x(\d+(?:\.\d+)?)([Bb])$", t, re.IGNORECASE)
            if mm:
                return f"{mm.group(1)}x{mm.group(2)}B", 20
            # Bare number (lowest priority — likely a version tag).
            mm = re.match(r"^(\d+(?:\.\d+)?)$", t)
            if mm:
                return mm.group(1), 10
            return None

        groups = [g for g in re.split(r"[-_]", stem) if g]
        tokens: list[str] = list(groups)

        # Find family: try compound first (longest match), then single.
        family_disp = None
        family_end = -1
        for n in (2, 1):
            if len(tokens) < n:
                continue
            head = " ".join(t.lower() for t in tokens[:n])
            if n == 2 and head in COMPOUND_FAMILIES:
                family_disp = COMPOUND_FAMILIES[head]
                family_end = n - 1
                break
            if n == 1 and head in FAMILIES:
                family_disp = FAMILIES[head]
                family_end = 0
                break
        if family_disp is None:
            return " ".join(t.title() for t in tokens) or stem

        # Find size token AFTER the family. Pick the highest-priority
        # match; skip non-size tokens like "mini", "4k", "v0.3".
        size_str = ""
        size_priority = -1
        size_end = -1
        # Phi-3 special: "phi-3-mini-4k-instruct" → "Phi 3 Mini Instruct".
        # The bare "3" is the version (low priority), but we still want
        # to surface it alongside the variant name.
        phi_version = ""
        if family_disp == "Phi":
            # Find the version number token (first bare number after Phi).
            for j in range(family_end + 1, len(tokens)):
                t = tokens[j].lower()
                if t in SKIP_TOKENS or (t.startswith("v") and re.match(r"^v\d", t)):
                    continue
                mm = re.match(r"^(\d+(?:\.\d+)?)$", tokens[j])
                mtch = _match_size(tokens[j])
                if mm and mtch:  # bare number
                    phi_version = mm.group(1)
                    break
                if mtch:
                    break
        for j in range(family_end + 1, len(tokens)):
            t = tokens[j].lower()
            if t in SKIP_TOKENS or (t.startswith("v") and re.match(r"^v\d", t)):
                continue
            mtch = _match_size(tokens[j])
            if mtch and mtch[1] > size_priority:
                size_str, size_priority = mtch[0], mtch[1]
                size_end = j
        # Phi-3 special override: if we found "mini" / "medium" / etc.,
        # use it as the size string and prepend the version.
        if family_disp == "Phi" and phi_version:
            for j in range(family_end + 1, len(tokens)):
                tlow = tokens[j].lower()
                if tlow in ("mini", "medium", "small", "vision"):
                    size_str = f"{phi_version} {tlow.capitalize()}"
                    size_priority = 35  # beats NB (30)
                    size_end = j
                    break

        # Find sub-variant token after the size.
        sub = ""
        if size_end != -1:
            for k in range(size_end + 1, len(tokens)):
                tlow = tokens[k].lower()
                if tlow in SUB_VARIANTS:
                    sub = tlow.capitalize()
                    break
        parts = [family_disp]
        if size_str:
            parts.append(size_str)
        if sub:
            parts.append(sub)
        return " ".join(parts)

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