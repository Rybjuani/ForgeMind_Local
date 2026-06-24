# ForgeMind UI — Fidelidad mockup v14 + kill primer arranque

**Goal:** Llevar la UI a paridad 1:1 con `Desktop/forgemind_claude_desktop_mockup_dark_claude_polish_v14.html` y eliminar la pantalla modal "Primer arranque" (`_show_first_run_wizard`).

**Branch:** `feat/ui-mockup-v14-fidelity` (base actual: `antigravity/visual-coherence`, sin commits).

**Mockup = fuente de verdad visual.** Tests existentes (1249 lines, 124 casos) no se tocan salvo que rompan features.

---

## Contexto

- Branch vacía (`git log` = vacío). Remote apunta a `Rybjuani/Africa_Deep_Tech` (Kijani), no a este repo — no se pushea.
- `app/ui_main.py` = 4566 líneas. QSS robusto (líneas 98–~810). Estructura ya coincide con el mockup en pantallas (6 screens) pero con divergencias visibles en `screenshots/01-chat.png`–`06-gpu.png`:
  - Header: NO tiene chips, NO tiene cmdk-btn, NO tiene botón "Nuevo chat".
  - Sidebar: model-card dice "Detenido", sin pill "Activo", sin history section.
  - Footer: tiene user row (mockup lo ELIMINA explícitamente, ver `forgemind_claude_desktop_mockup_dark_claude_polish_v14.html` último bloque CSS).
  - Composer: solo tiene trash + send arrow. Mockup requiere preset-pill, model-select-pill, attach, tools, clear.
  - Chat empty state: 2 cards en 2 cols. Mockup: 4 cards en 1 fila (full width 760px).
  - Config screen: sliders rotos (muestran "—"), campos no en grid 2-col, layout colapsado (ver `02-config.png`).
  - Benchmark: lista/detalle vacíos, botones cortados.
  - Titlebar: sin title-tabs (Chat/Benchmark/Code), sin status central.
- `_show_first_run_wizard` en `app/ui_main.py:4045` — modal que aparece con `QTimer.singleShot(250, ...)` cuando `self._first_run_needs_setup`. **KILL** (no se elimina la función, solo se quita el trigger — preserva el cmdk entry "Re-auto-detectar" como acción manual).

---

## Pasos

### 1. Setup
- Branch `feat/ui-mockup-v14-fidelity` desde `antigravity/visual-coherence`.
- Baseline tests: `pytest -q` debe pasar 124 tests.

### 2. Kill primer arranque
- `app/ui_main.py:3461-3463` — comentar / desactivar `QTimer.singleShot(250, self._show_first_run_wizard)`.
- `app/ui_main.py:3301-3309` — borrar / no-op las flags `_first_run_needs_setup`, `_first_run_was_just_run` (no se usan en otra parte).
- `app/main.py:73-75` — preservar `auto_config.first_run_setup()` (sigue creando settings.json sin abrir wizard). La detección silenciosa sirve para que la sidebar model-card muestre "Detenido" vs "Activo" sin molestar al usuario.
- Cmd palette gana item: "Re-auto-detectar" → invoca la misma lógica de auto-detection y refresh (en lugar de abrir el wizard). Verifica que existe en `_build_commands` (línea 1206).
- **Cierre honesto:** el item "Re-auto-detectar" sigue siendo funcional; sólo muere la aparición automática del modal.

### 3. Refactor header — agregar chips, cmdk, Nuevo chat (mockup l.730-770)
- `MainWindow.__init__` (~línea 3374-3410) ya tiene `btn_header_new_chat` pero el color es #d97757 (acento). Mockup quiere header-new-chat con `background: rgba(255,255,255,0.055)` (chip neutral), color #d8d4c8, sin box-shadow. Fix QSS inline.
- Los chips ya están creados (`chip_model`, `chip_backend`) pero NO se veían en `01-chat.png` porque están a la derecha después del botón + el botón tiene bg acento. Cambiar a neutral.
- cmdk button ya existe (`btn_cmdk`) — verificar posición (debe estar a la derecha de los chips, antes del logo) y que abra el palette al click.
- Conectar `btn_header_new_chat.clicked` → `_on_new_chat` (que ya existe en sidebar).

### 4. Refactor sidebar — model card + history + kill user row
- `Sidebar.set_model_card` (~línea 1606) — agregar pill "Activo"/"Detenido" arriba del nombre. Status pill con dot animado.
- Sidebar body (línea 1319+) — agregar `history-section` con heading "HISTORIAL" + items desde `history.list_runs()`. Ver `app/history.py:20`.
- Sidebar footer (línea 1644+) — quitar user row completo. Solo dejar `foot-row` con dot verde + RAM/tps (mockup l.772-776). El user row actual es `user_row` / `ForgeMind User` — eliminarlo.

### 5. Refactor composer — preset-pill + model-select-pill + tools + send (mockup l.860-940)
- `ChatScreen` (~línea 1844) — ya tiene preset pill, send btn, clear btn, attach/tools btn. Falta:
  - `model-select-pill` en `.composer-right` antes del attach (mockup l.924): "Gemma 4 12B" con dot verde + chevron.
  - `composer-input-shell` wrapper alrededor del textarea (mockup l.880-887) para aislar el focus border.
  - Hint con `kbd` shortcuts (mockup l.950): "Enter enviar · Shift+Enter nueva línea · Ctrl+K buscar".

