# Programas en C con CPU y GPU

A diferencia de `examples/asm` (`dma`, `race`, `render`), que está en
ensamblador, esto es C compilado con `mini-lcc`. Un mismo `.c` lleva el código de la CPU
(`main`) y los kernels de la GPU:

```c
#include "gpu.h"

void KERNEL(memset)(int *dst, int value, int n) {          /* GPU */
    int i, step = __gpu_nthreads;
    GRID_FOR(i, n, step)
        dst[i] = value;
}

int main(void) {                                           /* CPU */
    return GPU_RUN(memset, 4, buffer, 7, 4096);            /* kernel, warps, parámetros */
}
```

```text
python examples/c/build.py examples/c/dma/memset.c        # -> examples/c/_build/memset.bin
python cpu_gpu_sim.py examples/c/_build/memset.bin
```

## Dónde está cada cosa

`examples/asm` y `examples/c` tienen los mismos temas, y lo que existe en las dos tiene el mismo
nombre en la misma carpeta, para encontrar rápido la otra versión:

| Tema | Ensamblador | C |
|---|---|---|
| `dma` | `asm/dma/gpu_kernels.inc` (memset, memcpy, fill_rect, blit) | `c/dma/gpu_kernels.c` |
| `dma` | (dentro de `gpu_kernels.inc`) | `c/dma/memset.c`: programa completo con CPU y GPU |
| `race` | `asm/race/rotate.inc` (+ `rotate.asm`) | `c/race/rotate.c` (+ `rotate_body.h`) |
| `race` | `asm/race/cube.inc` + `race_host.inc` (+ `cube_board.asm`) | `c/race/cube.c` (+ `cube_body.h`): el demo entero, anfitrión incluido |
| `simt` | | `c/simt/diverge.c` (solo en C) |
| `render`, `launch.asm`, `race/{life,blur}` | sí | aún no |

En `c/system/` están las librerías del sistema (`gpu.h`, `gpu.c`, `mmio.h`); `build.py` pasa esa carpeta a
`mini-lcc -I`, así que los ejemplos solo escriben `#include "gpu.h"`. En `c/` quedan las herramientas
(`build.py`, `compare.py`, `compare_race.py`) y las salidas de la compilación van a `c/_build/`.

## Cómo funciona

- **`KERNEL(nombre)`** pone `__kernel_nombre` al nombre de la función. Es la marca que lee
  `mini-opt`: lcc no tiene atributos.
- **`mini-opt`** (pases `intrinsics` y `kernels`, ver `tools/README.md`) convierte esa función en
  el punto de entrada de una lane: carga los parámetros que el kernel lee desde el bloque de
  argumentos (`GETARG`) y sustituye el `JR R31` final por `EXIT`. Quita además el marco de
  pila que lcc monta para guardar y restaurar registros preservados, que a un kernel no le
  sirve (nadie recibe esos registros de vuelta). Solo si el kernel usa la pila de verdad (un
  array local, un derrame) fija la de su lane (`__gpu_stack`, 512 bytes por lane). Además cambia los desplazamientos con cantidad inmediata
  (`SHLI`) por los de registro, que son los únicos que tiene la GPU, y da un error si el
  kernel usa una instrucción que la GPU no ejecuta.
- **`GPU_RUN(nombre, warps, parámetros...)`** llama a `gpu_launch` (`system/gpu.c`), que rellena el
  bloque de argumentos y llama a `gpu_run` de `examples/asm/dma/gpu_runtime.inc` (el runtime de
  ensamblador de siempre). Lanza y espera.
- **El arranque** es `1.isa/runtime/crt0.s`; `build.py` compila con `mini-lcc --no-crt`.
- **La divergencia no se escribe:** un `if`, un `while` o un `break` cuyas lanes tomen
  caminos distintos necesita una región abierta con `SSY` (si no, `ERROR_SIMT`). Los pone
  el pase `ssy` de `mini-opt`: delante de cada salto que puede divergir, con el punto donde
  se juntan todos los caminos (su postdominador inmediato) como destino; en un bucle, una
  sola vez antes del bucle. Solo marca los saltos que dependen de `GETTID`/`GETLANE` (o de lo
  que se calcula bajo un salto así); `mini-opt --ssy-all` los marca todos.

