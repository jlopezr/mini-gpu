/* string.c - lo mínimo de la biblioteca C para mini-lcc (ver t.tests/inc/string.h).
 * Código de CPU, byte a byte: sin alineación ni palabras, para que valga con
 * cualquier puntero. Si alguno pasa a ser caliente, se optimiza aquí. */
#include <string.h>

void *memset(void *dst, int value, size_t n) {
    unsigned char *d = (unsigned char *)dst;
    while (n--) *d++ = (unsigned char)value;
    return dst;
}

void *memcpy(void *dst, const void *src, size_t n) {
    unsigned char *d = (unsigned char *)dst;
    const unsigned char *s = (const unsigned char *)src;
    while (n--) *d++ = *s++;
    return dst;
}

int memcmp(const void *a, const void *b, size_t n) {
    const unsigned char *p = (const unsigned char *)a, *q = (const unsigned char *)b;
    for (; n; n--, p++, q++)
        if (*p != *q) return *p < *q ? -1 : 1;
    return 0;
}
