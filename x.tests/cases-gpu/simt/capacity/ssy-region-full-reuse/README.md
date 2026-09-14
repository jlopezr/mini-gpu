# REGION llena pero SSY reutilizable

## Objetivo

Comprueba la regla especial: una pila REGION llena no impide reutilizar el
`SSY` que ya está en el top, porque esa operación no necesita hacer push.

## Comportamiento esperado

- Con `simt_region_depth = 1` la pila se llena con el primer `SSY`.
- El bucle vuelve a ese mismo `SSY` en cada vuelta.
- Si el simulador rechazara la operación por tener la pila llena, el caso daría
  `ERROR_SIMT` en la segunda vuelta.

## Qué comprueba el `test.json`

- Terminación sin error con la profundidad reducida.
- `R2 = 3` en las ocho lanes: el bucle completó sus tres vueltas.
- `instructions_executed = 18`.

## Notas

Usa `simulator_options.simt_region_depth = 1`, así que solo puede ejecutarse
con `--backend gpu-simulator`. Pareja de `ssy-region-overflow`.
