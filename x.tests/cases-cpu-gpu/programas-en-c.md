# Programas en C con CPU y GPU

Casi todos los programas de esta carpeta están en ensamblador; los de C se compilan con `mini-lcc`. Un mismo `.c`
lleva el código de la CPU (`main`) y los kernels de la GPU:

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
build-c x.tests/cases-cpu-gpu/dma/memset/memset.c          # -> _build/c/memset.bin (en la raíz del repo)
python 32.cpu-gpu-func-sim/cpu_gpu_sim.py _build/c/memset.bin
```

## El sistema y `build-c`

El sistema no está en los ejemplos sino en `x.tests`: las cabeceras `gpu.h` y `mmio.h` en `x.tests/inc/` (junto a
`mmio.inc`, el mismo mapa MMIO para el ensamblador) y `gpu.c` en `x.tests/runtime/gpu/`. `build-c`
(`tools/build_c.py`) pasa esa carpeta de cabeceras a `mini-lcc -I`, así que los ejemplos solo escriben
`#include "gpu.h"`, y compila `gpu.c` junto a cada programa. Las herramientas que comparan el C con el
ensamblador (`compare.py`, `compare_race.py`, `opt_stats.py`) están en
[`32.cpu-gpu-func-sim/compare`](../../32.cpu-gpu-func-sim/compare/README.md). Las salidas de la compilación van a
`_build/c/` en la raíz del repo (ignorada por git) o a donde diga `--outdir`.

`build-c` acepta cualquier `.c`, no solo los de esta carpeta:

```text
build-c programa.c [-o salida.bin] [--outdir DIR] [-I DIR]... [--data ETIQUETA=FICHERO]... [--board]
```

Las carpetas de programa que contienen C tienen además un `Makefile` fino. Desde la carpeta del programa,
con GNU Make y el entorno Python del repositorio activo:

```text
make          # construye la imagen para el simulador
make sim      # ejecuta el programa en el simulador apropiado
make debug    # abre el programa en mini-dbg
make compare  # ejecuta su comparativa o validacion contra el modelo
make run      # construye para BOARD y carga la imagen en la placa 36
```

Los `Makefile` solo declaran el nombre, los datos generados y las opciones particulares; las recetas comunes
están en `tools/c-program.mk` y llaman a los lanzadores Python directamente. No dependen de Bash, PowerShell ni
de extensiones `.ps1`, por lo que el mismo fichero sirve con GNU Make en Windows y Linux. `PYTHON` y `PROTOTYPE`
se pueden sustituir en la invocación (`make PYTHON=python3`, `make run PROTOTYPE=37`). Cada Makefile obtiene
`BASE` con `git rev-parse --show-toplevel`; también puede indicarse expresamente con `make BASE=/ruta/mini-gpu`.

`blur.c`, `life.c` y `rotate.c` no son aplicaciones autónomas: son cargas a las que el comparador inyecta datos.
En ellas `make compare` llama a `compare_race.py` para comprobar la implementación C; `make sim`, `make debug`
y `make run` usan el demo `.asm` completo de la misma carpeta, que aporta el anfitrión de vídeo y prepara la
memoria. No cargan directamente el binario C con punteros sin inicializar, que terminaría en
`ERROR_MEMORY_ACCESS`.

`--data` pega un binario tras el código con `.incbin`, bajo una etiqueta que el C declara con `extern unsigned
etiqueta[]`. `build-c` no genera datos: quien llama los prepara antes (ver [plane](race/plane/README.md)). `--board` define
`BOARD` para el ensamblador (`.define BOARD`), que activa en `gpu_runtime.inc` y `bench.inc` las ramas de la
placa 36 (lanzar con `RUN`, ciclos de CPU reales).

## Cómo funciona

- **`KERNEL(nombre)`** pone `__kernel_nombre` al nombre de la función. Es la marca que lee
  `mini-opt`: lcc no tiene atributos.
