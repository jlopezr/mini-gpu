#include "platform.h"

int width = PLATFORM_DEFAULT_W, height = PLATFORM_DEFAULT_H;
int frameCount, mouseX, mouseY, pmouseX, pmouseY, mousePressed;
int keyPressed, key, keyCode;

int platform_init(void *ram, int version) {
    frameCount = mouseX = mouseY = pmouseX = pmouseY = mousePressed = 0;
    keyPressed = key = keyCode = 0;
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
