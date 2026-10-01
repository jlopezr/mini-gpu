# `smoke`

## Objetivo

Prueba de humo: lo mínimo que tiene que funcionar para que el resto de casos
signifique algo. El propio `.asm` lo presenta como `fpga_smoke_test.asm`.

## Comportamiento esperado

- `MOVI` y `ADD`: `10 + 20 = 30`.
- `STORE`/`LOAD` en `0x00100100` y vuelta a un registro.
- Escribe `0x00000A41` en `0x00100200` (bytes `41 0A`, un `A` y un salto de
  línea), para probar la comparación de volcados con un contenido reconocible.
- `HALT`.

## Qué comprueba el `test.json`

- `R1`-`R7` y parada limpia en `pc = 0x30`.
- El volcado de `0x00100200` contra [`expected/result.hex`](expected/result.hex).
