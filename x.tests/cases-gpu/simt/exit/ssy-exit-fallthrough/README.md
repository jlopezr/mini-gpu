# `EXIT` en el camino activo

## Objetivo

Con una REGION abierta, las lanes 4..7 (fall-through) ejecutan `EXIT` mientras las 0..3 esperan en un PATH. Estas siguen y llegan al join.

## Comportamiento esperado

- Las lanes 4..7 mueren y no deben reaparecer al cerrar la REGION: no ejecutan `ADDI R3, R3, 1` del join.
- Las lanes 0..3 hacen `MOVI R3, 7`, llegan al join y terminan con `R3 = 8`.

## Qué comprueba el `test.json`

- `R3 = 8` en las lanes 0..3 y `R3 = 0` en las 4..7, en el warp 0 (y en lanes 0 y 7 de los demás).
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
