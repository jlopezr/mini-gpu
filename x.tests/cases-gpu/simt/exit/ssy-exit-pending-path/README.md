# EXIT desde un PATH seleccionado

## Objetivo

Distinto de `ssy-exit-with-pending`: aquí quien ejecuta el `EXIT` es el `PATH`
ya seleccionado. Comprueba que esas lanes salen de `live_mask` y no reaparecen
al cerrar la REGION.

## Comportamiento esperado

- El fall-through (lanes 0..3) escribe `R3 = 11` y llega al join.
- La normalización selecciona el `PATH` con las lanes 4..7.
- Esas lanes escriben `R3 = 22` y ejecutan `EXIT`.
- Al cerrar la REGION solo pueden restaurarse las lanes vivas.

## Qué comprueba el `test.json`

- `R3 = 11` en las lanes 0..3 y `R3 = 22` en las 4..7: ambos bloques se
  ejecutaron una vez.
- `active_mask = 0`: las lanes muertas dentro del `PATH` no volvieron a
  activarse al restaurar la máscara de la REGION.
