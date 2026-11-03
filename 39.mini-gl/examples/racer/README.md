# Niveles de racer

Cada nivel de [`racer.c`](../racer.c) es un fichero `.h` de esta carpeta: un nombre y tres mapas de texto
de 24 × 24 casillas, una letra por casilla, como en un editor de circuitos por casillas. Una casilla mide
40 unidades de lado (`TILE`) y un nivel de altura, 10 (`LEVEL`).

| Fichero | Nivel |
|---|---|
| [`coast.h`](coast.h) | COAST: el primero; monte al norte, puente sobre el canal del sur, faro |
| [`sierra.h`](sierra.h) | SIERRA: rampas hasta la cresta, puente alto sobre el fiordo, curva grande en cuesta |
| [`delta.h`](delta.h) | DELTA: llano y rápido, entre canales, seis pares de puentes |
| [`knot.h`](knot.h) | KNOT: tres lazos, curvas grandes, un paso elevado y un cruce |
| [`zigzag.h`](zigzag.h) | ZIGZAG: un monte todo en cuesta menos la cumbre; baja en zigzag con horquillas en cuesta y se sube de un tirón |

## El fichero

```c
/* Una línea o dos sobre el nivel. */
static const Level level_ejemplo = {
    "EJEMPLO",          /* el nombre que sale en pantalla: A-Z, 0-9 y espacios */
    { ...24 filas... }, /* ground: el terreno */
    { ...24 filas... }, /* track: el circuito */
    { ...24 filas... }, /* scenery: el decorado */
};
```

Cada mapa son 24 cadenas de 24 caracteres. La fila 0 es el norte (arriba en el minimapa) y la columna 0,
el oeste.

Para añadirlo al juego, en `racer.c`:

```c
#include "racer/ejemplo.h"
...
static const Level *const levels[] = {&level_coast, &level_sierra, &level_delta, &level_knot, &level_ejemplo};
```

La tecla N pasa de un nivel al siguiente, en ese orden.

## ground: el terreno

| Carácter | Qué |
|---|---|
| `0`–`9` | tierra a esa altura, en niveles (`3` = 30 unidades) |
| `~` | fondo de agua (−10) |

El agua está a −4: todo lo que queda por debajo es mar, río o lago. Fuera del mapa sigue el mar.

**Las alturas no son escalones.** La altura de cada esquina es la media de las cuatro casillas que la
tocan, y cada casilla son dos triángulos entre sus esquinas. Así salen laderas. Los colores salen solos:

- **arena**: junto al agua;
- **hierba**: lo normal;
- **roca**: lo muy empinado, más de 0.65 de pendiente (unos 2.5 niveles de diferencia entre dos esquinas
  vecinas). Por la roca **no se puede subir**: es un muro para el coche;
- **nieve**: por encima de 58 (nivel 6 y pico).

Un borde de `~` alrededor del mapa hace de costa. `0` junto al agua da playa.

