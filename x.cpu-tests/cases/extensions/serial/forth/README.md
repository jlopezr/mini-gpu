# El Forth de la 20, sobre la consola serie

Ejecuta [`20.forth/forth.asm`](../../../../../20.forth/forth.asm) entero y
compara el diálogo byte a byte: el banner, el eco de cada línea, los `ok>` y
los resultados.

## Por qué la sesión es la que es

Cada línea está por algo, y conviene no recortarla sin mirar:

| Línea | Qué prueba |
|---|---|
| `2 3 + .` | Camino corto: leer números, aritmética, imprimir |
| `: sq dup * ;` | El compilador: `:` anota la definición en vez de ejecutarla |
| `5 sq .` | El intérprete interno, que recorre el cuerpo compilado |
| `255 HEX .` | **`BASE` al imprimir**: se lee en decimal y se imprime en hexadecimal |
| `FF DECIMAL .` | **`BASE` al leer**: `FF` solo parsea con la base ya cambiada |
| `bye` | Parada limpia, con `HALT` y no por límite de instrucciones |

Las dos de `BASE` se añadieron al portar el programa a `R0` cableado a cero.
`BASE` vivía en `R0` y pasó a `R3` —ver el
[README de la 20](../../../../../20.forth/README.md#r0-es-el-cero-y-r3-es-base)—
y la sesión anterior **no cambiaba de base nunca**: habría dado por bueno el
port aunque `BASE` hubiera quedado en un registro que otra cosa pisara.

Están cruzadas a propósito. Una sesión ingenua como `HEX` + `FF .` imprime `FF`,
que es lo mismo que se escribió, y `100 .` da `100` en las dos bases: no
distingue nada. Cruzando la frontera —parsear en una base e imprimir en la
otra— cada línea falla de una forma distinta si `BASE` se pierde:

- Si `BASE` se queda en 10, `FF` no parsea y sale `? FF`.
- Si `BASE` se queda en 16, el `255` final sale como `FF`.

## Qué no prueba

El **tiempo**. El simulador entrega todos los bytes de `stdin` desde el
principio y la placa los recibe cuando el PC los manda. Para un programa de
petición-respuesta como éste da igual —lee lo que hay, contesta, vuelve a
esperar— y por eso el diálogo se puede comparar entre backends. Un programa que
dependiera de *cuándo* llega cada byte no se podría probar así.
