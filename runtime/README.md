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
| [`string.h`](include/string.h) | La biblioteca C mínima: memoria (`memset`, `memcpy`, `memcmp`) y cadenas (`strlen`, `strcmp`, `strncmp`, `strncpy`, `strrchr`, `strstr`). Se añade lo que algún programa vaya necesitando. La implementación es [`string.c`](src/string.c) |
| [`stdlib.h`](include/stdlib.h) | Utilidades (`atoi`, `abs`, `exit`) y heap freestanding (`mini_heap_init`, `malloc`, `free`, `calloc`, `realloc`). `exit` conserva su estado y ejecuta `HALT`. |
| [`ctype.h`](include/ctype.h) y [`strings.h`](include/strings.h) | Utilidades ASCII (`toupper`, `tolower`, `isspace`, `isprint`, `isalpha`, `isdigit`) y extensiones POSIX (`bzero`, `strcasecmp`, `strncasecmp`). |
| [`stdio.h`](include/stdio.h), [`console.h`](include/console.h) | Formatter mínimo (`printf`, `snprintf`) con salida serie por defecto; consola HDMI y espejo serie+consola como destinos explícitos. |
| [`audio.h`](include/audio.h) | Ring PCM S16 estéreo a 48 kHz. El productor C publica `write_index`; el futuro dispositivo HDMI actualizará `read_index`. |

## `src/`

| Fichero | Qué define | Depende de |
|---|---|---|
| [`crt0.s`](src/crt0.s) | `_start`: pone la pila, llama a `main` y para | — |
| [`gpu.c`](src/gpu.c) | `gpu_launch` y `__gpu_stack`, los 32 KiB de pila de las lanes de los kernels | `gpu.h`, `gpu_runtime.inc` |
| [`gpu_runtime.inc`](src/gpu_runtime.inc) | `gpu_run`: la CPU lanza un job en la GPU y lo espera | `mmio.inc`; con `BOARD`, la placa 36 |
| [`rop.h`](include/rop.h), [`rop.inc`](src/rop.inc) | API C y rutinas MiniABI para FILL, COPY, GENERATE, SPAN y CONFIG del ROP | capability `rop`, CPU 38 |
| [`bench.inc`](src/bench.inc) | `bench_init`, `bench_now`: los ciclos de CPU (cero en los simuladores) | `mmio.inc`; con `BOARD`, la placa |
| [`string.c`](src/string.c) | Memoria y cadenas de `string.h`. Código de CPU | `string.h` |
| [`stdlib.c`](src/stdlib.c) | Utilidades y heap con lista libre coalescente, inicializado sobre una arena del programa | `stdlib.h`, `string.h` |
| [`stdio.c`](src/stdio.c) | Formatter y sinks de texto serie, consola HDMI o buffer | `stdio.h`, `console.h`, `mmio.h` |
| [`audio.c`](src/audio.c) | Operaciones C89 del ring PCM, sin MMIO ni backend específico | `audio.h` |
| [`putpixel.inc`](src/putpixel.inc) | `putpixel` | `R1` = buffer trasero, `R24` = 640 |
| [`drawline.inc`](src/drawline.inc) | `drawline`, Bresenham de ocho octantes | `putpixel.inc`, que incluye él solo |
| [`sin256.inc`](src/sin256.inc) | `sin_table`, 256 entradas Q16.16 en `.rodata` | — |

`mini-cc` pone `crt0.s` solo. El runtime de la GPU se pide: `gpu.c`, `gpu_runtime.inc` y `bench.inc` (en los
Makefile, `$(GPU_RUNTIME)`). Un programa que no lanza trabajos en la GPU desde C no los necesita.

`gpu_runtime.inc` y `bench.inc` tienen una rama para la placa 36 y otra para los simuladores. Se elige con el
símbolo `BOARD`, antes del `.include`: `-D BOARD` en la línea de órdenes del ensamblador (así lo hacen `run-board`,
siempre, y `mini-cc --board`) o `.define BOARD` en el propio `.asm`. Un `.asm` que valga para el simulador y para la
placa no necesita variante `_board`: usa `.ifdef BOARD` para lo que sea solo de la placa y no repite el `.define`.

### ROP desde C

`rop.h` declara descriptores y funciones con ABI C; `rop.inc` implementa las
rutas cortas en ensamblador. El C no necesita conocer `P0`–`P9`: cada
`rop_submit_*()` toma un puntero a descriptor, carga los parámetros y encola
el trabajo. Es asíncrono; termina con `rop_wait()` o `rop_wait_invalidate()` si
la CPU va a leer memoria que haya escrito el ROP.

La API no relaja las restricciones del hardware: `FILL` y `COPY` requieren
direcciones, anchos y strides múltiplos de 16; `SPAN` tiene las alineaciones de
píxel que fija `isa.md` §7.5. Los descriptores no se validan en software: un
error de ese tipo es asíncrono y aparece en el siguiente `rop_wait*`.

`rop_submit_copy_fenced()` es la variante que hay que usar si la CPU acaba de
escribir el origen: emite `ROPSUBMIT.F` y confirma esos `STORE` antes de que el
ROP lea `src`. El `rop_submit_copy()` normal evita esa espera cuando el origen
ya era visible para el ROP.

```c
#include "rop.h"

rop_fill_t clear = { framebuffer, bytes_per_row, rows, bytes_per_row, 0, 0 };
rop_submit_fill(&clear);
rop_wait_invalidate();
```

Incluye `rop.inc` una vez al ensamblar el programa que use estas funciones. La
fuente lleva `.once`, por lo que puede ser dependencia transitiva de otros
trozos del runtime sin duplicar símbolos. `mode` y `groups` son `rop_u32` (una
palabra de MiniABI), de modo que la CPU valida el valor entero de `PMODE`.

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
