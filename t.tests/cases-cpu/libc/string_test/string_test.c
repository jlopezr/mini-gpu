/* La biblioteca C mínima (runtime/include/string.h, runtime/src/string.c):
   memoria y cadenas, con tamaños y desplazamientos que no son múltiplos de 4
   y con punteros alineados (memcpy por palabras).
   main devuelve un bit por comprobación que falla: 0 si todo va bien. */
#include <string.h>
#include <stdlib.h>
#include <ctype.h>
#include <strings.h>
#include <stdio.h>

unsigned char a[37], b[37];
unsigned w[10], v[10];
char text[32];
unsigned heap[64];

int main(void) {
    int errors = 0, i;
    unsigned char *p, *q, *r;
    memset(a, 0xAB, sizeof a);
    for (i = 0; i < 37; i++)
        if (a[i] != 0xAB) errors |= 1;
    for (i = 0; i < 37; i++) b[i] = (unsigned char)i;
    if (memcpy(a + 1, b, 30) != a + 1) errors |= 2;
    if (a[0] != 0xAB || a[1] != 0 || a[30] != 29 || a[31] != 0xAB) errors |= 4;
    if (memcmp(a + 1, b, 30) != 0) errors |= 8;
    if (memcmp(a, b, 1) <= 0) errors |= 16; /* 0xAB > 0x00: compara sin signo */
    if (memcmp(b, a, 1) >= 0) errors |= 32;
    if (memcmp(a, b, 0) != 0) errors |= 64;
    if (memset(b, 0, 0) != b || b[0] != 0 || b[1] != 1) errors |= 128;
    /* Alineados: dos veces 4 palabras, una palabra suelta y 3 bytes. */
    for (i = 0; i < 10; i++) {
        v[i] = 0x01020304U * (unsigned)(i + 1);
        w[i] = 0;
    }
    memcpy(w, v, 4 * 9 + 3);
    if (memcmp(w, v, 4 * 9 + 3) != 0 || ((unsigned char *)w)[39] != 0) errors |= 256;
    if (strlen("") != 0 || strlen("doom") != 4) errors |= 512;
    if (strcmp("abc", "abc") != 0 || strcmp("abc", "abd") >= 0
        || strcmp("abd", "abc") <= 0) errors |= 1024;
    if (strncmp("abc", "abd", 2) != 0 || strncmp("abc", "abd", 3) >= 0
        || strncmp("abc", "xyz", 0) != 0) errors |= 2048;
    memset(a, 0xAB, sizeof a);
    if (strncpy((char *)a, "doom", 7) != (char *)a || a[0] != 'd' || a[3] != 'm'
        || a[4] != 0 || a[5] != 0 || a[6] != 0 || a[7] != 0xAB) errors |= 4096;
    if (strrchr("doom.wad", 'o') != (char *)"doom.wad" + 2
        || strrchr("doom.wad", '\0') != (char *)"doom.wad" + 8
        || strrchr("doom.wad", 'x') != 0) errors |= 8192;
    if (strstr("doomgeneric", "generic") != (char *)"doomgeneric" + 4
        || strstr("doomgeneric", "") != (char *)"doomgeneric"
        || strstr("doomgeneric", "wad") != 0) errors |= 16384;
    if (atoi("42") != 42 || atoi(" \t-17x") != -17 || atoi("+003") != 3
        || atoi("no-number") != 0) errors |= 32768;
    if (abs(-9) != 9 || abs(7) != 7 || toupper('d') != 'D'
        || tolower('D') != 'd' || toupper('7') != '7') errors |= 65536;
    if (!isspace('\t') || isspace('x') || !isprint(' ') || isprint('\n')
        || !isalpha('D') || isalpha('7') || !isdigit('7') || isdigit('D'))
        errors |= 2097152;
    memset(a, 0xAB, sizeof a);
    bzero(a + 1, 30);
    if (a[0] != 0xAB || a[1] != 0 || a[30] != 0 || a[31] != 0xAB
        || strcasecmp("Doom", "dOoM") != 0 || strcasecmp("doom", "door") >= 0
        || strncasecmp("doom", "DOOR", 3) != 0 || strncasecmp("doom", "DOOR", 4) >= 0)
        errors |= 131072;
    if (snprintf(text, sizeof text, "%02i %s %x", -7, "doom", 0x2a) != 10
        || strcmp(text, "-7 doom 2a") != 0) errors |= 262144;
    if (snprintf(text, 5, "abcdef") != 6 || strcmp(text, "abcd") != 0) errors |= 524288;
    if (snprintf(text, sizeof text, "%5.3s", "doom") != 5 || strcmp(text, "  doo") != 0)
        errors |= 1048576;
    mini_heap_init(heap, sizeof heap);
    p = malloc(11);
    q = calloc(7, 4);
    if (!p || !q || mini_heap_bytes_used() == 0) errors |= 4194304;
    for (i = 0; q && i < 28; ++i)
        if (q[i] != 0) errors |= 4194304;
    if (p) {
        for (i = 0; i < 11; ++i) p[i] = (unsigned char)(i + 1);
        free(p);
        r = malloc(8);
        if (!r || r != p) errors |= 4194304;
        p = realloc(r, 40);
        if (!p) errors |= 4194304;
        for (i = 0; p && i < 8; ++i)
            if (p[i] != (unsigned char)(i + 1)) errors |= 4194304;
        free(p);
    }
    free(q);
    if (mini_heap_bytes_used() != 0 || mini_heap_bytes_free() != sizeof heap) errors |= 4194304;
    if (errors) exit(errors);
    return errors;
}
