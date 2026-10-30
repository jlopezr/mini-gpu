/* Plataforma MiniGPU (CPU + GPU con vídeo por MMIO): proporciona main(), size()
   y el bucle setup()/draw() de Processing sobre el vídeo de 320x240 RGB565.
   Corre igual en el simulador (sim-sys) y en las placas 36/37. Se compila con
   build-c (mini-lcc), no con el compilador del host.

   De momento solo V0: la CPU rasteriza al llamar.

   Se dibuja directamente en el buffer trasero. Processing conserva el lienzo de
   un frame al siguiente, pero el trasero tiene lo de hace dos frames: tras cada
   swap, mgl_set_target le apunta y deja pendiente copiarle el delantero. MiniGL
   solo copia si se dibuja algo antes de un background(), que lo tapa todo: en
   los sketches que borran cada frame no se copia nunca. */

#include "processing.h"
#include "mmio.h"

#define FB_W 320
#define FB_H 240
#define FB_WORDS (FB_W * FB_H / 2)

/* En RAM, lejos del programa (como render.asm); alineados a 16 bytes. */
#define FB_A 0x01000000u
#define FB_B 0x01025800u /* FB_A + 320*240*2 */

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

/* Termina el frame en el buffer trasero, pide el swap, espera a que se aplique
   y pasa a dibujar en el nuevo trasero. */
static void present(void) {
    mgl_finish();
    REG(VIDEO_SWAP) = 1;
    while (REG(VIDEO_SWAP))
        ;
    mgl_set_target((mgl_color_t *)REG(VIDEO_FB_BACK), (const mgl_color_t *)REG(VIDEO_FB_FRONT));
}

int main(void) {
    /* En la placa la SDRAM no empieza a cero: el lienzo empieza negro, como en el
       host (calloc). Basta con el delantero: el trasero lo copia de él. */
    clear(FB_A);
    REG(VIDEO_FB_FRONT) = FB_A;
    REG(VIDEO_FB_BACK) = FB_B;
    REG(VIDEO_CTRL) = VIDEO_MODE_SCANOUT;

    mgl_bind((mgl_color_t *)FB_B, FB_W, FB_H, FB_W);
    mgl_set_target((mgl_color_t *)FB_B, (const mgl_color_t *)FB_A);
    mgl_set_deferred(0);
    setup();
    if (bad_size) return 1;
    for (;;) {
        frameCount++;
        draw();
        present();
    }
}
