# `invalid-encoding`

## Objetivo

Una codificación inválida tiene que parar con error `0x05`.

## Comportamiento esperado

- `program.hex` es una sola palabra, `00000001`: un `NOP` con los 26 bits bajos
  distintos de cero. Se carga como `.hex` porque el ensamblador no la
  generaría.
- La CPU para en el propio `pc = 0` con `error_code = 0x05`.

## Qué comprueba el `test.json`

- `halted`, `error`, `error_code` y `pc`; no hay registros ni memoria.
- La regla de `NOP` no ha cambiado entre versiones de la ISA, así que vale en
  todos los backends. Para el campo reservado de los desplazamientos, que sí
  cambió, ver
  [`extensions/shift-immediate/reserved-fields`](../../extensions/shift-immediate/reserved-fields/).
