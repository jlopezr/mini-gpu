/* blur.c - la difusion de calor de x.tests/cases-cpu-gpu/race/blur/blur.inc, en C "natural": CPU, GPU inocente y GPU buena
 *
 *   python 32.cpu-gpu-func-sim/compare/compare_race.py blur
 *
 * Igual que life.c: el cuerpo esta en blur_body.h. Bloque de argumentos: p0 = rejilla actual, p1 = siguiente,
 * p2 = framebuffer (ya en la linea 32).
 */
#include "gpu.h"

#define BLUR_COLS 160
#define BLUR_ROWS 104
#define BLUR_STRIDE 168             /* palabras por fila de la rejilla (672 bytes) */
#define BLUR_BLOCK 0x001F0000       /* donde compare_race.py deja el bloque para la CPU */

typedef struct {
    int nwarps, nlanes;
    int p[6];
} Block;

#define NAME blur_cpu
#define DECLARE_ARGS (Block *arg)
#define BLOCK arg
#define ROW_FIRST 0
#define ROW_STEP 1
#define COL_FIRST 0
#define COL_STEP 1
#include "blur_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

#define NAME KERNEL(blur_naive)
#define DECLARE_ARGS (void)
#define BLOCK ((Block *)__gpu_arg)
#define ROW_FIRST __gpu_tid
#define ROW_STEP (BLOCK->nwarps * BLOCK->nlanes)
#define COL_FIRST 0
#define COL_STEP 1
#include "blur_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

#define NAME KERNEL(blur_good)
#define DECLARE_ARGS (void)
#define BLOCK ((Block *)__gpu_arg)
#define ROW_FIRST __gpu_lwarp
#define ROW_STEP (BLOCK->nwarps)
#define COL_FIRST __gpu_lane
#define COL_STEP (BLOCK->nlanes)
#include "blur_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

int main(void) {
    blur_cpu((Block *)BLUR_BLOCK);
    return 0;
}