## Los ejemplos

- **`dma/memset.c`**: el kernel más sencillo, sin divergencia (`n` es múltiplo de los hilos).
- **`simt/diverge.c`**: cinco kernels con divergencia: un bucle cuyas lanes salen en vueltas
  distintas, `if`/`else` por id de hilo, un `while` con un número de vueltas distinto por
  lane, una salida anticipada y dos bucles anidados con `break`. Se comprueban contra un
  modelo en Python (`CDivergenceTest`).

## C frente a ensamblador

`dma/gpu_kernels.c` reescribe en C los cuatro kernels de sistema (`memset`, `memcpy`, `fill_rect`, `blit`),
con el mismo reparto y el mismo bloque de argumentos que `examples/asm/dma/gpu_kernels.inc`.
`compare.py` los lanza en el simulador sin programa de CPU, con los mismos datos, y cuenta las
instrucciones de warp que retira la GPU. Los dos juegos dejan la misma memoria (y la que dice un
modelo en Python):

| Carga | Elementos | Ensamblador | C | C / ens. | Instr. por elemento (ens.) | (C) |
|---|---:|---:|---:|---:|---:|---:|
| memset 4096 | 4096 | 3.132 | 3.136 | 1,00 | 0,76 | 0,77 |
| memcpy 4096 | 4096 | 4.156 | 4.160 | 1,00 | 1,01 | 1,02 |
| fill_rect 64x64 | 4096 | 3.640 | 3.640 | 1,00 | 0,89 | 0,89 |
| blit 64x64 | 4096 | 4.796 | 4.800 | 1,00 | 1,17 | 1,17 |
| fill_rect 7x13 (3 warps) | 91 | 182 | 182 | 1,00 | 2,00 | 2,00 |
| blit 7x13 (5 warps) | 91 | 257 | 262 | 1,02 | 2,82 | 2,88 |

**El C cuesta lo mismo que el ensamblador en estos kernels**, con diferencias de entre el 0 y el
2 %. El bucle interior es idéntico, seis instrucciones por vuelta en los dos: `SHL` más `ADD` para
indexar, la carga o el almacenamiento, el incremento y el salto. En C el `MOVI` previo al `SHL`
(la GPU no tiene `SHLI`) ocupa el sitio del `BGEU` de arriba del bucle de ensamblador, porque lcc
pone la condición abajo. Las cuatro o cinco instrucciones de más de la entrada se pagan una vez
por lane.

Dos reservas: son instrucciones de warp, no ciclos (una `LOAD` cuesta ~20 ciclos y una ALU 7, según
`36.fpga-cpu-gpu/sim/instr_rate.py`; la mezcla de los dos bucles es parecida, así que los ciclos
deberían serlo, pero no se ha medido en la placa), y son kernels cortos y sin estructuras. En uno
con mucho cálculo y campos de estructura (la rotación, el cubo) la diferencia puede ser mayor:
lcc relee de la estructura cada campo que usa en el bucle. `CSystemKernelsTest` pone un tope del
10 % a la proporción para que un cambio en el compilador que empeore el código se note.

## Las tres versiones de una demo: CPU, GPU inocente y GPU buena

`GRID_FOR` es solo el reparto más sencillo para una dimensión. Lo que distingue a la GPU inocente de
la buena en `examples/asm/race` no es un bucle distinto: es **qué hilo hace qué trozo del trabajo**. En C
se ve así: el cuerpo se escribe una sola vez (`race/rotate_body.h`) y cada versión lo incluye con cuatro
expresiones distintas, la fila y la columna por la que empieza el hilo y de cuánto en cuánto salta:

