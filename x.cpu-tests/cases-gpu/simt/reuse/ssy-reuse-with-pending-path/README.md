# Reutilizar el SSY con un PATH pendiente

## Objetivo

Comprueba que reejecutar el `SSY` del top mientras existe un `PATH` pendiente
reutiliza la REGION sin perder ese pendiente.

## Comportamiento esperado

- La primera divergencia aparca las lanes 4..7 como `PATH`.
- El fall-through vuelve al mismo `SSY` varias vueltas.
- El `PATH` pendiente debe seguir ahí cuando el bucle termine.

## Qué comprueba el `test.json`

- `R3 = 4` en las lanes 0..3: el bucle completó sus vueltas.
- `R4 = 99` en las lanes 4..7: el `PATH` pendiente sobrevivió a las
  reejecuciones del `SSY` y se ejecutó al final.
- `R4 = 0` en las lanes 0..3 y `R3 = 0` en las 4..7: ningún grupo ejecutó el
  bloque del otro.
