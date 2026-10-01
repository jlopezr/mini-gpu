# Visibilidad de memoria tras `BAR`

## Objetivo

Cada hilo escribe su `tid` en memoria, cruza una barrera de los 8 warps y lee lo que escribió el hilo opuesto (`tid ^ 63`). Sin la barrera la lectura podría ver memoria vieja.

## Comportamiento esperado

- El hilo `t` guarda `t` en `4096 + 4t`; tras `BAR` carga la palabra de `63 − t`.
- Al terminar, `R5 = 63 − t` en el hilo `t`, tanto si el opuesto está en su warp como en otro.

## Qué comprueba el `test.json`

- `R5` y `R4` de las lanes 0 y 7 de cada warp.
- Volcado de las 64 palabras de `4096..4351` (`expected/memory_1000.hex`): `mem[i] = i`.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
