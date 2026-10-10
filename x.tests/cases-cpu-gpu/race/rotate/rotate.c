/* rotate.c - la rotacion de textura de x.tests/cases-cpu-gpu/race/rotate/rotate.inc, en C: CPU, GPU inocente y GPU buena
 *
 *   python 32.cpu-gpu-func-sim/compare/compare_race.py rotate
 *
 * El cuerpo esta en rotate_body.h, una sola vez; este fichero lo incluye tres veces con otro
 * reparto de trabajo entre hilos (ver la tabla de rotate_body.h). Bloque de argumentos: el de
 * gpu_run, p0 = framebuffer, p1 = u de la celda (0, 0), p2 = v, p3 = dux, p4 = dvx.
 */
#include "gpu.h"

#define ROT_COLS 160
#define ROT_ROWS 104
#define ROT_TEX 0x010A0000          /* 128 x 128 palabras, como en rotate.inc */
#define ROT_BLOCK 0x001F0000        /* donde compare_race.py deja el bloque para la CPU */

typedef struct {
    int nwarps, nlanes;
    int p[6];
} Block;

/* ---- la CPU: una sola pasada, todas las filas y todas las columnas ---- */
#define NAME rot_cpu
#define DECLARE_ARGS (Block *arg)
#define BLOCK arg
#define ROW_FIRST 0
#define ROW_STEP 1
#define COL_FIRST 0
#define COL_STEP 1
#include "rotate_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- la GPU inocente: un hilo por fila ---- */
#define NAME KERNEL(rot_naive)
#define DECLARE_ARGS (void)
#define BLOCK ((Block *)__gpu_arg)
#define ROW_FIRST __gpu_tid
#define ROW_STEP (BLOCK->nwarps * BLOCK->nlanes)
#define COL_FIRST 0
#define COL_STEP 1
#include "rotate_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- la GPU buena: un warp por fila, una lane por columna de cada ocho ---- */
#define NAME KERNEL(rot_good)
#define DECLARE_ARGS (void)
#define BLOCK ((Block *)__gpu_arg)
#define ROW_FIRST __gpu_lwarp
#define ROW_STEP (BLOCK->nwarps)
#define COL_FIRST __gpu_lane
#define COL_STEP (BLOCK->nlanes)
#include "rotate_body.h"
#undef NAME
#undef DECLARE_ARGS
#undef BLOCK
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

int main(void) {
    rot_cpu((Block *)ROT_BLOCK);
    return 0;
}
