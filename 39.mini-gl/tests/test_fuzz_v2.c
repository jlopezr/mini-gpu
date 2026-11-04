/* test_fuzz_v2: V2 (renderer GPU emulado en el host: raster.c por lanes) contra V0 (raster.c directo), con escenas al azar:
   bordes gruesos, círculos, triángulos, líneas, puntos, imágenes y recortes por los cuatro lados. */
#include <stdio.h>
#include <string.h>
#include "minigl.h"
#include "gpu_renderer.h"
#define W 101
#define H 67
static mgl_color_t v0[W * H], v2[W * H];
static unsigned char bytes[1 << 16];
static mgl_cmd_buffer_t cmd;
static mgl_gpu_sprite_t sprites[MGL_GPU_MAX_SPRITES];
static mgl_color_t pix[7 * 5];
static mgl_sprite_t sprite = {pix, 7, 5, 7};
static unsigned seed;
static int rnd(int lo, int hi) {
    seed = seed * 1103515245u + 12345u;
    return lo + (int)((seed >> 8) % (unsigned)(hi - lo + 1));
}

static void scene(unsigned s) {
    int i, n;
    seed = s;
    n = rnd(1, 25);
    for (i = 0; i < n; i++) {
        int k = rnd(0, 9), x = rnd(-40, W + 40), y = rnd(-40, H + 40);
        if (k == 0) mgl_clear((mgl_color_t)rnd(0, 65535));
        else if (k == 1) { if (rnd(0, 3)) mgl_fill((mgl_color_t)rnd(1, 65535)); else mgl_no_fill(); }
        else if (k == 2) { if (rnd(0, 3)) mgl_stroke((mgl_color_t)rnd(1, 65535)); else mgl_no_stroke(); }
        else if (k == 3) mgl_stroke_weight(rnd(0, 12));
        else if (k == 4) mgl_point(x, y);
        else if (k == 5) mgl_line(x, y, rnd(-60, W + 60), rnd(-60, H + 60));
        else if (k == 6) mgl_rect(x, y, rnd(-5, 80), rnd(-5, 60));
        else if (k == 7) mgl_circle(x, y, rnd(-2, 50));
        else if (k == 8) mgl_triangle(x, y, rnd(-60, W + 60), rnd(-60, H + 60), rnd(-60, W + 60), rnd(-60, H + 60));
        else mgl_image(&sprite, x, y);
    }
}

int main(void) {
    unsigned round;
    int i;
    for (i = 0; i < 7 * 5; i++) pix[i] = (mgl_color_t)(i * 1999 + 7);
    for (round = 1; round <= 3000; round++) {
        {
            mgl_gpu_job_t job;
            memset(v0, 0, sizeof v0);
            memset(v2, 0, sizeof v2);
            mgl_bind(v0, W, H, W);
            mgl_set_deferred(0);
            scene(round);
            mgl_bind(v2, W, H, W);
            if (mgl_cmd_init(&cmd, bytes, sizeof bytes) != MGL_OK) return 1;
            mgl_set_deferred(&cmd);
            scene(round);
            mgl_set_deferred(0);
            if (mgl_cmd_status(&cmd) != MGL_OK) return 2;
            if (mgl_gpu_sprites_from_cmd(&cmd, sprites, MGL_GPU_MAX_SPRITES) != MGL_OK) return 3;
            job.commands = cmd.bytes;
            job.command_bytes = cmd.used;
            job.framebuffer = v2;
            job.width = W;
            job.height = H;
            job.pitch = W;
            job.sprites = sprites;
            job.sprite_count = cmd.sprite_count;
            if (mgl_gpu_render(&job) != MGL_OK) return 4;
            if (memcmp(v0, v2, sizeof v0)) {
                for (i = 0; i < W * H; i++)
                    if (v0[i] != v2[i]) break;
                printf("FALLO escena %u en (%d,%d): V0 %04x V2 %04x\n", round, i % W, i / W, v0[i], v2[i]);
                return 5;
            }
        }
    }
    puts("PASS: 3000 escenas, V0 == V2");
    return 0;
}
