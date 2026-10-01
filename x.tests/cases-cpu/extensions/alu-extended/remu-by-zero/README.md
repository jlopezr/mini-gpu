# `remu-by-zero`

## Objetivo

`REMU` con divisor cero para con `ERROR_DIVISION_BY_ZERO`, igual que `REM`.

## Comportamiento esperado

- Va en un caso aparte del de [`rem-by-zero`](../rem-by-zero/) porque los dos
  recorren ramas distintas del RTL: `REMU` no pasa los operandos por la negación
  condicional. Un arreglo que solo cubriera la rama con signo pasaría el otro caso
  sin enterarse.
- El programa carga `R1 = 7`, `R2 = 0` y ejecuta `REMU R3, R1, R2`.

## Qué comprueba el `test.json`

- Parada con error: `error_code = 0x04`.
- El PC observable queda en la instrucción culpable, la tercera: `pc = 0x08`.
- `requires: ["alu_extended"]`.

Contexto: [README de la categoría](../../README.md).
