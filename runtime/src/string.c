/* string.c - lo mínimo de la biblioteca C para mini-lcc (ver runtime/include/string.h).
 * Código de CPU, byte a byte para que valga con cualquier puntero; memcpy copia
 * por palabras si los dos punteros están alineados a 4 (los framebuffers). */
#include <string.h>

void *memset(void *dst, int value, size_t n) {
    unsigned char *d = (unsigned char *)dst;
    while (n--) *d++ = (unsigned char)value;
    return dst;
}

void *memcpy(void *dst, const void *src, size_t n) {
    unsigned char *d = (unsigned char *)dst;
    const unsigned char *s = (const unsigned char *)src;
    if ((((unsigned)d | (unsigned)s) & 3U) == 0) {
        unsigned *dw = (unsigned *)d;
        const unsigned *sw = (const unsigned *)s;
        for (; n >= 16; n -= 16, dw += 4, sw += 4) { /* lcc no desenrolla */
            dw[0] = sw[0];
            dw[1] = sw[1];
            dw[2] = sw[2];
            dw[3] = sw[3];
        }
        for (; n >= 4; n -= 4) *dw++ = *sw++;
        d = (unsigned char *)dw;
        s = (const unsigned char *)sw;
    }
    while (n--) *d++ = *s++;
    return dst;
}

int memcmp(const void *a, const void *b, size_t n) {
    const unsigned char *p = (const unsigned char *)a, *q = (const unsigned char *)b;
    for (; n; n--, p++, q++)
        if (*p != *q) return *p < *q ? -1 : 1;
    return 0;
}
