/* calls.c - un kernel escrito con funciones auxiliares
 *
 *   build-c t.tests/cases-cpu-gpu/simt/calls/calls.c
 *   python 32.cpu-gpu-func-sim/cpu_gpu_sim.py _build/c/calls.bin
 *
 * La GPU no tiene JAL: el pase `kernelcalls` de mini-opt expande en el kernel cada llamada, con el cuerpo entero
 * de la funcion (marco incluido). Aqui hay de todo lo que eso tiene que respetar: una hoja pequena, una funcion con
 * seis parametros (dos van por la pila), una con un bucle que usa registros preservados, una con un array local
 * cuya direccion se toma, llamadas anidadas y una llamada dentro de un `if` que depende de la lane. La CPU calcula
 * lo mismo con las mismas funciones, llamadas de verdad, y main devuelve cuantos resultados no coinciden.
 */
#include "gpu.h"

#define THREADS 32

int gpu_out[THREADS];

/* % es REM, que la GPU de la 36 no tiene: con DIV */
static int mod(int a, int b) {
    return a - a / b * b;
}

static int clamp(int v, int lo, int hi) {
    return v < lo ? lo : v > hi ? hi : v;
}

static int weighted(int a, int b, int c, int d, int e, int f) {
    return a + 2 * b + 3 * c + 4 * d + 5 * e + 6 * f;
}

static int sum_to(int n) {
    int i, s = 0, t = 1, u = 2, v = 3;
    for (i = 0; i < n; i++) {
        s += i * t;
        t = t + u;
        u = u ^ v;
        v = v + i;
    }
    return s + t + u + v;
}

static int table_sum(int k) {
    int table[6], i, s = 0;
    int *p = table;
    for (i = 0; i < 6; i++) p[i] = k * i - 3;
    for (i = 0; i < 6; i++) s += table[i] * (i + 1);
    return s;
}

static int combine(int x, int y) {
    return clamp(weighted(x, y, x - y, 7, -x, y * 2), -500, 5000) + table_sum(y);
}

static int value(int id) {
    int r = combine(id, sum_to(mod(id, 7)));
    if (id & 1) /* divergente: solo las lanes impares llaman */
        r += table_sum(id) - sum_to(mod(id, 5));
    return r;
}

void KERNEL(calls)(int *out) {
    int id = __gpu_tid;
    out[id] = value(id);
}

int main(void) {
    int i, bad = 0;
    GPU_RUN(calls, THREADS / 8, gpu_out);
    for (i = 0; i < THREADS; i++)
        if (gpu_out[i] != value(i)) bad++;
    return bad;
}
