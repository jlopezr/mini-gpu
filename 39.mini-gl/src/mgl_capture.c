#include "mgl_capture.h"
#include "mgl_bytes.h"
#include <stdio.h>
#include <string.h>

#define HEADER 32

int mgl_capture_save(const char *path, const mgl_capture_t *c, const void *ram) {
    unsigned char h[HEADER];
    FILE *f = fopen(path, "wb");
    int ok;
    if (!f) {
        perror(path);
        return -1;
    }
    memcpy(h, "MGLX", 4);
    WR32(h + 4, 1U);
    WR32(h + 8, c->ram_addr);
    WR32(h + 12, c->ram_size);
    WR32(h + 16, c->commands);
    WR32(h + 20, c->color);
    WR32(h + 24, c->width);
    WR32(h + 28, c->height);
    ok = fwrite(h, 1, HEADER, f) == HEADER && fwrite(ram, 1, c->ram_size, f) == c->ram_size;
    return fclose(f) == 0 && ok ? 0 : -1;
}

int mgl_capture_load(const char *path, mgl_capture_t *c, void *ram, mgl_u32 capacity) {
    unsigned char h[HEADER];
    FILE *f = fopen(path, "rb");
    int ok;
    if (!f) {
        perror(path);
        return -1;
    }
    ok = fread(h, 1, HEADER, f) == HEADER && !memcmp(h, "MGLX", 4) && RD32(h + 4) == 1U;
    if (ok) {
        c->ram_addr = RD32(h + 8);
        c->ram_size = RD32(h + 12);
        c->commands = RD32(h + 16);
        c->color = RD32(h + 20);
        c->width = RD32(h + 24);
        c->height = RD32(h + 28);
        ok = c->ram_size <= capacity && fread(ram, 1, c->ram_size, f) == c->ram_size;
    }
    fclose(f);
    if (!ok) fprintf(stderr, "%s: no es una captura MGLX valida\n", path);
    return ok ? 0 : -1;
}
