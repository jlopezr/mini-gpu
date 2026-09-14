# if/else con un PATH

## Objetivo

Caso básico de divergencia con trabajo en ambos lados antes del join. Debe
crearse exactamente un `PATH`.

## Comportamiento esperado

- `BGE` parte `FF` en fall-through `0x0F` y camino tomado `0xF0`.
- El camino tomado se aparca como `PATH`; primero se ejecuta el fall-through.
- Al llegar al join se selecciona el `PATH` pendiente.

## Qué comprueba el `test.json`

- `R3 = 11` en las lanes 0..3 y `R3 = 22` en las 4..7: cada mitad ejecutó su
  bloque y solo el suyo.
- `R1 = tid` en las ocho lanes.
