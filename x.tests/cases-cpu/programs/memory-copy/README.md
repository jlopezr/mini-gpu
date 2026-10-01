# `memory-copy`

## Objetivo

`LOAD` y `STORE` en bucle: copiar un bloque de memoria.

## Comportamiento esperado

- Copia seis palabras de `0x00100400` a `0x00100500`. El origen se precarga desde
  [`input.hex`](input.hex).
- Al final relee la última palabra copiada con `LOAD R6, R2, -4`, un
  desplazamiento negativo.

## Qué comprueba el `test.json`

- Los dos punteros terminan en `0x00100418` y `0x00100518`, el contador en 0, y
  `R5 = R6 = 0xDEADBEEF`; parada limpia en `pc = 0x38`.
- El volcado del destino es el mismo `input.hex`: la copia tiene que ser exacta.
