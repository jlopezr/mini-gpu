# `mulhi-signed`

## Objetivo

`MULHI` devuelve la parte alta del producto **con signo** (`1.isa/isa.md` §3).

## Comportamiento esperado

- El producto de 64 bits que construye el RTL es el *unsigned*: la mitad alta
  con signo necesita una corrección. Sin ella, todos los casos con operandos
  positivos seguirían saliendo bien, por eso casi todos los pares llevan al menos
  un negativo.
- El par más útil es `-1 x -1`: con signo da 1 (parte alta `0x00000000`) y sin
  signo daría `0xFFFFFFFE`.
- `MUL` y `MULHI` van pegados (`0x242D2080` y `0xF8CC93D6` para
  `0x12345678 x 0x9ABCDEF0`): son las dos mitades del mismo producto, y además es
  la secuencia que dispara el camino rápido, que no debe cambiar el resultado.

## Qué comprueba el `test.json`

- Los registros de resultado y parada limpia en `pc = 0x70`.
- `requires: ["alu_extended"]`.

Contexto: [README de la categoría](../../README.md).
