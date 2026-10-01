# `remainder-signs`

## Objetivo

`DIV`, `DIVU`, `REM` y `REMU`: las cuatro combinaciones de signo, y *unsigned*
frente a *signed* sobre el mismo patrón de bits.

## Comportamiento esperado

La regla: el resto acompaña a una división truncada hacia cero, así que lleva el
signo del **dividendo**, no el del cociente ni el del divisor
(`rem = a - (a/b)*b`).

| Operación | Cociente | Resto |
|---|---|---|
| `7 / 2` | 3 | 1 |
| `-7 / 2` | -3 | -1 |
| `7 / -2` | -3 | 1 |
| `-7 / -2` | 3 | -1 |

Los dos de en medio separan esta regla de la otra convención posible (resto con el
signo del divisor, o módulo matemático), que daría 1 y -1 en lugar de -1 y 1.

Cada `DIV` va seguido de su `REM`, que es como lo emite el código real y lo que
dispara el camino rápido; los últimos bloques mezclan el orden a propósito.

## Qué comprueba el `test.json`

- Los registros de cociente y resto de cada bloque y parada limpia en
  `pc = 0x84`.
- `requires: ["alu_extended"]`.

Contexto: [README de la categoría](../../README.md).
