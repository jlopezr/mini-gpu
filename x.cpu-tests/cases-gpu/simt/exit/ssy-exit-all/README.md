# Todas las lanes mueren dentro de la REGION

## Objetivo

Comprueba la terminación global: si `live_mask` llega a cero, el warp termina y
las pilas REGION y PATH quedan vacías.

## Comportamiento esperado

- La divergencia crea un `PATH` con las lanes 4..7.
- Las lanes 0..3 hacen `EXIT`; la normalización selecciona el `PATH`.
- Las lanes 4..7 también hacen `EXIT`: ya no queda ninguna viva.
- El `EXIT` situado en el join no debería llegar a ejecutarse.

## Qué comprueba el `test.json`

- `instructions_executed = 6`: `GETTID`, `MOVI`, `SSY`, `BGE` y los dos `EXIT`.
  Si el warp ejecutase además el `EXIT` del join serían 7.
- `pc = 24`: el PC quedó apuntando al join, pero sin ejecutarlo.
- Terminación limpia, sin `ERROR_SIMT` por pilas sin vaciar.
