# `bresenham-circles`

## Objetivo

El algoritmo del punto medio para circunferencias, ejecutado directamente desde
la demo de la 21 y comparado contra un modelo.

## Comportamiento esperado

- Dibuja las seis circunferencias del ejemplo: punto medio, los ocho puntos
  simétricos y tres niveles de llamadas.
- [`bresenham_circles.legacy-19.asm`](bresenham_circles.legacy-19.asm) es la
  variante para la 19 y no se ejecuta.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 1**, parada limpia y sin `underflow`.
- El frame capturado contra `expected/frame.bin`. [`reference.py`](reference.py)
  calcula las circunferencias por separado, no captura la salida del programa.
- `requires`: `frame_capture`, `subword_memory`, `calls` y `mul_div`.
- La secuencia exacta de puntos, sin depender del vídeo, la cubre
  [`programs/bresenham-circles-core`](../../programs/bresenham-circles-core/).

Contexto: [README de la categoría](../README.md).
