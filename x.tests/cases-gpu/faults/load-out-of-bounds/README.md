# LOAD fuera del mapa de memoria

## Objetivo

Comprueba que un `LOAD` cuya dirección se sale del mapa produce `ERROR_MEM`
(código 2) sin efectos parciales.

## Comportamiento esperado

- Cada lane calcula `0x02000000 - 12 + tid*4`.
- Las lanes 0..2 leen dentro del mapa; la lane 3 se sale por la dirección
  `0x02000000` y el resto quedaría aún más lejos.
- La instrucción falla antes de escribir ningún destino.

## Qué comprueba el `test.json`

- `error_code = 2` y `fault` con `pc = 28`, `core_id = 3` y `address =
  33554432`: la dirección exacta que provocó el fallo.
- `R5 = 99` en las lanes comprobadas: el `LOAD` no llegó a escribir.
- El volcado de `sentinel.hex` demuestra que la memoria no cambió.
