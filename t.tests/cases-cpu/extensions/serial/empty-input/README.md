# `empty-input`

## Objetivo

Escribir por el puerto serie sin haber leído nada, y comprobar que `STATUS` dice
la verdad.

## Comportamiento esperado

- [`uppercase`](../uppercase/) solo ejercita el camino PC → CPU. Este ejercita el
  otro, y el detalle en el que es más fácil equivocarse: con la cola de entrada
  vacía, `rx_count` tiene que ser **cero** y `tx_free` la profundidad entera.
- Si los dos campos de `STATUS` estuvieran cambiados de sitio, `uppercase`
  seguiría pasando (leería 64 en vez de 0 y entraría al bucle igual) y este no.
- Lee `STATUS` con las dos colas vacías y envía `"OK\n"`.

## Qué comprueba el `test.json`

- `R7 = 0x00004000` (`STATUS` inicial: ningún byte por leer y 64 huecos de
  escritura) y `R8 = 0x00003D00` (61 huecos tras escribir 3 bytes).
- La salida serie es exactamente `"OK\n"`; parada limpia en `pc = 0x2C`.
- `requires: ["serial"]`.

Contexto: [README de la categoría](../../README.md).
