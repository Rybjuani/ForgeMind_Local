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