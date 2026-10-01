# `text-console-demo`

## Objetivo

Demo de la consola de texto 80x30 del prototipo 30.

## Comportamiento esperado

- Muestra texto sobre el patrón de vídeo, **sin usar SDRAM**.
- Programa la paleta (`PALETTE[1]` naranja CPC, `[2]` cian, `[15]` blanco) y
  escribe celdas de texto directamente en la ventana de vídeo
  (`0x80200000`). Por ejemplo, `MINIGPU 2D` en la fila 12, columna 30, con
  `FG = 1` y `BG = 0`: la dirección de celda es
  `TEXT + 4 * (12*80 + 30) = 0x6F78`.

## Por qué no hay `test.json`

Es una demo para mirar a ojo en la placa, y la capa de texto es propia del
prototipo 30. (No he comprobado si el simulador modela esa capa ni si la captura
de frame de los demás casos la incluye, así que no sé si podría ser un caso.)

Contexto: [README de la categoría](../README.md).
Su pareja con movimiento es [`text-scroll-demo`](../text-scroll-demo/).
