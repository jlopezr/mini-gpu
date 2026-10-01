# `swap-demo`

## Objetivo

Una imagen que **se mueve**, para fijar el desfase entre el intercambio `N` y lo
que se ve. Es `swap_demo.asm` de la 16 ejecutado tal cual.

## Comportamiento esperado

- La misma banda de [`band`](../band/), pero **bajando dos píxeles por frame**,
  repintando las 240 líneas.
- Con una imagen fija, parar en el swap 24 o en el 25 da lo mismo y no se vería un
  error de uno. Con una que se mueve, el frame cuadra solo si tras el swap `N` se
  ve la banda en `2*(N-1)` y no en `2*N`: el intercambio hace visible lo que se
  dibujó antes del incremento.
- [`swap_demo.legacy-16-18-19.asm`](swap_demo.legacy-16-18-19.asm) es la variante
  para las placas viejas y no se ejecuta.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 24**, parada limpia y sin `underflow`.
- El frame capturado contra `expected/frame.bin`, que calcula
  [`reference.py`](reference.py) (`--swaps N` elige el intercambio).
- `requires: ["frame_capture"]`. [`swap-demo-fast`](../swap-demo-fast/) comparte
  este mismo frame esperado.

Contexto: [README de la categoría](../README.md).
