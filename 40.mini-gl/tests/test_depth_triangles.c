/* Diferencial del raster incremental: cobertura, error U16 y fallback
   en triángulos estrechos. No depende de los sketches de Processing. */
#include "mgr_stages.h"
#include <stdio.h>
#include <string.h>

mgl_s32 mgr_raster_triangle_reference(const mgr_window_vertex_t *a,
    const mgr_window_vertex_t *b, const mgr_window_vertex_t *c,
    const mgr_rect_t *clip, const mgr_fragment_t *f);

static mgl_u16 ref_color[1024 * 1024], inc_color[1024 * 1024];
static mgl_u16 ref_depth[1024 * 1024], inc_depth[1024 * 1024];
static mgl_u32 seed = 42;
static mgl_u32 random_value(void) {
    seed = seed * 1664525U + 1013904223U;
    return seed;
}

int main(void) {
    mgr_window_vertex_t v[3];
    mgr_rect_t clip;
    mgr_fragment_t f;
    mgl_s32 a, b;
    unsigned long changed = 0;
    int t, j, i, count, delta, max_delta = 0, fallback_pixels = 0;
    f.flags = MGL_STATE_DEPTH_WRITE;
    f.fill = 7;
    for (t = 0; t < 1002; t++) {
        clip.x0 = clip.y0 = 0;
        clip.x1 = t < 1000 ? 128 : 1024;
        clip.y1 = t < 1000 ? 96 : 1024;
        f.color_stride = f.depth_stride = clip.x1;
        count = clip.x1 * clip.y1;
        for (j = 0; j < 3; j++) {
            v[j].x = (mgl_s32)(random_value() % (mgl_u32)(clip.x1 * 16 + 1));
            v[j].y = (mgl_s32)(random_value() % (mgl_u32)(clip.y1 * 16 + 1));
            v[j].z = (float)(random_value() & 65535U) / 65535.0f;
        }
        if (t >= 1000) {
            /* Caja completa y área estrecha: pendientes grandes que se
               cancelan en el interior, pero desbordarían en las esquinas. */
            v[0].x = v[0].y = v[1].y = 0;
            v[1].x = 16;
            v[2].x = v[2].y = 16384;
            v[0].z = t == 1000 ? 0.0f : 1.0f;
            v[1].z = t == 1000 ? 1.0f : 0.0f;
            v[2].z = 0.5f;
        }
        memset(ref_color, 0, (size_t)count * 2);
        memset(inc_color, 0, (size_t)count * 2);
        memset(ref_depth, 255, (size_t)count * 2);
        memset(inc_depth, 255, (size_t)count * 2);
        f.color = ref_color;
        f.depth = ref_depth;
        a = mgr_raster_triangle_reference(&v[0], &v[1], &v[2], &clip, &f);
        f.color = inc_color;
        f.depth = inc_depth;
        b = mgr_raster_triangle(&v[0], &v[1], &v[2], &clip, &f);
        if (a != b) return 1;
        if (t >= 1000) fallback_pixels += (int)a;
        for (i = 0; i < count; i++) {
            if (ref_color[i] != inc_color[i]) return 1;
            delta = (int)ref_depth[i] - (int)inc_depth[i];
            if (delta < 0) delta = -delta;
            if (t >= 1000 && delta) return 1;
            changed += delta != 0;
            if (delta > max_delta) max_delta = delta;
        }
    }
    printf("1000 triangles + 2 skinny: depth_changed=%lu max_depth_delta=%d fallback_pixels=%d\n",
        changed, max_delta, fallback_pixels);
    return max_delta > 1 || !fallback_pixels;
}
