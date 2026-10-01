# Palabra en `0x1FFFC`

## Objetivo

Todos los hilos guardan 77 en `0x1FFFC` y lo releen tras una barrera. Es la última palabra de 128 KiB.

## Comportamiento esperado

- En un prototipo solo con BRAM (12) es la última palabra direccionable: un error de límite en el decodificador de direcciones daría `ERROR_MEMORY_ACCESS`.
- En los prototipos con SDRAM (32 MiB) y en los simuladores es una palabra más, justo debajo de la marca de 128 KiB; sirve para comprobar que no hay un efecto de borde ahí.
- Los 64 hilos escriben el mismo valor en la misma palabra.

## Qué comprueba el `test.json`

- `R1 = 0x1FFFC`, `R2 = 77` y `R3 = 77` (la relectura) en las lanes 0 y 7 de cada warp.
- Volcado de la palabra en `0x1FFFC` (`expected/memory_1fffc.hex`) = 77.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

No declara `large_memory`: esa capacidad es para accesos *por encima* de 128 KiB y este queda dentro.

Contexto: [README de la categoría](../README.md).
