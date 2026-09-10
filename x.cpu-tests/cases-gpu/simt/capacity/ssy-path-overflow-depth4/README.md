# Desbordamiento de la pila PATH

## Objetivo

Comprueba que una divergencia que necesita reservar un `PATH` con la pila llena
produce `ERROR_SIMT` (código 6) de forma atómica.

## Comportamiento esperado

- Con `simt_path_depth = 4`, las cuatro primeras divergencias llenan la pila.
- La quinta también necesita push y debe fallar.

## Qué comprueba el `test.json`

- `error_code = 6`.
- `fault.pc = 44` y `warp[0].pc = 44`: el `BGE` que desborda no avanzó el PC.
- `active_mask = 15`: la máscara tampoco se partió, es decir que el fallo
  ocurrió antes de cualquier commit.

## Notas

Usa `simulator_options.simt_path_depth = 4`. Pareja de
`ssy-path-full-direct-join`.
