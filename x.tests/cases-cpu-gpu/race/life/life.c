/* life.c - el juego de la vida de x.tests/cases-cpu-gpu/race/life/life.inc, en C "natural": CPU, GPU inocente y GPU buena
 *
 *   python 32.cpu-gpu-func-sim/compare/compare_race.py life
 *
 * El cuerpo esta en life_body.h, una sola vez; este fichero lo incluye tres veces con otro reparto de
 * trabajo entre hilos (ver la tabla de rotate_body.h). Bloque de argumentos como el de rotate.c: p0 = rejilla
 * actual, p1 = siguiente, p2 = framebuffer (ya en la linea 32), p3 = color de las vivas.
 */
#include "gpu.h"

#define LIFE_COLS 160
#define LIFE_ROWS 104
#define LIFE_STRIDE 168             /* palabras por fila de la rejilla (672 bytes) */
#define LIFE_BLOCK 0x001F0000       /* donde compare_race.py deja el bloque para la CPU */

typedef struct {
    int nwarps, nlanes;
    int p[6];
} Block;

/* ---- la CPU: una sola pasada ---- */
#define NAME life_cpu
#define DECLARE_ARGS (Block *arg)
#define BLOCK arg
#define ROW_FIRST 0
#define ROW_STEP 1
#define COL_FIRST 0
#define COL_STEP 1
#include "life_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- la GPU inocente: un hilo por fila ---- */
#define NAME KERNEL(life_naive)
#define DECLARE_ARGS (void)
#define BLOCK ((Block *)__gpu_arg)
#define ROW_FIRST __gpu_tid
#define ROW_STEP (BLOCK->nwarps * BLOCK->nlanes)
#define COL_FIRST 0
#define COL_STEP 1
#include "life_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- la GPU buena: un warp por fila, una lane por columna de cada ocho ---- */
#define NAME KERNEL(life_good)
#define DECLARE_ARGS (void)
#define BLOCK ((Block *)__gpu_arg)
#define ROW_FIRST __gpu_lwarp
#define ROW_STEP (BLOCK->nwarps)
#define COL_FIRST __gpu_lane
#define COL_STEP (BLOCK->nlanes)
#include "life_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

int main(void) {
    life_cpu((Block *)LIFE_BLOCK);
    return 0;
}
