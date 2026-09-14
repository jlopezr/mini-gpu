# Dos SSY distintos con el mismo join

## Objetivo

Comprueba que dos `SSY` en PCs distintos crean dos REGION distintas aunque
apunten al mismo join: la reutilización exige mismo PC, no mismo destino.

## Comportamiento esperado

- Se abren dos regiones consecutivas hacia el mismo `join`.
- Los `BGE` son uniformes (`R1 < 8` en todas las lanes), así que ninguno diverge.
- Las dos regiones se cierran ordenadamente al llegar al join.

## Qué comprueba el `test.json`

- `instructions_executed = 8` y `pc = 32`: no hubo caminos extra que ejecutar.
- `R2 = R3 = 8` en las ocho lanes y `active_mask = 0`.
