# El fall-through es el propio join

## Objetivo

Caso especial `PC+4 == join`: la máscara del fall-through se aparca sin
reservar un `PATH`.

## Comportamiento esperado

- `BGE` parte las lanes; el camino no tomado cae directamente en el join.
- Esas lanes se aparcan en la REGION, no en la pila `PATH`.
- Las lanes 4..7 ejecutan el bloque `taken` y reconvergen.

## Qué comprueba el `test.json`

- `R3 = 77` solo en las lanes 4..7: las lanes 0..3 nunca ejecutaron ese bloque.
- Terminación sin error con la pila equilibrada.
