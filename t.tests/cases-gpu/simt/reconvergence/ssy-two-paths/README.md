# Dos PATH en una misma REGION

## Objetivo

Comprueba dos divergencias sucesivas dentro de una única REGION antes de
alcanzar el join.

## Comportamiento esperado

- La primera divergencia aparca las lanes 6..7.
- La segunda aparca las lanes 3..5.
- El fall-through (lanes 0..2) llega al join y se consumen los dos pendientes.

## Qué comprueba el `test.json`

- `R3` por lane vale `10, 10, 10, 20, 20, 20, 30, 30`: los tres grupos
  ejecutaron bloques distintos y ninguno se mezcló.
