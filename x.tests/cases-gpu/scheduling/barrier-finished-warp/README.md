# Un warp terminado no bloquea la barrera

## Objetivo

El warp 1 arranca en el `EXIT` (`pc = 8`) y termina antes de que el warp 0 llegue a su `BAR`; el warp 0 no debe esperar a un warp que ya no puede llegar.

## Comportamiento esperado

- Warp 0: `BAR; MOVI R3, 8; EXIT` (3 instrucciones). Warp 1: solo el `EXIT` (1).
- Los warps 2..7 no se lanzan.

## Qué comprueba el `test.json`

- El warp 0 termina con `R3 = 8` en todas sus lanes: cruzó la barrera.
- 1 instrucción en el warp 1 y 4 en total.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
