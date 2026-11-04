#include "mgr_stages.h"

/* Coordenadas normalizadas (x, y, z en [-1, 1], y hacia arriba) a píxeles del
   destino (y hacia abajo) en 1/16 de píxel, y z a [0, 1]:
     x = vx + (xn + 1) / 2 * vw     y = vy + (1 - yn) / 2 * vh     z = (zn + 1) / 2
   El borde izquierdo del píxel 0 es x = 0, así que su centro es 0.5 (8/16). */
void mgr_viewport_map(const mgr_state_t *s, const mgl_vec4_t *v, mgr_window_vertex_t *out) {
    mgl_real_t inv_w = 1.0f / v->w, xn = v->x * inv_w, yn = v->y * inv_w, zn = v->z * inv_w;
    out->x = s->view_x + mgl_round((xn + 1.0f) * s->view_sx); /* view_*: del viewport, state.c */
    out->y = s->view_y + mgl_round((1.0f - yn) * s->view_sy);
    out->z = zn * 0.5f + 0.5f;
#if MGR_FIXED_DEPTH
    out->zq = mgl_round(out->z * 65536.0f);
#endif
}
