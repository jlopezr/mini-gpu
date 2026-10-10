/* Anfitrion autocontenido: incorpora la entrada generada por race_case_data.py. */
#define main life_comparison_main
#include "life.c"
#undef main

extern unsigned race_case[];

int main(void) {
    Block *arg = (Block *)race_case;
    int *next = (int *)arg->p[1];
    int i;

    arg->p[0] = (int)(race_case + 8);
    for (i = 0; i < 106 * LIFE_STRIDE + 16; ++i)
        next[i] = 0;
    life_cpu(arg);
    return 0;
}
