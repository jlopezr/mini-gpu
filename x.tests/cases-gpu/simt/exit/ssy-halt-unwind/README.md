# `HALT` con dos REGION abiertas

## Objetivo

Abre dos REGION anidadas (`SSY outer; SSY inner`) y ejecuta `HALT` sin que nadie haya divergido: al morir todas las lanes se deshacen las dos pilas y no se ejecuta nada más.

## Comportamiento esperado

- El `MOVI R3, 99` de `outer` no se ejecuta.
- Cada warp ejecuta 3 instrucciones (`SSY`, `SSY`, `HALT`) y termina con `pc = 12`.

## Qué comprueba el `test.json`

- `R3 = 0` en las 8 lanes del warp 0 (y lanes 0 y 7 de los demás).
- `pc = 12` y `active_mask = 0`.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
