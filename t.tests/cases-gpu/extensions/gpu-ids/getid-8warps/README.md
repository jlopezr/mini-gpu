# `GETID` con 8 lanes y warps no contiguos

## Objetivo

Comprueba la familia `GETID` en la configuración que tiene el RTL: ocho lanes por
warp y varios warps, con el id lógico distinto del slot físico y con valores que
ocupan los 32 bits.

## Comportamiento esperado

- Cuatro warps en los slots 0, 1, 2 y 5, con ids lógicos 11, 10, 9 y `0x80000000`
  y argumentos `0x100`, `0x200`, `0x300` y `0xFFFFFFFF`. Los otros cuatro slots
  quedan apagados.
- Cada hilo (`tid = warp * 8 + lane`) escribe cinco palabras seguidas en
  `4096 + 20 * tid`: `GETTID`, `GETLANE`, `GETWARP`, `GETLWARP`, `GETARG`.
- `GETWARP` es el slot físico (0, 1, 2, 5); `GETLWARP` y `GETARG` los que puso la
  configuración, iguales para las ocho lanes de un warp.

## Qué comprueba el `test.json`

- Volcado de las 240 palabras (`expected/memory_1000.hex`). Se contrastó con un
  cálculo independiente del simulador.
- Registros de las lanes 0 y 7 de cada warp.
- `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador y
  `gpu_system_bl8_tb.v` compara el estado completo del RTL, incluidos los dos
  arrays `LOGICAL_WARP_ID` y `WARP_ARG` releídos por MMIO.

## Notas

`requires: ["gpu_ids"]`. Lo declaran los simuladores y la 29.
