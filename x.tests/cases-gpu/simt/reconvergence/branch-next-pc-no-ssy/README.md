# Salto al PC siguiente sin `SSY`

## Objetivo

Un `BEQ R1, R0, next` cuyo destino es la instrucción siguiente, sin ningún `SSY`. No hay divergencia arquitectónica: no se debe abrir REGION ni PATH, y no debe fallar por falta de `SSY`. Es la variante sin `SSY` de [`branch-target-next-pc`](../branch-target-next-pc/).

## Comportamiento esperado

- Solo la lane 0 cumple la condición, pero las dos salidas van al mismo PC: el warp sigue unido.
- Todas las lanes ejecutan `ADDI R3, R3, 1` y `EXIT`: `R3 = 1`.

## Qué comprueba el `test.json`

- `R3 = 1` en las 8 lanes del warp 0 (y lanes 0 y 7 de los demás); 5 instrucciones por warp.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Profundidad máxima medida: 0 REGION y 0 PATH.

Contexto: [README de la categoría](../README.md).
