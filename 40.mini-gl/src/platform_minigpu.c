/* Plataforma MiniGPU (CPU + GPU con vídeo por MMIO): proporciona main(), size()
   y el bucle setup()/draw() de Processing sobre el vídeo de 320x240 RGB565.
   Corre igual en el simulador (sim-sys) y en las placas 36/37. Se compila con
   build-c (mini-lcc), no con el compilador del host.

   De momento solo V0: la CPU rasteriza al llamar.

   Processing conserva el lienzo de un frame al siguiente, pero con doble buffer
   el trasero tiene lo de hace dos frames, y cambiar de buffer con mgl_bind
   reiniciaría el estado de dibujo (fill, stroke...). Por eso se dibuja en un
   lienzo fijo que se enlaza una sola vez, y se copia al buffer trasero antes de
   cada swap. */

#include "processing.h"
#include "mmio.h"

#define FB_W 320
#define FB_H 240
#define FB_WORDS (FB_W * FB_H / 2)

/* En RAM, lejos del programa (como render.asm); alineados a 16 bytes. */
#define FB_A 0x01000000u
#define FB_B 0x01025800u   /* FB_A + 320*240*2 */
#define CANVAS 0x0104B000u /* FB_B + 320*240*2 */

int width = FB_W, height = FB_H;
int frameCount, mouseX, mouseY, mousePressed;

static int bad_size;

/* El vídeo es siempre de 320x240: otro tamaño hace que main() acabe con 1. */
void size(int w, int h) {
    if (w != FB_W || h != FB_H) bad_size = 1;
}

static void clear(unsigned address) {
    unsigned *p = (unsigned *)address;
    int i;
    for (i = 0; i < FB_WORDS; i++) p[i] = 0;
}

/* Copia el lienzo al buffer trasero, pide el swap y espera a que se aplique. */
static void present(void) {
    unsigned *back = (unsigned *)REG(VIDEO_FB_BACK);
    const unsigned *canvas = (const unsigned *)CANVAS;
    int i;
    for (i = 0; i < FB_WORDS; i++) back[i] = canvas[i];
    REG(VIDEO_SWAP) = 1;
    while (REG(VIDEO_SWAP))
        ;
}

int main(void) {
    /* En la placa la SDRAM no empieza a cero: el lienzo empieza negro, como en el host (calloc). */
    clear(CANVAS);
    clear(FB_A);
    REG(VIDEO_FB_FRONT) = FB_A;
    REG(VIDEO_FB_BACK) = FB_B;
    REG(VIDEO_CTRL) = VIDEO_MODE_SCANOUT;

    mgl_bind((mgl_color_t *)CANVAS, FB_W, FB_H, FB_W);
    mgl_set_deferred(0);
    setup();
    if (bad_size) return 1;
    for (;;) {
        frameCount++;
        draw();
        present();
    }
}
