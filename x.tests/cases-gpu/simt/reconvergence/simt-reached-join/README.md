# El join cierra la REGION en cada vuelta

## Objetivo

Comprueba que llegar al `join` retira la entrada de sincronización, de modo que
un bucle que ejecuta `SSY` en cada vuelta no acumula regiones.

## Comportamiento esperado

- El bucle da 9 vueltas; cada una abre una REGION y salta de inmediato al join.
- Si el join no cerrase la REGION, la novena vuelta desbordaría la pila
  (`ERROR_SIMT`).

## Qué comprueba el `test.json`

- Terminación sin error tras las 9 vueltas.
- `R1 = 9` en la lane 0: el bucle completó todas las iteraciones.
- `R1 = 0` en la lane 7, inactiva desde el principio.
- `instructions_executed = 39`, que fija el coste exacto del bucle.

## Notas

Este caso arranca con `active_mask = 1`: una única lane activa. No prueba
divergencia, solo la gestión de la pila de regiones.
