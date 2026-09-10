# PATH llena pero divergencia sin push

## Objetivo

Comprueba que con la pila `PATH` llena sigue permitida una divergencia cuyo
camino tomado va directamente al join, porque no necesita reservar entrada.

## Comportamiento esperado

- Con `simt_path_depth = 2`, las dos primeras divergencias llenan la pila.
- La tercera manda las lanes 2..3 directamente al join: se aparcan en la REGION,
  sin `push`.
- La operación debe estar permitida pese a la pila llena.

## Qué comprueba el `test.json`

- Terminación sin error, que es lo contrario de `ssy-path-overflow-depth4`.
- `R3` vale `10, 10, 0, 0, 20, 20, 30, 30`: las lanes 2..3 saltaron al join sin
  ejecutar ningún bloque, y el resto ejecutó el suyo.

## Notas

Usa `simulator_options.simt_path_depth = 2`. Junto a
`ssy-path-overflow-depth4` valida que el simulador comprueba **si realmente
necesita reservar** antes de dar overflow, en vez de rechazar cualquier
operación con la pila llena.
