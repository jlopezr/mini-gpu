# `bresenham-lines`

## Objetivo

El algoritmo de rectas de Bresenham, ejecutado directamente desde la demo de la
21 y comparado contra un modelo.

## Comportamiento esperado

- Compara el primer abanico completo: sus 36 extremos recorren los ocho
  octantes.
- De paso integra llamadas, `MUL`, `STOREH`, RGB565 y doble buffer.
- [`bresenham_lines.legacy-19.asm`](bresenham_lines.legacy-19.asm) es la variante
  para la 19 y no se ejecuta.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 1**, parada limpia y sin `underflow`.
- El frame capturado contra `expected/frame.bin`. [`reference.py`](reference.py)
  calcula las rectas por separado, no captura la salida del programa.
- `requires`: `frame_capture`, `subword_memory`, `calls`, `shift_immediate` y
  `mul_div`.
- La secuencia exacta de puntos, sin depender del vídeo, la cubre
  [`programs/bresenham-lines-core`](../../programs/bresenham-lines-core/).

Contexto: [README de la categoría](../README.md).
