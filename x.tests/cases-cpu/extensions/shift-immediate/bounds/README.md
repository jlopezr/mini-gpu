# `bounds`

## Objetivo

`SHLI`, `SHRI` y `SARI`: los bordes de la cantidad y el modo aritmético.

## Comportamiento esperado

- Opción B de `propuesta-v0.2.md` §4.2: no hay opcodes nuevos. `SHL`, `SHR` y
  `SAR` siguen siendo R-Type y el bit 10 del campo `extra` dice que la cantidad
  es inmediata, tomándola de los cinco bits del campo `Rb`.
- Cantidad 0 (no da ni un paso) y 31 (el otro borde), sobre `R1 = 0x89ABCDEF`,
  que es negativo.
- `R4` vale 17 a propósito. Los desplazamientos de 4 usan el **campo**, no el
  registro número 4, y con `R4 = 4` un multiplexor al revés «funcionaría» igual.
  Con `R4 = 17`, si el camino inmediato leyera el registro, el resultado saldría
  desplazado 17.

## Qué comprueba el `test.json`

- Los registros de cada desplazamiento y parada limpia en `pc = 0x58`.
- `requires: ["shift_immediate"]`. En un bitstream sin ella el bit 10 sigue
  reservado y el programa para con `0x05`, no con `0x01`; el `SKIP` evita esa
  confusión.

Contexto: [README de la categoría](../../README.md) y
[`reserved-fields`](../reserved-fields/).
