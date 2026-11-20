/* string.c - lo mínimo de la biblioteca C para mini-lcc (ver runtime/include/string.h).
 * Código de CPU, byte a byte para que valga con cualquier puntero; memcpy copia
 * por palabras si los dos punteros están alineados a 4 (los framebuffers). */
#include <string.h>
#include <stdlib.h>

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

void *memmove(void *dst, const void *src, size_t n) {
    unsigned char *d = dst;
    const unsigned char *s = src;
    if (d < s) while (n--) *d++ = *s++;
    else if (d > s) {
        d += n;
        s += n;
        while (n--) *--d = *--s;
    }
    return dst;
}

int memcmp(const void *a, const void *b, size_t n) {
    const unsigned char *p = (const unsigned char *)a, *q = (const unsigned char *)b;
    for (; n; n--, p++, q++)
        if (*p != *q) return *p < *q ? -1 : 1;
    return 0;
}

size_t strlen(const char *s) {
    const char *p = s;
    while (*p) ++p;
    return (size_t)(p - s);
}

int strcmp(const char *a, const char *b) {
    while (*a && *a == *b) {
        ++a;
        ++b;
    }
    return (unsigned char)*a - (unsigned char)*b;
}

int strncmp(const char *a, const char *b, size_t n) {
    while (n && *a && *a == *b) {
        ++a;
        ++b;
        --n;
    }
    if (!n) return 0;
    return (unsigned char)*a - (unsigned char)*b;
}

char *strncpy(char *dst, const char *src, size_t n) {
    char *result = dst;
    while (n && *src) {
        *dst++ = *src++;
        --n;
    }
    while (n--) *dst++ = '\0';
    return result;
}

char *strrchr(const char *s, int c) {
    const char *result = 0;
    char needle = (char)c;
    do {
        if (*s == needle) result = s;
    } while (*s++);
    return (char *)result;
}

char *strchr(const char *s, int c) {
    while (*s != (char)c) if (!*s++) return 0;
    return (char *)s;
}

char *strstr(const char *haystack, const char *needle) {
    size_t needle_len = strlen(needle);
    if (!needle_len) return (char *)haystack;
    while (*haystack) {
        if (*haystack == *needle && !strncmp(haystack, needle, needle_len))
            return (char *)haystack;
        ++haystack;
    }
    return 0;
}

char *strdup(const char *s) {
    size_t size = strlen(s) + 1;
    char *copy = malloc(size);
    if (copy) memcpy(copy, s, size);
    return copy;
}

int toupper(int c) {
    return c >= 'a' && c <= 'z' ? c - ('a' - 'A') : c;
}

int tolower(int c) {
    return c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c;
}

int isspace(int c) {
    return c == ' ' || (c >= '\t' && c <= '\r');
}

int isprint(int c) {
    return c >= ' ' && c <= '~';
}

int isalpha(int c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
}

int isdigit(int c) {
    return c >= '0' && c <= '9';
}

void bzero(void *dst, size_t n) {
    memset(dst, 0, n);
}

int strcasecmp(const char *a, const char *b) {
    int ca, cb;
    do {
        ca = toupper((unsigned char)*a++);
        cb = toupper((unsigned char)*b++);
    } while (ca && ca == cb);
    return ca - cb;
}

int strncasecmp(const char *a, const char *b, size_t n) {
    int ca = 0, cb = 0;
    while (n--) {
        ca = toupper((unsigned char)*a++);
        cb = toupper((unsigned char)*b++);
        if (ca != cb || !ca) return ca - cb;
    }
    return 0;
}