### 6. Refactor chat empty state (mockup l.957-1010)
- 4 suggestion cards en grid horizontal (`grid-template-columns: repeat(4, minmax(0,1fr))`) en vez de 2.
- Logo asterisco "*" centrado arriba del título (serif Newsreader, 66px, glow radial detrás).
- Título "Hola, Juan" (mockup dice "Juan" hardcoded — usar nombre del settings o fallback "ahí"). Subtitle "ForgeMind Local listo para razonar, auditar y medir modelos sin salir de tu PC."
- Las 4 sugerencias del mockup (Comparar/Correr/Medir/Probar) con íconos SVG + título + desc.

### 7. Fix config screen (mockup l.1014-1130)
- `ConfigScreen` (~línea 2400) — los sliders se renderizan como "—" porque falta el `_set_value` en `MetricTile`. Verificar `slider-field` + `slider-row` + `slider-value` widgets existen en la construcción. Mockup quiere temp/top_p/repeat_penalty sliders reales (rangos, fill highlight).
- Form grid 2 columnas, field-label arriba, hint abajo.
- Botones: "Aplicar config al backend" (primary), "Refrescar info" (ghost). Backend card: dropdown backend_kind + paths + "Probar"/"Iniciar"/"Detener".
- Log del backend: consola monospace al final.

### 8. Fix benchmark screen (mockup l.1183-1260)
- `BenchmarkScreen` (~línea 2800) — verificar `runs-grid` (320px lista + 1fr detalle) con tabla `compare-table`. Si la lista está vacía y los botones cortados, ajustar layout/spacing.
- Botones: "Correr benchmark" (primary), "Comparar seleccionados", "Guardar comparación".

### 9. Update titlebar (mockup l.680-712)
- `TitleBar` (~línea 1015) — agregar center widget con `title-tabs` (Chat/Benchmark/Code) + status dot + texto "Gemma 4 12B · Q4_K_M · 7.4 GB · llama-cli". Ya existe `#StatusDot` + brand.
- Los title-tabs son decorativos en esta app (single mode) pero el mockup los muestra. Hacerlos funcionales como filtro del ChatScreen (filtrar prompts por modo).
- Wire `titlebar.set_status_text(...)` desde `MainWindow.refresh_status_chips` (ya existe).

### 10. Verify backend functionality
- `python -m app.main --mock` debe abrir sin error y permitir enviar mensaje al composer → recibir respuesta mock del backend.
- `python -m app.main --check` debe imprimir resumen de entorno sin GUI.
- Sin modelo real: la sidebar debe decir "Detenido" sin toast de error, el composer debe aceptar input pero mostrar toast "Sin modelo — andá a Modelo y backend" al enviar.

### 11. Smoke + visual validation
- Correr `python smoke_ui.py` (existente) en offscreen mode.
- Capturar nuevos screenshots con `python smoke_all_screens.py` para los 6 screens. Comparar contra mockup visualmente.
- `pytest -q` debe seguir 124 passed.

### 12. Commit + build
- Commit por step (per visual-fidelity-loop: one fix per commit).
- `python build.bat` para regenerar .exe.
- End with explicit "NO es PASS visual global" + lista de divergencias estéticas pendientes.

---

## Files (cambios principales)

| Archivo | Tipo | Razón |
|---|---|---|
| `app/ui_main.py` | modify | Header chips, sidebar model card + history + kill user row, composer (input-shell, model-pill), chat empty 4-col, config sliders, bench layout, kill wizard trigger |
| `app/main.py` | read-only | `_run_ui` sigue llamando `first_run_setup()` (settings.json se crea silencioso) |
| `app/auto_config.py` | read-only | wizard function se preserva (no se usa más) |
| `screenshots/0[1-6]-*.png` | regenerate | después de cada cambio visible |
| `qa/VISUAL_LOOP_LOG.md` | create | log del loop visual per skill |

NO se tocan: `app/backend_base.py`, `app/llama_backend.py`, `app/ollama_backend.py`, `app/benchmark.py`, `app/metrics.py`, `app/gpu_detect.py`, `app/history.py`, `app/presets.py`, `app/model_config.py`, `app/downloader.py`, tests, `forgemind.spec`, `build.bat`.

---

## Verificación

1. `pytest -q` → 124 passed.
2. `python -m app.main --check` → exit 0 con resumen.
3. `QT_QPA_PLATFORM=offscreen python -m app.main --mock &` → arranca, captura via `smoke_all_screens.py`, exit clean.
4. Screenshots nuevos comparados contra mockup en el chat.
5. Wizard modal NO aparece en `--mock` ni en arranque normal sin modelo.

---

## Riesgos / trade-offs

- **QStackedWidget QSS cascade:** per `pyqt6-visual-fidelity-loop` skill, QSS a veces NO cascadea a páginas dentro de QStackedWidget. Si un screen se ve sin estilos después del refactor, setear `setStyleSheet()` inline en cada Screen como fallback.
- **Fonts:** mockup usa Inter + JetBrains Mono no bundleados → fallback a Segoe UI / Consolas (visualmente OK, lo confirma skill).
- **Box-shadow / backdrop-filter:** ignorados por Qt. Usar gradientes lineales o aceptar divergencia.
- **CSS `::before`:** nav active indicator de 3px debe ser un `QFrame` real child, no pseudo-elemento.

## Cierre honesto

Al final, frase literal: **"NO es PASS visual global"** + lista de divergencias restantes (estéticas vs funcionales) — per directive del user.