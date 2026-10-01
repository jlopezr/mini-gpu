# `fpga-smoke-test`

## Objetivo

La prueba de humo que se carga en la placa para ver que CPU, memoria y monitor
están vivos. Comparte el mapa global entre la CPU y el monitor.

## Comportamiento esperado

- `MOVI`, `ADD` (`10 + 20 = 30`), `STORE` en `0x00100010`, `LOAD` y `HALT`.

## Qué comprueba el `test.json`

- `R1`-`R5` y parada limpia en `pc = 32`.
- `requires: ["large_memory"]`, porque escribe por encima de `0x00100000`.
- Es la versión de placa; la de la suite, que además vuelca memoria, es
  [`basics/smoke`](../../basics/smoke/).
