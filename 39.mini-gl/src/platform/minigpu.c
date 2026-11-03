/* Driver MiniGPU común a 2D y 3D: vídeo, entrada HID y bucle setup/draw.
   El contexto enlazado administra comandos, profundidad y conservación del
   lienzo. MGL_VERSION selecciona V0/V1/V2 para el contexto 2D; 3D usa 0.
   Funciona en el simulador y con el mapa MMIO de las placas 36/37. */

#include "platform.h"
#include "mmio.h"

#define FB_W PLATFORM_DEFAULT_W
#define FB_H PLATFORM_DEFAULT_H
#define FB_WORDS (FB_W * FB_H / 2)
#define FB_A PLATFORM_FB_A
#define FB_B PLATFORM_FB_B
#ifndef MGL_VERSION
#define MGL_VERSION 0
#endif

static void clear(unsigned address) {
    unsigned *p = (unsigned *)address;
    int n;
    for (n = FB_WORDS; n > 0; n -= 4, p += 4) {
        p[0] = 0;
        p[1] = 0;
        p[2] = 0;
        p[3] = 0;
    }
}

static int has_input;
static int half_x = FB_W, half_y = FB_H; /* el raton, en medios pixeles */

#define HID_SHIFT 0x22 /* Shift izquierdo y derecho en el bitmap de modificadores */

static void key_down(int usage, int modifiers) {
    int shift = modifiers & HID_SHIFT, c = 0;
    if (usage >= 0x4F && usage <= 0x52) { /* derecha, izquierda, abajo, arriba */
        key = CODED;
        keyCode = usage == 0x4F ? RIGHT : usage == 0x50 ? LEFT : usage == 0x51 ? DOWN : UP;
        return;
    }
    if (usage >= 0x04 && usage <= 0x1D)
        c = (shift ? 'A' : 'a') + usage - 0x04;
    else if (usage >= 0x1E && usage <= 0x38)
        c = (shift ? platform_hid_shift : platform_hid_plain)[usage - 0x1E];
    else if (usage == 0x4C)
        c = DELETE;
    if (c) {
        key = c;
        keyCode = 0;
    }
}

/* Antes de cada draw(): vacia la cola de eventos y lee el estado. */
static void poll_input(void) {
    unsigned event, type;
    int i;
    pmouseX = mouseX;
    pmouseY = mouseY;
    if (!has_input) return;
    while (REG(INPUT_STATUS) & MMIO_INPUT_STATUS_COUNT_MASK) {
        event = REG(INPUT_EVENT_DATA);
        type = event >> 24;
        if (type == MMIO_INPUT_TYPE_MOUSE_MOVE) {
            half_x += (int)(event << 20) >> 20; /* DX y DY: 12 bits con signo */
            half_y += (int)(event << 8) >> 20;
            if (half_x < 0) half_x = 0;
            if (half_x > 2 * FB_W - 1) half_x = 2 * FB_W - 1;
            if (half_y < 0) half_y = 0;
            if (half_y > 2 * FB_H - 1) half_y = 2 * FB_H - 1;
        } else if (type == MMIO_INPUT_TYPE_KEY && (event & 0x1FF) > 0x100) /* KEY != 0 y DOWN */
            key_down(event & 0xFF, (event >> 16) & 0xFF);
    }
    mouseX = half_x / 2;
    mouseY = half_y / 2;
    mousePressed = REG(INPUT_MOUSE_BUTTONS) != 0;
    keyPressed = 0;
    for (i = 0; i < 8; i++)
        if ((platform_keys[i] = REG(INPUT_KEY_STATE0 + 4 * i))) keyPressed = 1;
}

/* Presentación compartida: el contexto decide si conserva el lienzo. */
int main(void) {
    mgl_u32 back = FB_B, front = FB_A;
    clear(FB_A);
    if (mgl_context_is3d()) clear(FB_B);
    REG(VIDEO_FB_FRONT) = FB_A;
    REG(VIDEO_FB_BACK) = FB_B;
    REG(VIDEO_CTRL) = VIDEO_MODE_SCANOUT;
    if (platform_init((void *)FB_A, MGL_VERSION) != MGL_OK) return 2;
    has_input = (REG(SYSTEM_DEVICES) & DEV_INPUT) != 0;
    if (platform_frame(back, front, frameCount ? draw : setup, 0) != MGL_OK) return 2;
    if (width != FB_W || height != FB_H) return 1;
    for (;;) {
        frameCount++;
        poll_input();
        if (platform_frame(back, front, frameCount ? draw : setup, 0) != MGL_OK) return 2;
        REG(VIDEO_SWAP) = 1;
        while (REG(VIDEO_SWAP))
            ;
        back = REG(VIDEO_FB_BACK);
        front = REG(VIDEO_FB_FRONT);
    }
}
