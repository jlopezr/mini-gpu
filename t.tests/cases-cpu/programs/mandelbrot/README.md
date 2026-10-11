# `mandelbrot`

## Objetivo

Un caso largo y determinista, sin E/S ni vídeo en tiempo real, para comparar el
CPI entre versiones con `--measure`.

## Comportamiento esperado

- Es una versión reducida de `1.isa/mandelbrot.asm`: mismo algoritmo, misma
  región del plano complejo y mismo `MAX_ITER`, pero a **64x48** en vez de
  320x240, para que `expected.hex` quepa en el repo.
- Aritmética en coma fija Q16.16. Escribe una palabra por píxel (el número de
  iteraciones, no un color) desde `0x00100000`.

## Qué comprueba el `test.json`

- `R1 = 0x40`, `R2 = 0x30` (las dimensiones), `R13 = 0x00103000` (fin del
  framebuffer) y parada limpia en `pc = 0xC4`.
- El volcado de `0x00100000` contra [`expected.hex`](expected.hex).
- `requires: ["mul_div"]`, y límites holgados (5 millones de instrucciones,
  30 s).
