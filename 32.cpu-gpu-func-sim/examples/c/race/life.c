/* life.c - el juego de la vida de examples/asm/race/life.inc, en C "natural": solo la CPU
 *
 *   python examples/c/compare_life.py
 *
 * Es una medida, no un port: se escribe como lo escribiria quien no piensa en el compilador (indices
 * de la rejilla con (y + 1) * STRIDE + 8 + x, la regla con un if, un bucle por eje), para ver cuanto
 * se aleja de life.inc sin trucos. Bloque de argumentos como el de rotate.c: p0 = rejilla actual,
 * p1 = siguiente, p2 = framebuffer (ya en la linea 32), p3 = color de las vivas.
 */
#include "gpu.h"

#define LIFE_COLS 160
#define LIFE_ROWS 104
#define LIFE_STRIDE 168             /* palabras por fila de la rejilla (672 bytes) */
#define LIFE_BLOCK 0x001F0000       /* donde compare_life.py deja el bloque para la CPU */

typedef struct {
    int nwarps, nlanes;
    int p[6];
} Block;

#define CELL(grid, x, y) ((grid)[((y) + 1) * LIFE_STRIDE + 8 + (x)])

void life_cpu(Block *arg) {
    int *cur = (int *)arg->p[0], *next = (int *)arg->p[1], *fb = (int *)arg->p[2];
    int color = arg->p[3];
    int x, y, n, alive;

    for (y = 0; y < LIFE_ROWS; y++) {
        for (x = 0; x < LIFE_COLS; x++) {
            n = CELL(cur, x - 1, y - 1) + CELL(cur, x, y - 1) + CELL(cur, x + 1, y - 1)
              + CELL(cur, x - 1, y)                            + CELL(cur, x + 1, y)
              + CELL(cur, x - 1, y + 1) + CELL(cur, x, y + 1) + CELL(cur, x + 1, y + 1);
            if (CELL(cur, x, y))
                alive = n == 2 || n == 3;
            else
                alive = n == 3;
            CELL(next, x, y) = alive;
            fb[y * 2 * LIFE_COLS + x] = alive ? color : 0;
            fb[y * 2 * LIFE_COLS + LIFE_COLS + x] = alive ? color : 0;
        }
    }
}

int main(void) {
    life_cpu((Block *)LIFE_BLOCK);
    return 0;
}
