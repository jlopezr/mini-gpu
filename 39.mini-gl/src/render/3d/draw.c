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
   dura un DRAW_INDEXED: cada entrada lleva el dibujo en que se llenó, así que
   no hay que vaciarla al empezar otro (ver cache_generation). */
#define MGR_VCACHE 64

/* Con MGR_FIXED_GEOMETRY los vértices transformados, el outcode, el recorte y el viewport son Q16.16 (fixed.c). */
#if MGR_FIXED_GEOMETRY
typedef mgr_vec4q_t mgr_clipv_t;
typedef mgr_mat4q_t mgr_mvp_t;
#define TRANSFORM_AT mgr_transform_at_q
#define OUTCODE mgr_outcode_q
#define CLIP_TRIANGLE mgr_clip_triangle_q
#define VIEWPORT_MAP mgr_viewport_map_q
#define W_POSITIVE(v) ((v)->w > 0)
#else
typedef mgl_vec4_t mgr_clipv_t;
typedef mgl_mat4_t mgr_mvp_t;
#define TRANSFORM_AT mgr_transform_at
#define OUTCODE mgr_outcode
#define CLIP_TRIANGLE mgr_clip_triangle
#define VIEWPORT_MAP mgr_viewport_map
#define W_POSITIVE(v) ((v)->w > 0.0f)
#endif

typedef struct {
    mgl_u32 tag; /* (generación << 16) | índice; MGR_VCACHE_EMPTY: libre */
    mgr_clipv_t clip;
    unsigned int out;
    int mapped; /* window ya calculado */
    mgl_color_t color; /* con MGL_VERTEX_POSITION_F32_XYZ_RGB565 */
    mgr_window_vertex_t window;
} mgr_vcache_t;

#define MGR_VCACHE_EMPTY 0xffffffffU

/* La caché queda entre un DRAW_INDEXED y el siguiente, y la generación cambia en cada uno: vaciarla eran 64
   escrituras por dibujo (unas 60000 instrucciones por frame en racer). Generaciones de 1 a 0xfffe, para que
   ninguna etiqueta valga MGR_VCACHE_EMPTY; al dar la vuelta se vacía de verdad. Los índices caben en 16 bits
   (vcount <= 65536). */
static mgr_vcache_t cache[MGR_VCACHE];
static mgl_u32 cache_generation;

static void triangle(mgr_stats_t *st, const mgr_window_vertex_t *a, const mgr_window_vertex_t *b,
    const mgr_window_vertex_t *c, const mgr_rect_t *clip, const mgr_fragment_t *f) {
    /* Lo que mgr_raster_triangle descartaría al empezar (área nula o cara descartada), sin llamarla: con
       culling es la mitad de los triángulos, y ella guarda y restaura catorce registros. Los aceptados van a
       mgr_raster_triangle_area con el área ya calculada, sin repetir las comprobaciones. */
    mgl_s32 covered = (b->x - a->x) * (c->y - a->y) - (b->y - a->y) * (c->x - a->x);
    if (covered == 0 || ((f->flags & MGL_STATE_CULL_BACK) && covered > 0) ||
        ((f->flags & MGL_STATE_CULL_FRONT) && covered < 0)) {
        st->culled++;
        return;
    }
    covered = mgr_raster_triangle_area(a, b, c, clip, f, covered);
    st->rasterized++;
    st->fragments += (mgl_u32)covered;
}

static void fan(mgr_state_t *s, mgr_stats_t *st, const mgr_clipv_t *v, int n, const mgr_rect_t *clip,
    const mgr_fragment_t *f) {
    mgr_window_vertex_t w[MGR_CLIP_MAX];
    int i;
    for (i = 0; i < n; i++) {
        if (!W_POSITIVE(&v[i])) return; /* solo con matrices degeneradas: dentro del volumen w >= 0 */
        VIEWPORT_MAP(s, &v[i], &w[i]);
    }
    for (i = 1; i + 1 < n; i++)
        triangle(st, &w[0], &w[i], &w[i + 1], clip, f);
}

