#include "mgr_stages.h"
#include "mgl_bytes.h"

/* DRAW_INDEXED: cada triángulo de principio a fin:
     leer índices -> transformar -> recortar -> viewport -> rasterizar
   Recortar puede dar un polígono de hasta MGR_CLIP_MAX vértices, que se dibuja
   como abanico de triángulos. Todo en la pila: nada de memoria dinámica.

   Caché de vértices transformados, como la de las GPU: en una malla cada
   vértice lo comparten unos 4-6 triángulos, y transformarlo, su outcode y su
   viewport son lo más caro del triángulo en float por software. Se guardan en
   MGR_VCACHE entradas de correspondencia directa (índice & (MGR_VCACHE - 1));
   el viewport, solo cuando hace falta (un triángulo sin recortar). Mismos
   cálculos con los mismos datos: los mismos bits que sin caché. Vale lo que
   dura un DRAW_INDEXED. */
#define MGR_VCACHE 64

typedef struct {
    mgl_u32 index; /* MGR_VCACHE_EMPTY: libre */
    mgl_vec4_t clip;
    unsigned int out;
    int mapped; /* window ya calculado */
    mgr_window_vertex_t window;
} mgr_vcache_t;

#define MGR_VCACHE_EMPTY 0xffffffffU

static void triangle(mgr_stats_t *st, const mgr_window_vertex_t *a, const mgr_window_vertex_t *b,
    const mgr_window_vertex_t *c, const mgr_rect_t *clip, const mgr_fragment_t *f) {
    /* Lo que mgr_raster_triangle descartaría al empezar (área nula o cara descartada), sin llamarla: con
       culling es la mitad de los triángulos, y ella guarda y restaura catorce registros. */
    mgl_s32 covered = (b->x - a->x) * (c->y - a->y) - (b->y - a->y) * (c->x - a->x);
    if (covered == 0 || ((f->flags & MGL_STATE_CULL_BACK) && covered > 0) ||
        ((f->flags & MGL_STATE_CULL_FRONT) && covered < 0)) {
        st->culled++;
        return;
    }
    covered = mgr_raster_triangle(a, b, c, clip, f);
    if (covered < 0) {
        st->culled++;
        return;
    }
    st->rasterized++;
    st->fragments += (mgl_u32)covered;
}

static void fan(mgr_state_t *s, mgr_stats_t *st, const mgl_vec4_t *v, int n, const mgr_rect_t *clip,
    const mgr_fragment_t *f) {
    mgr_window_vertex_t w[MGR_CLIP_MAX];
    int i;
    for (i = 0; i < n; i++) {
        if (!(v[i].w > 0.0f)) return; /* solo con matrices degeneradas: dentro del volumen w >= 0 */
        mgr_viewport_map(s, &v[i], &w[i]);
    }
    for (i = 1; i + 1 < n; i++)
        triangle(st, &w[0], &w[i], &w[i + 1], clip, f);
}

int mgr_draw_indexed(mgr_state_t *s, mgr_stats_t *st, const mgl_memory_t *m, const unsigned char *p) {
    mgr_vertices_t verts;
    mgr_fragment_t f;
    mgr_rect_t clip;
    const mgl_mat4_t *mvp;
    const unsigned char *indices;
    mgr_vcache_t cache[MGR_VCACHE], *c;
    mgr_window_vertex_t w[3];
    mgl_vec4_t tri[3], poly[MGR_CLIP_MAX];
    mgl_u32 vaddr = RD32(p + MGL_CMD_ARG0), iaddr = RD32(p + MGL_CMD_ARG1);
    mgl_u32 vcount = RD32(p + 16), icount = RD32(p + 20), stride = RD16(p + 28), i, k, index;
    unsigned int vformat = RD16(p + 24), iformat = RD16(p + 26), topology = RD16(p + 30);
    unsigned int out[3];
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
    for (k = 0; k < MGR_VCACHE; k++)
        cache[k].index = MGR_VCACHE_EMPTY;

    for (i = 0; i < icount; i += 3) {
        for (k = 0; k < 3; k++) {
            index = RD16(indices + 2U * (i + k));
            if (index >= vcount) return MGR_ERR_LIMIT;
            c = &cache[index & (MGR_VCACHE - 1U)];
            if (c->index != index) {
                c->index = index;
                mgr_transform_vertex(&verts, index, mvp, &c->clip);
                c->out = mgr_outcode(&c->clip);
                c->mapped = 0;
            }
            tri[k] = c->clip; /* copias: otro vértice del triángulo puede caer en la misma entrada */
            out[k] = c->out;
        }
        st->triangles++;
        if (out[0] & out[1] & out[2]) { /* los tres fuera del mismo plano */
            st->rejected++;
            continue;
        }
        if (!(out[0] | out[1] | out[2])) { /* dentro de todos: sin recortar */
            for (k = 0; k < 3; k++) {
                if (!(tri[k].w > 0.0f)) break; /* como en fan */
                index = RD16(indices + 2U * (i + k));
                c = &cache[index & (MGR_VCACHE - 1U)];
                if (c->index != index) { /* lo echó otro vértice de este triángulo */
                    mgr_viewport_map(s, &tri[k], &w[k]);
                    continue;
                }
                if (!c->mapped) {
                    mgr_viewport_map(s, &c->clip, &c->window);
                    c->mapped = 1;
                }
                w[k] = c->window;
            }
            if (k == 3) triangle(st, &w[0], &w[1], &w[2], &clip, &f);
            continue;
        }
        st->clipped++;
        n = mgr_clip_triangle(tri, poly);
        if (n) fan(s, st, poly, n, &clip, &f);
    }
    return MGR_OK;
}
