# `sysid-write`

## Objetivo

Las siete palabras de `SYSTEM` son de **solo lectura**: escribir una da error.

## Comportamiento esperado

- El programa hace `STORE` en `MMIO_SYSTEM_BASE + MMIO_SYSTEM_SYSTEM_ID_OFF`.
- Corre igual en CPU y GPU.

## Qué comprueba el `test.json`

- Parada con error: `error_code = 0x02`.

Contexto: [README de la categoría](../../README.md).
