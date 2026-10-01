# `bresenham-lines-core`

## Objetivo

El algoritmo de rectas de Bresenham aislado del vídeo: sin framebuffer, solo la
secuencia de puntos que genera.

## Comportamiento esperado

- Cada recta ocupa una ranura de 128 bytes a partir de `0x00100000`: primero el
  número de puntos y después cada punto como `(y << 16) | x`.
- Las rectas cubren: un punto único, horizontales y verticales en los dos
  sentidos, y un representante de cada octante, todos desde `(8, 8)`.
- Usa una subrutina (`JAL R31, drawline`), por eso necesita `calls`.

## Qué comprueba el `test.json`

- Parada limpia en `pc = 0x1A8` y el volcado de `0x00100000` contra
  [`expected.hex`](expected.hex).
- `requires: ["calls", "shift_immediate"]`.
- `expected.hex` lo calcula [`reference.py`](reference.py) por otro camino, y la
  suite lo regenera sola si falta.
- La versión con vídeo del mismo algoritmo es
  [`video/bresenham-lines`](../../video/bresenham-lines/).
