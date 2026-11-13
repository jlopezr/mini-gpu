#include "mgr_stages.h"
#include "mgl_bytes.h"

/* Lo que mgr_viewport_map necesita del viewport, calculado una vez cuando
   cambia y no en cada vértice (con las mismas operaciones: el mismo resultado). */
static void viewport_changed(mgr_state_t *s) {
    s->view_x = (mgl_s32)(s->vx * MGR_SUBPIXEL);
    s->view_y = (mgl_s32)(s->vy * MGR_SUBPIXEL);
    s->view_sx = (mgl_real_t)(s->vw * MGR_SUBPIXEL) * 0.5f;
    s->view_sy = (mgl_real_t)(s->vh * MGR_SUBPIXEL) * 0.5f;
    s->view_sxi = (mgl_s32)(s->vw * MGR_SUBPIXEL / 2);
    s->view_syi = (mgl_s32)(s->vh * MGR_SUBPIXEL / 2);
}

/* Estado inicial, al empezar cada ejecución y tras cada END_FRAME: sin destino,
   matrices identidad, MGL_STATE_DEFAULT (solo escritura de profundidad, como
   OpenGL) y color blanco. */
void mgr_state_reset(mgr_state_t *s) {
    s->color = 0;
    s->depth = 0;
    s->width = s->height = s->color_stride = s->depth_stride = 0;
    s->vx = s->vy = s->vw = s->vh = 0;
    viewport_changed(s);
    mgl_mat4_identity(&s->matrix[0]);
    mgl_mat4_identity(&s->matrix[1]);
    mgl_mat4_identity(&s->matrix[2]);
    mgl_mat4_identity(&s->mvp);
    mgl_mat4_identity(&s->pv);
    s->mvp_dirty = 0;
    s->pv_dirty = 0;
    s->mvp_q_dirty = 1;
    s->flags = MGL_STATE_DEFAULT;
    s->fill = 0xffff;
}

int mgr_state_target(mgr_state_t *s, const mgl_memory_t *m, const unsigned char *p) {
    mgl_u32 color = RD32(p + MGL_CMD_ARG0), depth = RD32(p + MGL_CMD_ARG1);
    int w = (int)RD16(p + 16), h = (int)RD16(p + 18), cs = (int)RD16(p + 20), ds = (int)RD16(p + 22);
    unsigned int cf = RD16(p + 24), df = RD16(p + 26);
    if (RD32(p + 28)) return MGR_ERR_FORMAT;
    if (cf != MGL_COLOR_RGB565 || (df != MGL_DEPTH_NONE && df != MGL_DEPTH_U16))
        return MGR_ERR_UNSUPPORTED;
    if ((df == MGL_DEPTH_NONE) != (depth == 0)) return MGR_ERR_FORMAT;
    if (w <= 0 || h <= 0 || w > MGL_MAX_TARGET_DIM || h > MGL_MAX_TARGET_DIM || cs < w ||
        cs > MGL_MAX_TARGET_DIM || (depth && (ds < w || ds > MGL_MAX_TARGET_DIM)))
        return MGR_ERR_LIMIT;
    s->color = (mgl_color_t *)mgl_memory_ptr(m, color, (mgl_u32)(cs * (h - 1) + w) * 2U, 2);
    s->depth = depth ? (mgl_u16 *)mgl_memory_ptr(m, depth, (mgl_u32)(ds * (h - 1) + w) * 2U, 2) : 0;
    if (!s->color || (depth && !s->depth)) {
        s->color = 0;
        s->depth = 0;
        return MGR_ERR_MEMORY;
    }
    s->width = w;
    s->height = h;
    s->color_stride = cs;
    s->depth_stride = depth ? ds : 0;
    s->vx = s->vy = 0;
    s->vw = w;
    s->vh = h;
    viewport_changed(s);
    return MGR_OK;
}

int mgr_state_viewport(mgr_state_t *s, const unsigned char *p) {
    mgl_u32 a0 = RD32(p + MGL_CMD_ARG0), a1 = RD32(p + MGL_CMD_ARG1);
    int x = LOW(a0), y = HIGH(a0), w = LOW(a1), h = HIGH(a1);
    if (x < -MGL_MAX_VIEWPORT_POS || x > MGL_MAX_VIEWPORT_POS || y < -MGL_MAX_VIEWPORT_POS ||
        y > MGL_MAX_VIEWPORT_POS || w <= 0 || h <= 0 || w > MGL_MAX_TARGET_DIM ||
        h > MGL_MAX_TARGET_DIM)
        return MGR_ERR_LIMIT;
    s->vx = x;
    s->vy = y;
    s->vw = w;
    s->vh = h;
    viewport_changed(s);
    return MGR_OK;
}

int mgr_state_matrix(mgr_state_t *s, const unsigned char *p) {
    mgl_u32 which = RD32(p + MGL_CMD_ARG0), format = RD32(p + MGL_CMD_ARG1);
    mgl_mat4_t *m;
    int i;
    if (which < MGL_MATRIX_MODEL || which > MGL_MATRIX_PROJECTION) return MGR_ERR_FORMAT;
    if (format == MGL_FORMAT_Q16_16) return MGR_ERR_UNSUPPORTED;
    if (format != MGL_FORMAT_FLOAT32) return MGR_ERR_FORMAT;
    m = &s->matrix[which - 1U];
    for (i = 0; i < 16; i++) m->m[i] = mgl_real_from_f32(RD32(p + 16 + 4 * i));
    s->mvp_dirty = 1;
    if (which != MGL_MATRIX_MODEL) s->pv_dirty = 1;
    return MGR_OK;
}

int mgr_state_flags(mgr_state_t *s, const unsigned char *p) {
    mgl_u32 f = RD32(p + MGL_CMD_ARG0);
    if (RD32(p + MGL_CMD_ARG1)) return MGR_ERR_FORMAT;
    if (f & MGL_STATE_BLEND) return MGR_ERR_UNSUPPORTED;
    if (f & ~(MGL_STATE_DEPTH_TEST | MGL_STATE_DEPTH_WRITE | MGL_STATE_CULL_BACK | MGL_STATE_CULL_FRONT))
        return MGR_ERR_FORMAT;
    s->flags = f;
    return MGR_OK;
}

int mgr_state_color(mgr_state_t *s, const unsigned char *p) {
    mgl_u32 c = RD32(p + MGL_CMD_ARG0);
    if (c > 0xffffU || RD32(p + MGL_CMD_ARG1)) return MGR_ERR_FORMAT;
    s->fill = (mgl_color_t)c;
    return MGR_OK;
}

const mgl_mat4_t *mgr_state_mvp(mgr_state_t *s) {
    if (s->mvp_dirty) {
        /* (P * V) * M, en ese orden: los mismos bits que sin guardar P * V */
        if (s->pv_dirty) {
            mgl_mat4_mul(&s->pv, &s->matrix[MGL_MATRIX_PROJECTION - 1U], &s->matrix[MGL_MATRIX_VIEW - 1U]);
            s->pv_dirty = 0;
        }
        mgl_mat4_mul(&s->mvp, &s->pv, &s->matrix[MGL_MATRIX_MODEL - 1U]);
        s->mvp_dirty = 0;
        s->mvp_q_dirty = 1;
    }
    return &s->mvp;
}
