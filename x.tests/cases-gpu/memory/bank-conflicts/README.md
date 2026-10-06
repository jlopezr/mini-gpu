# Acceso con stride de 32 bytes

## Objetivo

Cada hilo accede a `4096 + 32·tid`: las 8 lanes de un warp caen en 8 bloques de 32 bytes distintos, sin ninguna coalescencia. Es el caso opuesto a [`demos/vector`](../../demos/vector/), donde las 8 lanes comparten bloque.

## Comportamiento esperado

- Cada hilo guarda `tid + 123` en su dirección y lo relee: `R5 = tid + 123`.
- En una LSU con bancos o con transacciones de 16 bytes es el peor patrón de acceso.

## Qué comprueba el `test.json`

- `R3` (dirección), `R4` y `R5` de las lanes 0 y 7 de cada warp.
- Volcado de `4096..6143` (512 palabras, `expected/memory_1000.hex`): una palabra no nula cada 8.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).

Lleva initial_memory a cero sobre la zona que vuelca: escribe una palabra de cada ocho y compara el resto con ceros, y en la placa la SDRAM no se inicializa, así que dependía de lo que hubiera dejado el caso anterior.
