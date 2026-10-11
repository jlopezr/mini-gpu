# `fullframe`

## Objetivo

Un dibujo mínimo a resolución completa, escrito para que el banco de RTL pueda
simularlo hasta el final.

## Comportamiento esperado

- Pinta una «L» azul (la línea de arriba y la columna de la izquierda) y un
  cuadrado blanco fijo, y pide el intercambio. En bucle.
- Son 912 palabras por frame. Repintar el fondo entero serían 38 400 palabras
  (~1,35 M de ciclos), decenas de segundos por frame en `iverilog`; el fondo se
  queda como lo deja el modelo de SDRAM, todo ceros.
- La «L» no es simétrica a propósito: un marco completo se ve igual si alguien
  intercambia los ejes.
- El cuadrado no se mueve, para que el frame esperado no dependa de cuántos
  intercambios haya habido.
- [`fullframe_tb.asm`](fullframe_tb.asm) es la misma imagen con las bases bajas,
  para el banco de RTL.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 2**, parada limpia y sin `underflow` de vídeo.
- `requires: ["frame_capture"]`.
