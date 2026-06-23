"""Runner de benchmarks locales.

Lee prompts_es.json, ejecuta cada uno contra el backend activo, mide
metricas, y guarda un JSON + un Markdown con resultados.

NO inventa numeros. Si algo no se puede medir, queda como null con
nota en `notes`.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import time
from pathlib import Path
from typing import Any

from .backend_base import BackendBase
from .metrics import get_process_metrics, get_system_memory, measure_inference, peak_rss_self


DEFAULT_PROMPTS_FILE = "benchmarks/prompts_es.json"
DEFAULT_RESULTS_DIR = "benchmarks/results"


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


# Re-exports para que `from app.benchmark import compare_runs, list_runs, load_run`
# siga funcionando. Toda la logica vive en app.history.
from .history import (  # noqa: E402,F401
    compare_runs as compare_runs,
    list_runs as list_runs,
    load_run as load_run,
    render_compare_markdown as render_compare_markdown,
    save_compare as save_compare,
)


def run_benchmark(backend: BackendBase,
                  prompts: list[dict[str, Any]] | None = None,
                  prompts_file: str | None = None,
                  results_dir: str = DEFAULT_RESULTS_DIR,
                  label: str | None = None) -> dict[str, Any]:
    """Ejecuta todos los prompts contra el backend. Devuelve el dict de resultados."""
    if prompts is None:
        prompts = load_prompts(prompts_file or DEFAULT_PROMPTS_FILE)

    if not backend.is_running():
        backend.start()

    backend_status = backend.status()
    system_mem_before = get_system_memory()
    backend_pid = backend_status.get("pid")
    rss_before = get_process_metrics(backend_pid).get("rss_bytes")
    t_start = time.perf_counter()

    items: list[dict[str, Any]] = []
    for p in prompts:
        key = p.get("key", f"prompt_{len(items)+1}")
        title = p.get("title", key)
        prompt_text = p.get("prompt", "")
        system = p.get("system", "")
        # El backend NO debe raise; medir con wrapper
        m = measure_inference(backend.generate, prompt_text, system)
        # Capturar respuesta cruda (recortada para que el JSON no explote)
        resp_raw = backend.generate(prompt_text, system)
        resp = resp_raw if len(resp_raw) <= 4000 else resp_raw[:4000] + "\n...[recortado]..."
        items.append({
            "key": key,
            "title": title,
            "prompt": prompt_text,
            "response": resp,
            "metrics": m,
        })

    t_total = time.perf_counter() - t_start
    rss_after = get_process_metrics(backend_pid).get("rss_bytes")
    system_mem_after = get_system_memory()

    result: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "label": label or f"run-{_timestamp()}",
        "backend": backend_status,
        "hardware": {
            "system_mem_before": system_mem_before,
            "system_mem_after": system_mem_after,
            "backend_rss_before_bytes": rss_before,
            "backend_rss_after_bytes": rss_after,
            "backend_rss_peak_proxy_bytes": (
                max([x for x in (rss_before, rss_after) if x]) if (rss_before or rss_after) else 0
            ),
            "ui_peak_rss_bytes": peak_rss_self(),
        },
        "totals": {
            "wall_time_sec": round(t_total, 3),
            "prompts_run": len(items),
        },
        "items": items,
        "notes": [
            "tokens_per_sec_proxy = chars/4 / sec (orden de magnitud, NO exacto)",
            "Si backend.mock=True, los resultados son de MOCK (no medir rendimiento real).",
            "first_token_sec requiere streaming; queda pendiente en MVP.",
        ],
    }

    _save_results(result, results_dir)
    return result


def load_prompts(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "prompts" in data:
            return data["prompts"]
    except Exception:
        pass
    return []


def _save_results(result: dict[str, Any], results_dir: str) -> None:
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    json_path = Path(results_dir) / f"{result['label']}-{ts}.json"
    md_path = Path(results_dir) / f"{result['label']}-{ts}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(result), encoding="utf-8")


def _render_markdown(r: dict[str, Any]) -> str:
    be = r["backend"]
    hw = r["hardware"]
    cfg = (be.get("config") or {})
    lines: list[str] = []
    lines.append(f"# Benchmark {r['label']} - {r['timestamp']}")
    lines.append("")
    lines.append(f"- Backend: **{be.get('backend')}** (mock={be.get('mock')})")
    lines.append(f"- Modelo: `{cfg.get('name')}`")
    lines.append(f"- Path: `{cfg.get('gguf_path')}`")
    lines.append(f"- Cuant: `{cfg.get('quant') or '?'}`  Tamano disco: `{cfg.get('size_human')}`")
    lines.append(f"- Modo: `{cfg.get('mode')}`  GPU layers: `{cfg.get('gpu_layers')}`")
    lines.append(f"- Contexto: `{cfg.get('ctx_size')}`  Threads: `{cfg.get('threads')}`")
    lines.append(f"- Comando: `{be.get('command') or '(no capturado)'}`")
    lines.append("")
    lines.append("## Hardware durante el run")
    lines.append(f"- RAM total: `{hw['system_mem_before'].get('total_human')}`")
    lines.append(f"- RAM disponible antes: `{hw['system_mem_before'].get('available_human')}`")
    lines.append(f"- RAM disponible despues: `{hw['system_mem_after'].get('available_human')}`")
    lines.append(f"- RSS backend antes / despues (bytes): `{hw['backend_rss_before_bytes']}` / `{hw['backend_rss_after_bytes']}`")
    lines.append("")
    lines.append(f"## Totales")
    lines.append(f"- Wall time: `{r['totals']['wall_time_sec']} s`")
    lines.append(f"- Prompts corridos: `{r['totals']['prompts_run']}`")
    lines.append("")
    lines.append("## Resultados por prompt")
    lines.append("")
    lines.append("| # | Titulo | elapsed (s) | t/s (proxy) | chars |")
    lines.append("|---|--------|------------:|------------:|------:|")
    for i, it in enumerate(r["items"], start=1):
        m = it["metrics"]
        tps = m.get("tokens_per_sec_proxy")
        tps_s = f"{tps:.2f}" if isinstance(tps, (int, float)) else "-"
        lines.append(f"| {i} | {it['title']} | {m.get('elapsed_sec')} | {tps_s} | {m.get('char_count')} |")
    lines.append("")
    lines.append("## Respuestas (recortadas)")
    for i, it in enumerate(r["items"], start=1):
        lines.append(f"### {i}. {it['title']}")
        lines.append("")
        lines.append("**Prompt:**")
        lines.append("")
        lines.append("```")
        lines.append(it["prompt"])
        lines.append("```")
        lines.append("**Respuesta:**")
        lines.append("")
        lines.append("```")
        lines.append(it["response"])
        lines.append("```")
        lines.append("")
    lines.append("## Notas")
    for n in r["notes"]:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("## Observaciones manuales")
    lines.append("")
    lines.append("- [ ] Calidad percibida en espanol: ")
    lines.append("- [ ] Calidad coding: ")
    lines.append("- [ ] Calidad auditoria tecnica: ")
    lines.append("- [ ] Estabilidad (crashes / cuelgues): ")
    lines.append("- [ ] Sensacion general: ")
    return "\n".join(lines)


# ----------------- Comparacion entre corridas -----------------

def list_runs(results_dir: str = DEFAULT_RESULTS_DIR) -> list[dict[str, Any]]:
    """Lista metadata de todas las corridas previas (.json) en el directorio.

    Devuelve una lista ordenada por timestamp descendente (mas reciente primero).
    NO carga el contenido completo, solo lo necesario para mostrar en la UI.
    """
    p = Path(results_dir)
    if not p.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for jp in sorted(p.glob("*.json")):
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue
        be = data.get("backend") or {}
        cfg = be.get("config") or {}
        runs.append({
            "path": str(jp.resolve()),
            "filename": jp.name,
            "label": data.get("label") or jp.stem,
            "timestamp": data.get("timestamp") or "",
            "model": cfg.get("name") or "?",
            "backend": be.get("backend") or "?",
            "mock": bool(be.get("mock")),
            "quant": cfg.get("quant") or "?",
            "mode": cfg.get("mode") or "?",
            "ctx_size": cfg.get("ctx_size"),
            "threads": cfg.get("threads"),
            "size_human": cfg.get("size_human") or "?",
            "prompts_run": (data.get("totals") or {}).get("prompts_run"),
            "wall_time_sec": (data.get("totals") or {}).get("wall_time_sec"),
        })
    # Mas reciente primero (timestamp lexicografico ISO sortable)
    runs.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return runs


def load_run(path: str) -> dict[str, Any]:
    """Carga un run completo desde su JSON. None-safe."""
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def compare_runs(run_paths: list[str]) -> dict[str, Any]:
    """Compara 2+ corridas (mismos prompts, distintos modelos).

    Estructura:
      {
        "schema_version": 1,
        "created_at": ISO,
        "runs": [<run_data>, ...],
        "per_prompt": [
            {"key": "...", "title": "...",
             "by_run": {label: {"elapsed_sec": ..., "tokens_per_sec_proxy": ..., "char_count": ...}}},
            ...
        ],
        "totals_by_run": {label: {"wall_time_sec": ..., "total_chars": ..., "mean_elapsed_sec": ...}},
      }
    """
    runs: list[dict[str, Any]] = []
    for rp in run_paths:
        r = load_run(rp)
        if r:
            runs.append(r)
    if not runs:
        return {}

    # Union de keys de prompts (en orden de aparicion del primer run)
    keys_order: list[str] = []
    seen: set[str] = set()
    for r in runs:
        for it in (r.get("items") or []):
            k = it.get("key") or f"item_{len(seen)}"
            if k not in seen:
                seen.add(k)
                keys_order.append(k)

    # Indexar items por (run_label, key)
    by_run: dict[str, dict[str, dict[str, Any]]] = {}
    titles: dict[str, str] = {}
    for r in runs:
        lbl = r.get("label") or "?"
        by_run[lbl] = {}
        for it in (r.get("items") or []):
            k = it.get("key") or ""
            if k:
                by_run[lbl][k] = it.get("metrics") or {}
                if k not in titles:
                    titles[k] = it.get("title") or k

    per_prompt: list[dict[str, Any]] = []
    for k in keys_order:
        per_prompt.append({
            "key": k,
            "title": titles.get(k, k),
            "by_run": {lbl: by_run.get(lbl, {}).get(k, {}) for lbl in by_run},
        })

    # Totales por run
    totals_by_run: dict[str, dict[str, Any]] = {}
    for r in runs:
        lbl = r.get("label") or "?"
        items = r.get("items") or []
        elapsed_values = [(it.get("metrics") or {}).get("elapsed_sec") for it in items]
        elapsed_nums = [v for v in elapsed_values if isinstance(v, (int, float))]
        char_values = [(it.get("metrics") or {}).get("char_count") for it in items]
        char_nums = [v for v in char_values if isinstance(v, (int, float))]
        totals_by_run[lbl] = {
            "wall_time_sec": (r.get("totals") or {}).get("wall_time_sec"),
            "prompts_run": (r.get("totals") or {}).get("prompts_run"),
            "total_chars": sum(char_nums) if char_nums else 0,
            "mean_elapsed_sec": round(sum(elapsed_nums) / len(elapsed_nums), 3) if elapsed_nums else None,
        }

    return {
        "schema_version": 1,
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "runs": [
            {
                "label": (r.get("label") or "?"),
                "timestamp": r.get("timestamp") or "",
                "model": ((r.get("backend") or {}).get("config") or {}).get("name") or "?",
                "quant": ((r.get("backend") or {}).get("config") or {}).get("quant") or "?",
                "mode": ((r.get("backend") or {}).get("config") or {}).get("mode") or "?",
                "backend": (r.get("backend") or {}).get("backend") or "?",
                "mock": bool((r.get("backend") or {}).get("mock")),
                "ctx_size": ((r.get("backend") or {}).get("config") or {}).get("ctx_size"),
                "size_human": ((r.get("backend") or {}).get("config") or {}).get("size_human") or "?",
            }
            for r in runs
        ],
        "per_prompt": per_prompt,
        "totals_by_run": totals_by_run,
    }


def render_compare_markdown(cmp: dict[str, Any]) -> str:
    """Render del dict comparativo a Markdown (tabla por prompt + totales)."""
    if not cmp:
        return "(sin datos para comparar)"
    runs = cmp.get("runs") or []
    if not runs:
        return "(sin corridas)"
    lines: list[str] = []
    lines.append(f"# Comparacion de corridas - {cmp.get('created_at','')}")
    lines.append("")
    lines.append(f"Corridas comparadas: {len(runs)}")
    lines.append("")
    lines.append("## Modelos")
    lines.append("")
    lines.append("| Label | Modelo | Cuant | Tamano | Modo | Ctx | Backend | mock |")
    lines.append("|-------|--------|-------|--------|------|-----|---------|------|")
    for r in runs:
        lines.append(
            f"| {r.get('label')} | {r.get('model')} | {r.get('quant')} | "
            f"{r.get('size_human')} | {r.get('mode')} | {r.get('ctx_size')} | "
            f"{r.get('backend')} | {r.get('mock')} |"
        )
    lines.append("")

    # Tabla por prompt: elapsed y chars por run
    labels = [r.get("label") or "?" for r in runs]
    header_metrics = ["elapsed_sec", "tokens_per_sec_proxy", "char_count"]
    head_titles = ["elapsed (s)", "t/s (proxy)", "chars"]

    lines.append("## Por prompt")
    lines.append("")
    for prompt_block in (cmp.get("per_prompt") or []):
        title = prompt_block.get("title") or prompt_block.get("key")
        lines.append(f"### {title}")
        lines.append("")
        # Header: prompt | label1.elapsed | label1.tps | label1.chars | ...
        header_cells = ["prompt"]
        for lbl in labels:
            for ht in head_titles:
                header_cells.append(f"{lbl}.{ht}")
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cells)) + "|")
        # Una sola fila por prompt con todos los runs
        cells = [prompt_block.get("key") or "?"]
        for lbl in labels:
            m = (prompt_block.get("by_run") or {}).get(lbl) or {}
            for k in header_metrics:
                v = m.get(k)
                if isinstance(v, float):
                    cells.append(f"{v:.3f}")
                elif v is None:
                    cells.append("-")
                else:
                    cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    # Totales
    lines.append("## Totales por corrida")
    lines.append("")
    lines.append("| Label | wall (s) | prompts | chars total | elapsed medio (s) |")
    lines.append("|-------|---------:|--------:|------------:|------------------:|")
    for lbl in labels:
        t = (cmp.get("totals_by_run") or {}).get(lbl) or {}
        wall = t.get("wall_time_sec")
        prompts_run = t.get("prompts_run")
        chars = t.get("total_chars")
        mean = t.get("mean_elapsed_sec")
        wall_s = f"{wall:.2f}" if isinstance(wall, (int, float)) else "-"
        mean_s = f"{mean:.3f}" if isinstance(mean, (int, float)) else "-"
        chars_s = str(chars) if isinstance(chars, int) else "-"
        lines.append(f"| {lbl} | {wall_s} | {prompts_run or '-'} | {chars_s} | {mean_s} |")
    lines.append("")
    lines.append("## Observaciones")
    lines.append("")
    lines.append("- Comparacion automatica: NO declara ganador.")
    lines.append("- Mismos prompts = misma base. Diferencias en calidad hay que medirlas a ojo.")
    lines.append("- t/s proxy es chars/4/sec (orden de magnitud, NO exacto).")
    lines.append("- Si una corrida es mock=True, descartar sus numeros para rendimiento.")
    lines.append("- Para tokens/s exactos: parsear stdout de llama.cpp (eval time).")
    return "\n".join(lines)


def save_compare(cmp: dict[str, Any], results_dir: str = DEFAULT_RESULTS_DIR) -> tuple[str, str]:
    """Guarda la comparacion como JSON + Markdown. Devuelve (json_path, md_path)."""
    if not cmp:
        return ("", "")
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    base = f"compare-{ts}"
    json_path = Path(results_dir) / f"{base}.json"
    md_path = Path(results_dir) / f"{base}.md"
    json_path.write_text(json.dumps(cmp, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_compare_markdown(cmp), encoding="utf-8")
    return (str(json_path), str(md_path))