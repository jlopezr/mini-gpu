# `starfield-fast`

## Objetivo

El mismo campo de estrellas con **borrado incremental**: en vez de pintar de
negro 38 400 palabras para volver a encender 256 píxeles, borra solo esos 256.

## Comportamiento esperado

- Pasa de unas 123 000 a unas 16 000 instrucciones por frame (4 930 000 contra
  641 000 hasta el swap 40).
- El ahorro cuesta contabilidad: con doble buffer, el buffer trasero contiene el
  frame de **hace dos**, así que cada estrella guarda dos direcciones y se borra
  la más vieja.
- Los borrados van todos en una pasada previa a los dibujos; entrelazados, el
  borrado de una estrella apagaría el píxel que otra acaba de encender.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 40**, parada limpia y sin `underflow`.
- **Compara contra el `expected/frame.bin` de [`starfield`](../starfield/)**, no
  contra uno propio. Es todo el caso: un fallo de contabilidad no se ve a ojo,
  pero sí contra el frame de la versión que repinta entero.
- Mismos `requires` que `starfield`.

Contexto: [README de la categoría](../README.md).
