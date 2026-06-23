"""Background downloader for llama.cpp binaries + starter GGUF models.

Why a custom downloader instead of urllib / requests?
- We need a *real* progress bar (Content-Length + chunked reads)
- We need resume support (Range:) so a flaky connection doesn't
  force a 1 GB re-download.
- We need to run inside a QThread so the UI never blocks.

URLs are versioned and pinned. We never auto-update; if a user
wants a newer llama.cpp they re-trigger the wizard or click
"Re-descargar" in the model screen.

Sources
--------
- llama.cpp Windows CPU build: binned releases on GitHub.
  https://github.com/ggerganov/llama.cpp/releases
  Pinned to b5000+ (we test against whichever is current at
  install time, but the URL below is the LATEST cpu build).
- Qwen2.5-1.5B-Instruct Q4_K_M GGUF:
  https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
  This is the smallest "actually useful" chat model — ~1.0 GB,
  fits in 16 GB RAM, and runs at ~20-30 t/s on a 4-core CPU.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Catalogue: name -> (url, expected_size_bytes, kind)
# kind = "zip_extract" for the llama.cpp release archive
# kind = "raw" for a single .gguf file
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DownloadSpec:
    key: str
    label: str
    url: str
    size_bytes: int
    kind: str          # "zip_extract" | "raw"
    target: str        # human-friendly description of where it lands


# Pinned URLs. These resolve to *current* GitHub release assets; we
# pin by tag (b5xxx) to avoid surprise breakage.
LLAMA_CPP_RELEASE_TAG = "b5831"  # latest stable as of 2026-06

# CPU-only Windows x64 zip from official ggerganov/llama.cpp releases
LLAMA_CPP_CPU_URL = (
    f"https://github.com/ggml-org/llama.cpp/releases/download/"
    f"{LLAMA_CPP_RELEASE_TAG}/llama-{LLAMA_CPP_RELEASE_TAG}-bin-win-cpu-x64.zip"
)
# Vulkan-capable Windows x64 build (larger but works with your RX550)
LLAMA_CPP_VULKAN_URL = (
    f"https://github.com/ggml-org/llama.cpp/releases/download/"
    f"{LLAMA_CPP_RELEASE_TAG}/llama-{LLAMA_CPP_RELEASE_TAG}-bin-win-vulkan-x64.zip"
)

# Qwen2.5-1.5B-Instruct Q4_K_M — small, fast, well-behaved for chat.
# ~1.0 GB. Alternative: a smaller 0.5B model for ultra-tight setups.
QWEN_15B_Q4_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/"
    "resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
)

# Even smaller backup if 1.5B is too big: Llama-3.2-1B Q4_K_M (~0.8 GB)
LLAMA_1B_Q4_URL = (
    "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/"
    "resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
)


def get_catalog(variant: str = "cpu") -> list[DownloadSpec]:
    """Return the download catalogue.

    ``variant``:
      - ``"cpu"``     → llama.cpp CPU build (smaller, ~3 MB zip)
      - ``"vulkan"``  → llama.cpp Vulkan build (~25 MB zip)
    """
    out: list[DownloadSpec] = []
    if variant == "vulkan":
        out.append(DownloadSpec(
            key="llama_cpp_vulkan",
            label="llama.cpp (Windows · Vulkan · x64)",
            url=LLAMA_CPP_VULKAN_URL,
            size_bytes=30_000_000,  # ~30 MB
            kind="zip_extract",
            target="bin/llama-cli.exe, bin/llama-server.exe",
        ))
    else:
        out.append(DownloadSpec(
            key="llama_cpp_cpu",
            label="llama.cpp (Windows · CPU · x64)",
            url=LLAMA_CPP_CPU_URL,
            size_bytes=3_500_000,  # ~3.5 MB
            kind="zip_extract",
            target="bin/llama-cli.exe, bin/llama-server.exe",
        ))
    out.append(DownloadSpec(
        key="qwen_15b_q4",
        label="Qwen2.5-1.5B-Instruct Q4_K_M (starter chat)",
        url=QWEN_15B_Q4_URL,
        size_bytes=1_100_000_000,  # ~1.05 GB
        kind="raw",
        target="models/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    ))
    return out


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[str, int, int], None]  # (key, bytes_done, total)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def download_file(
    url: str,
    dest: Path,
    *,
    progress: Optional[ProgressCallback] = None,
    key: str = "",
    chunk_size: int = 64 * 1024,
    timeout: float = 30.0,
) -> Path:
    """Download a single URL to ``dest``. Resumes via HTTP Range.

    Parameters
    ----------
    url : str
        Source URL (http/https).
    dest : Path
        Final file path. Parent dirs are created.
    progress : callable, optional
        Called as ``progress(key, bytes_done, total)`` every chunk.
        ``total`` is ``-1`` if the server didn't send Content-Length.
    key : str
        Identifier passed back to the progress callback.
    chunk_size : int
        Read buffer size.
    timeout : float
        Per-request timeout (seconds).

    Returns
    -------
    Path
        ``dest`` on success.

    Raises
    ------
    urllib.error.URLError
        Network failure after exhausting retries.
    OSError
        Filesystem failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Resume from partial download if present
    resume_from = dest.stat().st_size if dest.exists() else 0
    headers = {}
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    req = urllib.request.Request(url, headers=headers)
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # Server returned 200 (full) or 206 (partial)
                code = resp.getcode()
                if code not in (200, 206):
                    raise urllib.error.HTTPError(
                        url, code, f"unexpected status {code}", resp.headers, None
                    )

                # Determine total size
                cl = resp.headers.get("Content-Length")
                if cl is not None:
                    chunk_total = int(cl)
                    total = (resume_from + chunk_total) if code == 206 else chunk_total
                else:
                    total = -1

                mode = "ab" if code == 206 else "wb"
                with dest.open(mode) as fh:
                    done = resume_from
                    t0 = time.time()
                    last_emit = 0.0
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        if progress is not None:
                            # Throttle progress to ~10 Hz max
                            now = time.time()
                            if now - last_emit > 0.1 or done == total:
                                progress(key, done, total)
                                last_emit = now
                    if progress is not None:
                        progress(key, done, total)
                return dest
        except (urllib.error.URLError, OSError) as e:
            last_err = e
            # Exponential backoff
            time.sleep(0.5 * (2 ** attempt))
            continue
    # All retries failed
    if last_err is not None:
        raise last_err
    raise RuntimeError("download failed for unknown reason")


def extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Extract a zip into ``dest_dir`` (created if needed).

    Returns the list of extracted files. Skips the top-level directory
    inside the zip (llama.cpp releases always wrap everything in a
    single root folder like ``llama-b5000-bin-win-cpu-x64/``).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Strip the first path component
            parts = Path(info.filename).parts
            if len(parts) > 1:
                rel = Path(*parts[1:])
            elif parts:
                rel = Path(parts[0])
            else:
                continue  # empty filename, skip
            target = dest_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            out.append(target)
    return out


# ---------------------------------------------------------------------------
# High-level convenience
# ---------------------------------------------------------------------------

def install_starter_kit(
    config_dir: Path,
    *,
    variant: str = "cpu",
    progress: Optional[ProgressCallback] = None,
) -> dict[str, str]:
    """One-shot installer: llama.cpp + a starter model.

    Writes to ``<config_dir>/bin/`` and ``<config_dir>/models/``.

    Parameters
    ----------
    config_dir : Path
        ForgeMind config root (the directory that holds settings.json).
    variant : str
        ``"cpu"`` (default) or ``"vulkan"``.
    progress : callable, optional
        ``progress(key, done, total)`` for UI feedback.

    Returns
    -------
    dict[str, str]
        Mapping of resource → absolute path on disk. Keys:
          - ``llama_cli``   : path to llama-cli.exe
          - ``llama_server``: path to llama-server.exe
          - ``model``       : path to the downloaded .gguf
        Missing keys mean the download was skipped or failed.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    bin_dir = config_dir / "bin"
    models_dir = config_dir / "models"
    bin_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    out: dict[str, str] = {}

    for spec in get_catalog(variant):
        if spec.kind == "zip_extract":
            zip_dest = config_dir / f"_downloads/{spec.key}.zip"
            zip_dest.parent.mkdir(parents=True, exist_ok=True)
            download_file(spec.url, zip_dest, progress=progress, key=spec.key)
            extracted = extract_zip(zip_dest, bin_dir)
            # Clean up the zip
            try:
                zip_dest.unlink()
            except OSError:
                pass
            # Find the binaries
            for f in extracted:
                if f.name.lower() in ("llama-cli.exe", "llama-cli"):
                    out["llama_cli"] = str(f)
                elif f.name.lower() in ("llama-server.exe", "llama-server"):
                    out["llama_server"] = str(f)
        elif spec.kind == "raw":
            fname = spec.url.rsplit("/", 1)[-1]
            gguf_dest = models_dir / fname
            download_file(spec.url, gguf_dest, progress=progress, key=spec.key)
            out["model"] = str(gguf_dest)

    return out


# ---------------------------------------------------------------------------
# Smoke entry: python -m app.downloader cpu
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    variant = argv[1] if len(argv) > 1 else "cpu"
    here = Path(__file__).resolve().parent.parent
    print(f"Installing starter kit (variant={variant}) into {here}")
    last_total = {"t": 0}

    def on_progress(key: str, done: int, total: int) -> None:
        if total > 0:
            pct = (done / total) * 100
            sys.stdout.write(
                f"\r  {key}: {human_bytes(done)} / {human_bytes(total)}  "
                f"({pct:5.1f}%)"
            )
            sys.stdout.flush()
        else:
            sys.stdout.write(f"\r  {key}: {human_bytes(done)}")
            sys.stdout.flush()

    result = install_starter_kit(here, variant=variant, progress=on_progress)
    print()
    print("DONE:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
