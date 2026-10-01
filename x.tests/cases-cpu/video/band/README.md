# `band`

## Objetivo

La cadena completa hasta el framebuffer, con la imagen más simple posible.

## Comportamiento esperado

- Pinta una banda verde fija (líneas 96 a 111) sobre fondo azul.
- Es fija a propósito: quita del caso la pregunta de en qué intercambio se para,
  para que un fallo solo pueda venir de la cadena hasta el framebuffer.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 4**, parada limpia y sin `underflow`.
- El frame capturado contra `expected/frame.bin`, que calcula
  [`reference.py`](reference.py) por otro camino (no se captura de la placa).
- `requires: ["frame_capture"]`.

Contexto: [README de la categoría](../README.md).
