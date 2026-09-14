# path_base de una REGION anidada

## Objetivo

Comprueba que una REGION interior abierta mientras existe un `PATH` exterior
pendiente no consume ese camino: el `path_base` separa ambas capas.

## Comportamiento esperado

- La divergencia exterior aparca las lanes 4..7.
- El fall-through abre una REGION interior y vuelve a divergir.
- Al cerrar la interior solo deben consumirse sus propios `PATH`; el exterior
  tiene que seguir pendiente.

## Qué comprueba el `test.json`

- `R4` vale `10, 10, 20, 20, 0, 0, 0, 0`: solo las lanes 0..3 entraron en la
  región interior, y allí se repartieron correctamente.
- `R5` vale `30` en las lanes 0..3 y `40` en las 4..7: el `PATH` exterior
  sobrevivió al cierre de la región interior y se ejecutó después.
- `instructions_executed = 16`.

## Notas

Con `--trace-detail` se comprueba que el `PATH` exterior queda por debajo del
`path_base` de la región interior.
