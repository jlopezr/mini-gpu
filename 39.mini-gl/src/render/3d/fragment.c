#include "mgr_stages.h"

#if defined(MGR_USE_ROP) && defined(__MINIGPU__)
#include "rop.h"
static int rop_pending;

int mgr_fragment_rop_begin(const mgr_fragment_t *f, mgl_s32 dz) {
    rop_config_t c;
    if (!f->depth || (f->flags & (MGL_STATE_DEPTH_TEST | MGL_STATE_DEPTH_WRITE)) !=
        (MGL_STATE_DEPTH_TEST | MGL_STATE_DEPTH_WRITE)) return 0;
    c.color_base = (rop_u32)f->color; c.z_base = (rop_u32)f->depth;
    c.color_stride = (rop_u32)(f->color_stride * 2); c.z_stride = (rop_u32)(f->depth_stride * 2);
    c.color_value = f->fill; c.z_initial = 0; c.dx = (rop_u32)dz; c.dy = 0;
    c.render_mode = ROP_Z_LT | ROP_MODE_WRITE_Z | ROP_MODE_WRITE_COLOR |
        (MGR_DEPTH_FRAC << 8) | ROP_MODE_SAT;
    c.groups = ROP_CONFIG_BASES | ROP_CONFIG_STRIDES | ROP_CONFIG_COLOR | ROP_CONFIG_Z | ROP_CONFIG_MODE;
    rop_submit_config_fenced(&c);
    rop_pending = 1;
    return 1;
}

void mgr_fragment_rop_span(const mgr_fragment_t *f, int y, int x0, int x1, mgl_s32 z) {
    rop_span_compact_t s;
    s.color_offset = (rop_u32)((y * f->color_stride + x0) * 2);
    s.z_offset = (rop_u32)((y * f->depth_stride + x0) * 2);
    s.pixels = (rop_u32)(x1 - x0); s.rows = 1; s.z_initial = (rop_u32)z;
    s.mode = 0x1200; /* COMPACT + sustituye Z0 */
    rop_submit_span_compact(&s);
}

void mgr_fragment_rop_finish(void) { if (rop_pending) { rop_wait_invalidate(); rop_pending = 0; } }
#else
int mgr_fragment_rop_begin(const mgr_fragment_t *f, mgl_s32 dz) { (void)f; (void)dz; return 0; }
void mgr_fragment_rop_span(const mgr_fragment_t *f, int y, int x0, int x1, mgl_s32 z)
{ (void)f; (void)y; (void)x0; (void)x1; (void)z; }
void mgr_fragment_rop_finish(void) {}
#endif

/* Por píxel, en orden: profundidad (si hay buffer y está activa la prueba: pasa
   si es menor, LESS), escritura de profundidad (si está activa) y color. Sin
   blending todavía: el color se escribe tal cual.

   Todo entero: la profundidad llega interpolada en punto fijo (raster3d.c) y
   aquí solo se suma. El redondeo puede sacarla un poco de [0, 1] en los
   bordes: se recorta. */
void mgr_fragment_span(const mgr_fragment_t *f, int y, int x0, int x1, mgl_s32 z, mgl_s32 dz) {
    mgl_color_t *c = f->color + y * f->color_stride + x0, fill = f->fill;
    mgl_u16 *d;
    /* z y dz, a locales: son el quinto y sexto argumento, llegan por la pila, y mini-lcc los leía de memoria en
       cada píxel. Los spans de un modelo pequeño son de pocos píxeles: lo que cuesta es lo de fuera del bucle. */
    mgl_s32 n = x1 - x0, zz = z, step = dz;
    unsigned int v, mode;
    if (n <= 0) return;
    mode = f->depth ? f->flags & (MGL_STATE_DEPTH_TEST | MGL_STATE_DEPTH_WRITE) : 0U;
    if (!mode) {
        for (; n > 0; n--) *c++ = fill;
        return;
    }
    d = f->depth + y * f->depth_stride + x0;
    /* El modo es constante en todo el span: decidir fuera del bucle evita
       comprobar test/write en cada píxel, también en mini-lcc. */
    if (mode == (MGL_STATE_DEPTH_TEST | MGL_STATE_DEPTH_WRITE)) {
        /* z es lineal en el span: si los dos extremos están dentro de (0, MAX), todos lo están y no hace falta
           acotar cada píxel (los mismos valores). Y el final como puntero, sin contador: 9 instrucciones por
           píxel en MiniGPU en vez de 12. Es el caso de casi todos los spans. */
        mgl_s32 last = zz + step * (n - 1);
        if (zz > 0 && zz < MGR_DEPTH_MAX && last > 0 && last < MGR_DEPTH_MAX) {
            mgl_color_t *end = c + n;
            for (; c != end; c++, d++, zz += step) {
                v = (unsigned int)zz >> MGR_DEPTH_FRAC;
                if (v >= *d) continue;
                *d = (mgl_u16)v;
                *c = fill;
            }
            return;
        }
        for (; n > 0; n--, c++, d++, zz += step) {
            v = zz <= 0 ? 0U : zz >= MGR_DEPTH_MAX ? 65535U : (unsigned int)zz >> MGR_DEPTH_FRAC;
            if (v >= *d) continue;
            *d = (mgl_u16)v;
            *c = fill;
        }
        return;
    }
    if (mode == MGL_STATE_DEPTH_TEST) {
        for (; n > 0; n--, c++, d++, zz += step) {
            v = zz <= 0 ? 0U : zz >= MGR_DEPTH_MAX ? 65535U : (unsigned int)zz >> MGR_DEPTH_FRAC;
            if (v < *d) *c = fill;
        }
        return;
    }
    for (; n > 0; n--, c++, d++, zz += step) {
        v = zz <= 0 ? 0U : zz >= MGR_DEPTH_MAX ? 65535U : (unsigned int)zz >> MGR_DEPTH_FRAC;
        *d = (mgl_u16)v;
        *c = fill;
    }
}

/* Color y profundidad son buffers de 16 bits. En MiniGPU, como en raster.c,
   lcc permite escribir pares con palabras de 32 bits (sin strict aliasing).
   Cada fila se alinea por separado: el destino y el stride pueden ser impares
   en unidades de 16 bits. Nunca se escribe el padding ni fuera del ancho.
   En el host se conserva el acceso de 16 bits, que el compilador vectoriza. */
static void clear_buffer(mgl_u16 *row, int width, int height, int stride, mgl_u16 value) {
    int y, n;
    mgl_u16 *p;
#ifdef __MINIGPU__
    mgl_u32 pair = value | (mgl_u32)value << 16, *w;
#endif
    for (y = 0; y < height; y++, row += stride) {
        p = row;
        n = width;
#ifdef __MINIGPU__
        if (n > 0 && ((mgl_u32)p & 2U)) {
            *p++ = value;
            n--;
        }
        w = (mgl_u32 *)p;
        for (; n >= 8; n -= 8, w += 4) {
            w[0] = pair;
            w[1] = pair;
            w[2] = pair;
            w[3] = pair;
        }
        for (; n >= 2; n -= 2) *w++ = pair;
        p = (mgl_u16 *)w;
#endif
        for (; n > 0; n--) *p++ = value;
    }
}

void mgr_clear_color(const mgr_state_t *s, mgl_color_t c) {
    clear_buffer(s->color, s->width, s->height, s->color_stride, c);
}

void mgr_clear_depth(const mgr_state_t *s, mgl_u16 d) {
    if (!s->depth) return;
    clear_buffer(s->depth, s->width, s->height, s->depth_stride, d);
}
