#include "gfx.h"
#include "demo_icons.h"
#include <stdio.h>
#include <stdlib.h>

static int make_demo(int w, int h, const char *path) {
    uint16_t *frame = calloc((size_t)w * h, sizeof *frame);
    if (!frame) return -1;
    GfxSurface surface = {frame, (uint32_t)w, (uint32_t)h, (uint32_t)w};
    GfxBitmap images[] = {
        {icon_0, 40, 20, 5, GFX_BITMAP_MONO1},
        {icon_1, 40, 20, 5, GFX_BITMAP_MONO1},
        {icon_2, 40, 20, 5, GFX_BITMAP_MONO1},
        {icon_3, 40, 20, 5, GFX_BITMAP_MONO1},
        {icon_4, 40, 20, 5, GFX_BITMAP_MONO1}};
    GfxResources resources = {.bitmaps = images, .bitmap_count = 5};
    GfxDisplayList dl;
    gfx_list_init(&dl);
    gfx_list_add(&dl, (GfxCommand){.opcode = GFX_CLEAR, .data.clear = {0xFFFF}});
    /* Draw at 40x40 (original visual aspect), 64x64 and 80x80. */
    int widths[] = {40, 64, 80};
    int ox[] = {10, 64, 142};
    int oy[] = {20, 20, 20};
    if (w == 640) {
        for (int i = 0; i < 3; ++i) {
            widths[i] *= 2;
            ox[i] *= 2;
            oy[i] *= 2;
        }
    }
    for (int i = 0; i < 3; ++i) {
        gfx_list_add(&dl, (GfxCommand){.opcode = GFX_BLIT, .data.blit = {.resource_id = (uint32_t)i, .src = {0, 0, 40, 20}, .dst = {ox[i], oy[i], widths[i], widths[i]}, .foreground = 0x0000, .background = 0xFFFF, .mode = GFX_BLIT_TRANSPARENT_ZERO}});
    }
    /* Deliberately clip a large icon to a 66x40 viewport. */
    int mul = w / 320;
    gfx_list_add(&dl, (GfxCommand){.opcode = GFX_SET_CLIP, .data.clip = {{16 * mul, 132 * mul, 66 * mul, 40 * mul}}});
    gfx_list_add(&dl, (GfxCommand){.opcode = GFX_BLIT, .data.blit = {.resource_id = 3, .src = {0, 0, 40, 20}, .dst = {10 * mul, 122 * mul, 80 * mul, 80 * mul}, .foreground = 0x001F, .mode = GFX_BLIT_TRANSPARENT_ZERO}});
    int rc = gfx_execute_cpu_resources(&dl, &surface, &resources);
    if (!rc) rc = gfx_write_ppm(path, &surface);
    gfx_list_destroy(&dl);
    free(frame);
    return rc;
}
int main(void) {
    if (make_demo(320, 240, "blit-320x240.ppm") ||
        make_demo(640, 480, "blit-640x480.ppm")) return 1;
    puts("Created BLIT demos");
    return 0;
}
