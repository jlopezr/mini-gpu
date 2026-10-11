# `multiply`

## Objetivo

El caso más corto posible de `MUL`: `10 * 20 = 200`.

## Comportamiento esperado

- `R1 = 10`, `R2 = 20`, `R3 = MUL(R1, R2) = 200`, y `HALT`.

## Qué comprueba el `test.json`

- `R1`, `R2` y `R3`, y parada limpia en `pc = 0x10`.
- Declara `requires: ["mul_div"]`. `MUL` es base de la MiniISA, pero
  `10.fpga-cpu-ram` no tiene multiplicador, y ahí el caso se omite con `SKIP`.
  El porqué está en el [README de la categoría](../README.md).
