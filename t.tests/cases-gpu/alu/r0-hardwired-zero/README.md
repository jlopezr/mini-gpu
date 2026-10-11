# `R0` cableado a cero

## Objetivo

Comprueba por separado el contrato de `R0` (ISA §«R0 está cableado a cero»): una escritura se descarta sea cual sea la instrucción que la hace y las lecturas valen siempre 0.

## Comportamiento esperado

- `MOVI R0, 77` no cambia nada: `ADDI R1, R0, 5` da `R1 = 5`.
- `ADD R0, R6, R6` tampoco: `ADD R2, R0, R6` da `R2 = R6 = 1234`.
- `LOAD R0, R5, 0` lee la palabra (1234) y descarta el resultado: `ADD R3, R0, R0 = 0`.
- `SUB R0, R0, R6` (que daría −1234) tampoco escribe: `R4 = 0`.

## Qué comprueba el `test.json`

- `R0`, `R3` y `R4` valen 0 y `R1 = 5`, `R2 = 1234` en las lanes 0 y 7 de cada warp.
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Que `LOAD R0` *haga el acceso* (y por tanto pueda fallar) lo comprueba
[`r0-load-still-faults`](../r0-load-still-faults/). La GPU no tiene `JALR` (`calls` es solo de CPU), así
que la otra mitad del contrato (`JALR R0` salta) no aplica.

Contexto: [README de la categoría](../README.md).
