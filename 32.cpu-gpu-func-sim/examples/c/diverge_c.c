/* diverge_c.c - kernels en C cuyas lanes toman caminos distintos
 *
 *   python examples/c/build.py examples/c/diverge_c.c
 *   python cpu_gpu_sim.py examples/c/_build/diverge_c.bin
 *
 * Lo que comprueba el pase `ssy` de mini-opt: el compilador no sabe de lanes, asi que es
 * mini-opt quien pone los `SSY` donde los caminos reconvergen. Cada kernel lleva un tipo de
 * divergencia (la prueba esta en CDivergenceTest, test_cpu_gpu_sim.py, contra un modelo en Python):
 *
 *   tail     bucle cuyo numero de vueltas no es multiplo de los hilos: las lanes salen
 *            en vueltas distintas
 *   parity   if / else segun el id del hilo
 *   steps    bucle con un numero de vueltas distinto por lane (while)
 *   guard    `if (id >= n) return;`, la salida anticipada
 *   nested   dos bucles, el interior con `break`
 */
#include "gpu.h"

#define N 1000                      /* no es multiplo de 32 hilos */
#define THREADS 32

int tail[N + 16];                   /* los 16 ultimos, de guarda */
int parity[THREADS];
int steps[THREADS];
int guard[THREADS + 8];             /* los 8 ultimos, de guarda */
int nested[THREADS];
int status[5];

void KERNEL(tail)(int *dst, int value, int n) {
    int i, step = __gpu_nthreads;

    GRID_FOR(i, n, step)
        dst[i] = value;
}

void KERNEL(parity)(int *out) {
    int id = __gpu_tid;

    if (id & 1)
        out[id] = id * 3;
    else
        out[id] = id + 100;
}

/* pasos hasta que el valor llega a 1: x/2 si es par, x+1 si es impar (no es Collatz) */
void KERNEL(steps)(int *out) {
    int id = __gpu_tid;
    int x = id + 1, count = 0;

    while (x > 1) {
        if (x & 1)
            x = x + 1;
        else
            x = x >> 1;
        count = count + 1;
    }
    out[id] = count;
}

void KERNEL(guard)(int *out, int n) {
    int id = __gpu_tid;

    if (id >= n)
        return;
    out[id] = id * id + 1;
}

/* cuantas parejas (a, b) con a < id % 7 + 1 y b < 6 hasta que a * b >= 10: cuenta hasta el break */
void KERNEL(nested)(int *out) {
    int id = __gpu_tid;
    int limit = (id & 7) + 1, a, b, count = 0;

    for (a = 0; a < limit; a++) {
        for (b = 0; b < 6; b++) {
            if (a * b >= 10)
                break;
            count = count + 1;
        }
    }
    out[id] = count;
}

int main(void) {
    int i;

    status[0] = GPU_RUN(tail, 4, tail, 0xABCD, N);
    status[1] = GPU_RUN(parity, 4, parity);
    status[2] = GPU_RUN(steps, 4, steps);
    for (i = 0; i < THREADS + 8; i++)
        guard[i] = 0x5555;
    status[3] = GPU_RUN(guard, 4, guard, 21);
    status[4] = GPU_RUN(nested, 4, nested);
    return 0;
}
