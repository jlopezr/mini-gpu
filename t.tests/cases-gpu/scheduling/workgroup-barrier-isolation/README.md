# Aislamiento de las barreras por grupo

## Objetivo

Comprueba que una `BAR` solo espera a los warps de **su** grupo de trabajo. Completa
[`workgroup-barriers`](../workgroup-barriers/), que pasaría igual con una barrera global.

## Comportamiento esperado

- Grupo 0 (warps 0..3, `pc = 0`): cruza una `BAR`, escribe `7` en `4096` y termina.
- Grupo 1 (warps 4..7, `pc = 20`): gira leyendo `4096` hasta que no sea 0, y solo entonces ejecuta su `BAR`.
- Con barreras por grupo, el grupo 0 cruza su `BAR` sin esperar al 1, levanta la bandera y el grupo 1 sigue.
- Con una barrera global la `BAR` del grupo 0 esperaría a unos warps que esperan a esa `BAR`: no termina.
  Comprobado en el simulador con los 8 warps en un solo grupo: agota el límite de instrucciones.

## Qué comprueba el `test.json`

- Parada limpia sin error, `R3 = 7` en el grupo 0, `R4 = 9` y `R6 = 7` (la bandera leída) en el grupo 1.
- 5 instrucciones en cada warp del grupo 0. De los del grupo 1 **no** se cuentan: las vueltas de espera
  dependen del planificador.
- No lleva `rtl.differential` por lo mismo: el diferencial compara contadores de instrucciones exactos.

## Por qué la espera va en una región `SSY`

La primera versión del caso esperaba la bandera con `LOAD` + `BEQ R6, R0, wait` sin más, y **fallaba en la
placa (`fpga-gpu`) con la suite completa**: `error_code 0x06` (`ERROR_SIMT`) con los warps 4..7 parados en
el `BEQ`. Solo, o en su carpeta, pasaba; en el simulador y en el diferencial de RTL tampoco fallaba.
Medido el 2026-11-05 con apio (monitor 3.12) y con el bitstream del 2026-10-08.

Era una carrera del propio programa, no un fallo del hardware:

- Un `LOAD` de warp son ocho lecturas separadas. Los ocho carriles leen la misma dirección (`4096`),
  que cae en un solo banco, y el LSU sirve **un carril por banco y por ola**
  ([`gpu_lsu.v`](../../../../12.fpga-gpu/gpu_lsu.v)): hacen falta ocho olas en ciclos distintos.
- Si el `STORE` del grupo 0 cae en medio, unos carriles leen `0` y otros `7` (`R6 = 0` en los carriles
  0..5 y `R6 = 7` en el 6 y el 7). El `BEQ` diverge dentro del warp y, sin región `SSY` abierta, el SM
  levanta `ERROR_SIMT` (`gpu_sm.v`, rama `FINISH` con `sp == 0`).
- En el simulador el `LOAD` es atómico, así que el warp ve la bandera entera a `0` o entera a `7`.
- Que fallara solo en la suite dependía del ciclo exacto en que el `STORE` llega al banco, que cambia con
  lo que se ejecutó antes (el árbitro de bancos rota tras cada ola).

**Arreglo aplicado (2026-11-08):** el bucle de espera ahora abre una región `SSY done` antes de
`BNE R6, R0, done`. La divergencia es legal: los carriles que ya vieron la bandera esperan en `done` y el
warp reconverge entero antes de la `BAR`, sea cual sea el reparto de olas. El resultado final no depende
del ciclo en que caiga el `STORE`. Sigue probando lo mismo: con una barrera global, la `BAR` del grupo 0
esperaría a unos warps que esperan a esa `BAR`.

**Mejora de hardware posible: broadcast en el LSU.** El LSU no compara las direcciones de los
carriles: cada uno es un candidato a su banco (`addr[4:2]`) y, si el banco ya está cogido en esa ola,
espera a la siguiente ([`gpu_lsu.v`](../../../../12.fpga-gpu/gpu_lsu.v), bucle de `route_*`). Por eso
ocho carriles que leen la misma palabra cuestan ocho olas. Con broadcast (leer una vez y repartir el
dato a todos los carriles que piden esa misma palabra) la lectura de la bandera sería de una sola ola,
atómica para el warp, y esta carrera no ocurriría en este caso. Los accesos uniformes (constantes,
punteros base, límites de bucle, banderas) son comunes en un kernel, y es lo que hace la memoria
compartida de las GPU reales. Matices:

- Cuesta lógica: comparar las direcciones de los carriles que caen en cada banco y repartir el dato de
  vuelta, en un camino (el del LSU) que ya es sensible al timing. No está medido.
- No elimina el caso general: carriles con direcciones distintas del mismo banco se siguen
  serializando, y una lectura de warp partida entre ciclos sigue siendo posible.
- Falta saber cuántos `LOAD` de los kernels reales son uniformes; se podría contar en el simulador
  (`gpu-vecsum`, `mandelbrot`...) antes de decidir. Es una decisión para las GPU más nuevas, no para la 12.

Contexto: [README de la categoría](../README.md).
