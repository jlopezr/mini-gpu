/* memset.c - el primer programa en C con CPU y GPU en el mismo fichero
 *
 *   build-c x.tests/cases-cpu-gpu/dma/memset/memset.c
 *   python cpu_gpu_sim.py ../_build/c/memset.bin
 *
 * El kernel rellena `buffer` con un valor desde 4 warps de la GPU; la CPU lo lanza con una
 * sola llamada. A diferencia de los demas programas de x.tests/cases-cpu-gpu, que estan en
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
    int i;

    status = GPU_RUN(memset, 4, buffer, VALUE, N);
    if (status != GPU_OK)
        return status;
    for (i = 0; i < N; i++)
        if (buffer[i] != VALUE)
            return 10;
    for (; i < N + 16; i++)
        if (buffer[i] != 0)
            return 11;
    return 0;
}
