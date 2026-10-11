# `registers`

## Objetivo

La ventana de registros de vídeo desde un programa. No dibuja nada. Es el único
caso de vídeo que usa solo los cuatro registros que existen desde la 16, así que
**corre también allí**; por eso `video` y `frame_capture` son capacidades
distintas.

## Comportamiento esperado

- `FB_FRONT` y `FB_BACK` conservan las direcciones que se escriben y se alinean a
  16 bytes.
- `SWAP` intercambia las dos bases en lugar de copiar una sobre la otra.
- `STATUS` permite leer `UNDERFLOW`.
- Espera a que `SWAP` deje de estar pendiente antes de comprobar, así no depende
  del instante del frame en que se pidió. A propósito **no** comprueba que
  quede pendiente justo después: caería en un intervalo de microsegundos cada
  16,7 ms y el caso fallaría una de cada mil.

## Qué comprueba el `test.json`

- `R1 = R4 = 0x01000000`, `R2 = R3 = 0x01025800`, `R5 = 0x01100000` y
  `R6 = 0` (sin `underflow`).
- `requires: ["video"]`. El backend de placa devuelve las bases a sus valores de
  reset antes de cada ejecución, así que el caso verifica que se leen y se
  intercambian, no el valor de encendido.

Contexto: [README de la categoría](../README.md).
