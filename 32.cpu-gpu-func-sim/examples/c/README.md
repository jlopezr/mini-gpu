# Programas en C con CPU y GPU

A diferencia de `examples/dma`, `examples/race` y `examples/render`, que están en
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
python examples/c/build.py examples/c/memset_c.c        # -> examples/c/_build/memset_c.bin
python cpu_gpu_sim.py examples/c/_build/memset_c.bin
```

## Cómo funciona

- **`KERNEL(nombre)`** pone `__kernel_nombre` al nombre de la función. Es la marca que lee
  `mini-opt`: lcc no tiene atributos.
- **`mini-opt`** (pases `intrinsics` y `kernels`, ver `tools/README.md`) convierte esa función en
  el punto de entrada de una lane: fija su pila (`__gpu_stack`, 512 bytes por lane), carga los
  parámetros que el kernel lee desde el bloque de argumentos (`GETARG`) y sustituye el
  `JR R31` final por `EXIT`. Además cambia los desplazamientos con cantidad inmediata
  (`SHLI`) por los de registro, que son los únicos que tiene la GPU, y da un error si el
  kernel usa una instrucción que la GPU no ejecuta.
- **`GPU_RUN(nombre, warps, parámetros...)`** llama a `gpu_launch` (`gpu.c`), que rellena el
  bloque de argumentos y llama a `gpu_run` de `examples/dma/gpu_runtime.inc` (el runtime de
  ensamblador de siempre). Lanza y espera.
- **El arranque** es `1.isa/runtime/crt0.s`; `build.py` compila con `mini-lcc --no-crt`.

## Límites de hoy

- **Hasta 4 parámetros** de 32 bits por kernel (`R1`–`R4`); con más, un puntero a estructura.
- **Un kernel no se puede llamar desde la CPU** (empieza con `GETTID` y acaba con `EXIT`).
- **Sin `SSY` automático todavía:** un bucle o un `if` que haga que las lanes de un warp
  tomen caminos distintos acaba en `ERROR_SIMT`. `memset_c` no diverge porque `n` es múltiplo
  de los hilos del lanzamiento (4096 entre 32).
- **Sin llamadas dentro de un kernel** (la GPU de la 36 no tiene `JAL`), ni `long long`,
  ni `float`, ni división sin signo.
- **Sólo el simulador de la 32** está probado; en la placa falta el lanzamiento con `RUN`
  de `gpu_runtime_board.inc` (la 36 no tiene `WARP_START`).

La prueba es `CKernelTest` en `test_cpu_gpu_sim.py` (se omite si no hay compilador: necesita
`y.lcc/build/rcc` y MSVC).