**Bajo la carretera, la cifra es la altura de la carretera** (ver [Alturas de la carretera](#alturas-de-la-carretera)),
salvo bajo `^`, los puentes y los cruces, donde es solo el terreno. Las esquinas de una casilla con
carretera se ponen a la altura de la carretera: el terreno de alrededor se adapta a ella, no al revés.

## track: el circuito

El circuito es **un único recorrido cerrado**: se sigue desde la salida y tiene que volver a ella.
`.` es "sin carretera".

| Carácter | Pieza |
|---|---|
| `-` `\|` | recta este-oeste o norte-sur |
| `r` `7` `L` `J` | curva: une los lados que dibuja la esquina (`r` ┌ sur y este, `7` ┐ oeste y sur, `L` └ norte y este, `J` ┘ norte y oeste) |
| `^` | cuesta marcada: una recta (en cualquier dirección) donde se hace el cambio de altura entero; ver [Cuestas marcadas](#cuestas-marcadas-con-) |
| `=` | puente: recta a la altura a la que se llega, con barandillas y un pilar hasta el fondo; el terreno de debajo se queda como esté (agua, un barranco) |
| `+` | cruce: el circuito pasa por aquí **dos veces**, en línea recta |
| `S` | la salida: una recta. Arranca hacia la primera casilla vecina con carretera, mirando en este orden: N, E, S, O |

### Curvas: tres tamaños

| Tamaño | Cómo se escribe | Radio del eje | Velocidad del piloto automático |
|---|---|---|---|
| 1 × 1 | una letra | 20 | unos 48 km/h |
| 2 × 2 | un cuadrado de 2 × 2 con la misma letra | 60 | unos 100 km/h |
| 3 × 3 | un cuadrado de 3 × 3 con la misma letra | 100 | unos 150 km/h |

La curva gira alrededor de la esquina del cuadrado que queda por dentro y ocupa el bloque entero (llano,
o en cuesta si la hay: ver [Alturas de la carretera](#alturas-de-la-carretera)). **Se entra y se sale por las casillas del borde que están a un radio
de esa esquina**: las que siguen a las rectas. Por ejemplo, una `r` de 2 × 2 a la que se llega subiendo y
de la que se sale hacia el este:

```
.rr---
.rr...
.|....
```

La recta de abajo tiene que llegar a la **columna de la izquierda** del bloque, y la de la derecha sale de
la **fila de arriba**. Una de 3 × 3, igual, con las rectas en la columna y la fila de los bordes:

```
.rrr---
.rrr...
.rrr...
.|.....
```

Si una recta llega a otra casilla del bloque, el circuito se corta ahí.

Dos de 2 × 2 una encima de otra hacen una **horquilla**: se da la vuelta entre dos rectas a tres filas.
Como en ZIGZAG, entrando hacia el este por la fila de arriba:

```
---77
...77
...JJ
---JJ
```

Dos curvas iguales pegadas forman un bloque si hacen un cuadrado. Con una curva de 1 × 1 eso no puede pasar
en un circuito bien hecho: dos `r` vecinas no se pueden unir entre sí.

### Alturas de la carretera

La carretera sigue las cifras de `ground` que tiene debajo: **las cuestas salen donde cambia la cifra**.
Si quieres una cuesta en un sitio concreto, márcala con `^` (ver [más abajo](#cuestas-marcadas-con-)).

- **Rectas y curvas**: cada una tiene la altura de su casilla (una curva, la de la casilla por la que se
  entra; pon la misma cifra en todo el bloque).
- **Puentes `=` y cruces `+`**: siguen a la altura a la que se llega; su cifra es lo que hay debajo (agua,
  un barranco, la otra carretera).
- **Donde cambia la altura**, la carretera hace una cuesta en línea recta centrada en el cambio. Por cada
  lado ocupa **la mitad de lo que dura esa altura, como mucho 3 casillas** (una curva cuenta lo que mide
  su arco). Nunca entra en un puente, un cruce ni la salida: siguen planos, y la cuesta se hace solo por
  el otro lado.
- **Las curvas también pueden ir en cuesta**: si la cuesta entra en una curva, la curva sube o baja con
  el ángulo. Para que una curva grande suba entera, ponle una cifra intermedia entre la de antes y la de
  después: con `1`, la curva a `2` y `3` después, sube de 1 a 3 a lo largo de la curva y de lo que la
  rodea.

Así **la pendiente sale de cómo pongas las cifras**: el cambio de altura entre lo que ocupa la cuesta.

| Cifras bajo la carretera, en el sentido de la marcha | La cuesta ocupa | Pendiente |
|---|---|---|
| `1 2 3 4` | 1 casilla por nivel | 0.25 seguida |
| `1 1 2 2 3 3` | 2 casillas por nivel | 0.125 seguida |
| `1 1 1 2 2 2` | 3 casillas | 0.083 |
| `1 1 1 1 1 1 2 2 2 2 2 2` | 6 casillas (3 y 3), con llano a los dos lados | 0.042 |
| `1 3` | 1 casilla | 0.5: empinada |
| `1 1 3 3` | 2 casillas | 0.25 |
| `1 1` (curva 2×2 a `2`) `2 2` | 2 casillas y media curva | unos 0.08 |

Bajar es lo mismo al revés. Un llano largo entre dos cuestas queda llano en medio: la mitad de cada lado
como mucho 3 casillas.

- **Entre dos puentes o cruces no cabe una cuesta automática**: si la cifra cambia ahí, queda un escalón,
  un muro en la carretera. Pon al menos una recta o una curva entre ellos, o una `^`.
- Al final de una cuesta empinada, a toda velocidad, el coche salta. Una curva justo después es difícil.
- Más de 0.5 de pendiente apenas se puede subir: el coche pierde velocidad cuesta arriba.

#### Cuestas marcadas con `^`

Una casilla `^` en una recta, o varias seguidas, dice **dónde va la cuesta**: el cambio de altura entre lo
que hay antes y lo que hay después se hace entero en ellas, en línea recta. Da igual hacia dónde vaya la
carretera y si sube o baja. Las cifras bajo las `^` no cuentan, y las cuestas automáticas no entran en
ellas: lo de antes y lo de después se queda llano.

| Cifras | track | Resultado |
|---|---|---|
| `1 1 1 1 · 2 2 2 2` | `- - - - ^ - - - -` | llano, sube 10 en 1 casilla (0.25), llano |
| `1 1 1 · · 2 2 2` | `- - - ^ ^ - - -` | llano, sube 10 en 2 casillas (0.125), llano |
| `1 1 1 1 2 2 2 2` | `- - - - - - - -` | sin `^`: sube 10 en 4 casillas (0.0625), centrado |
| `1 · 3` entre dos curvas | `r ^ 7` | sube 20 en esa casilla (0.5) |

(`·`: la cifra que haya, no cuenta.) Es la forma de hacer una rampa corta en medio de un llano largo, la
que hace saltar al coche, o una cuesta entre dos curvas.

### Cruces y pasos elevados

`+` se pasa dos veces, siempre en línea recta (de norte a sur una vez y de este a oeste la otra). Qué es
lo decide la altura de cada pasada:

- **a la misma altura, un cruce**: una cruz de asfalto. El tráfico cede el paso a lo que ya está dentro y a
  lo que llega por su derecha;
- **a distinta altura, un paso elevado**: la de arriba es un puente sin pilar, sujeto por los estribos, y
  la de abajo pasa por debajo. Para que el coche y la cámara de detrás quepan, la de arriba tiene que ir
  **dos niveles** más alta. Por ejemplo, en KNOT:

  ```
  ground  ~011122331332211111110~~
  track   ..LL-^-^-+-^-^77........
  ```

  Recorrida hacia el oeste, desde la curva (nivel 1): una `^`, la recta de la columna 12 a nivel 2, otra
  `^` y la de la 10 a nivel 3; el cruce sigue a nivel 3 (el `1` de debajo es la otra carretera, la de
  abajo) y luego baja igual por `^` hasta el nivel 1. La otra pasada, de norte a sur, va a nivel 1.

Donde el terreno no puede seguir a la carretera (los terraplenes del paso elevado), una pared vertical tapa
el desnivel. Sale sola.

### Límites

- Como mucho 128 piezas (`MAX_PATH`). Una curva grande cuenta como una sola.
- El tráfico sale en las piezas `n/10`, `13n/50` y `22n/50` del circuito (n = piezas).
- La vuelta cuenta si se pasa por las piezas en orden. Se puede saltar alguna, por ejemplo volando al final
  de una cuesta, pero no atajar.

## scenery: el decorado

| Carácter | Qué |
|---|---|
| `T` | pino |
| `t` | árbol |
| `H` | casa |
| `s` | señal: tiene que estar **junto a una casilla con carretera**, y la mira |
| `F` | el faro, con su haz girando |
| `.` | nada |

No pongas nada sobre la carretera ni en el agua. Cada árbol sale un poco desplazado, girado y de un tamaño
al azar, siempre igual en cada nivel. Los árboles, las casas y el faro son obstáculos.

Como mucho 200 objetos por nivel (`MAX_PROPS`).

## Probarlo

- `make sdl-racer`, y N hasta llegar al nivel.
- P pone el piloto automático: si da la vuelta entera sin caerse ni salirse, el circuito se puede correr.
- Si un circuito está mal cerrado, en el minimapa se ve dónde se corta: ahí acaba la carretera.
- G congela la escena y enseña sus datos; con ellos, `make racer-scene SCENE="..."` la vuelve a dibujar en
  el host.
