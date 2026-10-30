/* Plataforma host para sketches Processing: proporciona main() y ejecuta
   setup() y un solo draw() con la version de MiniGL elegida, y guarda el
   framebuffer RGB565 como PPM.

   Uso: sketch [-v 0|1|2|all] [-f frames] [-o salida.ppm|salida.bin]
     -v 0    V0: directo, la CPU rasteriza al llamar
     -v 1    V1: diferido, command buffer interpretado por la CPU
     -v 2    V2: diferido, command buffer interpretado por la GPU (8 lanes, emulacion host)
     -v all  las tres; comprueba que los framebuffers son identicos (por defecto)
     -f N    ejecuta draw() N veces (por defecto 1) y guarda el ultimo frame
   Salida por defecto: <sketch>-v<N>.ppm en el directorio actual. Con -o x.bin, RGB565
   crudo little-endian: el mismo formato que vuelca el simulador (--frame-output),
   para compararlos con tools/compare-frames.py. */

#include "platform.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Ejecuta setup() y `frames` draw() con la version v; deja el resultado en platform_frame. */
static int run(int v, int frames) {
    platform_reset();
    if (platform_begin(v) != MGL_OK) return -1;
    setup();
    if (platform_end(v) != MGL_OK) return -1;
    while (frameCount < frames) {
        frameCount++;
        if (platform_begin(v) != MGL_OK) return -1;
        draw();
        if (platform_end(v) != MGL_OK) return -1;
    }
    return MGL_OK;
}

static int write_ppm(const char *path) {
    FILE *f = fopen(path, "wb");
    long i, n = (long)width * height;
    if (!f) {
        perror(path);
        return -1;
    }
    fprintf(f, "P6\n%d %d\n255\n", width, height);
    for (i = 0; i < n; i++) {
        unsigned int c = platform_frame[i], r = (c >> 11) & 31U, g = (c >> 5) & 63U, b = c & 31U;
        putc((int)((r << 3) | (r >> 2)), f);
        putc((int)((g << 2) | (g >> 4)), f);
        putc((int)((b << 3) | (b >> 2)), f);
    }
    return fclose(f) == 0 ? 0 : -1;
}

/* RGB565 crudo, little-endian, como `sim-sys --frame-output`. */
static int write_rgb565(const char *path) {
    FILE *f = fopen(path, "wb");
    long i, n = (long)width * height;
    if (!f) {
        perror(path);
        return -1;
    }
    for (i = 0; i < n; i++) {
        putc((int)(platform_frame[i] & 0xffU), f);
        putc((int)(platform_frame[i] >> 8), f);
    }
    return fclose(f) == 0 ? 0 : -1;
}

static int is_bin(const char *path) {
    size_t n = strlen(path);
    return n > 4 && !strcmp(path + n - 4, ".bin");
}

static const char *base_name(const char *path) {
    const char *s = strrchr(path, '/');
    return s ? s + 1 : path;
}

static int usage(const char *prog) {
    fprintf(stderr, "uso: %s [-v 0|1|2|all] [-f frames] [-o salida.ppm|salida.bin]\n", prog);
    return 2;
}

int main(int argc, char **argv) {
    const char *version = "all", *out = 0;
    char path[256];
    mgl_color_t *reference = 0;
    int i, v, first, last, x, y, frames = 1;
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-v") && i + 1 < argc)
            version = argv[++i];
        else if (!strcmp(argv[i], "-f") && i + 1 < argc) {
            if ((frames = atoi(argv[++i])) < 1) return usage(argv[0]);
        } else if (!strcmp(argv[i], "-o") && i + 1 < argc)
            out = argv[++i];
        else
            return usage(argv[0]);
    }
    if (!strcmp(version, "all")) {
        first = 0;
        last = PLATFORM_VERSIONS - 1;
    } else if ((first = last = platform_parse_version(version)) < 0)
        return usage(argv[0]);
    if (out && first != last) {
        fputs("-o solo con una version concreta\n", stderr);
        return 2;
    }

    for (v = first; v <= last; v++) {
        if (run(v, frames)) return 1;
        if (out)
            strncpy(path, out, sizeof path - 1);
        else
            sprintf(path, "%.200s-v%d.ppm", base_name(argv[0]), v);
        path[sizeof path - 1] = 0;
        if (is_bin(path) ? write_rgb565(path) : write_ppm(path)) return 1;
        printf("V%d %dx%d -> %s", v, width, height, path);
        if (v > 0) printf(" (%u bytes de comandos)", platform_command_bytes());
        putchar('\n');
        if (first == last) continue;
        if (!reference) {
            reference = (mgl_color_t *)malloc((size_t)width * height * sizeof *reference);
            if (!reference) {
                fputs("sin memoria\n", stderr);
                return 1;
            }
            memcpy(reference, platform_frame, (size_t)width * height * sizeof *reference);
            continue;
        }
        for (y = 0; y < height; y++)
            for (x = 0; x < width; x++)
                if (reference[y * width + x] != platform_frame[y * width + x]) {
                    printf("FAIL: V%d distinto de V0 en (%d,%d): %04x frente a %04x\n", v, x, y,
                        (unsigned)platform_frame[y * width + x],
                        (unsigned)reference[y * width + x]);
                    return 1;
                }
    }
    if (first != last) printf("PASS: V0 == V1 == V2\n");
    free(reference);
    return 0;
}
