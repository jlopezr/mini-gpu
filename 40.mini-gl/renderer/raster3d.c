#include "mgr_stages.h"

/* Cobertura con funciones de borde en enteros, escalar y determinista.

   Coordenadas en 1/16 de píxel (viewport.c). Para la arista de A a B,
     E(P) = (B.x - A.x) * (P.y - A.y) - (B.y - A.y) * (P.x - A.x)
   Con los vértices ordenados para que el área sea positiva, un punto está
   dentro si las tres E son positivas. Se prueba el centro de cada píxel.

   Regla top-left (la de Direct3D, que también usa y hacia abajo): un centro
   justo sobre una arista solo cuenta si es una arista superior (horizontal, con
   el triángulo debajo) o izquierda. Así dos triángulos que comparten arista no
   pintan dos veces el mismo píxel ni dejan huecos.

   Desbordamiento: las diferencias de coordenadas están acotadas por el viewport
   (clipping.c deja los vértices dentro), como mucho 1024 píxeles = 16384
   unidades más el redondeo, y E < 2 * 16400^2 < 2^31.

   La profundidad es un plano z = z0 + a (x - x0) + b (y - y0). Los gradientes
   se calculan en float por triángulo, el valor al principio de cada span en
   float por fila y, dentro del span, en punto fijo por suma (fragment.c). */

#define DEPTH_SCALE 16776960.0f /* 65535 << MGR_DEPTH_FRAC */

static mgl_s32 floor16(mgl_s32 v) {
    return v >= 0 ? v / MGR_SUBPIXEL : -((-v + MGR_SUBPIXEL - 1) / MGR_SUBPIXEL);
}

typedef struct {
    mgl_s32 dx, dy; /* B - A */
    mgl_s32 w;      /* E en el centro del píxel actual, con el sesgo de la regla top-left */
} edge_t;

/* Prepara la arista de a a b para empezar en el centro (px, py) en 1/16. */
static void edge_setup(edge_t *e, const mgr_window_vertex_t *a, const mgr_window_vertex_t *b,
    mgl_s32 px, mgl_s32 py) {
    int top_left;
    e->dx = b->x - a->x;
    e->dy = b->y - a->y;
    top_left = (e->dy == 0 && e->dx > 0) || e->dy < 0;
    /* Dentro si E > 0, o E == 0 en una arista top-left: w = E - 1 (+1) >= 0. */
    e->w = e->dx * (py - a->y) - e->dy * (px - a->x) - (top_left ? 0 : 1);
}

mgl_s32 mgr_raster_triangle(const mgr_window_vertex_t *a, const mgr_window_vertex_t *b,
    const mgr_window_vertex_t *c, const mgr_rect_t *clip, const mgr_fragment_t *f) {
    const mgr_window_vertex_t *t;
    mgl_s32 area, minx, maxx, miny, maxy, x0, x1, y0, y1, x, y, start, px, py, step0, step1, step2;
    mgl_s32 w0, w1, w2, covered = 0, zi, dzi;
    mgl_real_t fa, ga, gb, dz1, dz2, zrow, zf;
    edge_t e0, e1, e2;

    /* Cara: de frente es antihorario con y hacia arriba, es decir, área negativa aquí (y hacia abajo). */
    area = (b->x - a->x) * (c->y - a->y) - (b->y - a->y) * (c->x - a->x);
    if (area == 0) return -1;
    if ((f->flags & MGL_STATE_CULL_BACK) && area > 0) return -1;
    if ((f->flags & MGL_STATE_CULL_FRONT) && area < 0) return -1;
    if (area < 0) {
        t = b;
        b = c;
        c = t;
        area = -area;
    }

    /* Píxeles cuyo centro (16 i + 8) cae en la caja del triángulo, dentro de clip. */
    minx = a->x < b->x ? a->x : b->x;
    minx = c->x < minx ? c->x : minx;
    maxx = a->x > b->x ? a->x : b->x;
    maxx = c->x > maxx ? c->x : maxx;
    miny = a->y < b->y ? a->y : b->y;
    miny = c->y < miny ? c->y : miny;
    maxy = a->y > b->y ? a->y : b->y;
    maxy = c->y > maxy ? c->y : maxy;
    x0 = floor16(minx + MGR_SUBPIXEL / 2 - 1);
    x1 = floor16(maxx - MGR_SUBPIXEL / 2) + 1;
    y0 = floor16(miny + MGR_SUBPIXEL / 2 - 1);
    y1 = floor16(maxy - MGR_SUBPIXEL / 2) + 1;
    if (x0 < clip->x0) x0 = clip->x0;
    if (y0 < clip->y0) y0 = clip->y0;
    if (x1 > clip->x1) x1 = clip->x1;
    if (y1 > clip->y1) y1 = clip->y1;
    if (x0 >= x1 || y0 >= y1) return 0;

    px = x0 * MGR_SUBPIXEL + MGR_SUBPIXEL / 2;
    py = y0 * MGR_SUBPIXEL + MGR_SUBPIXEL / 2;
    edge_setup(&e0, b, c, px, py);
    edge_setup(&e1, c, a, px, py);
    edge_setup(&e2, a, b, px, py);
    step0 = e0.dy * MGR_SUBPIXEL;
    step1 = e1.dy * MGR_SUBPIXEL;
    step2 = e2.dy * MGR_SUBPIXEL;

    /* Gradientes de z por unidad de 1/16 de píxel. */
    fa = (mgl_real_t)area;
    dz1 = b->z - a->z;
    dz2 = c->z - a->z;
    ga = (dz1 * (mgl_real_t)(c->y - a->y) - dz2 * (mgl_real_t)(b->y - a->y)) / fa;
    gb = (dz2 * (mgl_real_t)(b->x - a->x) - dz1 * (mgl_real_t)(c->x - a->x)) / fa;
    zf = ga * (mgl_real_t)(MGR_SUBPIXEL) * DEPTH_SCALE;
    /* Acotado: en un span z no sale de [0, 1] salvo por redondeo, y así z + dz no desborda. */
    if (zf > 33553920.0f) zf = 33553920.0f;
    if (-zf > 33553920.0f) zf = -33553920.0f; /* -zf: mini-lcc deja los literales negativos en double */
    dzi = mgl_round(zf);

    for (y = y0; y < y1; y++, py += MGR_SUBPIXEL) {
        w0 = e0.w;
        w1 = e1.w;
        w2 = e2.w;
        for (x = x0; x < x1 && (w0 | w1 | w2) < 0; x++) {
            w0 -= step0;
            w1 -= step1;
            w2 -= step2;
        }
        start = x;
        for (; x < x1 && (w0 | w1 | w2) >= 0; x++) {
            w0 -= step0;
            w1 -= step1;
            w2 -= step2;
        }
        if (x > start) {
            zrow = a->z + gb * (mgl_real_t)(py - a->y);
            zf = (zrow + ga * (mgl_real_t)(start * MGR_SUBPIXEL + MGR_SUBPIXEL / 2 - a->x)) * DEPTH_SCALE;
            zi = zf <= 0.0f ? 0 : zf >= DEPTH_SCALE ? MGR_DEPTH_MAX : mgl_round(zf);
            mgr_fragment_span(f, (int)y, (int)start, (int)x, zi, dzi);
            covered += x - start;
        }
        e0.w += e0.dx * MGR_SUBPIXEL;
        e1.w += e1.dx * MGR_SUBPIXEL;
        e2.w += e2.dx * MGR_SUBPIXEL;
    }
    return covered;
}
