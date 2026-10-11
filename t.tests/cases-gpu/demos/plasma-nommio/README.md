# `plasma-nommio`

## Objetivo

Plasma **sin accesos a MMIO**, para validar `23.gpu-sim-uarch`. Es la referencia de
calibración, no un programa útil.

## Comportamiento esperado

- El simulador funcional de `11.gpu-sim-func` no tiene ventana MMIO (ni debe
  tenerla), así que un programa con `LOAD`/`STORE` a `0x80000xxx` revienta allí
  con `ERROR_MEMORY_ACCESS` y el modelo de ciclos acabaría midiendo un recorrido
  distinto al del RTL.
- Esta versión usa una base de framebuffer fija y no pide intercambio, así que RTL
  y modelo ejecutan **exactamente** la misma secuencia.
- Es la excepción a la regla de la carpeta: los demás ejemplos se configuran el
  vídeo ellos mismos, y este no puede, porque en cuanto escribiera un registro
  MMIO dejaría de correr en el simulador.
- El programa no está en esta carpeta: es
  [`../plasma/plasma_nommio.asm`](../plasma/plasma_nommio.asm).

## Qué comprueba el `test.json`

- Parada limpia sin error, 151 880 instrucciones en total (18 985 por warp) y los
  registros de cada warp (`warps.json`).
- `requires: ["large_memory"]`.

Contexto: [README de la categoría](../README.md).
