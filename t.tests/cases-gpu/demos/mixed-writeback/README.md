# `mixed-writeback`

## Objetivo

Que convivan warps que cargan de memoria con warps que solo calculan, de modo que
el write-back del banco de registros reciba a la vez resultados de la LSU y de la
ALU.

## Comportamiento esperado

- Los warps 0 a 3 (`tid < 32`) entran en un bucle de 32 `LOAD` de la misma
  dirección; los warps 4 a 7 en un bucle de 256 sumas.
- El salto es **uniforme dentro de cada warp**, así que no hace falta `SSY`.

## Qué comprueba el `test.json`

- Parada limpia sin error, hasta 1000 instrucciones, y los registros y el
  contador de instrucciones de cada warp (`warps.json`).

Contexto: [README de la categoría](../README.md).
