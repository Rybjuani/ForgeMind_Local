# Backends

## MVP: llama.cpp (obligatorio)

Tres modos seleccionables en `Backend kind`:

### `llama_cli` (default)
- **Pro**: portable, no requiere build, usa ejecutable ya compilado.
- **Contra**: cada request = un proceso nuevo (overhead ~1-2 s).
- **Uso recomendado**: tareas one-shot, benchmarks, prompt largo unico.

Comportamiento: al `Iniciar modelo`, el backend queda "activo" en modo lazy; `generate()` lanza un subprocess de `llama-cli` por cada envio y devuelve stdout.

### `llama_server`
- **Pro**: el modelo queda cargado en memoria, requests HTTP repetidos son baratos. Permite streaming real (cuando se implemente).
- **Contra**: ocupa RAM continuamente, hay que esperar al health check al arrancar.
- **Uso recomendado**: sesiones de chat largas, benchmarks iterativos.

Comportamiento: arranca `llama-server` en `127.0.0.1:8081` (configurable en codigo). `generate()` hace `POST /completion`.

### `llama_cpp` (binding Python)
- **Pro**: latencia minima (in-process), control fino.
- **Contra**: requiere `pip install llama-cpp-python` (build desde source en Windows puede pedir toolchain); en AMD sin CUDA el backend usa CPU igual.
- **Uso recomendado**: dev/test, integracion estrecha.

Si no esta instalado, cae automaticamente a `llama-cli`.

## Como instalar llama.cpp en Windows

1. Ir a https://github.com/ggerganov/llama.cpp/releases
2. Bajar el ZIP para Windows:
   - `llama-bXXXX-bin-win-vulkan-x64.zip` si queres soporte Vulkan experimental.
   - `llama-bXXXX-bin-win-cpu-x64.zip` si solo queres CPU.
3. Extraer en una carpeta fija (ej `C:\tools\llama.cpp\`).
4. Agregar esa carpeta al PATH **o** poner la ruta completa en la UI (`llama-cli` / `llama-server`).

Si el build Vulkan falla al cargar el modelo, volve a `cpu` (boton en UI) y reintenta. La app no se rompe.

## Fallos tipicos

| Sintoma | Causa comun | Fix |
|---|---|---|
| `Backend activo: mock (mock=True)` | `llama-cli` no esta en PATH o ruta mal cargada | Pestana Backend -> `Probar backend` |
| `Modelo no existe` | Ruta al `.gguf` no es accesible | Pestana Modelo -> verificar ruta |
| `llama-cli exit N` | Cuant no soportada / modelo corrupto / OOM | Probar con contexto mas chico o cuant menor |
| `server unreachable` | `llama-server` no termino de arrancar | Aumentar timeout; revisar log; o volver a `llama_cli` |
| `inference error` (binding) | `llama-cpp-python` no compilado para tu arquitectura | `pip install --upgrade --force-reinstall llama-cpp-python` |

## Backends implementados (MVP+)

### `llama_cli` (default MVP)
- **Pro**: portable, no requiere build, usa ejecutable ya compilado.
- **Contra**: cada request = un proceso nuevo (overhead ~1-2 s).
- **Uso recomendado**: tareas one-shot, benchmarks, prompt largo unico.

Comportamiento: al `Iniciar modelo`, el backend queda "activo" en modo lazy; `generate()` lanza un subprocess de `llama-cli` por cada envio y devuelve stdout.

### `llama_server`
- **Pro**: el modelo queda cargado en memoria, requests HTTP repetidos son baratos. Permite streaming real (cuando se implemente).
- **Contra**: ocupa RAM continuamente, hay que esperar al health check al arrancar.
- **Uso recomendado**: sesiones de chat largas, benchmarks iterativos.

Comportamiento: arranca `llama-server` en `127.0.0.1:8081` (configurable en codigo). `generate()` hace `POST /completion`.

### `llama_cpp` (binding Python)
- **Pro**: latencia minima (in-process), control fino.
- **Contra**: requiere `pip install llama-cpp-python` (build desde source en Windows puede pedir toolchain); en AMD sin CUDA el backend usa CPU igual.
- **Uso recomendado**: dev/test, integracion estrecha.

Si no esta instalado, cae automaticamente a `llama-cli`.

### `ollama` (HTTP, sin llama.cpp)
- **Pro**: cero build, modelos ya descargados via `ollama pull`, aprovecha el daemon de Ollama que ya tenes corriendo.
- **Contra**: requiere Ollama instalado y corriendo (`ollama serve`); no tenes control fino del offload GPU.
- **Uso recomendado**: comparar contra el mismo modelo en Ollama vs llama.cpp directo.

Seleccionar en UI: pestana `Backend` -> `Backend kind: ollama`. URL por defecto `http://127.0.0.1:11434`. El "modelo" se identifica por el campo `name` (en lugar de la ruta al .gguf).

Endpoints usados:
- `GET /api/tags` (lista de modelos, health check)
- `POST /api/generate` con `stream: true` para NDJSON streaming

Si Ollama no responde, el backend cae a modo mock etiquetado: `[ollama-mock] Ollama no esta corriendo en http://127.0.0.1:11434`.

## Pendiente

- Tokens/s exacto (parsear `eval time` / `tokens evaluated` de llama.cpp stdout)
- LM Studio API local (sigue en futuro, no implementado)
- NSIS installer para distribuir el .exe (no necesario para uso personal)
- Code signing (no aplica a uso personal)