#include "platform.h"

int width = PLATFORM_DEFAULT_W, height = PLATFORM_DEFAULT_H;
int frameCount, mouseX, mouseY, pmouseX, pmouseY, mousePressed;
int keyPressed, key, keyCode;
mgl_u32 platform_keys[8];

/* 0x32 es la tecla de fuera de EE. UU.: no da caracter. */
const char platform_hid_plain[] = "1234567890\n\033\b\t -=[]\\\0;'`,./";
const char platform_hid_shift[] = "!@#$%^&*()\n\033\b\t _+{}|\0:\"~<>?";

/* El Usage ID HID de la tecla que da k, o -1. */
static int hid_usage(int k) {
    int i;
    if (k == RIGHT) return 0x4F; /* antes que los caracteres: 37..40 son tambien % & ' ( */
    if (k == LEFT) return 0x50;
    if (k == DOWN) return 0x51;
    if (k == UP) return 0x52;
    if (k == DELETE) return 0x4C;
    if (k >= 'a' && k <= 'z') return 0x04 + k - 'a';
    if (k >= 'A' && k <= 'Z') return 0x04 + k - 'A';
    for (i = 0; i <= 0x38 - 0x1E; i++)
        if (k && (platform_hid_plain[i] == k || platform_hid_shift[i] == k)) return 0x1E + i;
    return -1;
}

int keyIsDown(int k) {
    int u = hid_usage(k);
    return u >= 0 && (platform_keys[u >> 5] >> (u & 31) & 1);
}

int platform_init(void *ram, int version) {
    int i;
    frameCount = mouseX = mouseY = pmouseX = pmouseY = mousePressed = 0;
    keyPressed = key = keyCode = 0;
    for (i = 0; i < 8; i++) platform_keys[i] = 0;
    return mgl_context_init(ram, version);
}

int platform_frame(mgl_u32 back, mgl_u32 front, void (*sketch)(void), void (*before_execute)(void)) {
    int r = mgl_context_begin(back, front);
    if (r != MGL_OK) return r;
    sketch();
    return mgl_context_end(before_execute);
}

void platform_shutdown(void) {
    mgl_context_shutdown();
}

int platform_parse_version(const char *s) {
    if (s[0] >= '0' && s[0] < '0' + PLATFORM_VERSIONS && s[1] == 0) return s[0] - '0';
    return -1;
}
