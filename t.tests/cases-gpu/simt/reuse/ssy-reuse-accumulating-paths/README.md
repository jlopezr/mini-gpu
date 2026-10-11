# Reutilización de REGION acumulando PATH

## Objetivo

Bucle con `SSY` donde en cada vuelta una lane más cumple `R1 == 0` y se desvía a `handler`: la pila de PATH crece hasta 7 mientras la REGION se reutiliza una y otra vez. Combina lo que [`ssy-reuse-with-pending-path`](../ssy-reuse-with-pending-path/) (1 PATH) y [`ssy-all-paths`](../../capacity/ssy-all-paths/) (7 PATH sin bucle) prueban por separado.

## Comportamiento esperado

- Cada lane acaba ejecutando `handler` (`+10`) y `done` (`+1`).
- Cada vuelta separa una lane más (la que llega a `R1 == 0`) y las ocho reconvergen en `done`.

## Qué comprueba el `test.json`

- `R3 = 11` en las 8 lanes del warp 0 y en las lanes 0 y 7 de los demás; 50 instrucciones por warp.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Profundidad máxima medida en el simulador funcional: 1 REGION y 7 PATH.

Contexto: [README de la categoría](../README.md).
