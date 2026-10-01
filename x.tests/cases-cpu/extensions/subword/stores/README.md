# `stores`

## Objetivo

`STOREB` y `STOREH` tocan solo sus bytes.

## Comportamiento esperado

- El dato se replica en los cuatro carriles de la palabra y es la máscara de byte
  la que elige cuál vale, así que un fallo en la máscara se ve como bytes vecinos
  pisados.
- Por eso dos de las tres palabras de partida son `0xFFFFFFFF`: sobre ceros,
  escribir de más pasaría desapercibido.
- Escribe siempre desde registros con los 32 bits distintos de cero, para
  comprobar también que `STOREB` usa solo `R[7:0]` y `STOREH` solo `R[15:0]`.
- Dos `STOREB` (bytes 1 y 2 de la palabra 0) y dos `STOREH` (mitad baja de la
  palabra 1 y mitad alta de la 2).

## Qué comprueba el `test.json`

- Las palabras se precargan desde [`input.hex`](input.hex) en `0x00100400` y el
  volcado resultante se compara con [`expected.hex`](expected.hex).
- `R2 = 0xAAAAAAAA`, `R3 = 0x12345678` y parada limpia en `pc = 0x2C`.
- `requires: ["subword_memory"]`.

Contexto: [README de la categoría](../../README.md).
