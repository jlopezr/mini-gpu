# `simt`

## Objetivo

Divergencia **anidada**: parte cada warp en tres caminos y comprueba que la pila
de reconvergencia los vuelve a juntar en el orden bueno.

## Comportamiento esperado

- No toca memoria a propósito: lo que se mide es solo el control de flujo SIMT
  (la pila `SSY`), no la LSU. Si esto falla, el problema está en el SM.
- En esta ISA un salto divergente necesita `SSY etiqueta` delante, marcando el
  punto de reconvergencia; sin él, el SM para con `ERROR_SIMT (0x06)`. Aquí hay
  dos `SSY` anidados, que es justo lo que se quiere estresar.
- Reparto por lane (`ANDI ..., 7` deja el id **dentro** del warp, así que los 8
  warps hacen lo mismo):

| Lanes | Camino | `R3` final |
|---|---|---|
| 0-1 | `lowest`: 10, +1 en `inner`, +1 en `join` | 12 |
| 2-3 | `low`: 20, +1 en `inner`, +1 en `join` | 22 |
| 4-7 | `alto`: 30, +1 en `join` | 31 |

- Acaba en `EXIT`, no en `HALT`: cada hilo termina por su cuenta.
- [`simt.legacy-12-14-17.asm`](simt.legacy-12-14-17.asm) es la variante para las
  placas viejas y no se ejecuta.

## Qué comprueba el `test.json`

- Parada limpia sin error y los registros de cada warp (`warps.json`).
- La versión de un solo nivel es [`simt-demo`](../simt-demo/).
- Lleva `rtl.differential` con `warp_config` de 8 warps: `tools/make_rtl_fixtures.py` lo ejecuta así en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL. El caso, en cambio, se prueba con los 2 warps de `warps.json`.

Contexto: [README de la categoría](../README.md).
