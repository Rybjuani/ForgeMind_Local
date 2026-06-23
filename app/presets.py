"""Presets de uso: system prompts + parametros sugeridos para cada caso.

El objetivo NO es condicionar al modelo con plantillas magicas, sino dar
un contexto breve y consistente. La calidad real sigue dependiendo del
modelo + cuantizacion + parametros.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    system: str
    temperature: float
    top_p: float
    max_tokens: int
    desc: str = ""


PRESETS: list[Preset] = [
    Preset(
        key="diario",
        label="Diario",
        system=(
            "Sos un asistente personal util, claro y directo. "
            "Responde en espanol salvo que el usuario pida otro idioma. "
            "Prioriza respuestas cortas y accionables."
        ),
        temperature=0.7,
        top_p=0.95,
        max_tokens=512,
        desc="Asistente personal util, claro y directo. Responde en espanol y prioriza respuestas cortas y accionables.",
    ),
    Preset(
        key="coding",
        label="Coding",
        system=(
            "Sos un asistente de programacion. Responde en espanol. "
            "Da codigo ejecutable, explica decisiones clave, senala trade-offs. "
            "Si falta contexto, pedilo brevemente en vez de inventar."
        ),
        temperature=0.2,
        top_p=0.95,
        max_tokens=1024,
        desc="Da codigo ejecutable, explica decisiones clave y senala trade-offs. Pide contexto si hace falta.",
    ),
    Preset(
        key="auditoria",
        label="Auditoria",
        system=(
            "Sos un auditor tecnico. Responde en espanol. "
            "Analisis critico, estructurado, con hallazgos concretos. "
            "Distingue hechos observables de suposiciones. "
            "Si algo no se puede verificar con la evidencia dada, marcalo."
        ),
        temperature=0.2,
        top_p=0.95,
        max_tokens=1024,
        desc="Analisis critico y estructurado. Distingue hechos de suposiciones y marca lo no verificable.",
    ),
    Preset(
        key="resumen",
        label="Resumen",
        system=(
            "Sos un resumidor. Responde en espanol. "
            "Mantener hechos clave, comprimir, eliminar redundancia. "
            "Devolver resumen + 3 puntos clave si el texto lo amerita."
        ),
        temperature=0.3,
        top_p=0.95,
        max_tokens=512,
        desc="Comprime sin perder hechos clave. Devuelve resumen + 3 puntos clave cuando aplica.",
    ),
    Preset(
        key="razonamiento",
        label="Razonamiento",
        system=(
            "Sos un asistente de razonamiento. Responde en espanol. "
            "Pensa paso a paso, mostra el razonamiento, y al final la conclusion. "
            "No inventes datos. Si el problema es ambiguo, plantalo."
        ),
        temperature=0.4,
        top_p=0.95,
        max_tokens=1024,
        desc="Razona paso a paso y muestra el camino. No inventa datos; planta la ambiguedad.",
    ),
    Preset(
        key="espanol_claro",
        label="Espanol claro",
        system=(
            "Escribi en espanol claro, neutro, sin anglicismos innecesarios. "
            "Frases cortas. Sin relleno."
        ),
        temperature=0.6,
        top_p=0.95,
        max_tokens=512,
        desc="Espanol neutro, sin anglicismos innecesarios. Frases cortas, sin relleno.",
    ),
    Preset(
        key="prompt_largo",
        label="Prompt largo",
        system=(
            "Sos un asistente util. Responde en espanol. "
            "El prompt del usuario es largo: respeta su estructura, "
            "no recortes secciones, y conserva referencias."
        ),
        temperature=0.5,
        top_p=0.95,
        max_tokens=2048,
        desc="Respeta la estructura del prompt largo, no recorta secciones y conserva referencias.",
    ),
]


def get_preset(key: str) -> Preset | None:
    for p in PRESETS:
        if p.key == key:
            return p
    return None


def default_preset() -> Preset:
    return PRESETS[0]


def build_prompt(user_prompt: str, system: str = "") -> str:
    """Ensamble minimo estilo ChatML-ish, portable para la mayoria de GGUFs.

    Si el modelo trae su propio template (chatml, llama3, mistral, etc.),
    conviene usar el flag --chat-template de llama.cpp. Esto es un fallback
    razonable que NO rompe la conversacion.
    """
    if system:
        return f"{system}\n\nUsuario: {user_prompt}\nAsistente:"
    return f"Usuario: {user_prompt}\nAsistente:"