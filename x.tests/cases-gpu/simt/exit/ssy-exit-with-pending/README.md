# EXIT con caminos pendientes

## Objetivo

Comprueba que si el camino activo hace `EXIT` mientras existen `PATH`
pendientes, la normalización continúa con el siguiente pendiente.

## Comportamiento esperado

- Las lanes 0..3 hacen `EXIT` en el fall-through.
- Queda un `PATH` con las lanes 4..7, que debe seleccionarse a continuación.
- Al cerrar la REGION las lanes muertas no pueden reaparecer.

## Qué comprueba el `test.json`

- `R3 = 99` en las lanes 4..7: el pendiente se ejecutó pese al `EXIT` previo.
- `active_mask = 0` al terminar.
