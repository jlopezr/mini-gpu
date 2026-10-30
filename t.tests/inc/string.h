/* string.h - lo mínimo de la biblioteca C para mini-lcc
 *
 * La librería de lcc para MiniISA (u.lcc/include/mini/none) no trae string.h, y sin
 * esta cabecera `cc -E` cogería la del sistema anfitrión, que lcc no sabe leer.
 * La implementación está en t.tests/runtime/libc/string.c, que build-c compila con
 * cada programa. Solo lo que algún programa necesita: se añade a medida que haga falta.
 */
#ifndef MINI_STRING_H
#define MINI_STRING_H

#include <stddef.h>

void *memset(void *dst, int value, size_t n);
void *memcpy(void *dst, const void *src, size_t n);
int memcmp(const void *a, const void *b, size_t n);

#endif
