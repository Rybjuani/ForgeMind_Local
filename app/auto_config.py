"""First-run auto-configuration for ForgeMind Local.

Goals
-----
When the user double-clicks ``ForgeMind.exe`` we want the app to:

1. Find a writable location to drop ``settings.json`` so the user can
   edit it with any text editor (Notepad, VSCode, etc.).
2. Auto-detect ``llama-cli`` / ``llama-server`` on PATH or in common
   install locations.
3. Auto-discover any ``.gguf`` model in the same directory tree, in the
   user's home, or in well-known model locations (``C:\\modelos``,
   ``%USERPROFILE%\\models``).
4. On a truly empty first run, build a *valid* ``settings.json`` with
   the auto-detected values (or empty strings) so the user can fill
   in the gaps via the in-app Config screen or by editing the file.

Design notes
------------
- **No state lives in the app code**: ``settings.json`` next to the
  .exe is the single source of truth. The user can move it, back it
  up, share it with a friend, or wipe it to reset.
- **One file, JSON, no schema migration**: the file is short enough
  that adding a field doesn't require a migration step; missing
  fields fall back to ``ModelConfig()`` defaults.
- **Scans are cheap**: we only walk a handful of known directories
  and cap each one at a reasonable depth; a real install will have
  one or two GGUFs in a single ``models/`` directory.

Public surface
--------------
- :func:`config_dir`     - the directory where ``settings.json`` lives
- :func:`settings_path`  - full path to ``settings.json``
- :func:`load_settings`  - read settings.json (returns empty dict on miss)
- :func:`save_settings`  - write settings.json (pretty-printed)
- :func:`first_run_setup` - run auto-detection + persist; returns dict
- :func:`find_llama_cli`  - locate the llama-cli executable
- :func:`find_gguf`       - locate any .gguf in standard locations
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# The directory we treat as the "user's ForgeMind home" for settings.json.
# In dev (python -m app.main) we use the project root. In a frozen
# PyInstaller build, ``sys.executable`` is the .exe path; that's the
# most natural place for a non-tech user to find an editable JSON.
def config_dir() -> Path:
    """Return the directory where ``settings.json`` should live.

    Resolution order:
    1. ``sys.executable`` parent — works for both ``python`` and the
       frozen ``ForgeMind.exe`` (onefile PyInstaller).
    2. ``FORGEMIND_HOME`` env var override.
    3. ``%APPDATA%\\ForgeMind`` (Windows) / ``~/.config/forgemind``
       (POSIX) — used only if (1) is not writable.
    """
    env = os.environ.get("FORGEMIND_HOME")
    if env:
        p = Path(env).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    if getattr(sys, "frozen", False):
        # PyInstaller: sys.executable is the .exe path
        candidate = Path(sys.executable).parent
    else:
        # Dev: sys.executable is python.exe; project root is two levels up
        # (Desktop\ForgeMind_Local\.venv\Scripts\python.exe)
        candidate = Path(__file__).resolve().parent.parent
    # Try candidate; if not writable, fall back to APPDATA / .config
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        test = candidate / ".write_probe"
        test.write_text("ok", encoding="utf-8")
        test.unlink()
        return candidate
    except OSError:
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData/Roaming"))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        fallback = base / "ForgeMind"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def settings_path() -> Path:
    return config_dir() / "settings.json"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": 1,
    "model": {
        "name": "modelo-sin-nombre",
        "gguf_path": "",
        "ctx_size": 4096,
        "threads": 8,
        "temperature": 0.7,
        "top_p": 0.95,
        "repeat_penalty": 1.1,
        "max_tokens": 512,
        "mode": "cpu",
        "gpu_layers": 0,
        "backend_kind": "llama_cli",
        "llama_cli_path": "",
        "llama_server_path": "",
        "ollama_url": "",
    },
    "paths": {
        "models_dir": "",          # the user's models directory (if any)
        "bin_dir": "",             # the user's llama.cpp bin directory
        "results_dir": "results",  # benchmark results subdir
    },
    "ui": {
        "last_screen": "chat",
        "auto_start_backend": True,
        "metrics_refresh_ms": 2500,
    },
}


def load_settings() -> dict[str, Any]:
    """Read settings.json, merging with defaults so all keys exist.

    Never raises: returns a fresh default dict on parse / IO errors.
    """
    path = settings_path()
    if not path.exists():
        return json.loads(json.dumps(_DEFAULT_SETTINGS))  # deep copy
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(_DEFAULT_SETTINGS))
    return _merge_defaults(data, _DEFAULT_SETTINGS)


def save_settings(data: dict[str, Any]) -> Path:
    """Write settings.json (pretty-printed) and return the path.

    The on-disk file is the canonical source of truth — every other
    in-app state (the Config screen, the sidebar model card) is just
    a view over this dict.
    """
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _merge_defaults(data, _DEFAULT_SETTINGS)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)
    return path


def _merge_defaults(data: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``data`` over ``defaults`` so all expected keys exist."""
    if not isinstance(data, dict):
        return json.loads(json.dumps(defaults))
    out = json.loads(json.dumps(defaults))  # deep copy of defaults
    for k, v in data.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge_defaults(v, out[k])
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

