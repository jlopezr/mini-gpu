# `unaligned-target`

## Objetivo

Un destino indirecto desalineado **no** para la CPU.

## Comportamiento esperado

- `JALR` y `JR` toman el destino de un registro, que el programa puede haber
  dejado en cualquier byte. La CPU descarta los dos bits bajos en vez de abrir una
  quinta ruta de error: el fetch queda siempre alineado sin ensanchar el mapa de
  códigos de error.
- Aquí `JR` a `0x0E` salta a la palabra `0x0C`.
- El `MOVI` de `0x08` es el testigo: si el salto fuera a otro sitio, o no
  saltara, `R2` acabaría escrito.

## Qué comprueba el `test.json`

- `R1 = 0x0E`, `R2 = 0` (el testigo no se ejecutó) y `R3 = 0xC0` (el destino
  real); parada limpia en `pc = 0x14`.
- `requires: ["calls"]`.

Contexto: [README de la categoría](../../README.md).
