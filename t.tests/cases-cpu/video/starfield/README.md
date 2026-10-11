# `starfield`

## Objetivo

El campo de estrellas de la 21, repintando el fondo entero en cada frame. Aporta
dos cosas que los Bresenham no.

## Comportamiento esperado

- **`DIV` con dividendo negativo**, 256 veces por frame y repartido por la
  pantalla. La proyección es `160 + x/z` con `x` de signo cualquiera. Truncar
  hacia menos infinito en vez de hacia cero desplaza un píxel las estrellas de la
  mitad izquierda y de la superior, y solo esas.
- **Estado que sobrevive entre frames**: es el único caso de vídeo cuyo frame N no
  se puede calcular sin los N-1 anteriores. La `z` de cada estrella se acumula y
  las reapariciones consumen tiradas del PRNG, lo que fija también el contrato
  del xorshift.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 40**, parada limpia y sin `underflow`.
- El frame capturado contra `expected/frame.bin`, que calcula
  [`reference.py`](reference.py).
- `requires`: `frame_capture`, `subword_memory`, `calls`, `shift_immediate` y
  `mul_div`.
- Su pareja con borrado incremental es [`starfield-fast`](../starfield-fast/),
  que compara contra este mismo frame.

Contexto: [README de la categoría](../README.md).
