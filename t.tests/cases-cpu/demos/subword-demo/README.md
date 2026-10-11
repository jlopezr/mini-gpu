# `subword-demo`

## Objetivo

El caso de uso que motiva las instrucciones de 16 bits: pintar un degradado
RGB565 píxel a píxel con `STOREH`.

## Comportamiento esperado

- El framebuffer es RGB565, 320x240 píxeles de dos bytes. Con solo `STORE` de 32
  bits, escribir un píxel obliga a leer la palabra, mezclar la mitad que toca y
  volver a escribirla. Con `STOREH` es una instrucción y no hay lectura.
- Dibuja rojo creciente con `x` y verde creciente con `y`.
- No busca velocidad: los desplazamientos son iterativos (un bit por ciclo) y
  dominan el coste. Lo que enseña es la escritura parcial.
- [`subword_demo.legacy-19.asm`](subword_demo.legacy-19.asm) es la variante para
  la 19 y no se ejecuta.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 2**, parada limpia y sin error.
- El frame capturado contra [`expected/frame.bin`](expected/frame.bin).
- `requires`: `frame_capture` y `subword_memory`.
