# `vector`

## Objetivo

Prueba mínima del camino de **datos**: cada hilo escribe un valor propio en su
propia palabra de memoria y lo vuelve a leer. Es el escalón siguiente a
[`smoke`](../smoke/), que no toca memoria.

## Comportamiento esperado

- Cada hilo usa la dirección `4096 + tid*4`: una palabra distinta por hilo y
  ninguna colisión. Las 8 lanes de un warp caen en 32 bytes consecutivos, el caso
  **coalescido**, que la LSU v2 resuelve en 2 transacciones de 16 bytes.
- Al acabar, el hilo `t` deja `R5 = t + 100` (lo que acaba de escribir y releer)
  y `R3` su dirección. Si `R5` no coincide con `R4`, el dato no viaja bien.
- Diagnóstico: `smoke` va y `vector` no → el fallo está en la LSU o la SDRAM, no
  en el fetch. Van los dos → camino completo vivo, ya se puede pasar a `bench`.
- [`vector.legacy-12-14-17.asm`](vector.legacy-12-14-17.asm) es la variante para
  las placas viejas y no se ejecuta.

## Qué comprueba el `test.json`

- Parada limpia sin error y los registros finales de cada warp (`warps.json`).
- Lleva `rtl.differential` con `warp_config` de 8 warps: `tools/make_rtl_fixtures.py` lo ejecuta así en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL. El caso, en cambio, se prueba con los 2 warps de `warps.json`.

Contexto: [README de la categoría](../README.md).
