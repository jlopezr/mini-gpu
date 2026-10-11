# `bounce`

## Objetivo

Un cuadrado rebotando en los cuatro bordes. Cubre lo que una banda horizontal no
puede: errores de pitch, los bordes y las escrituras parciales de línea.

## Comportamiento esperado

- El cuadrado se pinta encima del fondo ya escrito y ocupa 16 palabras de las
  160 de una línea, lo que obliga al búfer de combinación de escrituras a volcar
  y empezar línea en cada pasada.
- Repinta el fondo entero en cada frame, a propósito: así un fallo de
  contabilidad no se confunde con uno del hardware.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 80**: a esas alturas ya ha rebotado en los dos ejes
  (`y` en el paso 52 y `x` en el 72) y el cuadrado ha dejado la diagonal, así que
  el caso distingue un eje del otro.
- El frame capturado contra `expected/frame.bin`, que calcula
  [`reference.py`](reference.py).
- `max_instructions: 20000000`: son 80 repintados completos, unos 12,5 millones
  de instrucciones.

Contexto: [README de la categoría](../README.md).
