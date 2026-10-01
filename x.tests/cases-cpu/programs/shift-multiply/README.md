# `shift-multiply`

## Objetivo

Multiplicar sin `MUL`: el algoritmo clásico de sumas y desplazamientos.

## Comportamiento esperado

- Calcula `13 * 11 = 143` (`0x8F`) mirando el bit bajo del multiplicador,
  sumando el multiplicando desplazado cuando vale 1.
- Como no usa `MUL`, corre también en `10.fpga-cpu-ram`.

## Qué comprueba el `test.json`

- `R3 = 0x8F` (el producto), `R1 = 0xD0` (13 desplazado cuatro veces), `R2 = 0` y
  `R4 = 1`; parada limpia en `pc = 0x2C`.