| | filas: primera, paso | columnas: primera, paso | qué escriben las 8 lanes de un warp |
|---|---|---|---|
| CPU | 0, 1 | 0, 1 | (un solo hilo) |
| GPU inocente | `__gpu_tid`, todos los hilos | 0, 1 | ocho filas distintas, a 1280 B unas de otras |
| GPU buena | `__gpu_lwarp`, todos los warps | `__gpu_lane`, las lanes de un warp | ocho palabras seguidas |

`race/rotate.c` define esos valores tres veces con `#define`, incluye el cuerpo, y los deshace. La fila
`GRID_FOR(i, n, step)` de arriba es el caso unidimensional de la GPU buena: primera = `__gpu_tid`,
paso = `__gpu_nthreads`. Para una imagen se aplican dos veces, una por la fila y otra por la columna.

El cuerpo no puede ser una función que llame a otra: la GPU de la 36 no tiene `JAL`, así que lcc no
puede enlazar la llamada dentro de un kernel, y lcc no expande funciones en línea. De ahí la
plantilla por `#include`.

## C frente a ensamblador: la rotación de textura

`compare_race.py rotate` ejecuta los seis (tres métodos × C y ensamblador) con los mismos datos y comprueba
que cada uno dibuja la imagen del modelo en Python. Los kernels de GPU se lanzan sin programa de CPU y
la CPU se ejecuta hasta `HALT`:

| Método | Cuenta | Ensamblador | C | C / ens. |
|---|---|---:|---:|---:|
| CPU | instrucciones de CPU | 233.806 | 285.439 | 1,22 |
| GPU inocente | instrucciones de warp | 29.426 | 42.231 | 1,44 |
| GPU buena | instrucciones de warp | 30.864 | 44.664 | 1,45 |

Aquí sí hay diferencia, a diferencia de los kernels de sistema. El bucle de celdas son **20
instrucciones en C contra 14 en ensamblador**, y las seis de más son de tres clases, las tres de
sacar del bucle lo que no cambia en él:

- **`MOVI` + desplazamiento** (dos veces por celda): la GPU no tiene `SHLI`, y la constante (7, 2) se
  vuelve a cargar en cada vuelta. En ensamblador está en un registro desde antes del bucle.
- **`p += cstep` escalado a cada vuelta:** un `MOVI`, un `SHL` y un `ADD` donde el ensamblador tiene un
  `ADDI`, aunque `cstep` no cambia dentro del bucle.
- **Una copia del texel** (`ADD R28,R15,R0`) y **la constante 160 cargada antes de cada `BLT`**.

Dos cosas que importan de cara a escribir C para esta máquina:

- **lcc reparte los registros por orden de declaración.** Con 14 registros preservados y 18 variables,
  declarar primero las frías (`blk`, `fb`, `u00`...) dejaba a `u`, `v` y `texel` en la pila, y el bucle
  de celdas leía y escribía la pila en cada vuelta. En `rotate_body.h` las variables se declaran de la más
  caliente a la más fría.
- **Una pila en la GPU es cara.** Cada lane tiene su porción, a 512 bytes de la siguiente, así que un
  acceso a la pila de los ocho lanes son ocho transacciones. `mini-opt` ya quita los guardados y
  restauraciones de registros preservados aunque el kernel tenga locales, pero no los locales.

Esa brecha es la que cierra el pase `licm` de `mini-opt` (sección siguiente): los números de arriba son
los de antes de él, y con todos los pases la rotación queda en 1,00 / 1,00 / 1,01 veces el ensamblador
(CPU, GPU inocente, GPU buena; tabla más abajo).

## Los pases de `mini-opt`, medidos

`python examples/c/opt_stats.py` compila los ejemplos con los pases de antes (`intrinsics,kernels,ssy`,
lo imprescindible) y con los de ahora, y cuenta en el simulador las instrucciones que se ejecutan. Los
pases nuevos son:

