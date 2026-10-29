#include "minifont.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s font.mf output.ppm\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f)
        return 1;
    if (fseek(f, 0, SEEK_END)) {
        fclose(f);
        return 1;
    }
    long size = ftell(f);
    rewind(f);
    if (size <= 0) {
        fclose(f);
        return 1;
    }
    uint8_t *buf = malloc((size_t)size);
    if (!buf || fread(buf, 1, (size_t)size, f) != (size_t)size) {
        fclose(f);
        free(buf);
        return 1;
    }
    fclose(f);
    MfFont font;
    if (mf_open(&font, buf, (size_t)size)) {
        fprintf(stderr, "invalid font\n");
        free(buf);
        return 1;
    }
    enum {
        W = 320,
        H = 100
    };
    uint16_t *pixels = malloc(W * H * sizeof(*pixels));
    if (!pixels) {
        free(buf);
        return 1;
    }
    for (size_t i = 0; i < W * H; i++)
        pixels[i] = 0xffff;
    const char *line = "MiniFont ABC 123";
    int32_t x = 12, baseline = 30;
    for (const unsigned char *p = (const unsigned char *)line; *p; p++) {
        MfGlyph g;
        if (mf_find_glyph(&font, *p, &g) == 0) {
            mf_draw_glyph_rgb565(&font, &g, pixels, W, H, W, x, baseline, 0x0000);
            x += g.advance_x + font.font_spacing;
        }
    }
    FILE *out = fopen(argv[2], "wb");
    if (!out) {
        free(pixels);
        free(buf);
        return 1;
    }
    fprintf(out, "P6\n%d %d\n255\n", W, H);
    for (size_t i = 0; i < W * H; i++) {
        uint16_t c = pixels[i];
        unsigned char rgb[3] = {(unsigned char)(((c >> 11) & 31) * 255 / 31), (unsigned char)(((c >> 5) & 63) * 255 / 63), (unsigned char)((c & 31) * 255 / 31)};
        fwrite(rgb, 1, 3, out);
    }
    fclose(out);
    free(pixels);
    free(buf);
    printf("wrote %s\n", argv[2]);
    return 0;
}
