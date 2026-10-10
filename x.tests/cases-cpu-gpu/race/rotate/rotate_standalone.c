/* Anfitrion autocontenido: incorpora la entrada generada por race_case_data.py. */
#define main rotate_comparison_main
#include "rotate.c"
#undef main

extern unsigned race_case[];

int main(void) {
    Block *arg = (Block *)race_case;

    arg->p[5] = (int)(race_case + 8);
    rot_cpu(arg);
    return 0;
}
