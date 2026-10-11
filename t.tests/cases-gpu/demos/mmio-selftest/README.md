# `mmio-selftest`

## Objetivo

Comprobar que la GPU alcanza la ventana MMIO **por sí misma**, algo que antes era
imposible: la LSU marcaba fallo todo lo que pasara de `0x02000000` y el MMIO
exigía `halted`, o sea que solo lo tocaba el host.

## Comportamiento esperado

- Solo el hilo 0 toca el MMIO. Los accesos son **escalares** (una lane cada vez):
  dejar que los 64 hilos escribieran el mismo registro sería correcto pero
  absurdo.
- El hilo 0 escribe `VIDEO_CTRL = 2` (scanout) y lo relee; lee los contadores
  `CYCLES` y `RETIRED` antes y después de un tramo de trabajo (memoria coalescida
  más algo de ALU) para cronometrarse a sí mismo, sin simular y sin UART.
- Los contadores no cuelgan de la base de vídeo: en MMIO v2 son un bloque aparte
  (`MMIO_GPU_PERF_BASE`, `0x82030000`).
- Dos cosas de esta ISA que el programa respeta: un salto divergente necesita
  `SSY`, y el inmediato de `LOAD`/`STORE` es un desplazamiento en **bytes**.
- Deja en el hilo 0: `R10` = `VIDEO_CTRL` releído, `R11` = ciclos del tramo y
  `R12` = instrucciones retiradas en él.

## Qué comprueba el `test.json`

- Parada limpia sin error y los registros de cada warp (`warps.json`).
- `requires: ["video", "perf_counters"]`.

Contexto: [README de la categoría](../README.md).
