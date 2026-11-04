/* La biblioteca C mínima (t.tests/inc/string.h, t.tests/runtime/libc/string.c):
   memset, memcpy y memcmp, con tamaños y desplazamientos que no son múltiplos de 4
   y con punteros alineados (memcpy por palabras).
   main devuelve un bit por comprobación que falla: 0 si todo va bien. */
#include <string.h>

unsigned char a[37], b[37];
unsigned w[10], v[10];

int main(void) {
    int errors = 0, i;
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
    return errors;
}
