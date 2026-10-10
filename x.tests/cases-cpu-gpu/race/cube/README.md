# cube

Un cubo sólido con una textura por cara, girando sobre dos ejes (ortográfico), en ensamblador (`cube.asm`) y en C
(`cube.c`).

```text
mini-dbg --gpu x.tests/cases-cpu-gpu/race/cube/cube.asm --window
```

## El cubo en la placa

`race/cube/cube.c` es el demo completo en C: texturas, matriz y caras, anfitrión de vídeo con doble
buffer, método que toca cada 60 fotogramas y gráfica de tiempos. Se compila para la placa 36 con
`--board` (runtime con `RUN` y `bench_now()` con los ciclos de CPU reales):

```text
build-c x.tests/cases-cpu-gpu/race/cube/cube.c --board        # -> _build/c/cube_board.bin
run-board --prototype 36 --program _build/c/cube_board.bin
```

`CCubeRaceTest` comprueba en el simulador que dibuja, método a método, lo mismo que `cube.asm`.
Ciclos de CPU a 80 MHz por fotograma, medidos en la placa (último trabajo de cada método, de
`race_cycles`):

| Método | Ensamblador | C | C / ens. |
|---|---:|---:|---:|
| CPU | 7.073.724 | 10.486.159 | 1,48 |
| GPU inocente | 2.206.206 | 2.603.215 | 1,18 |
| GPU buena | 1.258.934 | 2.150.567 | 1,71 |

Eso, sin `licm` ni `SSY` unidos. Con ellos (el mismo programa recompilado, otra lectura de cada uno), y
después con `copyprop` además:

| Método | Ensamblador | C con `licm` | C con `licm` y `copyprop` | C con `constprop` y R1..R4/R31 | C / ens. |
|---|---:|---:|---:|---:|---:|
| CPU | 7.073.724 | 8.198.496 | 6.785.491 | 7.080.804 | 1,00 |
| GPU inocente | 2.206.206 | 2.390.343 | 2.330.803 | 2.290.832 | 1,04 |
| GPU buena | 1.258.934 | 1.895.447 | 1.656.606 | 1.579.128 | 1,25 |

Cada columna es una lectura distinta de `race_cycles`, del último fotograma de ese método, y el coste
de un fotograma depende del ángulo del cubo: entre columnas hay unos puntos de ruido (la CPU sube de 6,79 M
a 7,08 M sin que el código de su bucle haya cambiado), y solo la GPU buena muestra una mejora clara.

Es una sola medida de cada uno, no una media. Los `SSY` bajan de 16 a 6 y las constantes salen del bucle.
La GPU buena sigue siendo la peor. El bucle de celdas ya lleva un solo `SSY` por celda, como el
ensamblador, pero quedan una copia `ADD Rd, Rs, R0` por cada coordenada que se compara (lcc copia para el
cast a `unsigned`), la carga de la base de la textura en cada acierto (el ensamblador la tiene en un
registro) y un `SHL` donde el ensamblador suma el valor a sí mismo.

Con `sharebase`, `stackslots` y los cambios de `constprop` y `copyprop` (9 de octubre de 2026), medido en la
placa 36 con el mismo programa y el ensamblador en la misma sesión. Mediana de unas 40 lecturas de
`race_cycles` por variante (con el cubo girando, una lectura varía ±8 % según el ángulo; repetir la misma
variante da lo mismo a un 1 %). «Antes» es el pipeline anterior a esos dos pases, pero ya con los pases de
`constprop` nuevos:

| Método | Ensamblador | C antes | C con `sharebase` | C con `stackslots` y `sharebase` | C / ens. |
|---|---:|---:|---:|---:|---:|
| CPU | 7.159.000 | 7.024.800 | 6.866.900 | 6.850.200 | 0,96 |
| GPU inocente | 2.187.000 | 2.318.600 | 2.319.600 | 2.260.000 | 1,03 |
| GPU buena | 1.257.000 | 1.564.000 | 1.537.100 | 1.343.800 | 1,07 |

Casi toda la mejora de la GPU buena (1,24 → 1,07 veces el ensamblador, de 1,56 M a 1,34 M ciclos) viene de
`stackslots`: la fila, la lane y el paso dejan de leerse de la pila de la lane. `sharebase` aporta un 1-2 %,
que está al nivel del ruido. Después se añadió en `licm` la carga de globales que el kernel solo lee, que saca del bucle de celdas la carga
de la base de la textura. Al medirlo era la suposición `--assume-noalias` (los kernels no escriben por sus
punteros de argumento lo que leen por el nombre de una global); ahora `mini-opt` lo demuestra solo, mirando
las dos unidades, el arranque y el runtime: `cube_faces` no tiene la dirección escapada ni es `volatile`, y
sale lo mismo sin flag (`MINI_OPT_NOALIAS=1` conserva la suposición). Medido igual (dos rondas, cada variante
con el ensamblador intercalado): GPU inocente 2.260.000 → 2.211.000 ciclos y GPU buena 1.351.600 → 1.326.200, un
2 % cada una, y la CPU no cambia. Con eso la GPU buena queda en 1,06 veces el ensamblador (1,07 antes) y la
inocente en 1,01. Para medirlo: `halt`, `read-block` de `race_cycles` y `run` con el `monitor.py`
de la 36 (no lee memoria con la CPU en marcha); la dirección sale de las etiquetas del ensamblado.
