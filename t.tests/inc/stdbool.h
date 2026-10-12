/* stdbool.h - bool para mini-lcc
 *
 * lcc es C89 y no tiene `_Bool`: `bool` es un `int`. A diferencia de `_Bool`,
 * asignarle un valor distinto de 0 o 1 no lo normaliza; usar `!!x` si hace falta.
 */
#ifndef MINI_STDBOOL_H
#define MINI_STDBOOL_H

#define bool  int
#define true  1
#define false 0
#define __bool_true_false_are_defined 1

#endif