int mgr_draw_indexed(mgr_state_t *s, mgr_stats_t *st, const mgl_memory_t *m, const unsigned char *p) {
    mgr_vertices_t verts;
    mgr_fragment_t f;
    mgr_rect_t clip;
    const mgr_mvp_t *mvp;
    const unsigned char *indices, *vp;
    mgr_vcache_t *c, *e[3], local[3];
    mgr_clipv_t tri[3];
    mgr_clipv_t poly[MGR_CLIP_MAX];
    mgl_u32 vaddr = RD32(p + MGL_CMD_ARG0), iaddr = RD32(p + MGL_CMD_ARG1);
    mgl_u32 vcount = RD32(p + 16), icount = RD32(p + 20), stride = RD16(p + 28), i, k, index, generation, tag;
    unsigned int vformat = RD16(p + 24), iformat = RD16(p + 26), topology = RD16(p + 30);
    int n, colored = vformat == MGL_VERTEX_POSITION_F32_XYZ_RGB565;

    if (vformat == MGL_VERTEX_POSITION_Q16_16_XYZ || iformat == MGL_INDEX_UINT32)
        return MGR_ERR_UNSUPPORTED;
    if ((vformat != MGL_VERTEX_POSITION_F32_XYZ && !colored) || iformat != MGL_INDEX_UINT16 ||
        topology != MGL_TOPOLOGY_TRIANGLES)
        return MGR_ERR_FORMAT;
    if (stride < (colored ? 16U : 12U) || (stride & 3U) || !vcount || vcount > 65536U || icount % 3U ||
        icount > 0x7fffffffU / 2U)
        return MGR_ERR_LIMIT;
    if (!s->color) return MGR_ERR_STATE;
    verts.base = (const unsigned char *)mgl_memory_ptr(m, vaddr, (vcount - 1U) * stride + (colored ? 16U : 12U), 4);
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
#if MGR_FIXED_GEOMETRY
    mvp = mgr_state_mvp_q(s);
#else
    mvp = mgr_state_mvp(s);
#endif
    if (++cache_generation > 0xfffeU) {
        for (k = 0; k < MGR_VCACHE; k++)
            cache[k].tag = MGR_VCACHE_EMPTY;
        cache_generation = 1;
    }
    generation = cache_generation << 16;

    for (i = 0; i < icount; i += 3) {
        /* e[k]: la entrada del vértice k, sin copiarla. Si otro vértice de este triángulo ya está en la misma
           entrada (índices iguales módulo MGR_VCACHE, raro), este va a una local. */
        for (k = 0; k < 3; k++) {
            index = RD16(indices + 2U * (i + k));
            if (index >= vcount) return MGR_ERR_LIMIT;
            tag = generation | index;
            c = &cache[index & (MGR_VCACHE - 1U)];
            if (c->tag != tag) {
                if ((k > 0 && e[0] == c) || (k > 1 && e[1] == c)) c = &local[k];
                c->tag = tag;
                vp = verts.base + index * stride;
                TRANSFORM_AT(vp, mvp, &c->clip);
                c->out = OUTCODE(&c->clip);
                c->mapped = 0;
                if (colored) c->color = RD16(vp + 12);
            }
            e[k] = c;
        }
        st->triangles++;
        if (e[0]->out & e[1]->out & e[2]->out) { /* los tres fuera del mismo plano */
            st->rejected++;
            continue;
        }
        if (colored) f.fill = e[0]->color; /* el del primer vértice; también para lo que salga del recorte */
        if (!(e[0]->out | e[1]->out | e[2]->out)) { /* dentro de todos: sin recortar */
            for (k = 0; k < 3; k++) {
                c = e[k];
                if (!W_POSITIVE(&c->clip)) break; /* como en fan */
                if (!c->mapped) {
                    VIEWPORT_MAP(s, &c->clip, &c->window);
                    c->mapped = 1;
                }
            }
            if (k == 3) triangle(st, &e[0]->window, &e[1]->window, &e[2]->window, &clip, &f);
            continue;
        }
        st->clipped++;
        for (k = 0; k < 3; k++)
            tri[k] = e[k]->clip;
        n = CLIP_TRIANGLE(tri, poly);
        if (n) fan(s, st, poly, n, &clip, &f);
    }
    return MGR_OK;
}
