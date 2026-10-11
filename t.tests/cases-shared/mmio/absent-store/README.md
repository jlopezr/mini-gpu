# `absent-store`

## Objetivo

El mismo caso que [`absent-load`](../absent-load/), en escritura: tampoco se
descarta en silencio.

## Comportamiento esperado

- El programa hace `STORE` a `MMIO_TIMER_BASE`, un bloque sin dispositivo.
- Corre igual en CPU y GPU.

## Qué comprueba el `test.json`

- Parada con error: `error_code = 0x02`.

Contexto: [README de la categoría](../../README.md).
