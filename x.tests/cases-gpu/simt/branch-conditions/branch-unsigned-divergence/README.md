# `BLTU` y `BGEU` con divergencia

## Objetivo

Cubre lo que [`branch-bltu`](../branch-bltu/) y [`branch-bgeu`](../branch-bgeu/) no pueden: que la
comparación sin signo **diverja**. Comparan `R1 = (tid & 7) - 4` (de −4 a 3) con `R2 = 2` en vez de con
`R0`, y cada salto abre su propio `SSY`.

## Comportamiento esperado

- `BLTU R1, R2`: sin signo, los valores "negativos" (lanes 0..3) son enormes y no son menores que 2. Solo
  saltan las lanes 4 y 5 (`R1` = 0 y 1): `R3 = 7` ahí y `R3 = 3` en el resto. Con `BLT` saltarían las lanes 0..5.
- `BGEU R1, R2`: saltan las lanes 0..3, 6 y 7 (`R4 = 7`) y no las 4 y 5 (`R4 = 3`). Con `BGE` solo saltarían la 6 y la 7.
- Los dos saltos reconvergen en su join y el warp termina con `HALT`.

## Qué comprueba el `test.json`

- `R3` y `R4` de las 8 lanes del warp 0 (`R3 = 3,3,3,3,7,7,3,3` y `R4 = 7,7,7,7,3,3,7,7`) y de las lanes 0 y 7
  de los demás warps.
- 15 instrucciones por warp (120 en total), que solo salen si hay divergencia en los dos saltos: se ejecutan
  las dos ramas de cada uno.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
