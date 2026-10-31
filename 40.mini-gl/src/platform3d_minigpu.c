/* Plataforma MiniGPU para sketches 3D: el renderer de referencia (renderer/)
   corre en la CPU sobre la SDRAM real, con el mismo código y las mismas
   direcciones que en el host (platform3d.h). La GPU no se usa todavía. Se
   compila con build-c (mini-lcc): make minigpu3d, sim-rotating_cube.

   Doble buffer como en platform_minigpu.c: se dibuja en el trasero, se pide el
   swap y se espera. Un sketch 3D borra en cada draw(): el trasero no recibe una
   copia del delantero (lo que no se dibuje es de hace dos frames). Sin entrada:
   el ratón se queda en el centro. El vídeo es de 320x240: otro size() hace que
   main() acabe con 1; un error de MiniGL o del renderer, con 2. */

#include "platform3d.h"
#include "mmio.h"

#define FB_WORDS (P3D_MAX_W * P3D_MAX_H / 2)

static void clear(unsigned address) {
    unsigned *p = (unsigned *)address;
    int n;
    for (n = FB_WORDS; n > 0; n -= 4, p += 4) { /* FB_WORDS es multiplo de 4 */
        p[0] = 0;
        p[1] = 0;
        p[2] = 0;
        p[3] = 0;
    }
}

int main(void) {
    mgl_u32 back = P3D_FB_B;
    clear(P3D_FB_A); /* en la placa la SDRAM no empieza a cero */
    clear(P3D_FB_B);
    REG(VIDEO_FB_FRONT) = P3D_FB_A;
    REG(VIDEO_FB_BACK) = P3D_FB_B;
    REG(VIDEO_CTRL) = VIDEO_MODE_SCANOUT;
    if (platform3d_init((void *)P3D_RAM_BASE)) return 2;
    if (platform3d_begin(back) != MGL_OK) return 2;
    setup();
    if (platform3d_end(0) != MGL_OK) return 2;
    if (width != P3D_MAX_W || height != P3D_MAX_H) return 1;
    for (;;) {
        frameCount++;
        if (platform3d_begin(back) != MGL_OK) return 2;
        draw();
        if (platform3d_end(0) != MGL_OK) return 2;
        REG(VIDEO_SWAP) = 1;
        while (REG(VIDEO_SWAP))
            ;
        back = REG(VIDEO_FB_BACK);
    }
}
