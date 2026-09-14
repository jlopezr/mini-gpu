# BAR con máscara parcial

## Objetivo

Comprueba la regla de barreras del simulador: `BAR` exige que participen todas
las lanes vivas, de modo que alcanzarla dentro de un camino divergente produce
`ERROR_BARRIER` (código 7).

## Comportamiento esperado

- La divergencia deja el fall-through con `active_mask = 0x0F` mientras
  `live_mask` sigue siendo `0xFF`.
- `BAR` se alcanza con esa máscara parcial.

## Qué comprueba el `test.json`

- `error_code = 7`.
- `fault.pc = 16` y `warp[0].pc = 16`: la barrera no avanzó el PC.
- `active_mask = 15`: la máscara con la que se detectó la violación.

## Notas

Contrapunto de `ssy-bar-at-join`, donde la misma barrera es legal porque se
alcanza ya reconvergida.
