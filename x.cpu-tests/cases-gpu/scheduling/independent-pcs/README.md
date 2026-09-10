# PCs independientes por warp

## Objetivo

Comprueba que cada warp mantiene su propio PC y su propio contador de
instrucciones, y que un warp que termina antes no arrastra a los demás.

## Comportamiento esperado

- El warp 0 arranca en `pc = 0` y ejecuta `MOVI R1, 11` + `HALT`.
- El warp 3 arranca en `pc = 8` y ejecuta `MOVI R1, 22`, `ADDI` y `HALT`.
- El warp 1 no está configurado y no debe ejecutar nada.

## Qué comprueba el `test.json`

- `R1 = 11` en el warp 0 y `R1 = 23` en el warp 3: cada uno siguió su camino.
- `instructions_executed` por warp (2 y 3) y total (5).
- El warp 1 queda con `pc = 0` e `instructions_executed = 0`.
