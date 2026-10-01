# Código y datos en la misma memoria

## Objetivo

Un `STORE` sobre la zona de código cambia la instrucción que se ejecuta después. Prueba que la escritura de la LSU llega a la captura de instrucciones.

## Comportamiento esperado

- `LOAD R2, R0, 0` lee la primera instrucción como dato (`R2 = 0x54400000`).
- `STORE` escribe en la dirección 64 la palabra `0x40E0007B`, que es `MOVI R7, 123`, encima de un `HALT`.
- Tras `BAR`, `BRA modified` aterriza en 64 y ejecuta la instrucción nueva: `R7 = 123`. Si se ejecutara el `HALT` antiguo, `R7` valdría 0.

## Qué comprueba el `test.json`

- `R2`, `R4 = 0x40E0007B` y `R7 = 123` en las lanes 0 y 7 de cada warp; PC final 72.
- Volcado de la palabra en 64 (`expected/memory_40.hex`) = `0x40E0007B`.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