- **`jumps`**: un `BRA` o salto condicional a una etiqueta que solo salta, va directo al destino, y un
  `BRA` a la línea siguiente se quita. En estos ejemplos no encontró nada que hacer (lcc ya no deja esas
  cadenas): se queda por seguridad, pero no hay medida a su favor.
- **`licm`**: en cada bucle sin llamadas (de dentro afuera: lo que sube del bucle de celdas sube otra vez
  del de filas si tampoco cambia con la fila), saca al preheader lo que no cambia: las
  constantes (`MOVI`/`LI`, el `MOVI` previo a cada desplazamiento de la GPU, los límites de las
  comparaciones) y las cuentas cuyos operandos son fijos (`SHL p, cstep, 2`). Usa un registro que el
  bucle no toque y que la vida de registros diga libre (R5..R15, R1..R4, R31, y en un kernel también los
  R16..R29 sin uso; R31 solo mientras la función no tenga que volver por él); un cero se cambia por `R0`. No
  toca cargas ni `DIV`. Es LICM (*loop-invariant code motion*) conservador, sobre registros ya asignados.
- **`constprop`**: donde un registro vale una constante por todos los caminos, la instrucción que lo lee usa
  el inmediato: `MOVI R7, 256 ; SUB d, a, R7` pasa a `ADDI d, a, -256` (también `ADD`, `AND`, `OR`, `XOR`), y
  `SHL d, a, R9` con R9 = 1 pasa a `ADD d, a, a`. La constante deja de ocupar un registro, que es lo que
  importa en un kernel: los saltos y los desplazamientos de la GPU no tienen inmediato, así que esas
  constantes se quedan. Hace además cuatro cosas más con lo mismo (ver `tools/README.md`): quita el `MOVI`/`LI`
  que recarga lo que el registro ya vale (lcc carga el `3` de cada `SHL` aunque no lo haya tocado), hace en el
  filtro las operaciones entre dos constantes, simplifica identidades (`x+0`, `x*1`, `x-x`...) y funde un `MUL`
  por una constante seguido de un `SHL` en un solo `MUL` (`320 * 4` pasa a `1280`). Casi todo es estático:
  en las cargas de arriba cambia en menos de un 1 % las instrucciones ejecutadas.
- **`stackslots`**: lo que lcc no cabe en registros va a la pila de la lane, que en la GPU cuesta 8
  transacciones por acceso de un warp. En el cubo, la fila, la lane y el paso del bucle de filas se leían y
  escribían 6 veces por fila; ahora viven en registros que el kernel no usa (R31, R4...) y desaparece el marco
  entero con su preparación (unas 7 instrucciones por lane). Solo se promocionan los huecos de los que nadie
  toma la dirección y que se acceden con `LOAD`/`STORE` de palabra; si no queda registro libre, no se hace
  nada. Además, `constprop` sigue ahora las constantes a través de copias y `copyprop` borra las copias de un
  registro sobre sí mismo, para limpiar lo que deja. Como `sharebase`, su efecto está sobre todo en ciclos de
  memoria y solo se confirma en la placa.
- **`sharebase`**: lcc carga cada campo de una tabla con su propio `LI` (`LI R12, cube_faces+4 ; LOAD R12,
  R12, 0`), 24 veces en la preparación de cada fila del cubo. Dentro de un bloque cambia los `LI` del mismo
  símbolo por uno solo en un registro libre y suma cada desplazamiento al del `LOAD`, como hace a mano
  `cube.inc`. Es estático: en el cubo quita 66 instrucciones del texto, pero su efecto
  en ciclos solo se sabe midiéndolo en la placa.
- **`copyprop`**: propagación de copias y código muerto. Donde `ADD d, s, R0` llega a un uso de `d` por todos
  los caminos sin que `d` ni `s` se reescriban, el uso lee `s`; las copias y cualquier instrucción pura
  cuyo resultado nadie lee se borran. lcc copia a un temporal casi todo lo que compara o indexa. Un `EXIT`
  no cuenta como lector de R16..R29 (el hilo desaparece), así que también se va la copia al `texel` de la
  rotación, que nadie lee y que costaba una instrucción por celda: de 1,08 / 1,10 a 1,01 / 1,04 veces el
  ensamblador. `JR`, `HALT` y `TRAP` sí siguen conservándolos.
