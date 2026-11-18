#include "mgr_stages.h"
#include "mgl_bytes.h"

/* Las coordenadas homogéneas se conservan: la división por w la hace viewport.c
   después de recortar. */
void mgr_transform_vertex(const mgr_vertices_t *v, mgl_u32 index, const mgl_mat4_t *mvp,
    mgl_vec4_t *clip) {
    mgr_transform_at(v->base + index * v->stride, mvp, clip);
}

void mgr_transform_at(const unsigned char *p, const mgl_mat4_t *mvp, mgl_vec4_t *clip) {
    mgl_mat4_transform_point(mvp, mgl_real_from_f32(RD32(p)), mgl_real_from_f32(RD32(p + 4)),
        mgl_real_from_f32(RD32(p + 8)), clip);
}
