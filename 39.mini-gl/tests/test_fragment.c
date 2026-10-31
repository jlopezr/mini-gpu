/* Contrasta todos los modos de profundidad contra el bucle escalar original.
   Incluye LESS estricto, saturación, gradientes de ambos signos, strides
   distintos y spans vacíos. Sin libc para ejecutarlo también en MiniGPU. */
#include "mgr_stages.h"

static mgl_u16 color[48], depth[48], expected_color[48], expected_depth[48];
static const mgl_s32 starts[] = {-512, 0, 256, MGR_DEPTH_MAX - 256, MGR_DEPTH_MAX + 512};
static const mgl_s32 steps[] = {-257, 0, 257};

int main(void) {
    mgr_fragment_t f;
    int mode, buffer, a, b, length, i, j;
    mgl_s32 z;
    unsigned int v;
    f.color = color;
    f.color_stride = 12;
    f.depth_stride = 13;
    f.fill = 0x1234;
    for (mode = 0; mode < 4; mode++)
        for (buffer = 0; buffer < 2; buffer++)
            for (a = 0; a < 5; a++)
                for (b = 0; b < 3; b++)
                    for (length = -1; length <= 8; length++) {
                        f.flags = (mode & 1 ? MGL_STATE_DEPTH_TEST : 0) |
                            (mode & 2 ? MGL_STATE_DEPTH_WRITE : 0);
                        f.depth = buffer ? depth : 0;
                        for (i = 0; i < 48; i++) {
                            color[i] = expected_color[i] = 0xa55a;
                            depth[i] = expected_depth[i] = (mgl_u16)((i % 3) * 32767);
                        }
                        z = starts[a];
                        for (i = 0; i < length; i++, z += steps[b]) {
                            j = 15 + i; /* fila 1, columna 2, stride 13 */
                            v = z <= 0 ? 0U : z >= MGR_DEPTH_MAX ? 65535U :
                                (unsigned int)z >> MGR_DEPTH_FRAC;
                            if (buffer && (mode & 1) && v >= expected_depth[j]) continue;
                            if (buffer && (mode & 2)) expected_depth[j] = (mgl_u16)v;
                            expected_color[14 + i] = f.fill;
                        }
                        mgr_fragment_span(&f, 1, 2, 2 + length, starts[a], steps[b]);
                        for (i = 0; i < 48; i++)
                            if (color[i] != expected_color[i] || depth[i] != expected_depth[i]) return 1;
                    }
    return 0;
}
