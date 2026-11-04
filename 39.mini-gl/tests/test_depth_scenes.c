/* Experimento diferencial: el mismo command buffer y la misma RAM inicial
   con el renderer de referencia y con profundidad incremental. */
#include "context3d.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int mgr_execute_reference(mgr_renderer_t *r, mgl_u32 addr);

static unsigned char *snapshot;
static mgl_u16 reference_color[P3D_MAX_W * P3D_MAX_H];
static mgl_u16 reference_depth[P3D_MAX_W * P3D_MAX_H];

static void save_ram(void) {
    memcpy(snapshot, context3d_memory.base, P3D_RAM_SIZE);
}

static int dump(const char *prefix, const char *suffix, const mgl_u16 *p) {
    char path[256];
    FILE *file;
    int ok;
    if (strlen(prefix) > 200) return 1;
    sprintf(path, "%s-%s.bin", prefix, suffix);
    file = fopen(path, "wb");
    if (!file) return 1;
    ok = fwrite(p, sizeof *p, P3D_MAX_W * P3D_MAX_H, file) == P3D_MAX_W * P3D_MAX_H;
    if (fclose(file)) ok = 0;
    return !ok;
}

int main(int argc, char **argv) {
    unsigned char *ram = (unsigned char *)calloc(P3D_RAM_SIZE, 1);
    mgl_u16 *color, *depth;
    unsigned long color_changes = 0, depth_changes = 0;
    int frame, i, delta, max_delta = 0;
    snapshot = (unsigned char *)malloc(P3D_RAM_SIZE);
    if (!ram || !snapshot || context3d_init(ram)) return 2;
    for (frame = 0; frame <= 120; frame++) {
        frameCount = frame;
        if (context3d_begin(P3D_FB_A) != MGL_OK) return 2;
        if (frame) draw(); else setup();
        if (context3d_end(save_ram) != MGL_OK) return 2;
        memcpy(ram, snapshot, P3D_RAM_SIZE);
        if (mgr_execute_reference(&context3d_renderer, P3D_COMMANDS) != MGR_OK) return 2;
        color = context3d_pixels(P3D_FB_A);
        depth = (mgl_u16 *)mgl_memory_ptr(&context3d_memory, P3D_DEPTH, sizeof reference_depth, 2);
        memcpy(reference_color, color, sizeof reference_color);
        memcpy(reference_depth, depth, sizeof reference_depth);
        memcpy(ram, snapshot, P3D_RAM_SIZE);
        if (mgr_execute(&context3d_renderer, P3D_COMMANDS) != MGR_OK) return 2;
        if (frame == 3 && argc == 2) {
            if (dump(argv[1], "reference-color", reference_color) ||
                dump(argv[1], "reference-depth", reference_depth) ||
                dump(argv[1], "incremental-color", color) ||
                dump(argv[1], "incremental-depth", depth)) return 2;
        }
        for (i = 0; i < P3D_MAX_W * P3D_MAX_H; i++) {
            color_changes += color[i] != reference_color[i];
            depth_changes += depth[i] != reference_depth[i];
            delta = (int)depth[i] - (int)reference_depth[i];
            if (delta < 0) delta = -delta;
            if (delta > max_delta) max_delta = delta;
        }
        /* El siguiente frame siempre parte del resultado de referencia. */
        memcpy(color, reference_color, sizeof reference_color);
        memcpy(depth, reference_depth, sizeof reference_depth);
    }
    printf("120 frames: color_changed=%lu depth_changed=%lu max_depth_delta=%d\n",
        color_changes, depth_changes, max_delta);
    free(snapshot);
    free(ram);
    return color_changes || max_delta > 1;
}
