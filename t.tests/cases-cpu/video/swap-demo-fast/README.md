# `swap-demo-fast`

## Objetivo

El mismo frame que [`swap-demo`](../swap-demo/) por **redibujo incremental sobre
dos buffers**: repinta solo 32 líneas, borrando la banda vieja y dibujando la
nueva, en vez de las 240.

## Comportamiento esperado

- Es `swap_demo_fast.asm` de la 16 ejecutado tal cual.
- El fallo clásico de esta optimización es borrar usando la posición del otro
  buffer, olvidando que hay dos: deja un rastro de bandas verdes que no se borran
  nunca. Contra un frame esperado es un fallo; a ojo, en una demo que corre,
  cuesta fijarse.
- [`swap_demo_fast.legacy-16-18-19.asm`](swap_demo_fast.legacy-16-18-19.asm) es la
  variante para las placas viejas y no se ejecuta.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 24**, parada limpia y sin `underflow`.
- **Compara contra el `expected/frame.bin` de [`swap-demo`](../swap-demo/)**: los
  dos programas tienen que dibujar lo mismo.
- `requires: ["frame_capture"]`.

Sus hermanos `tear_demo*.asm` no son casos: nunca piden `SWAP` y lo que enseñan
es una carrera entre la CPU y el barrido, que el simulador no modela. Ver el
[README de la categoría](../README.md).
