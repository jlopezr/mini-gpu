# `double-buffer`

## Objetivo

El contrato de doble buffer, **igual en CPU y en GPU**. Es el mismo binario en las
dos familias: si la 21 y la 22 no respondieran igual a las mismas escrituras, el
caso fallaría en una de las dos.

## Comportamiento esperado

Tres decisiones deliberadas lo hacen portable:

- **Un solo hilo.** Un programa de GPU normal reparte con `GETTID` entre 64 hilos,
  que no existen en la CPU. El reparto se evita desde fuera: `warps.json` deja
  `active_mask: 1`.
- **No depende de las bases de encendido.** `FB_FRONT` y `FB_BACK` arrancan con
  valores distintos en cada familia, así que el caso no afirma ninguna dirección
  absoluta: lee lo que haya y comprueba relaciones entre esos valores. El valor
  "sucio" que escribe se construye sobre `FB_BACK`.
- **El resultado va a memoria**, no a registros: una CPU declara
  `expect.registers` y una GPU los mete en `expect.warps`; `memory_dumps` es
  idéntico en ambas.

La palabra de resultado lleva la marca `0x5A5A` en la parte alta y un bit por
comprobación en la baja. La marca evita que "todo cero" signifique a la vez
"fallaron las cuatro" y "el programa no llegó a ejecutarse": un programa que no
corre deja `0x00000000` y el caso falla, que es lo correcto.

Solo usa instrucciones base (ni `MUL`, ni `SLT`, ni subpalabra), para correr
también en la 12 y la 10.

## Qué comprueba el `test.json`

- Parada limpia sin error y sin `underflow`.
- El volcado de `0x0200` contra [`expected.hex`](expected.hex).
- `requires: ["video"]`.

Contexto: [README de la categoría](../../README.md).
