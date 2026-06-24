# ForgeMind Local

App desktop para comparar modelos GGUF locales en Windows 10. Sin cloud, sin claves, sin CUDA.

## Que hace

- Selector de modelo GGUF con parametros (ctx, threads, temp, top-p, repeat penalty, GPU layers, modo CPU/Vulkan).
- Backend `llama.cpp` con tres modos: `llama-cli`, `llama-server`, binding Python (opcional).
- Chat con presets (Diario, Coding, Auditoria, Resumen, Razonamiento, Espanol claro, Prompt largo).
- Panel de rendimiento (RAM sistema, RSS backend, latencia, tokens/s proxy, contexto usado).
- Deteccion de GPU AMD y heuristica Vulkan.
- Benchmark local con 10 prompts fijos en espanol, guarda JSON + Markdown.

## Hardware objetivo

- Windows 10, 16 GB RAM, 1 TB disco.
- GPU: AMD Radeon RX550 4 GB (sin NVIDIA, sin CUDA).
- Vulkan como modo experimental (no se afirma que mejore sin benchmark).

## Quick start (Windows — sin linea de comandos)

Doble click en **`INICIAR.bat`** en la carpeta del proyecto. La primera vez:
1. Detecta o crea un venv con Python + PyQt6 + psutil + PyInstaller.
2. Empaqueta `dist\ForgeMind.exe` (1-3 minutos).
3. Abre la app automaticamente.

Las siguientes veces abre directo en 1 segundo (reusa el `.exe`).

Para tener un icono en el escritorio: doble click en **`Crear acceso.bat`**.

## Quick start (PowerShell nativo)

```powershell
cd C:\Users\nosom\Desktop\ForgeMind_Local
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\scripts\run.ps1              # arranca UI
.\scripts\run.ps1 -Check       # solo resumen de entorno (sin UI)
.\scripts\run.ps1 -Mock        # UI sin modelo (modo mock)
.\scripts\check_env.ps1        # idem, script dedicado
```

## Configurar el backend

1. Descargar `llama.cpp` para Windows (build oficial o build con Vulkan si queres probar GPU offload).
   Ejemplo de releases: https://github.com/ggerganov/llama.cpp/releases
   Tipico nombre: `llama-bXXXX-bin-win-vulkan-x64.zip` (o `-cpu-` si no queres Vulkan).
2. Extraer y agregar la carpeta al PATH del sistema, **o** apuntar a los `.exe` en la pestana `Backend` de la UI.
3. Descargar un `.gguf` (Gemma 4 12B Q4_K_M, Qwen3-14B Q4_K_M, Phi-4 14B Q4, etc.).
4. En la UI, pestana `Modelo`:
   - Seleccionar el `.gguf`
   - Poner nombre, contexto, threads, temp, top-p, etc.
   - `Aplicar config al backend`
5. Pestana `Backend`:
   - Elegir tipo: `llama_cli` (default MVP) o `llama_server`.
   - `Probar backend` para validar ejecutables.
   - `Iniciar modelo`.
6. Pestana `Chat`: escribir prompt y enviar. Preset desde el combo.

## Benchmark local

Pestana `Benchmark`:
- Archivo de prompts por defecto: `benchmarks/prompts_es.json`.
- Boton `Correr benchmark` ejecuta los 10 prompts contra el backend activo.
- Guarda `benchmarks/results/<label>-<timestamp>.json` y `.md`.
- No inventa numeros: si algo no se pudo medir, queda como `null` + nota.

## Historial y comparativa

En la misma pestana `Benchmark`, seccion inferior "Historial y comparacion":
- `Refrescar lista` lee todos los JSON en la carpeta de resultados.
- Cada item muestra: label, modelo, cuant, tamano, fecha, hora.
- Ctrl+click para multi-seleccionar 2 o mas corridas (incluso de modelos distintos).
- `Comparar seleccionados` genera tabla lado a lado: por prompt y resumen general (wall time, t/s prom, etc.).
- `Guardar comparacion` persiste el resultado como `compare-<timestamp>.{json,md}` en la misma carpeta.
- Doble-click en una corrida muestra detalle completo en el panel "Resumen ultima corrida".

Util para responder la pregunta clave: "cual modelo conviene para mi PC?" sin tener que correr los benchmarks lado a lado a ojo.

## Conversaciones de chat (persistencia)

La pestana `Chat` guarda automaticamente cada conversacion en `chats/<id>.json` (al lado de `settings.json`). Cada archivo incluye:
- `id`: timestamp `YYYYMMDD-HHMMSS`
- `title`: derivado del primer mensaje del usuario (primeros 40 chars)
- `created_at` / `updated_at`
- `model`: nombre del modelo activo al momento del chat
- `preset`: preset activo (diario, coding, etc.)
- `messages`: lista de `{role, content, ts, preset}` (user + ai)

El sidebar `HISTORIAL` muestra las 8 conversaciones mas recientes. Click en una entrada la carga completa en el chat screen (incluyendo respuestas del AI).

Boton `Nueva conversacion` (sidebar o header) empieza un chat nuevo sin perder los anteriores. Boton `Limpiar` (trash en el composer) limpia la vista pero el archivo sigue en disco.

Para borrar conversaciones: eliminar manualmente los `.json` en `chats/` (son archivos de texto plano, editables con cualquier editor).

## Estructura

```
ForgeMind_Local/
  app/                # codigo Python (main, UI, backend, metrics, gpu_detect, benchmark, presets, chat_history)
  configs/            # ejemplos .example.json (NO commitear configs reales)
  benchmarks/         # prompts_es.json + results/
  chats/              # conversaciones persistidas (auto-generado, NO commitear)
  scripts/            # run.ps1, check_env.ps1, build.ps1
  docs/               # notas (modelos, backends, vulkan, uso diario, build)
  tests/              # pytest, 172 tests
  run.py              # entry shim para PyInstaller
  forgemind.spec      # spec de PyInstaller
  INICIAR.bat         # doble click para abrir la app (buildea si hace falta)
  Crear acceso.bat    # crea icono en el escritorio
  build.bat           # genera dist\ForgeMind.exe
```

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

92 tests cubren: config, metrics, presets, backend mock, benchmark, gpu_detect (mockeado), backend_base, smoke test end-to-end. Tarda ~11 s.

## Build a .exe (PyInstaller)

```powershell
pip install pyinstaller
.\scripts\build.ps1              # genera dist\ForgeMind.exe (~70-90 MB)
.\scripts\build.ps1 -Clean       # limpia build/ y dist/ antes
.\scripts\build.ps1 -NoUpx       # desactiva compresor UPX
```

Ver `docs/BUILD.md` para detalle del shim `run.py` y opciones.

## Streaming + first-token timing

Chat usa `generate_stream()` (Popen stdout streaming para `llama-cli`, HTTP chunked para `llama-server`). Mide `first_token_sec` (tiempo a primer chunk) ademas de `elapsed_sec` y `tokens_per_sec_proxy`. El boton "Detener generacion" mata el subprocess best-effort.