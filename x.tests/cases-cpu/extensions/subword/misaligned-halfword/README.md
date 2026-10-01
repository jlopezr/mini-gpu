# `misaligned-halfword`

## Objetivo

Una media palabra en dirección impar es un acceso inválido.

## Comportamiento esperado

- El byte no tiene alineación que respetar, pero la media palabra sí, y quien lo
  comprueba es la CPU: es la única que conoce el tamaño del acceso.
- El adaptador de memoria ya no exige dirección múltiplo de cuatro, así que sin
  este trap la petición llegaría al bus partida entre dos palabras.
- El programa hace `LOADH R2, R1, 1` con `R1 = 0x00100400`, o sea la dirección
  impar `0x00100401`.

## Qué comprueba el `test.json`

- Parada con error: `error_code = 0x02`.
- El PC observable queda en la instrucción culpable, no en la siguiente:
  `pc = 0x08`. `R2` sigue en 0.
- `requires: ["subword_memory"]`.

Contexto: [README de la categoría](../../README.md).
