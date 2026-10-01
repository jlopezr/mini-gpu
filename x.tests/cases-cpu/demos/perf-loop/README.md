# `perf-loop`

## Objetivo

El bucle interior de `swap_demo_fast`, aislado para medir ciclos.

## Comportamiento esperado

- 160 iteraciones, que son una línea de framebuffer: `STORE` de un color en cada
  palabra, avanzando el puntero y el contador.

## Qué comprueba el `test.json`

- `R3 = R25 = 160`, `R6 = 0x00010280` (el puntero tras 160 palabras desde
  `0x00010000`) y `R13 = 0x1234`; parada limpia en `pc = 36`.
- `requires: ["large_memory"]` y un máximo de 1290 instrucciones.
