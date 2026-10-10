/* gpu.h - kernels de GPU y lanzamientos desde C (CPU y GPU en un mismo .c)
 *
 *   #include "gpu.h"
 *
 *   void KERNEL(memset)(int *dst, int value, int n) {      -- GPU
 *       int i, step = __gpu_nthreads;
 *       GRID_FOR(i, n, step)
 *           dst[i] = value;
 *   }
 *
 *   int main(void) {                                       -- CPU
 *       return GPU_RUN(memset, 4, buffer, 7, 4096);        -- kernel, warps, parametros
 *   }
 *
 * Un kernel es una funcion que se llama `__kernel_<nombre>` (la macro KERNEL lo pone).
 * `mini-opt` la convierte en el punto de entrada de una lane: fija su pila, carga sus
 * parametros del bloque de argumentos y termina con EXIT. Por eso la direccion del
 * kernel es la que se lanza, y un kernel no se puede llamar desde la CPU.
 *
 * Hasta cuatro parametros de 32 bits (R1..R4); con mas, un puntero a una estructura.
 * Las variables `__gpu_*` son intrinsecos: `mini-opt` las sustituye por la instruccion
 * (GETTID, ...). Solo valen dentro de un kernel.
 */
#ifndef GPU_H
#define GPU_H

#define KERNEL(name) __kernel_##name

/* Pila por lane y lanes de la GPU: tienen que coincidir con mini-opt (GPU_STACK_PER_LANE) */
#define GPU_STACK_PER_LANE 512
#define GPU_LANES 64

extern volatile int __gpu_tid;       /* id global del hilo: warp * lanes + lane (GETTID) */
extern volatile int __gpu_nthreads;  /* hilos del lanzamiento: nwarps * nlanes           */
extern volatile int __gpu_lane;      /* lane dentro del warp (GETLANE)                   */
extern volatile int __gpu_warp;      /* slot fisico del warp (GETWARP)                   */
extern volatile int __gpu_lwarp;     /* id logico del warp en el lanzamiento (GETLWARP)  */
extern volatile int __gpu_arg;       /* puntero al bloque de argumentos (GETARG)         */
extern volatile int __gpu_bar;       /* `__gpu_bar = 0;` es una barrera (BAR)            */

/* NOALIAS(p): p no tiene alias, como `restrict` (que C89 no tiene). Lo que se accede por p, o por un puntero que
   se calcule a partir de el, no se accede por ningun otro mientras dure la funcion; mini-opt (pase `noalias`) lo
   usa para sacar de un bucle lecturas que ningun store puede tocar. Se pone una vez, tras dar valor a p. Si se
   marca mal, el resultado es incorrecto sin aviso. Solo vale con mini-opt (la escritura se borra). */
extern volatile int __noalias_mark;
#define NOALIAS(p) (__noalias_mark = (int)(p))

/* Un bucle de rejilla: cada hilo salta `step` elementos, asi que los hilos consecutivos de
   un warp tocan palabras consecutivas (accesos coalescidos). `step` se calcula una vez antes
   del bucle, porque leer __gpu_nthreads son cuatro instrucciones. */
#define GRID_FOR(i, n, step) for ((i) = __gpu_tid; (i) < (n); (i) += (step))

#define GPU_OK 0

/* gpu_launch(kernel, nwarps, p0, p1, p2, p3): lanza y espera. Devuelve GPU_OK o un error
   del runtime (gpu_runtime.inc). Lee siempre cuatro parametros. */
int gpu_launch(int kernel, int nwarps, ...);

/* GPU_RUN(nombre, warps, parametros...): hasta cuatro; los que falten valen 0. */
#define GPU_RUN(name, warps, ...) \
    gpu_launch((int)KERNEL(name), (warps), __VA_ARGS__, 0, 0, 0, 0)

#endif