- **`mini-opt`** (pases `intrinsics` y `kernels`, ver `tools/README.md`) convierte esa función en
  el punto de entrada de una lane: carga los parámetros que el kernel lee desde el bloque de
  argumentos (`GETARG`) y sustituye el `JR R31` final por `EXIT`. Un kernel no escribe en ese bloque mientras corre (como la
  memoria constante de CUDA): `mini-opt` se apoya en eso para no releerlo en cada vuelta de un bucle (pase `argblock`).
  Quien necesite devolver resultados lo hace por un puntero que reciba en el bloque, no en el bloque.
  Para decirle además que un puntero no tiene alias (lo que en C99 sería `restrict`) está `NOALIAS(p);` en `gpu.h`. Quita además el marco de
  pila que lcc monta para guardar y restaurar registros preservados, que a un kernel no le
  sirve (nadie recibe esos registros de vuelta). Solo si el kernel usa la pila de verdad (un
  array local, un derrame) fija la de su lane (`__gpu_stack`, 512 bytes por lane). Además cambia los desplazamientos con cantidad inmediata
  (`SHLI`) por los de registro, que son los únicos que tiene la GPU, y da un error si el
  kernel usa una instrucción que la GPU no ejecuta.
- **`GPU_RUN(nombre, warps, parámetros...)`** llama a `gpu_launch` (`x.tests/runtime/gpu/gpu.c`), que rellena el
  bloque de argumentos y llama a `gpu_run` de `x.tests/inc/gpu_runtime.inc` (el runtime de
  ensamblador de siempre). Lanza y espera.
- **El arranque** es `1.isa/runtime/crt0.s`; `build-c` compila con `mini-lcc --no-crt`.
- **La divergencia no se escribe:** un `if`, un `while` o un `break` cuyas lanes tomen
  caminos distintos necesita una región abierta con `SSY` (si no, `ERROR_SIMT`). Los pone
  el pase `ssy` de `mini-opt`: delante de cada salto que puede divergir, con el punto donde
  se juntan todos los caminos (su postdominador inmediato) como destino; en un bucle, una
  sola vez antes del bucle. Solo marca los saltos que dependen de `GETTID`/`GETLANE` (o de lo
  que se calcula bajo un salto así); `mini-opt --ssy-all` los marca todos.

## Las tres versiones de una demo: CPU, GPU inocente y GPU buena

`GRID_FOR` es solo el reparto más sencillo para una dimensión. Lo que distingue a la GPU inocente de
la buena en [`race`](race/README.md) no es un bucle distinto: es **qué hilo hace qué trozo del trabajo**. En C
se ve así: el cuerpo se escribe una sola vez (`race/rotate/rotate_body.h`) y cada versión lo incluye con cuatro
expresiones distintas, la fila y la columna por la que empieza el hilo y de cuánto en cuánto salta:

| | filas: primera, paso | columnas: primera, paso | qué escriben las 8 lanes de un warp |
|---|---|---|---|
| CPU | 0, 1 | 0, 1 | (un solo hilo) |
| GPU inocente | `__gpu_tid`, todos los hilos | 0, 1 | ocho filas distintas, a 1280 B unas de otras |
| GPU buena | `__gpu_lwarp`, todos los warps | `__gpu_lane`, las lanes de un warp | ocho palabras seguidas |

`race/rotate/rotate.c` define esos valores tres veces con `#define`, incluye el cuerpo, y los deshace. La fila
`GRID_FOR(i, n, step)` de arriba es el caso unidimensional de la GPU buena: primera = `__gpu_tid`,
paso = `__gpu_nthreads`. Para una imagen se aplican dos veces, una por la fila y otra por la columna.

El cuerpo no puede ser una función que llame a otra: la GPU de la 36 no tiene `JAL`, así que lcc no
puede enlazar la llamada dentro de un kernel, y lcc no expande funciones en línea. De ahí la
plantilla por `#include`.

## Límites de hoy

- **Hasta 4 parámetros** de 32 bits por kernel (`R1`–`R4`); con más, un puntero a estructura.
- **Un kernel no se puede llamar desde la CPU** (empieza con `GETTID` y acaba con `EXIT`).
- **Sin llamadas dentro de un kernel** (la GPU de la 36 no tiene `JAL`), ni `long long`,
  ni `float`, ni división sin signo.
- **Placa:** solo está probado el cubo (`--board`, runtime con `RUN`, la 36 no tiene `WARP_START`). El plano
  compila y pasa en el simulador, pero no se ha probado en la placa.

Las pruebas son `CKernelTest` y `CDivergenceTest` en `test_cpu_gpu_sim.py` (se omite si no hay compilador: necesita
`y.lcc/build/rcc` y MSVC).