- **`ssy`** ahora quita el `SSY` que cae siempre después de otro con el mismo destino (la región ya está
  abierta; la GPU deja divergir más de un salto dentro de ella, como en el `if / else if` del cubo).

Instrucciones ejecutadas (simulador) en C frente a ensamblador, antes y después:

| Carga | Ensamblador | C antes | C ahora | antes / ens. | ahora / ens. | mejora |
|---|---:|---:|---:|---:|---:|---:|
| memset 4096 | 3.132 | 3.136 | 2.616 | 1,00 | 0,84 | 1,20x |
| memcpy 4096 | 4.156 | 4.160 | 3.640 | 1,00 | 0,88 | 1,14x |
| fill_rect 64x64 | 3.640 | 3.640 | 3.132 | 1,00 | 0,86 | 1,16x |
| blit 64x64 | 4.796 | 4.800 | 4.292 | 1,00 | 0,89 | 1,12x |
| fill_rect 7x13 (3 warps) | 182 | 182 | 171 | 1,00 | 0,94 | 1,06x |
| blit 7x13 (5 warps) | 257 | 262 | 253 | 1,02 | 0,98 | 1,04x |
| rotación, CPU | 233.806 | 285.125 | 234.564 | 1,22 | 1,00 | 1,22x |
| rotación, GPU inocente (warp) | 29.426 | 42.112 | 29.528 | 1,43 | 1,00 | 1,43x |
| rotación, GPU buena (warp) | 30.864 | 44.272 | 31.024 | 1,43 | 1,01 | 1,43x |
| cubo, CPU | 322.000 | 482.000 | 321.000 | 1,50 | 1,00 | 1,50x |
| cubo, GPU inocente (warp) | 46.170 | 71.449 | 46.000 | 1,55 | 1,00 | 1,55x |
| cubo, GPU buena (warp) | 50.758 | 77.328 | 51.274 | 1,52 | 1,01 | 1,51x |

El cubo (`compare_race.py cube`) corre el demo entero con `race_period = 1`, un método por fotograma, y mide
un fotograma de cada método del segundo giro (fotogramas 3 a 5): la CPU en su método y los warps en los
de GPU (la CPU de esos solo espera). El primer giro se descarta porque el fotograma 0 lleva el arranque
del demo, la generación de las texturas (unas 530.000 instrucciones de CPU en ensamblador y 670.000 en
C): con él, la CPU salía a 1,12 del ensamblador, y no era el método sino el arranque. Los números de CPU
salen redondos porque un fotograma acaba en un cambio de buffer, cada 1.000 instrucciones (±0,3 %). Con
todos los pases, el cubo queda a 1,00 / 1,00 / 1,01 veces el ensamblador (CPU, GPU inocente, GPU buena).

No todo C llega a eso. `compare_race.py life` mide el juego de la vida en la CPU (una generación de 160 x 104) contra
`life.inc`, con dos C del mismo algoritmo: con índices de la rejilla `(y + 1) * 168 + 8 + x` (`race/life.c`) sale a 2,30
veces el ensamblador (1.148.051 frente a 499.839 instrucciones), y con punteros que avanzan y desplazamientos constantes
(`race/life_ptr.c`), a 1,05 (526.289). Sin el pase `strength` era la diferencia entre 2,30 y 1,05: cada acceso a una vecina
costaba 4 instrucciones en vez de 1. Con él, el C con índices baja a 565.761 instrucciones (1,13), con los registros que quedan
libres antes de `licm` (tres punteros).

