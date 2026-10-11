# Accesos de 8 y 16 bits con 64 hilos

## Objetivo

Ejercita los seis accesos pequeños (`STOREB`, `STOREH`, `LOADB`, `LOADUB`,
`LOADH`, `LOADUH`) en el caso que el RTL tiene que resolver bien: **varias lanes
del mismo warp escribiendo bytes o mitades distintas de la misma palabra**, y
lecturas de otro warp que ven lo que escribió el hilo opuesto.

## Comportamiento esperado

- `STOREB`: el hilo `t` escribe `5t + 0x7C` (solo `R[7:0]`) en `b[t]`. Cuatro
  lanes consecutivas comparten palabra y ninguna pisa a las vecinas. Los valores
  cruzan `0x80`, así que hay bytes con el bit de signo a uno y a cero.
- `LOAD` de la palabra que contiene `b[t]`: ve los cuatro bytes juntos.
- Tras `BAR`, el hilo `t` lee `b[63 - t]` con `LOADUB` (ceros) y con `LOADB`
  (signo).
- `STOREH` y `LOADUH`/`LOADH` repiten lo mismo con mitades `t * 0x451 + 0x7F00`,
  que cruzan `0x8000`.

Mapa, todo dentro de `4096..6143`: `0x1000` `b[64]`, `0x1100` bytes sin signo,
`0x1200` bytes con signo, `0x1300` `h[64]`, `0x1400` mitades sin signo, `0x1500`
mitades con signo, `0x1600` la palabra que contiene `b[t]`.

## Qué comprueba el `test.json`

- Volcado de las 448 palabras (`expected/memory_1000.hex`), contrastado con un
  cálculo independiente del simulador.
- Registros de las lanes 0 y 7 de cada warp.
- `rtl.differential`: el banco de la 29 compara con esto el estado completo.

## Notas

`requires: ["subword_memory"]`. Lo declaran los simuladores y la 29.
