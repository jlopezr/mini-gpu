# TRAP detiene toda la GPU

## Objetivo

Comprueba que `TRAP` produce `ERROR_TRAP` (código 3) y detiene todos los warps,
no solo el que la ejecuta.

## Comportamiento esperado

- Los dos warps arrancan en `pc = 0` y ejecutan `NOP`.
- El primero en llegar a `TRAP` levanta el fallo global.

## Qué comprueba el `test.json`

- `error_code = 3` y `fault` con `pc = 4` y `warp_id = 0`.
- Ambos warps quedan en `pc = 4` con una única instrucción ejecutada: el
  segundo warp no siguió avanzando tras el `TRAP` del primero.
- `instructions_executed = 2` en total.
