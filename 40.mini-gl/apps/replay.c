/* mgl-replay: ejecuta una captura (mgl_capture.h) con el renderer de
   referencia y guarda el framebuffer. No enlaza MiniGL ni Processing: prueba
   que el command buffer y la RAM bastan para reproducir el frame.

   Uso: mgl-replay captura.mglx salida.ppm|salida.bin */

#include "mgr.h"
#include "mgl_capture.h"
#include "ppm.h"
#include <stdio.h>
#include <stdlib.h>

#define MAX_RAM 0x01000000u

int main(int argc, char **argv) {
    mgl_capture_t c;
    mgl_memory_t m;
    mgr_renderer_t r;
    unsigned char *ram;
    mgl_color_t *pixels;
    int result;
    if (argc != 3) {
        fprintf(stderr, "uso: %s captura.mglx salida.ppm|salida.bin\n", argv[0]);
        return 2;
    }
    ram = (unsigned char *)malloc(MAX_RAM);
    if (!ram || mgl_capture_load(argv[1], &c, ram, MAX_RAM)) return 1;
    if (mgl_memory_init(&m, ram, c.ram_addr, c.ram_size) || mgr_init(&r, &m) != MGR_OK) return 1;
    result = mgr_execute(&r, c.commands);
    if (result != MGR_OK) {
        fprintf(stderr, "error %d en el offset %u\n", result, (unsigned)r.error_offset);
        return 1;
    }
    pixels = (mgl_color_t *)mgl_memory_ptr(&m, c.color, c.width * c.height * 2U, 2);
    if (!pixels) return 1;
    if ((ppm_is_raw(argv[2]) ? ppm_write_raw : ppm_write)(argv[2], pixels, (int)c.width, (int)c.height,
            (int)c.width))
        return 1;
    printf("%u comandos, %u triángulos, %u fragmentos -> %s\n", r.stats.commands, r.stats.triangles,
        r.stats.fragments, argv[2]);
    free(ram);
    return 0;
}
