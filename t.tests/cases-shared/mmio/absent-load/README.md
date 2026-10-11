# `absent-load`

## Objetivo

Un bloque MMIO **sin dispositivo** da error, no cero (`mmio.md` v2 §4.3).

## Comportamiento esperado

- En la v1 esto era "una ranura de 256 bytes vacía dentro de la página"; en la v2
  es un bloque entero del mapa que este prototipo no implementa.
- El programa hace `LOAD` desde `MMIO_TIMER_BASE`.
- Corre igual en CPU y GPU (`"architecture": ["cpu", "gpu"]`).

## Qué comprueba el `test.json`

- Parada con error: `error_code = 0x02`.

Su equivalente en escritura es [`absent-store`](../absent-store/).

Contexto: [README de la categoría](../../README.md).
