"""Historial y comparativa de corridas de benchmark.

Lee todos los JSON generados por `run_benchmark` en una carpeta,
los agrupa por label y permite compararlos lado a lado.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


_FILENAME_RE = re.compile(r"^(?P<label>.+)-(?P<ts>\d{8}-\d{6})$")


def list_runs(results_dir: str | Path) -> list[dict[str, Any]]:
    """Devuelve metadata de los runs (.json) en `results_dir`, mas recientes primero.

    Cada item incluye el dict crudo bajo `_raw` para que `compare_runs`
    no tenga que volver a leer disco.
    """
    p = Path(results_dir)
    if not p.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for json_path in sorted(p.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        be = data.get("backend") or {}
        cfg = be.get("config") or {}
        runs.append({
            "path": str(json_path),
            "label": data.get("label", json_path.stem),
            "timestamp": data.get("timestamp", ""),
            "backend": be.get("backend", "?"),
            "mock": bool(be.get("mock", False)),
            "model_name": cfg.get("name", "?"),
            "model_path": cfg.get("gguf_path", ""),
            "quant": cfg.get("quant", ""),
            "size_human": cfg.get("size_human", "?"),
            "mode": cfg.get("mode", ""),
            "wall_time_sec": (data.get("totals") or {}).get("wall_time_sec"),
            "prompts_run": (data.get("totals") or {}).get("prompts_run"),
            "schema_version": data.get("schema_version", 0),
            "_raw": data,
        })
    runs.sort(key=lambda r: (r["timestamp"], r["path"]), reverse=True)
    return runs


def load_run(json_path: str | Path) -> dict[str, Any] | None:
    """Carga un run desde disco. None si falla."""
    try:
        return json.loads(Path(json_path).read_text(encoding="utf-8"))
    except Exception:
        return None


def compare_runs(runs_or_paths: list[Any]) -> dict[str, Any]:
    """Compara varios runs.

    Acepta una lista de:
      - paths (str / Path) -> se cargan con load_run()
      - dicts (con `_raw` adentro, como devuelve list_runs) -> se usan directo
      - dicts crudos de un run -> se usan directo

    Devuelve dict con:
      - runs: lista de dicts crudos (los que se compararon)
      - summary: lista con stats agregadas por run (para tabla resumen)
      - per_prompt: dict[prompt_key] = lista de filas comparativas
      - markdown: tabla en markdown lista para mostrar
    """
    raw_list: list[dict[str, Any]] = []
    for item in runs_or_paths:
        if isinstance(item, (str, Path)):
            r = load_run(item)
            if r is not None:
                raw_list.append(r)
        elif isinstance(item, dict):
            if "_raw" in item and isinstance(item["_raw"], dict):
                raw_list.append(item["_raw"])
            elif "label" in item and "items" in item:
                # ya es un dict de run
                raw_list.append(item)
    if not raw_list:
        return {"runs": [], "summary": [], "per_prompt": {}, "markdown": "(sin runs)"}

    # Per-prompt: agrupar por key
    per_prompt: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_list:
        run_label = raw.get("label", "?")
        for it in raw.get("items") or []:
            key = it.get("key") or it.get("title") or f"prompt_{len(per_prompt)}"
            m = it.get("metrics") or {}
            per_prompt.setdefault(key, []).append({
                "run_label": run_label,
                "title": it.get("title", key),
                "elapsed_sec": m.get("elapsed_sec"),
                "first_token_sec": m.get("first_token_sec"),
                "tokens_per_sec_proxy": m.get("tokens_per_sec_proxy"),
                "char_count": m.get("char_count"),
                "response_preview": (it.get("response") or "")[:160],
            })

    # Summary: una linea por run
    summary: list[dict[str, Any]] = []
    for raw in raw_list:
        be = raw.get("backend") or {}
        cfg = be.get("config") or {}
        items = raw.get("items") or []
        elapsed_vals = [(it.get("metrics") or {}).get("elapsed_sec") for it in items
                        if (it.get("metrics") or {}).get("elapsed_sec") is not None]
        tps_vals = [(it.get("metrics") or {}).get("tokens_per_sec_proxy") for it in items
                    if (it.get("metrics") or {}).get("tokens_per_sec_proxy") is not None]
        avg_tps = round(sum(tps_vals) / len(tps_vals), 2) if tps_vals else None
        avg_elapsed = round(sum(elapsed_vals) / len(elapsed_vals), 3) if elapsed_vals else None
        summary.append({
            "label": raw.get("label", "?"),
            "timestamp": raw.get("timestamp", ""),
            "backend": be.get("backend", "?"),
            "mock": bool(be.get("mock")),
            "model": cfg.get("name", "?"),
            "quant": cfg.get("quant") or "?",
            "size_human": cfg.get("size_human", "?"),
            "mode": cfg.get("mode", "?"),
            "wall_time_sec": (raw.get("totals") or {}).get("wall_time_sec"),
            "avg_elapsed_sec": avg_elapsed,
            "avg_tps_proxy": avg_tps,
            "prompts_run": (raw.get("totals") or {}).get("prompts_run"),
        })

    return {
        "runs": raw_list,
        "summary": summary,
        "per_prompt": per_prompt,
        "markdown": _render_markdown(summary, per_prompt),
    }


def render_compare_markdown(cmp_data: dict[str, Any]) -> str:
    """Wrapper publico sobre el renderer privado (para UI y tests)."""
    return _render_markdown(cmp_data.get("summary") or [],
                            cmp_data.get("per_prompt") or {})


def save_compare(cmp_data: dict[str, Any], results_dir: str | Path
                 ) -> tuple[Path, Path]:
    """Guarda la comparacion como JSON + Markdown en `results_dir`.

    Devuelve (json_path, md_path).
    """
    out_dir = Path(results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = out_dir / f"compare-{ts}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(cmp_data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    md_path.write_text(cmp_data.get("markdown") or render_compare_markdown(cmp_data),
                       encoding="utf-8")
    return json_path, md_path


def _render_markdown(summary: list[dict[str, Any]],
                     per_prompt: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    lines.append("# Comparativa de corridas")
    lines.append("")
    if summary:
        lines.append("## Runs")
        lines.append("")
        lines.append("| Label | Modelo | Cuant | Backend | Modo | Wall (s) | Promedio elapsed | t/s prom (proxy) | Prompts |")
        lines.append("|---|---|---|---|---|---:|---:|---:|---:|")
        for s in summary:
            lines.append(
                f"| {s['label']} | {s['model']} | {s['quant']} | "
                f"{s['backend']}{' (mock)' if s['mock'] else ''} | {s['mode']} | "
                f"{s['wall_time_sec']} | {s['avg_elapsed_sec']} | "
                f"{s['avg_tps_proxy']} | {s['prompts_run']} |"
            )
        lines.append("")

    lines.append("## Por prompt")
    lines.append("")
    for key, rows in per_prompt.items():
        title = rows[0].get("title", key) if rows else key
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| Run | elapsed (s) | 1er token (s) | t/s (proxy) | chars |")
        lines.append("|---|---:|---:|---:|---:|")
        for r in rows:
            first = r.get("first_token_sec")
            first_s = f"{first:.3f}" if isinstance(first, (int, float)) else "-"
            tps = r.get("tokens_per_sec_proxy")
            tps_s = f"{tps:.2f}" if isinstance(tps, (int, float)) else "-"
            elapsed = r.get("elapsed_sec")
            elapsed_s = f"{elapsed:.3f}" if isinstance(elapsed, (int, float)) else "-"
            lines.append(
                f"| {r['run_label']} | {elapsed_s} | {first_s} | {tps_s} | {r['char_count']} |"
            )
        lines.append("")
    return "\n".join(lines)