# Where we look for llama.cpp executables, in priority order. The first
# one that contains ``llama-cli.exe`` / ``llama-cli`` wins.
_BIN_SEARCH_DIRS: list[Path] = []

# Where we look for .gguf models. First hit wins (we pick the first
# model alphabetically if there are multiple).
_GGUF_SEARCH_DIRS: list[Path] = []


def _populate_search_dirs() -> None:
    """Populate _BIN_SEARCH_DIRS and _GGUF_SEARCH_DIRS once per process."""
    if _BIN_SEARCH_DIRS:
        return
    here = config_dir()
    # 1. Same dir as the .exe / settings.json (drop llama-cli.exe here)
    _BIN_SEARCH_DIRS.append(here)
    _BIN_SEARCH_DIRS.append(here / "bin")
    # 2. Conventional llama.cpp install paths on Windows
    if os.name == "nt":
        for cand in (
            Path("C:/llama.cpp"),
            Path("C:/llama.cpp/build/bin/Release"),
            Path("C:/llama.cpp/build/bin/Debug"),
            Path("C:/Program Files/llama.cpp/bin"),
            Path("C:/Program Files (x86)/llama.cpp/bin"),
            Path.home() / "llama.cpp",
            Path.home() / "llama.cpp/build/bin/Release",
        ):
            _BIN_SEARCH_DIRS.append(cand)
    else:
        for cand in (
            Path("/usr/local/bin"),
            Path("/opt/llama.cpp/bin"),
            Path.home() / ".local/bin",
        ):
            _BIN_SEARCH_DIRS.append(cand)
    # 3. GitHub Releases default extraction dirs
    _BIN_SEARCH_DIRS.append(Path.home() / "llama-bin")
    # 4. PATH (handled inside find_llama_cli directly)

    # ---- model dirs ----
    # 1. The ForgeMind config dir (drop .gguf here!)
    _GGUF_SEARCH_DIRS.append(here / "models")
    _GGUF_SEARCH_DIRS.append(here)
    # 2. Standard "I keep my models here" locations
    for cand in (
        Path("C:/modelos"),
        Path("C:/models"),
        Path("C:/LLM/models"),
        Path.home() / "models",
        Path.home() / "modelos",
        Path.home() / "LLM/models",
        Path.home() / ".cache/lm-studio/models",
        Path.home() / ".cache/ollama/models",
    ):
        _GGUF_SEARCH_DIRS.append(cand)


def find_llama_cli() -> str | None:
    """Locate the ``llama-cli`` / ``llama-cli.exe`` executable.

    Returns the full path as a string, or ``None`` if not found. PATH
    is searched first (most common case: user installed via winget /
    choco / scoop / installer), then the well-known local dirs.
    """
    exe_names = ["llama-cli.exe", "llama-cli"] if os.name == "nt" else ["llama-cli"]
    for name in exe_names:
        hit = shutil.which(name)
        if hit:
            return hit
    _populate_search_dirs()
    for d in _BIN_SEARCH_DIRS:
        if not d.exists() or not d.is_dir():
            continue
        for name in exe_names:
            p = d / name
            if p.is_file():
                return str(p)
    return None


def find_llama_server() -> str | None:
    """Same as :func:`find_llama_cli` but for ``llama-server``."""
    exe_names = ["llama-server.exe", "llama-server"] if os.name == "nt" else ["llama-server"]
    for name in exe_names:
        hit = shutil.which(name)
        if hit:
            return hit
    _populate_search_dirs()
    for d in _BIN_SEARCH_DIRS:
        if not d.exists() or not d.is_dir():
            continue
        for name in exe_names:
            p = d / name
            if p.is_file():
                return str(p)
    return None


