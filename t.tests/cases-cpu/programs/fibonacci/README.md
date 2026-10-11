# `fibonacci`

## Objetivo

Un bucle con dependencia entre iteraciones: cada término depende de los dos
anteriores.

## Comportamiento esperado

- Genera los diez primeros términos de Fibonacci (0, 1, 1, 2, 3, 5, 8, 13, 21,
  34) y los guarda en `0x00100200`.

## Qué comprueba el `test.json`

- `R1 = 0x37` (55) y `R2 = 0x59` (89), los dos términos siguientes a los
  guardados, `R3` apuntando justo después de la tabla y `R4 = 0`; parada limpia
  en `pc = 0x38`.
- El volcado de `0x00100200` contra [`expected.hex`](expected.hex).
