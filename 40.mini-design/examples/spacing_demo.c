/* Spacing demo: 12 NewsMaster fonts laid out with advance_x only (blue) and
   with advance_x + font_spacing (black), to check the spacing visually.
   Output: spacing.ppm (2x scaled)
   Usage: spacing_demo [font_dir] [output.ppm]   (defaults build/fonts, spacing.ppm) */
#include "gfx.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { W = 640,
    SCALE = 2,
    MAXG = 128,
    MAXF = 12 };
static const char *names[] = {"park10", "park12", "news10", "news12", "news18", "hampton", "office", "scribe", "twig", "cafe", "smallcap", "bremen"};
static const char *sample = "Hamburgefonstiv AVWA mm ii 0123";

static uint8_t *load(const char *file, size_t *n) {
    FILE *f = fopen(file, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END)) {
        fclose(f);
        return NULL;
    }
    long z = ftell(f);
    if (z <= 0 || fseek(f, 0, SEEK_SET)) {
        fclose(f);
        return NULL;
    }
    uint8_t *p = malloc((size_t)z);
    if (!p) {
        fclose(f);
        return NULL;
    }
    if (fread(p, 1, (size_t)z, f) != (size_t)z) {
        free(p);
        fclose(f);
        return NULL;
    }
    fclose(f);
    *n = (size_t)z;
    return p;
}
/* extra=0: solo advance_x; extra=font_spacing: advance_x + spacing. El espacio (sin glifo) avanza pixel_size/2. */
static uint32_t layout(const MfFont *font, const char *text, int x, int baseline, int extra, GfxPositionedGlyph *out) {
    uint32_t n = 0;
    int pen = x;
    for (const unsigned char *p = (const unsigned char *)text; *p && n < MAXG; p++) {
        MfGlyph g;
        if (mf_find_glyph(font, *p, &g)) {
            pen += font->pixel_size / 2 + extra;
            continue;
        }
        out[n++] = (GfxPositionedGlyph){*p, pen, baseline};
        pen += g.advance_x + extra;
    }
    return n;
}
static int write_scaled(const char *path, const GfxSurface *s) {
    FILE *f = fopen(path, "wb");
    if (!f) return -1;
    fprintf(f, "P6\n%u %u\n255\n", s->width * SCALE, s->height * SCALE);
    for (uint32_t y = 0; y < s->height * SCALE; y++)
        for (uint32_t x = 0; x < s->width * SCALE; x++) {
            uint16_t c = s->pixels[(y / SCALE) * s->stride + x / SCALE];
            unsigned char rgb[3] = {(unsigned char)((c >> 11) * 255 / 31), (unsigned char)(((c >> 5) & 63) * 255 / 63), (unsigned char)((c & 31) * 255 / 31)};
            fwrite(rgb, 1, 3, f);
        }
    return fclose(f) ? -1 : 0;
}
int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : "build/fonts", *outp = argc > 2 ? argv[2] : "spacing.ppm";
    MfFont fonts[MAXF];
    uint8_t *data[MAXF] = {0};
    const MfFont *fp[MAXF];
    for (int i = 0; i < MAXF; i++) {
        char path[512];
        size_t n = 0;
        snprintf(path, sizeof path, "%s/%s.mf", dir, names[i]);
        if (!(data[i] = load(path, &n)) || mf_open(&fonts[i], data[i], n)) {
            fprintf(stderr, "Cannot open MFNT font: %s\n", path);
            return 1;
        }
        fp[i] = &fonts[i];
    }
    static GfxPositionedGlyph glyphs[MAXF * 3][MAXG];
    GfxGlyphRun runs[MAXF * 3];
    static char labels[MAXF][64];
    int y = 6, lh = fonts[0].ascent + fonts[0].descent;
    for (int i = 0; i < MAXF; i++) {
        int h = fonts[i].ascent + fonts[i].descent + 3;
        snprintf(labels[i], sizeof labels[i], "%s   font_spacing=%d", names[i], fonts[i].font_spacing);
        y += fonts[0].ascent;
        runs[3 * i] = (GfxGlyphRun){glyphs[3 * i], layout(&fonts[0], labels[i], 8, y, fonts[0].font_spacing, glyphs[3 * i]), 0};
        y += fonts[0].descent + 2;
        y += fonts[i].ascent;
        runs[3 * i + 1] = (GfxGlyphRun){glyphs[3 * i + 1], layout(&fonts[i], sample, 24, y, 0, glyphs[3 * i + 1]), (uint32_t)i};
        y += h - fonts[i].ascent;
        y += fonts[i].ascent;
        runs[3 * i + 2] = (GfxGlyphRun){glyphs[3 * i + 2], layout(&fonts[i], sample, 24, y, fonts[i].font_spacing, glyphs[3 * i + 2]), (uint32_t)i};
        y += h - fonts[i].ascent + lh / 2;
    }
    int H = y + 4;
    uint16_t *pixels = calloc((size_t)W * H, sizeof(uint16_t));
    if (!pixels) return 1;
    GfxSurface surface = {pixels, W, (uint32_t)H, W};
    GfxResources res = {.fonts = fp, .font_count = MAXF, .runs = runs, .run_count = MAXF * 3};
    GfxDisplayList dl;
    gfx_list_init(&dl);
    int fail = 0;
    fail |= gfx_list_add(&dl, (GfxCommand){.opcode = GFX_CLEAR, .data.clear = {0xFFFF}});
    for (uint32_t r = 0; r < MAXF * 3; r++) {
        uint16_t color = r % 3 == 0 ? 0x8410 : r % 3 == 1 ? 0x0016
                                                          : 0x0000; /* etiqueta gris, sin spacing azul, con spacing negro */
        fail |= gfx_list_add(&dl, (GfxCommand){.opcode = GFX_GLYPH_RUN, .data.glyph_run = {.run_id = r, .color = color}});
    }
    if (!fail) fail = gfx_execute_cpu_resources(&dl, &surface, &res);
    if (!fail) fail = write_scaled(outp, &surface);
    gfx_list_destroy(&dl);
    free(pixels);
    for (int i = 0; i < MAXF; i++) free(data[i]);
    if (fail) {
        fprintf(stderr, "spacing_demo failed\n");
        return 1;
    }
    printf("Created %s (azul: advance_x, negro: advance_x + font_spacing)\n", outp);
    return 0;
}
