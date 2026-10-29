#include "gfx.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    FILE *fp = fopen(argc > 1 ? argv[1] : "build/fonts/park10.mf", "rb");
    assert(fp);
    assert(!fseek(fp, 0, SEEK_END));
    long len = ftell(fp);
    assert(len > 0);
    rewind(fp);
    unsigned char *data = malloc((size_t)len);
    assert(data);
    assert(fread(data, 1, (size_t)len, fp) == (size_t)len);
    fclose(fp);
    MfFont font;
    assert(mf_open(&font, data, (size_t)len) == 0);
    MfGlyph g;
    assert(mf_find_glyph(&font, 'A', &g) == 0);
    uint16_t frame[32 * 32] = {0};
    GfxSurface surface = {frame, 32, 32, 32};
    GfxPositionedGlyph pg = {'A', 2, 15};
    GfxGlyphRun run = {&pg, 1, 0};
    const MfFont *fonts[] = {&font};
    GfxResources resources = {.fonts = fonts, .font_count = 1, .runs = &run, .run_count = 1};
    GfxDisplayList list;
    gfx_list_init(&list);
    assert(gfx_list_add(&list, (GfxCommand){.opcode = GFX_SET_CLIP, .data.clip = {{0, 0, 32, 32}}}) == 0);
    assert(gfx_list_add(&list, (GfxCommand){.opcode = GFX_GLYPH_RUN, .data.glyph_run = {.run_id = 0, .color = 0xffff}}) == 0);
    assert(gfx_execute_cpu_resources(&list, &surface, &resources) == 0);
    int touched = 0;
    for (int i = 0; i < 32 * 32; i++) touched += frame[i] != 0;
    assert(touched > 0);
    for (int i = 0; i < 32 * 32; i++) frame[i] = 0;
    list.commands[0].data.clip.rect = (GfxRect){0, 0, 1, 1};
    assert(gfx_execute_cpu_resources(&list, &surface, &resources) == 0);
    for (int i = 0; i < 32 * 32; i++) assert(frame[i] == 0);

    /* scale: 0 == 1; scale 2 turns every glyph pixel into a 2x2 block. */
    uint16_t one[32 * 32] = {0}, two[64 * 64] = {0};
    GfxSurface s1 = {one, 32, 32, 32}, s2 = {two, 64, 64, 64};
    list.commands[0].data.clip.rect = (GfxRect){0, 0, 64, 64};
    for (int i = 0; i < 32 * 32; i++) frame[i] = 0;
    assert(gfx_execute_cpu_resources(&list, &surface, &resources) == 0);
    list.commands[1].data.glyph_run.scale = 1;
    assert(gfx_execute_cpu_resources(&list, &s1, &resources) == 0);
    for (int i = 0; i < 32 * 32; i++) assert(one[i] == frame[i]);
    pg = (GfxPositionedGlyph){'A', 4, 30};
    list.commands[1].data.glyph_run.scale = 2;
    assert(gfx_execute_cpu_resources(&list, &s2, &resources) == 0);
    /* Same glyph at 1x with pen (2, 15) and at 2x with pen (4, 30): pixel (x, y) maps to block (2x, 2y). */
    for (int y = 0; y < 32; y++)
        for (int x = 0; x < 32; x++)
            for (int dy = 0; dy < 2; dy++)
                for (int dx = 0; dx < 2; dx++) assert(two[(2 * y + dy) * 64 + 2 * x + dx] == frame[y * 32 + x]);
    list.commands[1].data.glyph_run.scale = GFX_GLYPH_MAX_SCALE + 1;
    assert(gfx_execute_cpu_resources(&list, &s2, &resources) != 0);
    gfx_list_destroy(&list);
    free(data);
    puts("GLYPH_RUN, scale and clipping OK");
    return 0;
}
