#include "mgr_stages.h"
#include "mgl_ext.h"

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
   se calculan en float por triángulo y los inicios de fila avanzan en punto
   fijo. Dentro del span se suma también en punto fijo (fragment.c).
   MGR_INCREMENTAL_DEPTH=0 conserva la variante anterior, con inicio en float
   por fila y distinto redondeo, para comparación. */

#define DEPTH_SCALE 16776960.0f /* 65535 << MGR_DEPTH_FRAC */
/* MGR_SUBPIXEL * DEPTH_SCALE, exacto en float (65535 << 12). Multiplicar por 16 no redondea, así que
   g * 16 * DEPTH_SCALE y g * DEPTH_SCALE16 dan los mismos bits con una multiplicación menos. */
#define DEPTH_SCALE16 268431360.0f

/* División entera hacia -infinito entre MGR_SUBPIXEL, que es el desplazamiento aritmético: una instrucción y no
   una llamada (con su prólogo y sus divisiones) en MiniGPU. */
#define floor16(v) ((v) >> MGR_SUBPIXEL_BITS)

/* E de la arista de a a b en el centro (px, py), en 1/16, con el sesgo de la regla top-left: dentro si E > 0,
   o E == 0 en una arista top-left, es decir, si el resultado es >= 0. */
#define EDGE(a, b, px, py) \
    (((b)->x - (a)->x) * ((py) - (a)->y) - ((b)->y - (a)->y) * ((px) - (a)->x) - \
        ((((b)->y == (a)->y && (b)->x > (a)->x) || (b)->y < (a)->y) ? 0 : 1))

/* Los píxeles de una fila dentro de una arista, sin recorrerlos: con w su E en el primer píxel (x0) y s lo que
   baja E de un píxel al siguiente, w - s n >= 0 se cumple para n >= lo (s < 0) o n <= hi (s > 0). La división
   es exacta (enteros), así que salen los mismos píxeles que probándolos uno a uno. */
#define EDGE_SPAN(w, s)                                  \
    do {                                                 \
        if ((s) < 0) {                                   \
            if ((w) < 0) {                               \
                n = (-(w) - (s) - 1) / -(s); /* techo */ \
                MGL_SET_MAX(lo, n);                      \
            }                                            \
        } else if ((s) > 0) {                            \
            if ((w) < 0)                                 \
                hi = -1;                                 \
            else {                                       \
                n = (w) / (s);                           \
                MGL_SET_MIN(hi, n);                      \
            }                                            \
        } else if ((w) < 0)                              \
            hi = -1;                                     \
    } while (0)

mgl_s32 mgr_raster_triangle(const mgr_window_vertex_t *a, const mgr_window_vertex_t *b,
    const mgr_window_vertex_t *c, const mgr_rect_t *clip, const mgr_fragment_t *f) {
    /* Cara: de frente es antihorario con y hacia arriba, es decir, área negativa aquí (y hacia abajo). */
    mgl_s32 area = (b->x - a->x) * (c->y - a->y) - (b->y - a->y) * (c->x - a->x);
    if (area == 0) return -1;
    if ((f->flags & MGL_STATE_CULL_BACK) && area > 0) return -1;
    if ((f->flags & MGL_STATE_CULL_FRONT) && area < 0) return -1;
    return mgr_raster_triangle_area(a, b, c, clip, f, area);
}

/* Sin repetir las comprobaciones de arriba: draw.c ya las hace (con el área que pasa) y aquí se predecían
   casi siempre mal (una vez por triángulo, fuera de la BTB). */
