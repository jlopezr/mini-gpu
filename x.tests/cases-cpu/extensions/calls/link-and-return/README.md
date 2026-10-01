# `link-and-return`

## Objetivo

Llamada, retorno y anidamiento con `JAL` y `RET`.

## Comportamiento esperado

- `R31` es el registro de enlace por convención, no por hardware, así que una
  llamada dentro de otra lo machaca. `outer` lo salva en memoria antes de llamar
  a `inner` y lo restaura antes de volver: sin eso, su `RET` saltaría a su propia
  llamada anidada y el programa daría vueltas para siempre.
- No hay pila: `R1` apunta a una palabra suelta (`0x00100400`), que es cuanto
  necesita una anidación de un nivel.
- `RET` es un alias de `JR R31`.

## Qué comprueba el `test.json`

- `R11`, `R12`, `R13` (marcas de `outer` e `inner`) y `R20` (se ejecuta al volver
  de `outer`); `R31 = 0x0C`; parada limpia en `pc = 0x14`.
- El volcado de `0x00100400` contra [`expected.hex`](expected.hex): el enlace
  salvado.
- `requires: ["calls"]`.

Contexto: [README de la categoría](../../README.md).
