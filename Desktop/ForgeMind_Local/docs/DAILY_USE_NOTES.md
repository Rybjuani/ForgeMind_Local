# Uso diario - notas

## Workflow tipico

1. Abrir PowerShell, ir al proyecto:
   ```powershell
   cd C:\Users\nosom\Desktop\ForgeMind_Local
   .\scripts\run.ps1
   ```
2. Pestana `Modelo`: elegir `.gguf`, ajustar contexto / threads / temp.
3. Pestana `Backend`: `Probar backend`, luego `Iniciar modelo`.
4. Pestana `Chat`: usar preset acorde a la tarea.
5. Pestana `Benchmark`: correr benchmarks antes de decidir un modelo "default".

## Presets - cuando usar cada uno

| Preset | Uso tipico |
|---|---|
| Diario | Preguntas rapidas, consultas generales |
| Coding | Pedir codigo, revisar snippets, pedir refactors |
| Auditoria | Analisis critico de codigo/decisiones, busqueda de bugs |
| Resumen | Achicar textos largos |
| Razonamiento | Problemas logicos paso a paso |
| Espanol claro | Pedir redaccion sobria en espanol |
| Prompt largo | Pegar contexto grande y pedir respuesta estructurada |

## Recomendaciones operativas

- **Primer arranque del dia**: abrir el `.gguf` que vas a usar. Dejarlo cargado en RAM (usar `llama_server`).
- **Cambiar de modelo**: parar backend -> cambiar ruta -> aplicar -> iniciar.
- **Medir antes de comparar**: la pestana `Benchmark` siempre. Sin numeros no hay结论.
- **Apagar Vulkan si va mal**: pestana `Modelo` -> modo `cpu`, gpu_layers 0, reaplicar.

## Si la UI se congela

- En MVP la inferencia pasa por un QThread; no deberia congelarse.
- Si pasa: matar el proceso `python.exe` desde Task Manager.
- Si `llama-cli` se queda colgado: matar `llama-cli.exe` desde Task Manager. El backend lo detectara como muerto.

## Limpiar

- Modelos `.gguf` pesan GBs. Mantenerlos fuera del repo.
- Resultados de benchmark se acumulan en `benchmarks/results/`. Borrar manualmente los `.json` / `.md` viejos que no quieras conservar. La carpeta queda trackeada en git via `.gitkeep`.