#include "mgr_stages.h"
#include "mgl_bytes.h"

/* DRAW_INDEXED: cada triángulo de principio a fin, sin guardar los anteriores:
     leer índices -> transformar -> recortar -> viewport -> rasterizar
   Recortar puede dar un polígono de hasta MGR_CLIP_MAX vértices, que se dibuja
   como abanico de triángulos. Todo en la pila: nada de memoria dinámica. */

static void fan(mgr_state_t *s, mgr_stats_t *st, const mgl_vec4_t *v, int n, const mgr_rect_t *clip,
    const mgr_fragment_t *f) {
    mgr_window_vertex_t w[MGR_CLIP_MAX];
    mgl_s32 covered;
    int i;
    for (i = 0; i < n; i++) {
        if (!(v[i].w > 0.0f)) return; /* solo con matrices degeneradas: dentro del volumen w >= 0 */
        mgr_viewport_map(s, &v[i], &w[i]);
    }
    for (i = 1; i + 1 < n; i++) {
        covered = mgr_raster_triangle(&w[0], &w[i], &w[i + 1], clip, f);
        if (covered < 0) {
            st->culled++;
            continue;
        }
        st->rasterized++;
        st->fragments += (mgl_u32)covered;
    }
}

int mgr_draw_indexed(mgr_state_t *s, mgr_stats_t *st, const mgl_memory_t *m, const unsigned char *p) {
    mgr_vertices_t verts;
    mgr_fragment_t f;
    mgr_rect_t clip;
    const mgl_mat4_t *mvp;
    const unsigned char *indices;
    mgl_vec4_t tri[3], poly[MGR_CLIP_MAX];
    mgl_u32 vaddr = RD32(p + MGL_CMD_ARG0), iaddr = RD32(p + MGL_CMD_ARG1);
    mgl_u32 vcount = RD32(p + 16), icount = RD32(p + 20), stride = RD16(p + 28), i, k, index;
    unsigned int vformat = RD16(p + 24), iformat = RD16(p + 26), topology = RD16(p + 30);
    unsigned int out0, out1, out2;
    int n;

    if (vformat == MGL_VERTEX_POSITION_Q16_16_XYZ || iformat == MGL_INDEX_UINT32)
        return MGR_ERR_UNSUPPORTED;
    if (vformat != MGL_VERTEX_POSITION_F32_XYZ || iformat != MGL_INDEX_UINT16 ||
        topology != MGL_TOPOLOGY_TRIANGLES)
        return MGR_ERR_FORMAT;
    if (stride < 12U || (stride & 3U) || !vcount || vcount > 65536U || icount % 3U ||
        icount > 0x7fffffffU / 2U)
        return MGR_ERR_LIMIT;
    if (!s->color) return MGR_ERR_STATE;
    verts.base = (const unsigned char *)mgl_memory_ptr(m, vaddr, (vcount - 1U) * stride + 12U, 4);
    verts.stride = stride;
    verts.count = vcount;
    indices = (const unsigned char *)mgl_memory_ptr(m, iaddr, icount * 2U, 2);
    if (!verts.base || (icount && !indices)) return MGR_ERR_MEMORY;

    f.color = s->color;
    f.depth = s->depth;
    f.color_stride = s->color_stride;
    f.depth_stride = s->depth_stride;
    f.flags = s->flags;
    f.fill = s->fill;
    /* Donde se puede escribir: el viewport dentro del destino. */
    clip.x0 = s->vx > 0 ? s->vx : 0;
    clip.y0 = s->vy > 0 ? s->vy : 0;
    clip.x1 = s->vx + s->vw < s->width ? s->vx + s->vw : s->width;
    clip.y1 = s->vy + s->vh < s->height ? s->vy + s->vh : s->height;
    mvp = mgr_state_mvp(s);

    for (i = 0; i < icount; i += 3) {
        for (k = 0; k < 3; k++) {
            index = RD16(indices + 2U * (i + k));
            if (index >= vcount) return MGR_ERR_LIMIT;
            mgr_transform_vertex(&verts, index, mvp, &tri[k]);
        }
        st->triangles++;
        out0 = mgr_outcode(&tri[0]);
        out1 = mgr_outcode(&tri[1]);
        out2 = mgr_outcode(&tri[2]);
        if (out0 & out1 & out2) { /* los tres fuera del mismo plano */
            st->rejected++;
            continue;
        }
        if (!(out0 | out1 | out2)) { /* dentro de todos: sin recortar */
            fan(s, st, tri, 3, &clip, &f);
            continue;
        }
        st->clipped++;
        n = mgr_clip_triangle(tri, poly);
        if (n) fan(s, st, poly, n, &clip, &f);
    }
    return MGR_OK;
}
