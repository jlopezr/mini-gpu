# `simt-demo`

## Objetivo

Divergencia simple: dos caminos por warp, una reconvergencia y una barrera de
workgroup. Es la versión de un solo nivel de [`simt`](../simt/).

## Comportamiento esperado

- `R1 = tid & 7` es la lane dentro del warp.
- `SSY join` marca la reconvergencia; las lanes 0-3 toman `low` (`R3 = 10`) y las
  4-7 siguen de largo (`R3 = 20`).
- Todas suman 1 en `join` (`R3 = 11` o `21`), pasan por `BAR` y terminan con
  `EXIT`.

## Qué comprueba el `test.json`

- Parada limpia sin error y los registros de cada warp (`warps.json`).

Contexto: [README de la categoría](../README.md).
