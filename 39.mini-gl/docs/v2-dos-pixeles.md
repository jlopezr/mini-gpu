# V2: escribir dos píxeles por acceso

En V2, `raster.c` se ejecuta en la GPU, un warp de 8 lanes, y cada lane dibuja solo sus píxeles: los de las
columnas `x & 7 == lane`. Cada píxel se escribe con un `STOREH` de 16 bits. V0, en la CPU, escribe los tramos
largos de dos en dos píxeles con `STORE` de 32 bits. Este documento cuenta qué pasó al intentar lo mismo en la GPU,
por qué no compensa y qué se ha quedado.

## Punto de partida

En `shapes` (2 frames), `row_fill` se lleva 161 000 de las 348 000 instrucciones de warp de la GPU (46 %). Una lane
recorre sus píxeles de 8 en 8, con tres instrucciones por píxel:

```c
for (p = row + x0 + ((RASTER_LANE - x0) & 7); p < end; p += 8) *p = c;
```

La idea era hacer la mitad de vueltas escribiendo dos píxeles por `STORE`.

## Qué hace falta

Una palabra de 32 bits tiene dos píxeles, y una lane solo puede escribirla entera si los dos son suyos. Así que el
reparto pasa de columnas a **palabras**: cada lane es dueña de una palabra de cada ocho.

```c
#define OWNS(p) (((((unsigned long)(p) >> 2) - RASTER_LANE) & 7) == 0)
```

El dueño se decide por la **dirección**, no por `x`. Con un `pitch` impar (el fuzz usa 101), las filas no empiezan
alineadas a 4, y el mismo `x` cae en la primera mitad de una palabra en unas filas y en la segunda en otras.

Un tramo `[x0, x1)` queda así:

- un medio píxel suelto al principio, si no empieza alineado: lo escribe con `STOREH` la lane dueña de esa palabra;
- otro al final, si no acaba alineado;
- en medio, palabras enteras: cada lane escribe las suyas con `STORE`, de 16 en 16 píxeles.

`put`, la columna de `box` y `sw_image` solo cambian la comprobación del dueño. En el host la palabra se escribe con
dos `STOREH` (escribir un `mgl_color_t` con un `unsigned` no está definido en C), pero el recorrido es el mismo, y el
fuzz de V2 contra V0 lo prueba.

## Lo que se probó

Instrucciones de warp de la GPU, 2 frames por sketch. Las tres variantes daban los mismos píxeles que V0 (fuzz de
20 000 escenas y `check-minigpu`).

| | shapes | pattern | bounce | trail | paint |
|---|---|---|---|---|---|
| Antes (columnas, un píxel por `STOREH`) | 348 088 | 696 134 | 125 361 | 38 961 | 39 601 |
| 1. Palabras, con las puntas sueltas | 383 936 | 828 294 | 116 560 | 28 387 | 29 149 |
| 2. La 1, con `brush` y `box` rellenando varias filas con una sola preparación | 356 862 | 889 682 | 115 721 | 21 767 | 21 065 |
| 3. La 2, con un bucle sencillo para los tramos de menos de 32 píxeles | 346 598 | 815 322 | 109 997 | 21 337 | 20 913 |

Respecto a antes, la variante 3 deja trail y paint en casi la mitad (−45 %), bounce en −12 %, shapes igual y
**pattern un 17 % peor**.

Las variantes 2 y 3 añaden `fill_rows`, que rellena `rows` filas seguidas con una sola preparación: las puntas y la
primera palabra de la lane son las mismas en todas si el `pitch` es múltiplo de 16 píxeles (en la placa, 320). `box`
la usa cuando el `pitch` lo permite, y `brush` pasa a dibujar su cuadrado con `box` en lugar de un `span` por fila.

## Por qué no compensa

Lo que se gana está en los tramos largos: el borrado de pantalla baja de 69 000 a 47 000 instrucciones en shapes, y
trail y paint, que casi solo borran, bajan a la mitad. Pero cada `row_fill` paga más trabajo fijo:

- **Las puntas.** Ver si el medio píxel de cada punta cae dentro y de quién es: dos comprobaciones por llamada, y cada
  una es una región SIMT (`SSY`), porque solo una lane escribe.
- **La palabra.** Formar `c | c << 16` y calcular la primera palabra de la lane, con desplazamientos por registro
  (la GPU de la 36 no tiene `SHRI`).
- **Los registros.** `fill_rows` tiene más variables locales, y lcc guarda y restaura 6 registros preservados en cada
  llamada: unas 14 instrucciones. En un kernel, cada llamada es una copia expandida, y esos guardados se quedan.

En un tramo corto no hay nada que ganar. En una fila de 16 píxeles, cada lane escribe 2 píxeles igualmente: antes con
dos `STOREH`, ahora con un `STORE` o con dos medias. El trabajo fijo sube de unas 26 instrucciones por llamada a unas
46, y pattern, que pinta celdas pequeñas (círculos y triángulos de unos 16 píxeles por fila), lo paga en cada fila.
La variante 3 lo reduce con un bucle sin preparación para los tramos cortos, pero ese bucle comprueba cada mitad, y
sigue costando más que el de antes.

Durante la variante 3, la primera forma de escribirla (`row_fill` llamando a `fill_rows`) añadía un nivel de marcos,
y el kernel pasaba de los 496 bytes de pila por lane. Lo detectó el pase `lanestack` de mini-opt al compilar; sin
él, una lane habría escrito en la pila de la siguiente sin ningún aviso.

## Una alternativa que no se ha hecho: elegir el reparto en cada llamada

Lo mejor de las dos formas sería repartir los tramos cortos por columnas, como antes, y los largos por palabras. Hoy
no se puede, por dos motivos:

1. **El orden de las escrituras.** Si un píxel lo escribe la lane 3 en un primitivo y la lane 5 en el siguiente, el
   resultado depende de que la GPU aplique las escrituras en orden de programa. Con un solo warp que ejecuta en orden
   es así, pero hoy V2 no depende de ello: cada píxel tiene siempre la misma dueña, y cada lane escribe los suyos en
   su orden.
2. **La emulación del host.** En el host, `mgl_gpu_render` ejecuta el trabajo entero de la lane 0, después el de la 1,
   y así. Con un único reparto da lo mismo que la GPU. Con repartos distintos según la llamada, la última lane podría
   pisar con un valor antiguo lo que otra escribió después. Habría que emular las lanes dentro de cada llamada de
   escritura, y no por trabajo entero.

Vale la pena si algún día hay sketches con muchos tramos largos, o si las escrituras de 32 bits resultan importantes
en la placa: el simulador cuenta instrucciones, no accesos a memoria, y es posible que a la SDRAM le convengan.

## Qué se ha quedado

- **Las escrituras de palabras, no.** `raster.c` sigue repartiendo por columnas.
- **`brush` con `box`, sí.** Dibuja el mismo cuadrado con una sola llamada en lugar de un `span` por fila: `box`
  recorta `y` una vez y avanza la fila sin multiplicar. Es lo mismo en V0, V1 y V2:

  | | shapes (pinceles de 3 y 4) | bounce (pincel de 2) |
  |---|---|---|
  | V0, CPU | 587 000 → 577 000 (−1,7 %) | +512 (+0,2 %) |
  | V2, GPU | 348 088 → 336 488 (−3,3 %) | 125 361 → 124 993 |

  Con un pincel de 2, preparar `box` cuesta 4 instrucciones más por punto que dos `span`: se pierde un poco. Con 3
  o más se gana, y más cuanto más grueso.
