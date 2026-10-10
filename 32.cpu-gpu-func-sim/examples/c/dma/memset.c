/* memset.c - el primer programa en C con CPU y GPU en el mismo fichero
 *
 *   build-c 32.cpu-gpu-func-sim/examples/c/dma/memset.c
 *   python cpu_gpu_sim.py ../_build/c/memset.bin
 *
 * El kernel rellena `buffer` con un valor desde 4 warps de la GPU; la CPU lo lanza con una
 * sola llamada. A diferencia de los ejemplos de examples/asm, que estan en
 * ensamblador, esto es C compilado con mini-lcc (ver tools/build_c.py). La comprobacion esta en
 * CKernelTest (test_cpu_gpu_sim.py).
 */
#include "gpu.h"

#define N 4096
#define VALUE 0xABCD

int buffer[N + 16];         /* los 16 ultimos quedan a cero: lo que no debe tocar la GPU */
int status;

void KERNEL(memset)(int *dst, int value, int n) {
    int i, step = __gpu_nthreads;

    GRID_FOR(i, n, step)
        dst[i] = value;
}

int main(void) {
    status = GPU_RUN(memset, 4, buffer, VALUE, N);
    return status;
}
