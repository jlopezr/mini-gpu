/* gpu.c - el runtime de C del lado de la CPU: gpu_launch y la pila de las lanes.
 *
 * gpu_launch rellena el bloque de argumentos y llama a `gpu_run` de gpu_runtime.inc
 * (ensamblador, examples/asm/dma): descriptores, WARP_START y espera. gpu_run recibe R1 = PC
 * del kernel, R2 = nwarps, R3 = bloque, que son los tres primeros argumentos de C, asi
 * que se llama como cualquier otra funcion.
 */
#include <stdarg.h>
#include "gpu.h"

/* Bloque de argumentos de gpu_run: nwarps y nlanes los pone el runtime, p[0..5] el llamador. */
typedef struct {
    int nwarps, nlanes;
    int p[6];
} GpuBlock;

extern int gpu_run(int kernel, int nwarps, GpuBlock *block);   /* gpu_runtime.inc */

/* Pila de las lanes: cada kernel apunta R30 a su porcion (mini-opt, pase kernels) */
char __gpu_stack[GPU_LANES * GPU_STACK_PER_LANE];

static GpuBlock gpu_block;

int gpu_launch(int kernel, int nwarps, ...) {
    va_list ap;
    int i;

    va_start(ap, nwarps);
    for (i = 0; i < 4; i++)
        gpu_block.p[i] = va_arg(ap, int);
    va_end(ap);
    return gpu_run(kernel, nwarps, &gpu_block);
}
