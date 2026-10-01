# `trap`

## Objetivo

`TRAP` es una parada explícita por error, con su propio código.

## Comportamiento esperado

- `program.asm` es solo `TRAP`.
- La CPU para en `pc = 0` con `error_code = 0x03`.

## Qué comprueba el `test.json`

- `halted`, `error`, `error_code` y `pc`.
- El nombre interno del caso es `explicit-trap`.
