# División por cero

## Objetivo

Comprueba que un `DIV` por cero en una sola lane produce `ERROR_DIV` (código 4)
y que el fallo es atómico: ninguna lane del warp llega a escribir el resultado.

## Comportamiento esperado

- `R2 = 3 - tid`, luego la lane 3 de cada warp divide por cero.
- `R4` vale 99 antes del `DIV`.
- La instrucción falla antes de hacer commit en ninguna lane.

## Qué comprueba el `test.json`

- `error_code = 4` y `fault` con `pc = 20`, `warp_id = 0`, `core_id = 3`:
  identifica la lane culpable.
- `R4 = 99` en las lanes comprobadas: el `DIV` no escribió nada.
- `active_mask = 255` y `pc = 20` en ambos warps: el PC no avanzó.

## Notas

Dos warps activos, ambos con las ocho lanes.
