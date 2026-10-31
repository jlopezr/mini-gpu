/* Plataforma host para sketches 3D: RAM compartida emulada, setup() y N draw(),
   cada frame grabado por MiniGL y ejecutado por el renderer de referencia
   (renderer/). Guarda frames como PPM.

   Uso: sketch [-f frames] [-o salida.ppm|salida.bin] [-e K] [-c captura.mglx] [-q]
     -f N    ejecuta draw() N veces (por defecto 1) y guarda el último frame
     -o      salida del último frame (por defecto <sketch>.ppm); .bin: RGB565 crudo,
             como `sim-sys --frame-output`, para tools/compare-frames.py
     -e K    guarda además cada K frames como <sketch>-NNNN.ppm
     -c F    guarda la captura del último frame (RAM + command buffer) para mgl-replay
     -q      sin estadísticas */

#include "platform3d.h"
#include "mgl_capture.h"
#include "ppm.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char *ram;
static const char *capture_path;
static int capture_now;

static void capture(void) {
    mgl_capture_t c;
    if (!capture_now) return;
    c.ram_addr = P3D_RAM_BASE;
    c.ram_size = P3D_RAM_SIZE;
    c.commands = P3D_COMMANDS;
    c.color = P3D_FB_A;
    c.width = (mgl_u32)width;
    c.height = (mgl_u32)height;
    if (mgl_capture_save(capture_path, &c, ram)) exit(1);
}

static int frame(int last) {
    int r;
    if (platform3d_begin(P3D_FB_A) != MGL_OK) return -1;
    if (frameCount)
        draw();
    else
        setup();
    capture_now = last && capture_path;
    r = platform3d_end(capture);
    if (r != MGL_OK) {
        fprintf(stderr, "frame %d: error %d (comando en el offset %u)\n", frameCount, r,
            (unsigned)platform3d_renderer.error_offset);
        return -1;
    }
    return 0;
}

static const char *base_name(const char *path) {
    const char *s = strrchr(path, '/');
    return s ? s + 1 : path;
}

static int save(const char *path) {
    mgl_color_t *p = platform3d_pixels(P3D_FB_A);
    return (ppm_is_raw(path) ? ppm_write_raw : ppm_write)(path, p, width, height, width);
}

static int usage(const char *prog) {
    fprintf(stderr, "uso: %s [-f frames] [-o salida.ppm|salida.bin] [-e K] [-c captura.mglx] [-q]\n", prog);
    return 2;
}

int main(int argc, char **argv) {
    const char *out = 0;
    char path[256];
    int i, frames = 1, every = 0, quiet = 0;
    mgr_stats_t *st = &platform3d_renderer.stats;
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-f") && i + 1 < argc) {
            if ((frames = atoi(argv[++i])) < 1) return usage(argv[0]);
        } else if (!strcmp(argv[i], "-e") && i + 1 < argc) {
            if ((every = atoi(argv[++i])) < 1) return usage(argv[0]);
        } else if (!strcmp(argv[i], "-o") && i + 1 < argc)
            out = argv[++i];
        else if (!strcmp(argv[i], "-c") && i + 1 < argc)
            capture_path = argv[++i];
        else if (!strcmp(argv[i], "-q"))
            quiet = 1;
        else
            return usage(argv[0]);
    }
    ram = (unsigned char *)calloc(P3D_RAM_SIZE, 1); /* el lienzo empieza negro */
    if (!ram || platform3d_init(ram)) {
        fputs("no se pudo preparar la RAM emulada\n", stderr);
        return 1;
    }
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
    if (out)
        strncpy(path, out, sizeof path - 1);
    else
        sprintf(path, "%.200s.ppm", base_name(argv[0]));
    path[sizeof path - 1] = 0;
    if (save(path)) return 1;
    if (!quiet) {
        printf("%dx%d, %d frames -> %s (%u bytes de comandos en el último)\n", width, height, frames, path,
            (unsigned)platform3d_commands.used);
        printf("renderer: %u comandos, %u triángulos (%u descartados, %u recortados, %u por cara), "
               "%u rasterizados, %u fragmentos\n",
            st->commands, st->triangles, st->rejected, st->clipped, st->culled, st->rasterized,
            st->fragments);
    }
    free(ram);
    return 0;
}
