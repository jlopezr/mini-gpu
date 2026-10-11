# `swap-smoke`

## Objetivo

Comprobación mínima del doble buffer desde la CPU. No dibuja nada: ejercita el
camino completo CPU → registros de vídeo.

## Comportamiento esperado

1. Fija `FB_FRONT = 0x01000000` y `FB_BACK = 0x01025800` (un frame más arriba).
   Tras el reset las dos bases valen cero, así que el framebuffer es una
   decisión del programa.
2. Enciende el scanout con `VIDEO_CTRL = 2`; tras el reset el modo es `PATTERN`.
3. Lee `FB_FRONT` y `FB_BACK`, escribe `SWAP = 1` y espera a que el hardware lo
   aplique al empezar el frame siguiente.
4. Vuelve a leer: `FB_FRONT` tiene que valer lo que valía `FB_BACK`, y al revés.

Es el programa que corre `cpu_video_tb.v`. La versión larga (`swap_demo`) escribe
38 400 palabras por frame y en simulación no termina en un tiempo razonable.
[`swap_smoke.legacy-16-18-19.asm`](swap_smoke.legacy-16-18-19.asm) es la variante
para las placas viejas y no se ejecuta.

## Qué comprueba el `test.json`

- `R1 = R4 = 0x01000000` y `R2 = R3 = 0x01025800`, es decir, bases
  intercambiadas; `R7 = 1`; parada limpia en `pc = 76` y sin `underflow`.
- `requires: ["video"]`.
