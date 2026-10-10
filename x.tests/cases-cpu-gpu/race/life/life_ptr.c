/* life_ptr.c - lo mismo que life.c, pero escrito pensando en el compilador: punteros que avanzan
 * y desplazamientos constantes en vez de indices (y + 1) * STRIDE + 8 + x. Es el C que haria quien
 * sabe que lcc no reduce la fuerza de los indices. Ver compare_race.py.
 */
#include "gpu.h"

#define LIFE_COLS 160
#define LIFE_ROWS 104
#define LIFE_STRIDE 168             /* palabras por fila de la rejilla (672 bytes) */
#define LIFE_BLOCK 0x001F0000

typedef struct {
    int nwarps, nlanes;
    int p[6];
} Block;

void life_cpu(Block *arg) {
    int *p = (int *)arg->p[0] + LIFE_STRIDE + 8;        /* celda (0, 0) de la actual */
    int *q = (int *)arg->p[1] + LIFE_STRIDE + 8;        /* la misma en la siguiente */
    int *f = (int *)arg->p[2];
    int color = arg->p[3];
    int x, y, n, alive;

    for (y = 0; y < LIFE_ROWS; y++) {
        for (x = 0; x < LIFE_COLS; x++) {
            n = p[-LIFE_STRIDE - 1] + p[-LIFE_STRIDE] + p[-LIFE_STRIDE + 1]
              + p[-1] + p[1]
              + p[LIFE_STRIDE - 1] + p[LIFE_STRIDE] + p[LIFE_STRIDE + 1];
            if (p[0])
                alive = n == 2 || n == 3;
            else
                alive = n == 3;
            *q = alive;
            f[0] = f[LIFE_COLS] = alive ? color : 0;
            p++;
            q++;
            f++;
        }
        p += LIFE_STRIDE - LIFE_COLS;
        q += LIFE_STRIDE - LIFE_COLS;
        f += LIFE_COLS;
    }
}

int main(void) {
    life_cpu((Block *)LIFE_BLOCK);
    return 0;
}
