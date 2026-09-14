# BAR situada en el join

## Objetivo

Comprueba que una instrucción situada en el join no se ejecuta hasta que
termina la normalización de la REGION: `BAR` debe ver las lanes ya
reconvergidas, no la máscara parcial del primer camino que alcanza ese PC.

## Comportamiento esperado

- La divergencia crea un `PATH` con las lanes 4..7.
- Cuando el fall-through salta al join, el PC llega ahí, pero `normalize()` se
  ejecuta antes del siguiente fetch y selecciona el `PATH` pendiente.
- Solo tras consumir el pendiente se cierra la REGION y se hace fetch de `BAR`,
  ya con `active_mask = live_mask = 0xFF`.

## Qué comprueba el `test.json`

- `instructions_executed = 10`: `BAR` se ejecuta **una sola vez**. Si se
  ejecutara una vez por camino divergente serían 11.
- Que no haya error es la comprobación clave: `BAR` con máscara parcial daría
  `ERROR_BARRIER`, como demuestra `ssy-bar-partial-mask`.
- `R3 = 11 / 22` por mitades.
