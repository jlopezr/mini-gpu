# Máxima ocupación de la pila PATH

## Objetivo

Alcanza la ocupación simultánea máxima posible con ocho lanes: siete `PATH`
pendientes dentro de una sola REGION.

## Comportamiento esperado

- Siete divergencias consecutivas separan una lane cada vez.
- La máscara activa evoluciona `FF -> 7F -> 3F -> 1F -> 0F -> 07 -> 03 -> 01`.
- Después se consumen los pendientes en orden inverso hasta reconverger.

## Qué comprueba el `test.json`

- `R2` por lane, que identifica en qué divergencia se separó cada una.
- `instructions_executed = 32`, total y por warp.
- `active_mask = 0` al final: todas las lanes llegaron al join.

## Notas

Con `--trace-detail` se observa la secuencia completa de máscaras.
