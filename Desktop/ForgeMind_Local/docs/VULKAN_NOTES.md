# Vulkan en AMD Radeon RX550 (4 GB) - notas

## TL;DR

Vulkan **no cambia la inteligencia** del modelo. Solo cambia el backend de cómputo. Si un modelo responde mal en CPU, respondera igual (o peor) en Vulkan con la misma cuantizacion.

En hardware Radeon RX550 4 GB, la mejora esperable es marginal y depende mucho del modelo. CPU es el modo base confiable.

## Lo que la app hace

- Detecta GPUs via WMI (`Win32_VideoController`).
- Detecta si `vulkan-1.dll` esta presente (carga via `ctypes.WinDLL`).
- Si `vulkaninfo` esta instalado, intenta leer `--summary`.
- Reporta todo en la pestana `AMD / Vulkan`. **No afirma que Vulkan mejore nada.**
- Si Vulkan falla, se vuelve a CPU sin romper la app.

## Como habilitar Vulkan experimental

1. Descargar build Vulkan de llama.cpp:
   - `llama-bXXXX-bin-win-vulkan-x64.zip` desde GitHub releases.
2. Verificar que el binario detecta tu GPU:
   ```powershell
   llama-cli --version
   # Si lista "Vulkan" en capabilities, OK.
   ```
3. En la UI:
   - Pestana `Modelo`: modo = `vulkan`, gpu_layers > 0 (o dejar en 999 para offload total).
   - Pestana `Backend`: usar `llama_cli` o `llama_server` de la build Vulkan.
4. Medir. Comparar contra corrida CPU. **No creer el marketing.**

## Limitaciones esperables en RX550 4 GB

- VRAM 4 GB. Modelos 12B-14B Q4_K_M no entran enteros en GPU; cae a partial offload.
- Bandwidth de memoria de la RX550 es modesta vs GPUs modernas.
- Ganancia real vs CPU en esta maquina: probablemente 0-30% en t/s, y a veces **negativa** por overhead de copia.

Si el partial offload te da latencia peor que CPU puro: volver a `mode=cpu`, `gpu_layers=0`.

## Diagnostico rapido

- Revisar pestana `AMD / Vulkan`: que diga `vulkan_dll_present=True`.
- Si no aparece Vulkan en el summary de llama.cpp, la build no incluye soporte.
- Si `--vulkan` falla al cargar el modelo, probar `gpu_layers=10` (offload parcial minimo).

## Que NO prometer

- "Vulkan acelera inferencia X%". Falso hasta que se mida.
- "Vulkan mejora la calidad". Falso. La calidad es del modelo + cuantizacion.
- "Si Vulkan falla, hay que reinstalar drivers". Raramente necesario; primero verificar build.