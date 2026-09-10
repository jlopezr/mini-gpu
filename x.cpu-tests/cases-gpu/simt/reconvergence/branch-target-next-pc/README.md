# Destino de salto igual a PC+4

## Objetivo

Comprueba que si el destino tomado de un `BGE` coincide con la instrucción
siguiente no hay divergencia arquitectónica, aunque el predicado difiera entre
lanes. La región abierta por `SSY` debe cerrarse sin haber reservado un `PATH`.

## Comportamiento esperado

- `BGE R1, R2, next` evalúa distinto en las lanes 0..3 y 4..7.
- Los dos destinos posibles son el mismo PC, así que la máscara no se parte.
- Las ocho lanes ejecutan `MOVI R3, 55` juntas.

## Qué comprueba el `test.json`

- `R3 = 55` en las ocho lanes: ninguna se quedó aparcada en un camino.
- `active_mask = 0` y ausencia de error al terminar.
