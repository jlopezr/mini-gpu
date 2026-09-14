# Copia de memoria con dos warps

## Objetivo

Comprueba el camino de datos completo (`LOAD` + `STORE`) con dos warps que se
reparten 16 palabras, una por lane.

## Comportamiento esperado

- Cada lane copia la palabra `tid` de `0x100` a `0x180`.
- Los dos warps cubren los 16 índices sin solaparse.

## Qué comprueba el `test.json`

- El volcado de destino coincide con `input.hex`: la copia es completa y
  ninguna lane pisó la palabra de otra.
- El volcado del origen sigue siendo `input.hex`: la copia no lo alteró.
- `instructions_executed` por warp (10) y total (20).
