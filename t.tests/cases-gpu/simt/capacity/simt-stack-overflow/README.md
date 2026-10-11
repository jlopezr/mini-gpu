# Desbordamiento de la pila REGION

## Objetivo

Comprueba que abrir más regiones de las que caben produce `ERROR_SIMT`
(código 6) sin dejar estado a medias.

## Comportamiento esperado

- Nueve `SSY` consecutivos, todos con el mismo join pero en PCs distintos:
  ninguno es reutilización, así que cada uno necesita un push.
- La pila tiene 8 entradas, luego el noveno falla.

## Qué comprueba el `test.json`

- `error_code = 6`.
- `fault.pc = 32` y `warp[0].pc = 32`: el PC se quedó en el `SSY` que falló.
- `active_mask = 1` intacta e `instructions_executed = 8`: los ocho primeros
  `SSY` se ejecutaron y el noveno no hizo commit parcial.

## Notas

Pareja natural de `ssy-region-overflow`, que fuerza lo mismo con
`simt_region_depth = 1`.
