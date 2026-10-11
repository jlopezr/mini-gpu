# `keys-and-mouse`

## Objetivo

Comprobar que INPUT (`1.isa/mmio.md` §25) entrega los eventos de teclado y
ratón con el formato y el orden del contrato.

## Comportamiento esperado

- El teclado y el ratón están presentes desde `@0` y no generan eventos al
  conectarse (estado vacío).
- `key down LSHIFT A` es **un solo report**: primero el evento de modificadores
  (`KEY=0`, `MODIFIERS=0x02`) y después `A` down con esos mismos modificadores.
- `key up LSHIFT A` suelta las dos a la vez: `A` up primero, ya con los
  modificadores **nuevos** (cero), y después el evento `KEY=0` con el bitmap
  completo.
- `mouse report 1 3 -2` pulsa el botón izquierdo y mueve (3, −2) en el mismo
  report: el botón va antes que el movimiento. `DY = −2` es `0xFFE` en signed12.
- Al final `STATUS` vale `0x60000` (sin eventos, teclado y ratón presentes),
  `KEY_STATE0` y `MOUSE_BUTTONS` son cero.

El programa sondea `STATUS.COUNT` antes de cada lectura de `EVENT_DATA`: el
valor de `EVENT_DATA` por sí solo no dice si había un evento.

## Qué comprueba el `test.json`

- Las siete palabras de evento en `R10..R16` y el estado final en `R17..R19`.
- `requires: ["input"]`: solo los simuladores la declaran; ningún RTL implementa
  INPUT todavía, así que en la placa el caso se omite.

Los instantes del guion (`@200`...) son instrucciones completadas, no tiempo.

Contexto: [README de la categoría](../../README.md).
