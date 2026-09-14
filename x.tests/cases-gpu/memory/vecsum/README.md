# Suma de vectores

## Objetivo

Caso funcional completo: 16 lanes repartidas en dos warps calculan
`C[i] = A[i] + B[i]`.

## Comportamiento esperado

- Cada lane carga `A[tid]` y `B[tid]`, suma y escribe `C[tid]`.
- Ninguna lane diverge.

## Qué comprueba el `test.json`

- El volcado de `C` coincide con `expected.hex`.
- Los volcados de `A` y `B` siguen intactos.
- Los 32 registros de las 16 lanes y los contadores por warp.
