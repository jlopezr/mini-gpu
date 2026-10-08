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
  el punto de entrada de una lane: carga los parámetros que el kernel lee desde el bloque de
  argumentos (`GETARG`) y sustituye el `JR R31` final por `EXIT`. Quita además el marco de
  pila que lcc monta para guardar y restaurar registros preservados, que a un kernel no le
  sirve (nadie recibe esos registros de vuelta). Solo si el kernel usa la pila de verdad (un
  array local, un derrame) fija la de su lane (`__gpu_stack`, 512 bytes por lane). Además cambia los desplazamientos con cantidad inmediata
  (`SHLI`) por los de registro, que son los únicos que tiene la GPU, y da un error si el
  kernel usa una instrucción que la GPU no ejecuta.
- **`GPU_RUN(nombre, warps, parámetros...)`** llama a `gpu_launch` (`gpu.c`), que rellena el
  bloque de argumentos y llama a `gpu_run` de `examples/dma/gpu_runtime.inc` (el runtime de
  ensamblador de siempre). Lanza y espera.
- **El arranque** es `1.isa/runtime/crt0.s`; `build.py` compila con `mini-lcc --no-crt`.
- **La divergencia no se escribe:** un `if`, un `while` o un `break` cuyas lanes tomen
  caminos distintos necesita una región abierta con `SSY` (si no, `ERROR_SIMT`). Los pone
  el pase `ssy` de `mini-opt`: delante de cada salto que puede divergir, con el punto donde
  se juntan todos los caminos (su postdominador inmediato) como destino; en un bucle, una
  sola vez antes del bucle. Solo marca los saltos que dependen de `GETTID`/`GETLANE` (o de lo
  que se calcula bajo un salto así); `mini-opt --ssy-all` los marca todos.

## Los ejemplos

- **`memset_c.c`**: el kernel más sencillo, sin divergencia (`n` es múltiplo de los hilos).
- **`diverge_c.c`**: cinco kernels con divergencia: un bucle cuyas lanes salen en vueltas
  distintas, `if`/`else` por id de hilo, un `while` con un número de vueltas distinto por
  lane, una salida anticipada y dos bucles anidados con `break`. Se comprueban contra un
  modelo en Python (`CDivergenceTest`).

## C frente a ensamblador

`sysk_c.c` reescribe en C los cuatro kernels de sistema (`memset`, `memcpy`, `fill_rect`, `blit`),
con el mismo reparto y el mismo bloque de argumentos que `examples/dma/gpu_kernels.inc`.
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

## Límites de hoy

- **Hasta 4 parámetros** de 32 bits por kernel (`R1`–`R4`); con más, un puntero a estructura.
- **Un kernel no se puede llamar desde la CPU** (empieza con `GETTID` y acaba con `EXIT`).
- **Sin llamadas dentro de un kernel** (la GPU de la 36 no tiene `JAL`), ni `long long`,
  ni `float`, ni división sin signo.
- **Sólo el simulador de la 32** está probado; en la placa falta el lanzamiento con `RUN`
  de `gpu_runtime_board.inc` (la 36 no tiene `WARP_START`).

Las pruebas son `CKernelTest` y `CDivergenceTest` en `test_cpu_gpu_sim.py` (se omite si no hay compilador: necesita
`y.lcc/build/rcc` y MSVC).
