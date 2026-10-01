# `sysid-reserved`

## Objetivo

Un offset reservado **dentro** de un bloque que sí existe es un error, no un
alias.

## Comportamiento esperado

- `SYSTEM` tiene siete palabras (`mmio.md` v2 §5); la octava no es un alias de
  otra, es un error.
- El programa hace `LOAD` en `MMIO_SYSTEM_BASE + 0x1C`.
- Corre igual en CPU y GPU.

## Qué comprueba el `test.json`

- Parada con error: `error_code = 0x02`.

Contexto: [README de la categoría](../../README.md).
