#include "mgr_stages.h"

/* Coordenadas normalizadas (x, y, z en [-1, 1], y hacia arriba) a píxeles del
   destino (y hacia abajo) en 1/16 de píxel, y z a [0, 1]:
     x = vx + (xn + 1) / 2 * vw     y = vy + (1 - yn) / 2 * vh     z = (zn + 1) / 2
   El borde izquierdo del píxel 0 es x = 0, así que su centro es 0.5 (8/16). */
void mgr_viewport_map(const mgr_state_t *s, const mgl_vec4_t *v, mgr_window_vertex_t *out) {
    mgl_real_t inv_w = 1.0f / v->w, xn = v->x * inv_w, yn = v->y * inv_w, zn = v->z * inv_w;
    mgl_real_t sx = (mgl_real_t)(s->vw * MGR_SUBPIXEL) * 0.5f, sy = (mgl_real_t)(s->vh * MGR_SUBPIXEL) * 0.5f;
    out->x = (mgl_s32)(s->vx * MGR_SUBPIXEL) + mgl_round((xn + 1.0f) * sx);
    out->y = (mgl_s32)(s->vy * MGR_SUBPIXEL) + mgl_round((1.0f - yn) * sy);
    out->z = zn * 0.5f + 0.5f;
}
