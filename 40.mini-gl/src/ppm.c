#include "ppm.h"
#include <stdio.h>
#include <string.h>

int ppm_write(const char *path, const mgl_color_t *pixels, int width, int height, int stride) {
    FILE *f = fopen(path, "wb");
    int x, y;
    if (!f) {
        perror(path);
        return -1;
    }
    fprintf(f, "P6\n%d %d\n255\n", width, height);
    for (y = 0; y < height; y++)
        for (x = 0; x < width; x++) {
            unsigned int c = pixels[y * stride + x], r = (c >> 11) & 31U, g = (c >> 5) & 63U, b = c & 31U;
            putc((int)((r << 3) | (r >> 2)), f);
            putc((int)((g << 2) | (g >> 4)), f);
            putc((int)((b << 3) | (b >> 2)), f);
        }
    return fclose(f) == 0 ? 0 : -1;
}

int ppm_write_raw(const char *path, const mgl_color_t *pixels, int width, int height, int stride) {
    FILE *f = fopen(path, "wb");
    int x, y;
    if (!f) {
        perror(path);
        return -1;
    }
    for (y = 0; y < height; y++)
        for (x = 0; x < width; x++) {
            putc((int)(pixels[y * stride + x] & 0xffU), f);
            putc((int)(pixels[y * stride + x] >> 8), f);
        }
    return fclose(f) == 0 ? 0 : -1;
}

int ppm_is_raw(const char *path) {
    size_t n = strlen(path);
    return n > 4 && !strcmp(path + n - 4, ".bin");
}
