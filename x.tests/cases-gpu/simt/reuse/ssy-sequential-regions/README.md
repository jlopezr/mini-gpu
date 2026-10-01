# Dos REGION seguidas

## Objetivo

Dos `SSY` consecutivos; en cada uno la divergencia manda un grupo de lanes directamente al join. La segunda REGION se abre cuando la primera ya se cerró y la pila vuelve a estar a cero.

## Comportamiento esperado

- Primera REGION: `BLT R1, R2, first` aparca las lanes 0..3 en el join, que es el propio destino.
- Segunda REGION: `BGE R1, R2, second` aparca las lanes 4..7.
- Al final `R3 = 21` en las lanes 0..3 (+20 +1) y `R3 = 11` en las 4..7 (+10 +1).

## Qué comprueba el `test.json`

- `R3` de las 8 lanes del warp 0 y lanes 0 y 7 de los demás; 11 instrucciones por warp.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Profundidad máxima medida: 1 REGION y 0 PATH, como `ssy-fallthrough-is-join`; lo que añade es encadenar dos.

Contexto: [README de la categoría](../README.md).
