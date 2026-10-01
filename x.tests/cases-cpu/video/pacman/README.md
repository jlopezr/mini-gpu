# `pacman`

## Objetivo

Un programa largo y con estado corriendo millones de instrucciones sin
desviarse. Es el único caso de vídeo **sin frame esperado**.

## Comportamiento esperado

- Una demo que se juega sola: Pac-Man busca pastillas con un recorrido en
  anchura sobre la rejilla y cuatro fantasmas se mueven al azar.
- Unas 1 400 instrucciones de código, con llamadas anidadas, pila propia,
  accesos sub-palabra y `REMU`.
- El logo se incrusta con `.incbin` desde
  [`1.isa/minigpu-small.bin`](../../../../1.isa/minigpu-small.bin) (150 KB, RGB565
  320x240). [`render_logo.asm`](render_logo.asm) es un programa auxiliar que solo
  pinta ese logo.
- No tiene `expect.frame` a propósito: un `reference.py` sería una segunda
  implementación completa del juego, y fallaría la sincronía entre las dos.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 300**, parada limpia, sin error y sin `underflow`.
- `requires`: `frame_capture`, `subword_memory`, `calls`, `shift_immediate` y
  `alu_extended`; hasta 8 millones de instrucciones.
- Los fallos que encontró al escribirse (un temporal pisado en una rutina de
  dibujo, sprites sin borrar tras una colisión) están contados en el
  [README de la categoría](../README.md).
