# `fastpath-miss`

## Objetivo

Medir en la placa lo que ahorra el camino rápido de `DIV`/`REM` de la 21: mitad
**con fallo**. Va en pareja con [`fastpath-hit`](../fastpath-hit/), que es el
mismo fichero con un solo carácter distinto: allí el `REM` lee `R2` y aquí lee
`R3`.

## Comportamiento esperado

- `R2` y `R3` valen los dos 3, así que el resultado y las 4004 instrucciones
  son los mismos que en `hit`.
- Como la etiqueta del camino rápido guarda el **número** de registro, un `REM`
  que lee otro registro no acierta y repite la división entera.
- La resta de los contadores de las dos versiones es el ahorro.

## Qué comprueba el `test.json`

- Resultado funcional idéntico al de `hit`: `R1 = 30000`, `R2 = R3 = 3`,
  `R5 = 10000`, parada limpia en `pc = 36`.
- `requires: ["alu_extended"]`.
