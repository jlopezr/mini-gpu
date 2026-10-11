# Barreras por grupo de trabajo

## Objetivo

Lanza 8 warps en dos grupos de trabajo (`workgroup_id` 0 y 1) con programas distintos y máscaras parciales, y comprueba que cada grupo cruza sus dos `BAR` y termina.

## Comportamiento esperado

- Warps 0..3 (grupo 0) arrancan en `pc = 0`: `BAR; MOVI R3, 7; BAR; EXIT`. Warps 4..7 (grupo 1) en `pc = 16`: `BAR; MOVI R4, 9; BAR; EXIT`.
- Los warps pares usan `active_mask = 0xFF` y los impares `0x55`: las lanes inactivas no participan ni escriben.
- Terminan los 8 warps, 4 instrucciones cada uno.

## Qué comprueba el `test.json`

- `R3 = 7` (grupo 0) o `R4 = 9` (grupo 1) en las lanes activas; la lane 7 de los warps impares no escribe nada, porque está enmascarada.
- `pc` final de cada warp (16 y 32) y `active_mask = 0`.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Límite conocido: los dos grupos hacen el mismo número de barreras, así que el caso pasaría igual con una barrera global. Comprueba que `workgroup_id` y los `pc` distintos se aplican y no bloquean; el aislamiento lo prueba [`workgroup-barrier-isolation`](../workgroup-barrier-isolation/).

Contexto: [README de la categoría](../README.md).
