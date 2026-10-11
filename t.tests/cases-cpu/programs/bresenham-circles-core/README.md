# `bresenham-circles-core`

## Objetivo

El algoritmo de círculos de punto medio aislado del vídeo: sin framebuffer ni
pantalla, solo la secuencia de puntos que emite. Si falla aquí, el fallo es del
algoritmo y no de la cadena de vídeo.

## Comportamiento esperado

- Centro en `(32, 32)`. Cada radio ocupa 512 bytes a partir de `0x00100000`:
  una palabra con el número de puntos y después la secuencia exacta que emite la
  simetría de ocho.
- Usa una subrutina (`JAL R31, circle`), por eso necesita `calls`.

## Qué comprueba el `test.json`

- Parada limpia en `pc = 0x9C` y el volcado de `0x00100000` contra
  [`expected.hex`](expected.hex).
- `requires: ["calls", "shift_immediate"]`.
- `expected.hex` lo calcula [`reference.py`](reference.py) por otro camino, y la
  suite lo regenera sola si falta.
- La versión con vídeo del mismo algoritmo es
  [`video/bresenham-circles`](../../video/bresenham-circles/).
