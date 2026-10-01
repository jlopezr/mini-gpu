# `HALT` en un camino y `EXIT` en el otro

## Objetivo

Con una REGION abierta, las lanes 4..7 ejecutan `HALT` y las 0..3 `EXIT`: no queda ninguna lane viva antes de llegar al join.

## Comportamiento esperado

- El warp termina sin ejecutar `ADDI R3, R3, 1` del join ni la `BAR` posterior.
- Cada warp ejecuta 7 instrucciones.

## Qué comprueba el `test.json`

- `R3 = 0` en las 8 lanes del warp 0 (y lanes 0 y 7 de los demás): el join no se ejecutó.
- `pc` final 32 y `active_mask = 0`.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
