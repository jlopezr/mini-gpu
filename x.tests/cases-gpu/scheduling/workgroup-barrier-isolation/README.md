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

Contexto: [README de la categoría](../README.md).
