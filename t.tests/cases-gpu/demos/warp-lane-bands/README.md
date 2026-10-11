# `warp-lane-bands`

## Objetivo

Patrón de diagnóstico warp/lane: hace visible de un vistazo que arrancaron los
ocho warps, que participan las ocho lanes, y dónde empieza y acaba cada uno.

## Comportamiento esperado

- Pinta 320x240 RGB565 en `0x01000000`. Cada warp pinta una banda horizontal de
  30 filas (`30w .. 30w+29`, 19 200 bytes consecutivos) con su color base; dentro
  de la banda, cada lane pinta un escalón de intensidad (las palabras de índice
  `l`, `l+8`, `l+16`...).
- Solo escribe RAM. No toca MMIO: el framebuffer y el scanout los configura la
  CPU o el monitor desde fuera.
- Warp y lane salen de `GETTID` (`warp = tid >> 3`, `lane = tid & 7`). Se escribió
  primero con `GETWARP` y `GETLANE`, de la propuesta v0.2, que nunca llegaron a
  tener opcode.
- Es capability **Base**, salvo `MUL`/`DIV` (de ahí `requires: ["mul_div"]`).

## Qué comprueba el `test.json`

- Parada limpia sin error, hasta 40 000 instrucciones.
- El volcado de `0x01000000` contra [`expected.bin`](expected.bin) (150 KB). Lo
  calcula [`reference.py`](reference.py) por otro camino, y la suite lo regenera
  sola si falta.

Contexto: [README de la categoría](../README.md).
