# `xorshift`

## Objetivo

Un generador pseudoaleatorio xorshift32 como prueba de integración de `XOR` y
desplazamientos en bucle.

## Comportamiento esperado

- Semilla `0x12345678`. Cada iteración hace `x ^= x << 13; x ^= x >> 17;
  x ^= x << 5` y guarda el resultado en `0x00100200`. Son diez valores.
- Usa solo el núcleo de la ISA (`XOR` y `SHL`/`SHR` con registro), sin la
  extensión `shift_immediate`, para que corra en cualquier CPU del repo.

## Qué comprueba el `test.json`

- `R1 = 0x3AB14B11` (el último valor), `R2 = 0x00100228` y `R3 = 0`; parada
  limpia en `pc = 0x4C`.
- El volcado de `0x00100200` contra [`expected.hex`](expected.hex).
