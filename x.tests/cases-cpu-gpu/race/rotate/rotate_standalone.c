/* Anfitrion autocontenido: incorpora la entrada generada por race_case_data.py. */
#define main rotate_comparison_main
#include "rotate.c"
#undef main

extern unsigned race_case[];
extern int gpu_timeout_polls;

/* El puntero al bloque completo conserva sus seis p[]. */
#define NAME KERNEL(rot_test)
#define DECLARE_ARGS (Block *arg)
#define BLOCK arg
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
    Block *arg = (Block *)race_case;

    arg->p[5] = (int)(race_case + 8);
    gpu_timeout_polls = 1000000;
    return GPU_RUN(rot_test, 8, arg);
}
