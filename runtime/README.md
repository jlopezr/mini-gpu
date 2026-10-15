# runtime — código compartido por los programas

Cabeceras de C, trozos de ensamblador y el runtime de la GPU que usan los programas del repositorio. Estaba en
`t.tests/inc`, `t.tests/runtime` y `1.isa/runtime`; lo usan también `20.forth`, `2.cpu-sim-func`, `mini-cc` y los
ensambladores, así que no es de los tests.

```text
runtime/
  include/    lo que se incluye y no emite nada
  src/        código: lo que se pasa a mini-cc o se incluye en línea
```

La regla para elegir carpeta: **si emite bytes, va en `src/`**. `mmio.inc` solo tiene `.equ`, así que es el
equivalente en ensamblador de una cabecera; `drawline.inc` o `gpu_runtime.inc` contienen código y son fuentes.
Cuando haya enlazador, `src/` se compilará a `lib/` (objetos y bibliotecas), como en Unix; hoy no existe. Y cuando
una carpeta crezca, se divide en subcarpetas (`include/gpu/`…), con los nombres de cabecera con su prefijo.

## `include/`

| Fichero | Qué es |
|---|---|
| [`mmio.inc`](include/mmio.inc) | Las constantes del mapa MMIO para el ensamblador (`.equ`). **Generado** por `generate-mmio` desde `1.isa/mmio_map.vh` |
| [`mmio_map.h`](include/mmio_map.h) | Las mismas, para C (`#define`). **Generado** |
| [`mmio.h`](include/mmio.h) | Pone los nombres cortos (`VIDEO_SWAP`…) sobre `mmio_map.h` |
| [`gpu.h`](include/gpu.h) | `KERNEL`, `GPU_RUN`, `NOALIAS`, las variables `__gpu_*` |
| [`stdint.h`](include/stdint.h), [`stdbool.h`](include/stdbool.h) | Tipos de anchura fija y `bool` para `mini-lcc`. La librería de lcc no los trae, y sin ellos `cc -E` cogería los del sistema, que lcc no entiende. Aquí `bool` es un `int`, porque C89 no tiene `_Bool` |

## `src/`

| Fichero | Qué define | Depende de |
|---|---|---|
| [`crt0.s`](src/crt0.s) | `_start`: pone la pila, llama a `main` y para | — |
| [`gpu.c`](src/gpu.c) | `gpu_launch` y `__gpu_stack`, los 32 KiB de pila de las lanes de los kernels | `gpu.h`, `gpu_runtime.inc` |
| [`gpu_runtime.inc`](src/gpu_runtime.inc) | `gpu_run`: la CPU lanza un job en la GPU y lo espera | `mmio.inc`; con `BOARD`, la placa 36 |
| [`bench.inc`](src/bench.inc) | `bench_init`, `bench_now`: los ciclos de CPU (cero en los simuladores) | `mmio.inc`; con `BOARD`, la placa |
| [`putpixel.inc`](src/putpixel.inc) | `putpixel` | `R1` = buffer trasero, `R24` = 640 |
| [`drawline.inc`](src/drawline.inc) | `drawline`, Bresenham de ocho octantes | `putpixel.inc`, que incluye él solo |
| [`sin256.inc`](src/sin256.inc) | `sin_table`, 256 entradas Q16.16 en `.rodata` | — |

`mini-cc` pone `crt0.s` solo. El runtime de la GPU se pide: `gpu.c`, `gpu_runtime.inc` y `bench.inc` (en los
Makefile, `$(GPU_RUNTIME)`). Un programa que no lanza trabajos en la GPU desde C no los necesita.

`gpu_runtime.inc` y `bench.inc` tienen una rama para la placa 36 y otra para los simuladores. Se elige con el
símbolo `BOARD`, antes del `.include`: `-D BOARD` en la línea de órdenes del ensamblador (así lo hacen `run-board`,
siempre, y `mini-cc --board`) o `.define BOARD` en el propio `.asm`. Un `.asm` que valga para el simulador y para la
placa no necesita variante `_board`: usa `.ifdef BOARD` para lo que sea solo de la placa y no repite el `.define`.

## Cómo se buscan

Primero la carpeta del fichero que incluye, y **después** las carpetas de `-I`. Ese orden importa: un trozo local
con el mismo nombre tiene que ganar al compartido, o cambiar algo aquí rompería programas ajenos en silencio.

`runtime/include` y `runtime/src` van siempre en el `-I` del ensamblador (`run-board`, `run_tests.py`,
`mini-dbg`, `mini-cc`…); el compilador de C solo mira `runtime/include`. Desde un `.asm` o un `.c` del repo basta
con el nombre:

```asm
    .include "drawline.inc"     ; arrastra putpixel.inc por su cuenta
```

Las dos rutas están definidas en un solo sitio, [`1.isa/runtime_dirs.py`](../1.isa/runtime_dirs.py)
(`ASM_INCLUDE_DIRS`, `C_INCLUDE_DIRS`); lo que ya usa `mini_asm` lo importa de ahí. A mano, o desde fuera de los
lanzadores:

```bash
python 1.isa/mini_asm.py mi_programa.asm -I runtime/include -I runtime/src
```

## Dos cosas que hay que tener en la cabeza

**No hay espacios de nombres.** Las etiquetas de lo incluido son globales para todo el programa: `drawline`,
`dx_ready`, `line_step`, `putpixel`, `sin_table`… Cada `.inc` las lista en su cabecera. Un choque no pasa
desapercibido — el ensamblador dice los dos sitios:

```text
cube.asm:212: label duplicado: putpixel (ya definido en putpixel.inc:23)
```

**Los `.inc` que se incluyen en línea llevan `.once`**, así que uno puede arrastrar sus dependencias sin chocar con
el programa que también las incluya. `.once` lo pone el fichero incluido, no quien lo incluye: ser idempotente es
una propiedad suya, y así no hay que acordarse en cada sitio.

`putpixel.inc` y `drawline.inc` siguen siendo dos ficheros y no uno porque `bresenham_circles.asm` usa `putpixel` pero
no `drawline`, y así no se lleva código muerto.

## Al cambiar algo de aquí

Estos ficheros están en el camino de los casos de `t.tests`, así que un cambio se comprueba con la suite entera, no
sólo con el programa que se estaba tocando:

```bash
python t.tests/run_tests.py --backend sim-cpu t.tests/cases-cpu/video t.tests/cases-cpu/programs
test-board --prototype 21 -y t.tests/cases-cpu/video
```

Cuando el cambio pretende **no** alterar el código generado —como el que creó esta carpeta, y como moverla— lo que
hay que verificar es que el binario sale idéntico, que es más fuerte que pasar los tests:

```bash
python 1.isa/mini_asm.py <programa>.asm -o nuevo.bin -I runtime/include -I runtime/src
# y comparar nuevo.bin contra el de antes
```
