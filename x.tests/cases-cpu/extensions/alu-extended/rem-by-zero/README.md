# `rem-by-zero`

## Objetivo

`REM` con divisor cero para con `ERROR_DIVISION_BY_ZERO`, igual que `DIV`.

## Comportamiento esperado

- El resto no tiene más definición que la división que lo acompaña, así que no
  hay nada que devolver cuando la división no existe. `REM` hereda la regla de
  trap arquitectónico de la división por cero, sin excepciones.
- El programa carga `R1 = 7`, `R2 = 0`, un `NOP` y `REM R3, R1, R2`.

## Qué comprueba el `test.json`

- Parada con error: `error_code = 0x04`.
- El PC observable queda en la instrucción culpable, la cuarta: `pc = 0x0C`.
- `requires: ["alu_extended"]`.

Su pareja para `REMU` es [`remu-by-zero`](../remu-by-zero/).

Contexto: [README de la categoría](../../README.md).
