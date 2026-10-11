# `logic-immediates`

## Objetivo

`ANDI`, `XORI` y `ORI` extienden el inmediato con **ceros**, no con signo
(`1.isa/isa.md`). Es la regla que más fácil se implementa al revés.

## Comportamiento esperado

- Con `R1 = 0xFFFFFFFF`, `ANDI R2, R1, 0xFFFF` da `0x0000FFFF` y
  `XORI R3, R1, 0xFFFF` da `0xFFFF0000`. Con extensión de signo saldrían
  `0xFFFFFFFF` y `0x00000000`.
- `ORI` completa `0x12345678` sobre un `MOVHI`.
- `XOR` registro-registro: el complemento a 1 (`0xEDCBA987`), `a XOR a = 0` y
  `XORI` con 0 como identidad.

## Qué comprueba el `test.json`

- `R1`-`R8` con los valores de arriba y parada limpia en `pc = 0x28`.
- No lleva `requires`: la cumplen todas las implementaciones.
