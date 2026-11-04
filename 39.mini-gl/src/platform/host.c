/* Driver host común: CLI, memoria, bucle, capturas e imágenes. El contexto
   enlazado elige V0/V1/V2 o el pipeline 3D; aquí no se rasteriza. */
#include "platform.h"
#include "ppm.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *capture_path;
static int capture_now, capture_error;

static void capture(void) {
    mgl_capture_t c;
    const void *ram;
    if (!capture_now) return;
    if (mgl_context_capture(&c, &ram) != MGL_OK || mgl_capture_save(capture_path, &c, ram))
        capture_error = 1;
}

static int frame(int last) {
    mgl_context_info_t info;
    int r;
    capture_now = last && capture_path;
    r = platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, frameCount ? draw : setup, capture);
    if (r != MGL_OK || capture_error) {
        mgl_context_info(&info);
        fprintf(stderr, "frame %d: error %d (comando en el offset %u)\n", frameCount, r,
            (unsigned)info.error_offset);
        return 1;
    }
    return 0;
}

static const char *base_name(const char *path) {
    const char *s = strrchr(path, '/');
    return s ? s + 1 : path;
}

static int save(const char *path) {
    mgl_color_t *p = mgl_context_pixels();
    return (ppm_is_raw(path) ? ppm_write_raw : ppm_write)(path, p, width, height, width);
}

static int usage(const char *prog) {
    fprintf(stderr, "uso: %s [-v 0|1|2|all] [-f frames] [-e K] [-o salida.ppm|salida.bin] [-c captura.mglx] [-q]\n", prog);
    return 2;
}

int main(int argc, char **argv) {
    const char *version = 0, *out = 0;
    char path[256];
    mgl_color_t *reference = 0;
    unsigned char *ram = 0;
    mgl_u32 ram_size = mgl_context_ram_size();
    mgl_context_info_t info;
    int i, v, first = 0, last = 0, x, y, frames = 1, every = 0, quiet = 0;
    int reference_width = 0, reference_height = 0;
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-v") && i + 1 < argc)
            version = argv[++i];
        else if (!strcmp(argv[i], "-f") && i + 1 < argc) {
            if ((frames = atoi(argv[++i])) < 1) return usage(argv[0]);
        } else if (!strcmp(argv[i], "-e") && i + 1 < argc) {
            if ((every = atoi(argv[++i])) < 1) return usage(argv[0]);
        } else if (!strcmp(argv[i], "-o") && i + 1 < argc)
            out = argv[++i];
        else if (!strcmp(argv[i], "-c") && i + 1 < argc)
            capture_path = argv[++i];
        else if (!strcmp(argv[i], "-q")) quiet = 1;
        else return usage(argv[0]);
    }
    if (mgl_context_is3d()) {
        if (version) return usage(argv[0]);
    } else {
        if (capture_path) return usage(argv[0]);
        if (!version || !strcmp(version, "all")) last = PLATFORM_VERSIONS - 1;
        else if ((first = last = platform_parse_version(version)) < 0) return usage(argv[0]);
    }
    if ((out || every) && first != last) return usage(argv[0]);
    for (v = first; v <= last; v++) {
        if (ram_size) ram = (unsigned char *)calloc(ram_size, 1);
        if ((ram_size && !ram) || platform_init(ram, v) != MGL_OK) return 1;
        if (frame(0)) return 1;
        while (frameCount < frames) {
            frameCount++;
            if (frame(frameCount == frames)) return 1;
            if (every && frameCount % every == 0) {
                sprintf(path, "%.200s-%04d.ppm", base_name(argv[0]), frameCount);
                if (save(path)) return 1;
                if (!quiet) printf("frame %d -> %s\n", frameCount, path);
            }
        }
        if (out) strncpy(path, out, sizeof path - 1);
        else if (mgl_context_is3d()) sprintf(path, "%.200s.ppm", base_name(argv[0]));
        else sprintf(path, "%.200s-v%d.ppm", base_name(argv[0]), v);
        path[sizeof path - 1] = 0;
        if (save(path)) return 1;
        mgl_context_info(&info);
        if (!quiet) {
            if (mgl_context_is3d()) {
                printf("%dx%d, %d frames -> %s (%u bytes de comandos en el último)\n", width, height, frames,
                    path, (unsigned)info.command_bytes);
                printf("renderer: %u comandos, %u triángulos (%u descartados, %u recortados, %u por cara), "
                       "%u rasterizados, %u fragmentos\n", (unsigned)info.commands, (unsigned)info.triangles,
                    (unsigned)info.rejected, (unsigned)info.clipped, (unsigned)info.culled,
                    (unsigned)info.rasterized, (unsigned)info.fragments);
            } else {
                printf("V%d %dx%d -> %s", v, width, height, path);
                if (v > 0) printf(" (%u bytes de comandos)", (unsigned)info.command_bytes);
                putchar('\n');
            }
        }
        if (first != last) {
            if (!reference) {
                reference_width = width;
                reference_height = height;
                reference = (mgl_color_t *)malloc((size_t)width * height * sizeof *reference);
                if (!reference) return 1;
                memcpy(reference, mgl_context_pixels(), (size_t)width * height * sizeof *reference);
            } else {
                if (width != reference_width || height != reference_height) return 1;
                for (y = 0; y < height; y++)
                    for (x = 0; x < width; x++)
                        if (reference[y * width + x] != mgl_context_pixels()[y * width + x]) {
                            fprintf(stderr, "FAIL: V%d distinto de V0 en (%d,%d)\n", v, x, y);
                            return 1;
                        }
            }
        }
        platform_shutdown();
        free(ram);
        ram = 0;
    }
    if (first != last && !quiet) puts("PASS: V0 == V1 == V2");
    free(reference);
    return 0;
}
