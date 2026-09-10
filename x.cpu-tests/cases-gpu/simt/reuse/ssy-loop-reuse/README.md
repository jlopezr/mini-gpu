# Reutilización del SSY en un bucle

## Objetivo

Comprueba que un bucle que vuelve al mismo `SSY` reutiliza la REGION en vez de
crear una nueva en cada vuelta.

## Comportamiento esperado

- Cada lane itera hasta su propio límite `R1 = 100 + tid`.
- Las lanes salen del bucle en vueltas distintas, así que la REGION se usa de
  verdad, pero el `SSY` es siempre el mismo PC.

## Qué comprueba el `test.json`

- `R3 = R1 = 100 + tid` en las ocho lanes: cada una hizo exactamente el número
  de vueltas que le tocaba y todas reconvergieron.
- Terminación sin `ERROR_SIMT`, que es lo que ocurriría si cada vuelta empujara
  una REGION nueva.
