# `loads`

## Objetivo

Las seis cargas sub-palabra sobre la misma palabra, `0xBEEFAA78`.

## Comportamiento esperado

- Cada tamaño se lee dos veces, con y sin signo, y en una posición donde el bit
  alto vale uno y en otra donde vale cero. Así ninguna pareja de opcodes puede
  pasar el caso por coincidencia.
- La memoria es *little-endian*: el byte 0 de la palabra es `0x78` y el 3 es
  `0xBE`.
- `LOADUB` en una dirección impar de byte es legal.
- Una carga `LOAD` de la palabra entera, sin extender nada.

## Qué comprueba el `test.json`

- La palabra se precarga desde [`input.hex`](input.hex) en `0x00100400`.
- `R2`-`R11`: `LOADUB`/`LOADB` (`0xAA` → `0x000000AA` / `0xFFFFFFAA`),
  `LOADUH`/`LOADH` (`0xBEEF` → `0x0000BEEF` / `0xFFFFBEEF`), etc. Parada limpia
  en `pc = 0x34`.
- `requires: ["subword_memory"]`.

Contexto: [README de la categoría](../../README.md).
