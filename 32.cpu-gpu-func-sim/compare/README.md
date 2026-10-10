# compare

Herramientas que miden el C frente al ensamblador con el simulador de la 32. Los programas están en
[`x.tests/cases-cpu-gpu`](../../x.tests/cases-cpu-gpu/README.md).

```text
python 32.cpu-gpu-func-sim/compare/compare.py [--out tabla.md]            # kernels de sistema
python 32.cpu-gpu-func-sim/compare/compare_race.py [rotate|life|blur|cube|all]
python 32.cpu-gpu-func-sim/compare/opt_stats.py [--out tabla.md]          # los pases de mini-opt
```

## C frente a ensamblador

`dma/gpu_kernels.c` reescribe en C los cuatro kernels de sistema (`memset`, `memcpy`, `fill_rect`, `blit`),
con el mismo reparto y el mismo bloque de argumentos que `dma/gpu_kernels.inc`.
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

## Los pases de `mini-opt`, medidos

`python 32.cpu-gpu-func-sim/compare/opt_stats.py` compila los ejemplos con los pases de antes (`intrinsics,kernels,ssy`,
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
`life.inc`, con dos C del mismo algoritmo: con índices de la rejilla `(y + 1) * 168 + 8 + x` (`race/life/life.c`) sale a 2,30
veces el ensamblador (1.148.051 frente a 499.839 instrucciones), y con punteros que avanzan y desplazamientos constantes
(`race/life/life_ptr.c`), a 1,05 (526.289). Sin el pase `strength` era la diferencia entre 2,30 y 1,05: cada acceso a una vecina
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
| `race/rotate/rotate.c` | -36 | -2 | +3 | -40 |
| `race/cube/cube.c` | -20 | -23 (64 sacadas) | +6 (10 unidas) | -38 |
| `simt/diverge/diverge.c` | -14 | -1 | +7 | -11 |

`CSystemKernelsTest` y `CRotateTest` fijan topes a esas proporciones (1,05; y 1,05 / 1,2 / 1,2).
