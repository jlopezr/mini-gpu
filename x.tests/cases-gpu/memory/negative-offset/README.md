# LOAD y STORE con desplazamiento negativo

## Objetivo

Cubrir un fallo del RTL de la 29: `lsu_address` sumaba `d_rf_a + {8{imm}}` como
UN solo numero de 256 bits, y el acarreo de la lane n entraba en la lane n+1.
Con un desplazamiento negativo el inmediato extendido en signo es `0xFFFFFFxx`,
asi que casi cualquier suma acarrea, y cada lane recibia un byte de mas del
acarreo de la anterior: direcciones desalineadas y fallo de memoria.

Los simuladores nunca lo vieron porque suman por lane en Python. Hasta ahora
ningun caso usaba un desplazamiento negativo.

## Que hace

Un warp de ocho lanes con la base en `0x0200`:

- `STORE` con `-256`: `OUT[tid] = tid + 1` en `0x0100`.
- `LOAD` con `-192`: lee `IN[tid]` desde `0x0140`.
- `STORE` con `-128`: `COPY[tid] = IN[tid]` en `0x0180`.

## Que comprueba el `test.json`

- Sin error ni fallo, 9 instrucciones.
- `R5` y `R6` de las lanes 0 y 7.
- Los volcados de `OUT` y `COPY`.

Antes del arreglo debe fallar en el RTL de la 29 (y en la 36 anterior a
`5728e81`); en los simuladores pasa siempre.
