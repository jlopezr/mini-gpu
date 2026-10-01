# `EXIT` en el camino que salta

## Objetivo

Lo mismo pero al revés: mueren las lanes 0..3, que son las que saltan a `low`; las 4..7 siguen por el fall-through y llegan al join.

## Comportamiento esperado

- Las lanes 0..3 ejecutan `EXIT` desde su PATH y no vuelven.
- Las lanes 4..7 hacen `MOVI R3, 7`, el join y acaban con `R3 = 8`.

## Qué comprueba el `test.json`

- `R3 = 0` en las lanes 0..3 y `R3 = 8` en las 4..7, en el warp 0 (y lanes 0 y 7 de los demás).
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
