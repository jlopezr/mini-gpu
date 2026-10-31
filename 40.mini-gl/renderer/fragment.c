#include "mgr_stages.h"

/* Por píxel, en orden: profundidad (si hay buffer y está activa la prueba: pasa
   si es menor, LESS), escritura de profundidad (si está activa) y color. Sin
   blending todavía: el color se escribe tal cual.

   Todo entero: la profundidad llega interpolada en punto fijo (raster3d.c) y
   aquí solo se suma. El redondeo puede sacarla un poco de [0, 1] en los
   bordes: se recorta. */
void mgr_fragment_span(const mgr_fragment_t *f, int y, int x0, int x1, mgl_s32 z, mgl_s32 dz) {
    mgl_color_t *c = f->color + y * f->color_stride + x0, fill = f->fill;
    mgl_u16 *d;
    mgl_s32 n = x1 - x0;
    unsigned int v;
    int test, write;
    if (n <= 0) return;
    test = f->depth && (f->flags & MGL_STATE_DEPTH_TEST);
    write = f->depth && (f->flags & MGL_STATE_DEPTH_WRITE);
    if (!test && !write) {
        for (; n > 0; n--) *c++ = fill;
        return;
    }
    d = f->depth + y * f->depth_stride + x0;
    for (; n > 0; n--, c++, d++, z += dz) {
        v = z <= 0 ? 0U : z >= MGR_DEPTH_MAX ? 65535U : (unsigned int)z >> MGR_DEPTH_FRAC;
        if (test && v >= *d) continue;
        if (write) *d = (mgl_u16)v;
        *c = fill;
    }
}

void mgr_clear_color(const mgr_state_t *s, mgl_color_t c) {
    int x, y;
    mgl_color_t *row = s->color;
    for (y = 0; y < s->height; y++, row += s->color_stride)
        for (x = 0; x < s->width; x++) row[x] = c;
}

void mgr_clear_depth(const mgr_state_t *s, mgl_u16 d) {
    int x, y;
    mgl_u16 *row = s->depth;
    if (!row) return;
    for (y = 0; y < s->height; y++, row += s->depth_stride)
        for (x = 0; x < s->width; x++) row[x] = d;
}
