/* Anfitrion autocontenido: incorpora la entrada generada por race_case_data.py. */
#define main life_comparison_main
#include "life.c"
#undef main

extern unsigned race_case[];
extern int gpu_timeout_polls;

/* El puntero al bloque completo cabe en p0 de GPU_RUN. */
#define NAME KERNEL(life_test)
#define DECLARE_ARGS (Block *arg)
#define BLOCK arg
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
    Block *arg = (Block *)race_case;
    int *next = (int *)arg->p[1];
    int i;

    arg->p[0] = (int)(race_case + 8);
    gpu_timeout_polls = 1000000;
    for (i = 0; i < 106 * LIFE_STRIDE + 16; ++i)
        next[i] = 0;
    return GPU_RUN(life_test, 8, arg);
}
