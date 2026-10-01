# Bucle con SSY y un número de vueltas por lane

## Objetivo

Un `SSY` dentro de un bucle donde cada lane sale tras `tid & 7` vueltas. Similar a [`ssy-loop-reuse`](../ssy-loop-reuse/), pero la salida es `BEQ R1, R0, done` (con `R1` decreciente) y el contador es `R3`.

## Comportamiento esperado

- Cada vuelta re-ejecuta el `SSY` de la cima de la pila: se reutiliza la REGION.
- La lane `t` hace `t` vueltas y sale; al final `R3 = t`.

## Qué comprueba el `test.json`

- `R3` de las 8 lanes del warp 0 (`0..7`) y lanes 0 y 7 de los otros warps; 41 instrucciones por warp.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
