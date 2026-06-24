# Modelos - notas y candidatos

Sin ranking inventado. Medir primero, decidir despues.

## Candidatos iniciales

| Modelo | Cuant esperada | Por que esta en la lista | Riesgo en 16 GB RAM |
|---|---|---|---|
| Gemma 4 12B | Q4_K_M o Q4_0 | Candidato principal para uso personal | Medir RAM peak antes de declarar default |
| Qwen3-14B | Q4_K_M | Rival generalista / coding; soporte thinking/no-thinking | Verificar calidad en espanol |
| Phi-4 14B | Q4 | Razonamiento + codigo, alternativa si los dos anteriores pesan | Verificar VRAM/RAM |

Modelos mas grandes (Devstral, Mistral Small 24B) **fuera** del MVP por probabilidad alta de saturar 16 GB.

## Que medir (mismos prompts para todos)

Definidos en `benchmarks/prompts_es.json` (10 prompts en espanol):

- resumen corto / resumen largo
- auditoria tecnica de un fragmento de codigo
- explicacion simple
- tarea de coding
- razonamiento logico
- planificacion diaria
- respuesta larga controlada
- correccion de texto
- analisis critico

## Que registrar (por corrida)

La app ya guarda en `benchmarks/results/<label>-<timestamp>.json` y `.md`:

- timestamp, label
- backend activo (incluye si fue MOCK)
- modelo: nombre, path, cuant detectada, tamano disco
- modo (cpu/vulkan), gpu_layers, contexto, threads, temp, top-p, repeat penalty
- comando exacto lanzado al backend
- hardware: RAM total/disponible antes y despues, RSS backend antes/despues, peak UI
- wall time total
- por prompt: elapsed (s), char_count, tokens_per_sec proxy (chars/4 / seg)
- prompt completo y respuesta (recortada si >4000 chars)

Tokens/s es **proxy** (1 token ~= 4 chars). Para numeros exactos hay que parsear stdout de llama.cpp (`eval time`, `tokens evaluated`).

## Criterio de decision

- Si **Gemma 4 12B Q4_K_M** entra comodo en 16 GB y responde aceptablemente rapido -> candidato principal.
- Si Gemma satura RAM o es lento -> probar Qwen3-14B.
- Si ambos pesan demasiado -> Phi-4 14B, o bajar a 7B/8B.
- **No declarar "mejor modelo" sin medicion local.**

## Calidad vs backend

Vulkan/offload GPU **no cambia la inteligencia del modelo**.
La calidad depende de:
- el modelo base
- la cuantizacion
- los parametros de sampling (temp, top-p, repeat penalty)
- el template de chat (si el modelo lo trae)

Si un modelo responde mal en CPU, respondera igual (o peor) en Vulkan con la misma cuantizacion. Vulkan solo cambia throughput/latencia.