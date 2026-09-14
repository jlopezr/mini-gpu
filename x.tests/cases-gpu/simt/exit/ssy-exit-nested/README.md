# EXIT dentro de una REGION anidada

## Objetivo

Comprueba el filtrado por `live_mask` al restaurar máscaras cuando las lanes
mueren dentro de la región interior.

## Comportamiento esperado

- La divergencia exterior aparca las lanes 4..7.
- Dentro de la región interior, las lanes 0..1 ejecutan `EXIT` y las 2..3 toman
  el camino `inner_b`.
- Al cerrar cada REGION la máscara restaurada debe filtrarse por `live_mask`.

## Qué comprueba el `test.json`

- `R4` vale `0, 0, 44, 44, 88, 88, 88, 88`: las lanes 0..1 murieron antes de
  escribir nada, las 2..3 ejecutaron el camino interior y las 4..7 el exterior.
- Que las lanes 0..1 sigan a 0 demuestra que no reaparecieron al cerrar la
  región interior ni la exterior.
- `instructions_executed = 14`.
