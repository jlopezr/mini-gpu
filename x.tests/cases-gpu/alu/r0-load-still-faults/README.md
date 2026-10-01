# `LOAD R0` sigue accediendo a memoria

## Objetivo

Completa [`r0-hardwired-zero`](../r0-hardwired-zero/). Descartar la escritura a `R0` no elimina los demás
efectos de la instrucción (ISA, «`R0` está cableado a cero»): un `LOAD R0` debe hacer el acceso y poder
fallar.

## Comportamiento esperado

- `MOVHI R5, 0x7fff` deja `R5 = 0x7FFF0000`, fuera de memoria.
- `LOAD R0, R5, 0` termina con `ERROR_MEMORY_ACCESS` (`0x02`) y no escribe nada.
- El `MOVI R3, 1` siguiente no se ejecuta.

## Qué comprueba el `test.json`

- `error = true`, `error_code = 0x02` y el fallo: `pc = 4`, warp 0, lane 0, dirección `0x7FFF0000`.
- 1 instrucción completada y `pc = 4`: la anterior al fallo.
- No lleva `rtl.differential`: el banco diferencial exige que el simulador no termine con error.

Contexto: [README de la categoría](../README.md).
