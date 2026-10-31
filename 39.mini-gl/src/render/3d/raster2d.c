#include "mgr_stages.h"
#include "mgl_bytes.h"
#include "raster.h"

/* Los comandos 2D con el raster de V0 (src/render/2d/raster.c): los mismos píxeles que
   V0, V1 y V2. Solo escribe color; no mira ni cambia la profundidad. */

void mgr_raster2d_target(const mgr_state_t *s) {
    sw_bind(s->color, s->width, s->height, s->color_stride);
}

int mgr_raster2d_batch(const mgr_state_t *s, const unsigned char *p) {
    mgl_u32 t = RD32(p + 16), p0 = RD32(p + 20), p1 = RD32(p + 24), p2 = RD32(p + 28);
    unsigned int flags = RD16(p + 36);
    if (RD32(p + MGL_CMD_ARG0) != 1U || RD32(p + MGL_CMD_ARG1)) return MGR_ERR_FORMAT;
    /* IMAGE lleva un handle del contexto de V1, no una dirección. */
    if (t == MGL_PRIM_IMAGE) return MGR_ERR_UNSUPPORTED;
    if (t < MGL_PRIM_POINT || t > MGL_PRIM_TRIANGLE) return MGR_ERR_FORMAT;
    if (!s->color) return MGR_ERR_STATE;
    if (flags & MGL_BATCH_FILL)
        sw_fill((mgl_color_t)RD16(p + 32));
    else
        sw_no_fill();
    if (flags & MGL_BATCH_STROKE)
        sw_stroke((mgl_color_t)RD16(p + 34));
    else
        sw_no_stroke();
    sw_stroke_weight((int)RD16(p + 38));
    if (t == MGL_PRIM_POINT)
        sw_point(LOW(p0), HIGH(p0));
    else if (t == MGL_PRIM_LINE)
        sw_line(LOW(p0), HIGH(p0), LOW(p1), HIGH(p1));
    else if (t == MGL_PRIM_RECT)
        sw_rect(LOW(p0), HIGH(p0), LOW(p1), HIGH(p1));
    else if (t == MGL_PRIM_CIRCLE)
        sw_circle(LOW(p0), HIGH(p0), LOW(p1));
    else
        sw_triangle(LOW(p0), HIGH(p0), LOW(p1), HIGH(p1), LOW(p2), HIGH(p2));
    return MGR_OK;
}
