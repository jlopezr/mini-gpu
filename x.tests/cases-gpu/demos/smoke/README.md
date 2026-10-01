# `smoke`

## Objetivo

Prueba mínima de placa: dos instrucciones y **cero** accesos a memoria de datos.
Sirve para partir el problema en dos cuando la placa no hace nada.

## Comportamiento esperado

- `MOVI R1, 7`, `BAR` y `HALT`.
- `R1 = 7`: el fetch funciona (el búfer de instrucciones sirve la línea, la GPU
  arranca con `RUN` y para con `HALT`). Si esto va y [`vector`](../vector/) no, el
  problema está en la LSU o el camino de datos.
- `R1 = 0`: no se ha ejecutado nada. Hay que mirar antes el bitstream: tiene que
  ser el de `_build/default` (`top_bl8`). Si es el arnés de timing
  (`lsu_timing_top`) no hay ni UART ni GPU.

## Qué comprueba el `test.json`

- Parada limpia sin error, 1000 instrucciones como máximo y el estado de cada
  warp según [`warps.json`](warps.json).

Contexto: [README de la categoría](../README.md).