En los kernels de sistema el C ya ejecuta menos instrucciones que el ensamblador a mano (el ensamblador
del bucle de `gpu_kernels.inc` no saca de él el `MOVI` del desplazamiento). Que sea menos no quiere decir
que tarde menos: son instrucciones, no ciclos, y la mezcla de cargas y ALU es la misma.

Texto, por pase (`mini-opt --stats`; lo que añade o quita; `ssy` añade porque pone regiones que antes no
estaban, y `licm` quita menos de lo que mueve porque cada constante se carga una vez en el preheader):

| Fichero | kernels | licm | ssy | total |
|---|---:|---:|---:|---:|
| `dma/gpu_kernels.c` | -52 | +0 (4 sacadas) | +4 | -52 |
| `race/rotate.c` | -36 | -2 | +3 | -40 |
| `race/cube.c` | -20 | -23 (64 sacadas) | +6 (10 unidas) | -38 |
| `simt/diverge.c` | -14 | -1 | +7 | -11 |

`CSystemKernelsTest` y `CRotateTest` fijan topes a esas proporciones (1,05; y 1,05 / 1,2 / 1,2).

## El cubo en la placa

`race/cube.c` es el demo completo en C: texturas, matriz y caras, anfitrión de vídeo con doble
buffer, método que toca cada 60 fotogramas y gráfica de tiempos. Se compila para la placa 36 con
`--board` (runtime con `RUN` y `bench_now()` con los ciclos de CPU reales):

```text
python examples/c/build.py examples/c/race/cube.c --board        # -> _build/cube_board.bin
run-board --prototype 36 --program 32.cpu-gpu-func-sim/examples/c/_build/cube_board.bin
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

## El plano con logos y alfa

`race/plane.c` es el mismo anfitrión que el cubo con otro dibujo: un plano que gira sobre el eje vertical,
los Autobots delante, los Decepticons detrás, mezclados con alfa sobre un degradado vertical. El cuerpo
(`race/plane_body.h`) se incluye tres veces, como los otros. Como el plano solo gira sobre un eje, `v` no
depende de la columna: cada fila lee una sola fila de textura y solo `u` avanza.

```text
python examples/c/build.py examples/c/race/plane.c --board        # -> _build/plane_board.bin
```

Las texturas salen de `race/plane/logos.png` con `race/plane_tex.py` (dos de 128 × 128 palabras, 128 KiB), que
`build.py` ejecuta y deja tras el código con la etiqueta `plane_tex` (tabla `DATA`; el C la declara `extern`).
Cada palabra es un texel con su alfa: el RGB565 «abierto» (rojo y azul abajo, verde arriba, con huecos) y el
alfa de 0 a 32 en el hueco entre azul y rojo. Así `texel & 0x07E0F81F` ya está abierto y la mezcla con el
fondo de la fila es **una sola multiplicación** para los tres canales. El alfa sale del fondo negro de la
imagen (relleno desde el borde, suavizado al reducir). `python examples/c/race/plane_tex.py --preview v.png`
deja las dos texturas sobre el degradado. La imagen entra completa en el programa: el `.bin` pasa de 170 KiB.

`CPlaneRaceTest` comprueba en el simulador que los tres métodos dibujan, fotograma a fotograma, lo que el
modelo en Python.

## Límites de hoy

- **Hasta 4 parámetros** de 32 bits por kernel (`R1`–`R4`); con más, un puntero a estructura.
- **Un kernel no se puede llamar desde la CPU** (empieza con `GETTID` y acaba con `EXIT`).
- **Sin llamadas dentro de un kernel** (la GPU de la 36 no tiene `JAL`), ni `long long`,
  ni `float`, ni división sin signo.
- **Placa:** solo está probado el cubo (`--board`, runtime con `RUN`, la 36 no tiene `WARP_START`). El plano
  compila y pasa en el simulador, pero no se ha probado en la placa.

Las pruebas son `CKernelTest` y `CDivergenceTest` en `test_cpu_gpu_sim.py` (se omite si no hay compilador: necesita
`y.lcc/build/rcc` y MSVC).
