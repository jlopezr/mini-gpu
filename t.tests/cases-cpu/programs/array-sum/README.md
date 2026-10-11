# `array-sum`

## Objetivo

Recorrer un array con un acumulador: bucle con `LOAD`, `ADD` y un contador que
decrece hasta cero.

## Comportamiento esperado

- Suma cinco palabras que empiezan en `0x00100300` (cargadas desde
  [`input.hex`](input.hex)): `0xFFFFFFFF`, `1`, `0x7FFFFFFF`, `0x80000000` y `5`.
- La suma desborda 32 bits y da `4`: el caso también comprueba que el
  acarreo se descarta sin error. Se guarda en `0x00100340`.

## Qué comprueba el `test.json`

- `R2 = 0` (contador agotado), `R3 = 4` (la suma con desbordamiento) y `R5 = 5`
  (la última palabra leída), y parada limpia en `pc = 0x38`.
- El volcado de `0x00100340` contra [`expected.hex`](expected.hex).