def find_gguf(prefer_name: str | None = None) -> str | None:
    """Locate a single ``.gguf`` model in the standard search dirs.

    If multiple GGUFs are found, prefer the one whose filename
    contains ``prefer_name`` (case-insensitive), else return the
    first match alphabetically. Returns the absolute path or ``None``.
    """
    _populate_search_dirs()
    found: list[Path] = []
    for d in _GGUF_SEARCH_DIRS:
        if not d.exists() or not d.is_dir():
            continue
        try:
            for p in sorted(d.glob("*.gguf")):
                if p.is_file():
                    found.append(p.resolve())
        except OSError:
            continue
    if not found:
        return None
    if prefer_name:
        pl = prefer_name.lower()
        for p in found:
            if pl in p.name.lower():
                return str(p)
    return str(found[0])


def find_gguf_all() -> list[str]:
    """Return every .gguf found in the standard search dirs, sorted."""
    _populate_search_dirs()
    out: set[str] = set()
    for d in _GGUF_SEARCH_DIRS:
        if not d.exists() or not d.is_dir():
            continue
        try:
            for p in sorted(d.glob("*.gguf")):
                if p.is_file():
                    out.add(str(p.resolve()))
        except OSError:
            continue
    return sorted(out)


# ---------------------------------------------------------------------------
# First-run setup
# ---------------------------------------------------------------------------

def first_run_setup(*, interactive: bool = True) -> dict[str, Any]:
    """Auto-configure settings.json on the first run.

    Behaviour:
    1. If ``settings.json`` exists, return it untouched.
    2. Otherwise:
       - Create ``models/`` next to the config dir (so the user has a
         obvious place to drop GGUFs).
       - Run every auto-detector; if anything was found, fill the
         corresponding fields in the settings.
       - Persist the result and return it.

    The ``interactive`` flag is a forward-compat hook: when True (the
    default) the function MAY raise if a hard prerequisite is missing.
    The current implementation never raises (the UI handles the
    "nothing found" case gracefully).
    """
    existing = settings_path()
    if existing.exists():
        return load_settings()

    settings = json.loads(json.dumps(_DEFAULT_SETTINGS))  # deep copy

    # 1. Create the user-facing subfolders so the path exists for them
    #    to drop models and binaries into.
    cfg = config_dir()
    (cfg / "models").mkdir(parents=True, exist_ok=True)
    (cfg / "bin").mkdir(parents=True, exist_ok=True)
    (cfg / "results").mkdir(parents=True, exist_ok=True)

    # 2. Auto-detect llama.cpp
    cli = find_llama_cli()
    if cli:
        settings["model"]["llama_cli_path"] = cli
    srv = find_llama_server()
    if srv:
        settings["model"]["llama_server_path"] = srv

    # 3. Auto-detect a GGUF
    gguf = find_gguf()
    if gguf:
        settings["model"]["gguf_path"] = gguf
        # Best-effort: name the model from the filename (without ext / quant)
        name = Path(gguf).stem
        for q in ("Q4_K_M", "Q4_K_S", "Q4_0", "Q5_K_M", "Q6_K", "Q8_0",
                  "Q3_K_M", "Q2_K", "F16", "F32"):
            if q.lower() in name.lower():
                name = name.replace(q, "").replace(q.lower(), "").strip("._- ")
                break
        if name:
            settings["model"]["name"] = name

    # 4. Auto-arrancar el backend al abrir si tenemos modelo + cli.
    #    Si no encontramos nada, dejamos False para no estorbar al usuario
    #    con un toast de error apenas abre la app.
    if gguf and cli:
        settings["ui"]["auto_start_backend"] = True
    else:
        settings["ui"]["auto_start_backend"] = False

    # 5. Persist
    save_settings(settings)
    return settings


# ---------------------------------------------------------------------------
# Friendly printable report
# ---------------------------------------------------------------------------

def describe_environment(settings: dict[str, Any]) -> str:
    """Return a short, human-readable summary of what's been detected.

    Used by the in-app "First run" card and by ``--check`` from the
    CLI so the user always knows what is wired up and what is not.
    """
    cli = settings["model"].get("llama_cli_path") or ""
    gguf = settings["model"].get("gguf_path") or ""
    srv = settings["model"].get("llama_server_path") or ""
    bits: list[str] = []
    bits.append(f"Config dir : {config_dir()}")
    bits.append(f"Settings   : {settings_path()}{'  (auto-created)' if not settings_path().exists() else ''}")
    bits.append(f"llama-cli  : {cli or 'NOT FOUND — put llama-cli.exe in the ForgeMind folder or in PATH'}")
    bits.append(f"llama-srv  : {srv or 'NOT FOUND'}")
    bits.append(f"Model      : {gguf or 'NOT FOUND — drop a .gguf in the models/ subfolder'}")
    return "\n".join(bits)
