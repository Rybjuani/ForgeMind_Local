"""Persistencia de conversaciones de chat.

Guarda cada conversacion como un JSON en ``chats/`` (al lado de
``settings.json``). Cada archivo tiene:

  {
    "id": "20260624-153022",
    "title": "Hola, ¿cómo estás?",
    "created_at": "2026-06-24T15:30:22",
    "updated_at": "2026-06-24T15:31:08",
    "model": "Gemma 4 12B",
    "preset": "diario",
    "messages": [
      {"role": "user", "content": "...", "ts": "..."},
      {"role": "ai",   "content": "...", "ts": "...", "preset": "diario"},
      ...
    ]
  }

API publica:
  - chats_dir()          -> Path donde viven los JSON
  - save_chat(conv)      -> persiste (crea o actualiza)
  - list_chats()         -> lista metadata, mas recientes primero
  - load_chat(chat_id)   -> dict completo (None si no existe)
  - delete_chat(chat_id) -> borra un chat
  - new_chat_id()        -> string "YYYYMMDD-HHMMSS"
  - derive_title(text)   -> primer ~40 chars del primer mensaje
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def chats_dir() -> Path:
    """Directorio donde viven los JSON de chat.

    Vive al lado de ``settings.json`` (mismo ``config_dir()`` que
    usa ``auto_config``), asi el usuario lo encuentra facil y puede
    borrarlo / copiarlo / editarlo con cualquier editor.
    """
    from . import auto_config
    base = auto_config.config_dir()
    p = base / "chats"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_filename(text: str) -> str:
    """Convierte un texto arbitrario en un filename seguro."""
    # Solo alfanumericos, guion, guion_bajo. Todo lo demas -> guion.
    safe = re.sub(r"[^\w\-]", "-", text)[:60].strip("-")
    return safe or "chat"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def new_chat_id() -> str:
    """ID unico para una nueva conversacion: ``YYYYMMDD-HHMMSS``."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def derive_title(text: str) -> str:
    """Titulo corto derivado del primer mensaje del usuario.

    Trunca a ~40 chars y limpia saltos de linea para que quepa en
    el sidebar sin romper el layout.
    """
    if not text:
        return "(nueva conversacion)"
    flat = " ".join(text.split())  # collapse whitespace
    if len(flat) <= 40:
        return flat
    return flat[:37].rstrip(" .,;:!?-") + "..."


def save_chat(conv: dict[str, Any]) -> Path:
    """Persiste una conversacion.

    ``conv`` debe tener al menos ``id`` y ``messages``. Crea o
    actualiza el archivo ``chats/<id>.json``. Devuelve el Path
    donde se guardo.
    """
    cid = conv.get("id") or new_chat_id()
    conv["id"] = cid
    now = datetime.now().isoformat(timespec="seconds")
    if "created_at" not in conv:
        conv["created_at"] = now
    conv["updated_at"] = now
    # Garantizar que el titulo este derivado si no vino
    if not conv.get("title"):
        msgs = conv.get("messages") or []
        first_user = next((m for m in msgs if m.get("role") == "user"), {})
        conv["title"] = derive_title(first_user.get("content", ""))
    out = chats_dir() / f"{_safe_filename(cid)}.json"
    out.write_text(json.dumps(conv, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def list_chats(limit: int = 50) -> list[dict[str, Any]]:
    """Lista metadata de chats, mas recientes primero.

    Cada item: ``{id, title, created_at, updated_at, model, preset,
    message_count, path}``. NO incluye los mensajes completos (eso
    es ``load_chat``) para mantener liviano el sidebar.
    """
    d = chats_dir()
    out: list[dict[str, Any]] = []
    for jp in sorted(d.glob("*.json"), reverse=True):
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue
        msgs = data.get("messages") or []
        out.append({
            "id": data.get("id", jp.stem),
            "title": data.get("title", "(sin titulo)"),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "model": data.get("model", ""),
            "preset": data.get("preset", ""),
            "message_count": len(msgs),
            "path": str(jp),
        })
    # Sort by updated_at desc
    out.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return out[:limit]


def load_chat(chat_id: str) -> dict[str, Any] | None:
    """Carga un chat completo por ID. None si no existe."""
    p = chats_dir() / f"{_safe_filename(chat_id)}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_chat(chat_id: str) -> bool:
    """Borra un chat por ID. True si se borro, False si no existia."""
    p = chats_dir() / f"{_safe_filename(chat_id)}.json"
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except Exception:
        return False
