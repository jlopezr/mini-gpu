/* gpu_kernels.c - los cuatro kernels de sistema de la GPU, en C
 *
 * memset, memcpy, fill_rect y blit con el mismo reparto y el mismo bloque de argumentos que
 * `examples/asm/dma/gpu_kernels.inc` (ensamblador), para comparar instrucciones: ver compare.py.
 *
 *   python examples/c/compare.py
 *
 * Bloque de argumentos (gpu_run): +0 nwarps  +4 nlanes  +8 p0  +12 p1  +16 p2 ...
 *   memset     p0 = dst  p1 = valor  p2 = nwords
 *   memcpy     p0 = dst  p1 = src    p2 = nwords
 *   fill_rect  p0 = dst  p1 = pitch (bytes)  p2 = row_words  p3 = rows  p4 = valor
 *   blit       p0 = dst  p1 = dst_pitch  p2 = src  p3 = src_pitch  p4 = row_words  p5 = rows
 *
 * memset y memcpy reciben sus tres parametros como una funcion de C. fill_rect y blit tienen
 * cinco y seis, mas de los cuatro registros de argumentos, asi que leen el bloque directamente
 * (`__gpu_arg`), como el ensamblador.
 */
#include "../gpu.h"

typedef struct {
    int nwarps, nlanes;
    int p[6];
} Block;

void KERNEL(memset)(int *dst, int value, int n) {
    int i, step = __gpu_nthreads;

    GRID_FOR(i, n, step)
        dst[i] = value;
}

void KERNEL(memcpy)(int *dst, int *src, int n) {
    int i, step = __gpu_nthreads;

    GRID_FOR(i, n, step)
        dst[i] = src[i];
}

/* El warp w hace las filas w, w + nwarps...; dentro de la fila, la lane l las palabras
   l, l + nlanes...: las ocho lanes de un warp estan siempre en la misma fila. */
void KERNEL(fill_rect)(void) {
    Block *b = (Block *)__gpu_arg;
    char *dst = (char *)b->p[0];
    int pitch = b->p[1], row_words = b->p[2], rows = b->p[3], value = b->p[4];
    int nwarps = b->nwarps, nlanes = b->nlanes;
    int row, col;

    for (row = __gpu_lwarp; row < rows; row += nwarps) {
        int *line = (int *)(dst + row * pitch);

        for (col = __gpu_lane; col < row_words; col += nlanes)
            line[col] = value;
    }
}

void KERNEL(blit)(void) {
    Block *b = (Block *)__gpu_arg;
    char *dst = (char *)b->p[0];
    char *src = (char *)b->p[2];
    int dst_pitch = b->p[1], src_pitch = b->p[3], row_words = b->p[4], rows = b->p[5];
    int nwarps = b->nwarps, nlanes = b->nlanes;
    int row, col;

    for (row = __gpu_lwarp; row < rows; row += nwarps) {
        int *to = (int *)(dst + row * dst_pitch);
        int *from = (int *)(src + row * src_pitch);

        for (col = __gpu_lane; col < row_words; col += nlanes)
            to[col] = from[col];
    }
}

int main(void) {
    return 0;
}