mgl_s32 mgr_raster_triangle_area(const mgr_window_vertex_t *a, const mgr_window_vertex_t *b,
    const mgr_window_vertex_t *c, const mgr_rect_t *clip, const mgr_fragment_t *f, mgl_s32 area) {
    const mgr_window_vertex_t *t;
    mgl_s32 minx, maxx, miny, maxy, x0, x1, y0, y1, x, y, start, px, py, step0, step1, step2;
    mgl_s32 w0, w1, w2, row0, row1, row2, lo, hi, n, covered = 0, zi, dzi = 0;
    int ready = 0;
#if MGR_FIXED_DEPTH
    /* El plano de profundidad en enteros (fixed.c); el recorrido de filas es el mismo de abajo. */
    mgr_depth_plane_t plane;
    mgl_s32 depth_row = 0, depth_dx = 0, depth_dy = 0, depth_start, py0;
    long long depth_wide;
    int incremental = 0;
#else
    mgl_real_t fa, ga, gb, dz1, dz2, zrow, zf;
#if MGR_INCREMENTAL_DEPTH
    /* Q12 en unidades U16, cuatro bits más que los spans.
       Acotar todo el recorrido de la caja evita desbordar incluso cuando
       sus esquinas quedan muy lejos del interior de un triángulo estrecho. */
    mgl_real_t gx, gy, extent, origin;
    mgl_s32 depth_row = 0, depth_dx = 0, depth_dy = 0, depth_start, py0;
    int incremental = 0;
#endif
#endif

    if (area < 0) {
        t = b;
        b = c;
        c = t;
        area = -area;
    }

    /* Píxeles cuyo centro (16 i + 8) cae en la caja del triángulo, dentro de clip. */
    /* MGL_SET_MIN/MAX: MIN/MAX con MGL_EXT, o if sobre la propia variable (mgl_ext.h). */
    minx = maxx = a->x;
    MGL_SET_MIN(minx, b->x);
    MGL_SET_MAX(maxx, b->x);
    MGL_SET_MIN(minx, c->x);
    MGL_SET_MAX(maxx, c->x);
    miny = maxy = a->y;
    MGL_SET_MIN(miny, b->y);
    MGL_SET_MAX(maxy, b->y);
    MGL_SET_MIN(miny, c->y);
    MGL_SET_MAX(maxy, c->y);
    x0 = floor16(minx + MGR_SUBPIXEL / 2 - 1);
    x1 = floor16(maxx - MGR_SUBPIXEL / 2) + 1;
    y0 = floor16(miny + MGR_SUBPIXEL / 2 - 1);
    y1 = floor16(maxy - MGR_SUBPIXEL / 2) + 1;
    MGL_SET_MAX(x0, clip->x0);
    MGL_SET_MAX(y0, clip->y0);
    MGL_SET_MIN(x1, clip->x1);
    MGL_SET_MIN(y1, clip->y1);
    if (x0 >= x1 || y0 >= y1) return 0;

    px = x0 * MGR_SUBPIXEL + MGR_SUBPIXEL / 2;
    py = y0 * MGR_SUBPIXEL + MGR_SUBPIXEL / 2;
#if MGR_INCREMENTAL_DEPTH
    py0 = py;
#endif
    /* Las tres aristas: E en el primer píxel de la fila, lo que baja de un píxel al siguiente (step) y lo que
       sube de una fila a la siguiente (row). */
    w0 = EDGE(b, c, px, py);
    w1 = EDGE(c, a, px, py);
    w2 = EDGE(a, b, px, py);
    step0 = (c->y - b->y) * MGR_SUBPIXEL;
    step1 = (a->y - c->y) * MGR_SUBPIXEL;
    step2 = (b->y - a->y) * MGR_SUBPIXEL;
    row0 = (c->x - b->x) * MGR_SUBPIXEL;
    row1 = (a->x - c->x) * MGR_SUBPIXEL;
    row2 = (b->x - a->x) * MGR_SUBPIXEL;

    for (y = y0; y < y1; y++) { /* py, el centro de la fila y, solo hace falta sin el recorrido incremental */
        /* Dentro de las tres a la vez: un tramo, porque el triángulo es convexo. */
        lo = 0;
        hi = x1 - x0 - 1;
        EDGE_SPAN(w0, step0);
        EDGE_SPAN(w1, step1);
        EDGE_SPAN(w2, step2);
        start = x0 + lo;
        x = x0 + hi + 1;
        if (x > start) {
            if (!ready) {
                /* La profundidad, al encontrar el primer píxel: un triángulo que no cubre ningún centro (muchos
                   de un modelo pequeño en pantalla) se la ahorra. Mismos cálculos que antes del bucle. */
                ready = 1;
#if MGR_INCREMENTAL_DEPTH
                /* Sin prueba ni escritura de profundidad (el modo DEPTH_SORT, el algoritmo del pintor), el
                   plano no hace falta: fragment no mira z. Era lo más caro de un triángulo pequeño. */
                if (!f->depth || !(f->flags & (MGL_STATE_DEPTH_TEST | MGL_STATE_DEPTH_WRITE))) {
                    incremental = 1; /* depth_row, depth_dx, depth_dy y dzi se quedan a 0 */
                } else {
#endif
#if MGR_FIXED_DEPTH
                mgr_depth_plane(a, b, c, area, px, py0, x1 - x0, y1 - y0, &plane);
                dzi = plane.dzi;
                if (plane.incremental) {
                    depth_row = plane.row;
                    depth_dx = plane.dx;
                    depth_dy = plane.dy;
                    incremental = 1;
                    depth_row += depth_dy * (y - y0); /* lo que habrían sumado las filas anteriores */
                }
#else
                /* Gradientes de z por unidad de 1/16 de píxel. */
                fa = (mgl_real_t)area;
                dz1 = b->z - a->z;
                dz2 = c->z - a->z;
                ga = (dz1 * (mgl_real_t)(c->y - a->y) - dz2 * (mgl_real_t)(b->y - a->y)) / fa;
                gb = (dz2 * (mgl_real_t)(b->x - a->x) - dz1 * (mgl_real_t)(c->x - a->x)) / fa;
                zf = ga * DEPTH_SCALE16;
#if MGR_INCREMENTAL_DEPTH
                gx = zf * 16.0f; /* antes de acotar zf */
#endif
                /* Acotado: en un span z no sale de [0, 1] salvo por redondeo, y así z + dz no desborda. */
                if (zf > 33553920.0f) zf = 33553920.0f;
                if (-zf > 33553920.0f) zf = -33553920.0f;
                dzi = mgl_round(zf);

#if MGR_INCREMENTAL_DEPTH
                gy = gb * DEPTH_SCALE16 * 16.0f;
                zrow = a->z + gb * (mgl_real_t)(py0 - a->y);
                origin = ((zrow + ga * (mgl_real_t)(px - a->x)) * DEPTH_SCALE) * 16.0f;
                extent = (gx < 0.0f ? -gx : gx) * (mgl_real_t)(x1 - x0) +
                    (gy < 0.0f ? -gy : gy) * (mgl_real_t)(y1 - y0);
                /* |origin| <= 2^29 y recorrido <= 2^28: queda margen para el
                   redondeo de los incrementos y de la conversión final (+8). NaN e
                   infinitos tampoco pasan estas comparaciones. */
                if (extent <= 268435456.0f && origin <= 536870912.0f && -origin <= 536870912.0f) {
                    depth_row = mgl_round(origin);
                    depth_dx = mgl_round(gx);
                    depth_dy = mgl_round(gy);
                    incremental = 1;
                    depth_row += depth_dy * (y - y0); /* lo que habrían sumado las filas anteriores */
                }
#endif
#endif /* MGR_FIXED_DEPTH */
#if MGR_INCREMENTAL_DEPTH
                }
#endif
            }
#if MGR_INCREMENTAL_DEPTH
            if (incremental) {
                depth_start = depth_row + depth_dx * (start - x0);
                /* Acotar y redondear: 0 si <= 0 y MGR_DEPTH_MAX si >= MGR_DEPTH_MAX * 16 ((MAX * 16 + 8) >> 4 es
                   MAX). Con MIN y MAX (MGL_EXT) sin saltos: con if/else if, el caso de siempre era el último y su
                   salto se predecía mal en todos los spans. */
                MGL_SET_MAX(depth_start, 0);
                MGL_SET_MIN(depth_start, MGR_DEPTH_MAX * 16);
                zi = (depth_start + 8) >> 4;
            } else {
#endif
#if MGR_FIXED_DEPTH
            depth_wide = plane.origin + plane.dx64 * (start - x0) + plane.dy64 * (y - y0);
            zi = depth_wide <= 0 ? 0 : depth_wide >= (long long)MGR_DEPTH_MAX * 16 ? MGR_DEPTH_MAX :
                (mgl_s32)((depth_wide + 8) >> 4);
#else
            zrow = a->z + gb * (mgl_real_t)(y * MGR_SUBPIXEL + MGR_SUBPIXEL / 2 - a->y);
            zf = (zrow + ga * (mgl_real_t)(start * MGR_SUBPIXEL + MGR_SUBPIXEL / 2 - a->x)) * DEPTH_SCALE;
            zi = zf <= 0.0f ? 0 : zf >= DEPTH_SCALE ? MGR_DEPTH_MAX : mgl_round(zf);
#endif
#if MGR_INCREMENTAL_DEPTH
            }
#endif
            mgr_fragment_span(f, (int)y, (int)start, (int)x, zi, dzi);
            covered += x - start;
        }
        w0 += row0;
        w1 += row1;
        w2 += row2;
#if MGR_INCREMENTAL_DEPTH
        if (incremental) depth_row += depth_dy;
#endif
    }
    return covered;
}
