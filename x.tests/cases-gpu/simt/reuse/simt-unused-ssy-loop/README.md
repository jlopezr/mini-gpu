# SSY repetido sin divergencia

## Objetivo

Comprueba que reejecutar el mismo `SSY` (mismo PC, mismo join) reutiliza la
REGION del top en vez de consumir otra entrada de la pila.

## Comportamiento esperado

- El bucle da 9 vueltas y vuelve siempre al mismo `SSY`.
- Nunca hay divergencia, así que la REGION nunca llega a usarse.
- Con 8 entradas de pila, 9 pushes distintos darían `ERROR_SIMT`.

## Qué comprueba el `test.json`

- Terminación sin error: hubo reutilización, no acumulación.
- `R1 = 9` en la lane 0 y `R1 = 0` en la lane 7 (inactiva).
- `instructions_executed = 30`.

## Notas

Arranca con `active_mask = 1`. Complementa a `ssy-region-full-reuse`, que
prueba la misma regla con la pila deliberadamente llena.
