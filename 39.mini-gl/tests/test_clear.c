/* Se ejecuta en el host y, con build-c, en MiniGPU: comprueba también la
   ruta de palabras de 32 bits, alineación, colas y padding con centinelas. */
#include "mgr_stages.h"

static mgl_u16 color[128], depth[128];

int main(void) {
    mgr_state_t s;
    int width, pad, offset, i, y, x, inside;
    s.height = 3;
    for (width = 1; width <= 19; width++)
        for (pad = 0; pad <= 3; pad++)
            for (offset = 0; offset <= 1; offset++) {
                for (i = 0; i < 128; i++) color[i] = depth[i] = 0xa55a;
                s.width = width;
                s.color_stride = s.depth_stride = width + pad;
                s.color = color + 2 + offset;
                s.depth = depth + 2 + offset;
                mgr_clear_color(&s, 0x1234);
                mgr_clear_depth(&s, 0xfedc);
                for (i = 0; i < 128; i++) {
                    inside = 0;
                    for (y = 0; y < s.height; y++) {
                        x = i - (2 + offset + y * s.color_stride);
                        if (x >= 0 && x < width) inside = 1;
                    }
                    if (color[i] != (inside ? 0x1234 : 0xa55a) ||
                        depth[i] != (inside ? 0xfedc : 0xa55a)) return 1;
                }
            }
    s.depth = 0;
    mgr_clear_depth(&s, 0);
    return 0;
}
