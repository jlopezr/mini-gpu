#include "mgr_stages.h"
#include "mgl_ext.h"
#include "mgl_bytes.h"

/* Geometría en Q16.16 (MGR_FIXED_GEOMETRY=1): transformar, outcode, recorte y viewport.
   Un Q16.16 es un int: sumar y comparar son los operadores de C. El producto y la cociente usan los idiomas que
   mini-lcc baja a MULFX y a __mini_divfx (u.lcc/mini-tst/143-146); si se escriben distinto sigue siendo correcto
   pero cuesta unas 28 instrucciones por producto en vez de una. Los resultados NO coinciden bit a bit con los
   de float: ver check-minigpu. Sin desbordamiento controlado: las coordenadas de recorte han de caber en
   +-32768.

   MGR_FIXED_DEPTH=1: el plano de profundidad de cada triángulo (mgr_depth_plane) en enteros, con un solo
   recíproco de 1/área. */

#if MGR_FIXED_GEOMETRY || MGR_FIXED_DEPTH

#define Q_ONE 65536

static mgl_s32 q_mul(mgl_s32 a, mgl_s32 b) {
    return (mgl_s32)(((long long)a * (long long)b) >> 16);
}

static mgl_s32 q_div(mgl_s32 a, mgl_s32 b) {
    return (mgl_s32)((((long long)a) << 16) / (long long)b);
}


/* Ceros iniciales de x != 0: con MGL_EXT, la instrucción CLZ (mgl_ext.h). */
#if MGL_EXT_NATIVE
#define clz32(x) MGL_CLZ(x)
#else
static int clz32(mgl_u32 x) {
    int n = 0;
    if (!(x & 0xffff0000U)) { n += 16; x <<= 16; }
    if (!(x & 0xff000000U)) { n += 8; x <<= 8; }
    if (!(x & 0xf0000000U)) { n += 4; x <<= 4; }
    if (!(x & 0xc0000000U)) { n += 2; x <<= 2; }
    if (!(x & 0x80000000U)) n += 1;
    return n;
}
#endif

/* floor(n 2^bits / d) módulo 2^32, con 0 < d < 2^31: la división larga con la DIVU del hardware, que q_div
   (__mini_divfx) hace bit a bit en un bucle. El resto r < d deja clz(d) bits libres arriba: cada DIVU saca
   tantos bits del cociente. Con d de unas pocas unidades en Q16.16 (2^17 - 2^24) son dos o tres. */
static mgl_u32 udiv_shift(mgl_u32 n, mgl_u32 d, int bits) {
    mgl_u32 q = n / d, r = n - q * d, t;
    int k = clz32(d), step;
    while (bits > 0) {
        step = k;
        MGL_SET_MIN(step, bits); /* MIN con MGL_EXT: el ?: era un salto que fallaba la mitad de las veces */
        r <<= step;
        t = r / d;
        r -= t * d;
        q = (q << step) | t;
        bits -= step;
    }
    return q;
}

#endif

#if MGR_FIXED_GEOMETRY

/* Los bits de un float32 a Q16.16 sin pasar por soft-float: trunca hacia cero y satura. */
/* trunc(valor * 2^16), saturando a [-2^31, 2^31 - 1], y 0 con NaN o subnormal: lo mismo que la instrucción
   FTOI con fbits = 16 (isa.md), que es FMUL por 65536 (exacto) y FTOI en mini-lcc -fp32 (Q_FROM_FLOAT). */
static mgl_s32 q_from_f32(mgl_u32 bits) {
    mgl_u32 mag = bits & 0x7fffffffU, e = mag >> 23, m = (mag & 0x7fffffU) | 0x800000U, q;
    int shift = (int)e - 134; /* valor * 2^16 = m * 2^(e - 127 - 23 + 16) */
    if (e == 0 || mag > 0x7f800000U) return 0;
    if (shift > 7) return (bits >> 31) ? (mgl_s32)0x80000000U : 0x7fffffff;
    else if (shift >= 0) q = m << shift;
    else if (shift > -32) q = m >> -shift;
    else q = 0;
    return (bits >> 31) ? -(mgl_s32)q : (mgl_s32)q;
}

#ifdef __MINI_FP32__
#define Q_FROM_FLOAT(p) ((mgl_s32)(*(const float *)(p) * 65536.0f))
#else
#define Q_FROM_FLOAT(p) q_from_f32(RD32(p))
#endif

const mgr_mat4q_t *mgr_state_mvp_q(mgr_state_t *s) {
    const mgl_mat4_t *f = mgr_state_mvp(s);
    int i;
    if (s->mvp_q_dirty) {
        for (i = 0; i < 16; i++)
            s->mvp_q.m[i] = q_from_f32(mgl_real_to_f32(f->m[i]));
        s->mvp_q_dirty = 0;
    }
    return &s->mvp_q;
}

void mgr_transform_vertex_q(const mgr_vertices_t *v, mgl_u32 index, const mgr_mat4q_t *mvp,
    mgr_vec4q_t *clip) {
    mgr_transform_at_q(v->base + index * v->stride, mvp, clip);
}

void mgr_transform_at_q(const unsigned char *p, const mgr_mat4q_t *mvp, mgr_vec4q_t *clip) {
    const mgl_s32 *m = mvp->m;
    mgl_s32 x = Q_FROM_FLOAT(p), y = Q_FROM_FLOAT(p + 4), z = Q_FROM_FLOAT(p + 8);
    clip->x = q_mul(m[0], x) + q_mul(m[4], y) + q_mul(m[8], z) + m[12];
    clip->y = q_mul(m[1], x) + q_mul(m[5], y) + q_mul(m[9], z) + m[13];
    clip->z = q_mul(m[2], x) + q_mul(m[6], y) + q_mul(m[10], z) + m[14];
    clip->w = q_mul(m[3], x) + q_mul(m[7], y) + q_mul(m[11], z) + m[15];
}

unsigned int mgr_outcode_q(const mgr_vec4q_t *v) {
    mgl_s32 w = v->w, nw = -v->w;
    unsigned int code = 0;
    if (v->z < nw) code |= 1U;
    if (w < v->z) code |= 2U;
    if (v->x < nw) code |= 4U;
    if (w < v->x) code |= 8U;
    if (v->y < nw) code |= 16U;
    if (w < v->y) code |= 32U;
    return code;
}

/* Como mgr_viewport_map con v->w > 0. Una sola división: r = 2^46 / w, con 1/w a unos 30 bits en vez de los 16 de
   Q16.16 (que con w grande dejarían pocos bits), y cada coordenada sale de x * r >> 30 (MUL + MULHI). Cabe en 32
   bits si w > 0.5; con w menor (casi nunca: es la distancia a la cámara) se divide cada coordenada. El redondeo al
   más cercano de a * s (s entero, en 1/16 de píxel) es (floor(2 a s) + 1) >> 1. */
void mgr_viewport_map_q(const mgr_state_t *s, const mgr_vec4q_t *v, mgr_window_vertex_t *out) {
    mgl_s32 xn, yn, zn, r;
    if (v->w > 0x8000) {
        r = (mgl_s32)udiv_shift(0x40000000U, (mgl_u32)v->w, 16); /* q_div(0x40000000, v->w) */
        xn = (mgl_s32)(((long long)v->x * (long long)r) >> 30);
        yn = (mgl_s32)(((long long)v->y * (long long)r) >> 30);
        zn = (mgl_s32)(((long long)v->z * (long long)r) >> 30);
    } else {
        xn = q_div(v->x, v->w);
        yn = q_div(v->y, v->w);
        zn = q_div(v->z, v->w);
    }
    out->x = s->view_x + ((q_mul(xn + Q_ONE, 2 * s->view_sxi) + 1) >> 1);
    out->y = s->view_y + ((q_mul(Q_ONE - yn, 2 * s->view_syi) + 1) >> 1);
#if MGR_FIXED_DEPTH
    out->zq = (zn >> 1) + Q_ONE / 2;
#else
    out->z = (mgl_real_t)((zn >> 1) + Q_ONE / 2) * (1.0f / 65536.0f);
#endif
}

/* El recorte de clipping.c en Q16.16: los mismos planos, el mismo orden y el corte siempre desde el vértice de
   dentro (dos triángulos con una arista común obtienen el mismo punto). Dentro de un plano es la comparación del
   outcode, sin sumas. Las distancias del corte, di = w +- c >= 0 y do < 0, se restan en 32 bits: necesita
   |coordenada| < 2^30 (16384 unidades), un poco menos que el resto de fixed.c.

   t = di / (di - do) en [0, 1) con 30 bits de fracción (udiv_shift), no los 16 de q_div: con 16 el corte de una
   arista larga en el plano cercano se movería un cuarto de píxel. Luego p = inside + (outside - inside) * t
   (MUL + MULHI). */
static int inside_q(int k, const mgr_vec4q_t *v) {
    switch (k) {
    case 0:
        return !(v->z < -v->w); /* cercano */
    case 1:
        return !(v->w < v->z); /* lejano */
    case 2:
        return !(v->x < -v->w); /* izquierdo */
    case 3:
        return !(v->w < v->x); /* derecho */
    case 4:
        return !(v->y < -v->w); /* inferior */
    default:
        return !(v->w < v->y); /* superior */
    }
}

static mgl_s32 dist_q(int k, const mgr_vec4q_t *v) {
    switch (k) {
    case 0:
        return v->w + v->z;
    case 1:
        return v->w - v->z;
    case 2:
        return v->w + v->x;
    case 3:
        return v->w - v->x;
    case 4:
        return v->w + v->y;
    default:
        return v->w - v->y;
    }
}

static mgl_s32 lerp_q(mgl_s32 a, mgl_s32 b, mgl_s32 t30) {
    return a + (mgl_s32)(((long long)(b - a) * (long long)t30) >> 30);
}

static void intersect_q(int k, const mgr_vec4q_t *inside, const mgr_vec4q_t *outside, mgr_vec4q_t *out) {
    mgl_u32 n = (mgl_u32)dist_q(k, inside), d = n - (mgl_u32)dist_q(k, outside);
    mgl_s32 t30;
    if (d & 0x80000000U) { /* udiv_shift: n < d < 2^31 */
        n >>= 1;
        d >>= 1;
    }
    t30 = (mgl_s32)udiv_shift(n, d, 30); /* < 2^30: n < d */
    out->x = lerp_q(inside->x, outside->x, t30);
    out->y = lerp_q(inside->y, outside->y, t30);
    out->z = lerp_q(inside->z, outside->z, t30);
    out->w = lerp_q(inside->w, outside->w, t30);
}

int mgr_clip_triangle_q(const mgr_vec4q_t in[3], mgr_vec4q_t out[MGR_CLIP_MAX]) {
    mgr_vec4q_t buffer[2][MGR_CLIP_MAX];
    const mgr_vec4q_t *src;
    mgr_vec4q_t *dst;
    int n = 3, k, i, m, which = 0;
    unsigned int all = 0;
    for (i = 0; i < 3; i++) {
        buffer[0][i] = in[i];
        all |= mgr_outcode_q(&in[i]);
    }
    for (k = 0; k < 6; k++) {
        if (!(all & (1U << k))) continue;
        src = buffer[which];
        dst = buffer[which ^ 1];
        m = 0;
        for (i = 0; i < n; i++) {
            const mgr_vec4q_t *a = &src[i], *b = &src[i + 1 < n ? i + 1 : 0];
            int a_in = inside_q(k, a), b_in = inside_q(k, b);
            if (a_in) dst[m++] = *a;
            if (a_in != b_in) intersect_q(k, a_in ? a : b, a_in ? b : a, &dst[m++]);
        }
        which ^= 1;
        n = m;
        if (n < 3) return 0;
    }
    for (i = 0; i < n; i++) out[i] = buffer[which][i];
    return n;
}

#endif /* MGR_FIXED_GEOMETRY */

#if MGR_FIXED_DEPTH

/* t * r >> sh sin desbordar 64 bits (|t| < 2^58, r < 2^24, 24 <= sh <= 58): t se parte en una mitad alta y otra
   de 24 bits. Trunca hacia cero. */
static long long mulr(long long t, mgl_u32 r, int sh) {
    unsigned long long u = t < 0 ? (unsigned long long)(-t) : (unsigned long long)t;
    unsigned long long hi = u >> 24, lo = u & 0xffffffU;
    long long v = (long long)(((hi * r) >> (sh - 24)) + ((lo * r) >> sh));
    return t < 0 ? -v : v;
}

#define DEPTH_LIMIT 33553920 /* como DEPTH_SCALE16 en raster3d.c: lo máximo que se suma por píxel */

/* El plano z = z0 + gx x + gy y en el cuadrante de a, con los mismos cocientes que raster3d.c en float:
     Na = dzb * dyc - dzc * dyb       Nb = dzc * dxb - dzb * dxc       (z en Q16.16, 1/16 de píxel)
     gx = Na / area                   gy = Nb / area
   Y en unidades de profundidad (65535 << 12 por unidad de z y de píxel): dx = Na * 65535 / area (Q12 por píxel),
   dzi = dx / 16 (Q8), y la profundidad en (px, py) es (zq_a + (Na (px - ax) + Nb (py - ay)) / area) * 65535 / 16.
   La división por area es un solo recíproco: 1/area = r24 * 2^s / 2^54, con area << s en [2^30, 2^31); r0 sale
   de una __mini_divfx (16 bits) y una iteración de Newton lo lleva a unos 30. */
static void depth_plane_wide(const mgr_window_vertex_t *a, const mgr_window_vertex_t *b,
    const mgr_window_vertex_t *c, mgl_s32 area, mgl_s32 px, mgl_s32 py, int w, int h, mgr_depth_plane_t *out) {
    mgl_s32 dxb = b->x - a->x, dyb = b->y - a->y, dxc = c->x - a->x, dyc = c->y - a->y;
    mgl_s32 dzb = b->zq - a->zq, dzc = c->zq - a->zq;
    long long na = (long long)dzb * dyc - (long long)dzc * dyb;
    long long nb = (long long)dzc * dxb - (long long)dzb * dxc;
    long long r0s, e, r1s, gx, gy, origin, q8, ext, dz;
    int s = clz32((mgl_u32)area) - 1, sh = 54 - s;
    mgl_u32 an = (mgl_u32)area << s, r24;

    r0s = (long long)q_div(0x40000000, (mgl_s32)an) << 15; /* ~2^61 / an, 16 bits buenos */
    e = (1LL << 61) - (long long)an * r0s;
    r1s = r0s + ((r0s * (e >> 15)) >> 46);
    r24 = (mgl_u32)(r1s >> 7);

    gx = mulr(na * 65535, r24, sh);
    gy = mulr(nb * 65535, r24, sh);
    dz = (gx + 8) >> 4;
    out->dzi = (mgl_s32)(dz > DEPTH_LIMIT ? DEPTH_LIMIT : dz < -DEPTH_LIMIT ? -DEPTH_LIMIT : dz);
    q8 = mulr((na * (px - a->x) + nb * (py - a->y)) * 256, r24, sh);
    origin = ((((long long)a->zq << 8) + q8) * 65535) >> 12;
    ext = (gx < 0 ? -gx : gx) * w + (gy < 0 ? -gy : gy) * h;
    out->origin = origin;
    out->dx64 = gx;
    out->dy64 = gy;
    out->incremental = ext <= 268435456 && origin <= 536870912 && -origin <= 536870912;
    out->row = (mgl_s32)origin;
    out->dx = (mgl_s32)gx;
    out->dy = (mgl_s32)gy;
}

/* El caso de casi todos los triángulos, en 32 bits (unas 250 instrucciones en vez de unas 900): con las aristas
   por debajo de 1000 píxeles (16000 en 1/16) y |dz| <= 65536 + algo, Na y Nb caben en 32 bits, y cada gradiente
   es un cociente exacto, qx = Na 2^16 / area (udiv_shift, con la DIVU), sin recíproco ni productos partidos.
     dx = Na 65535 / area = qx - qx / 2^16          (Q12 por píxel, truncado hacia cero, como mulr)
     q8 = (qx (px - ax) + qy (py - ay)) / 2^8        (z en Q8 respecto a a: MUL + MULHI)
     origin = ((zq_a << 8) + q8) 65535 >> 12 = 16 x - ceil(x / 4096)
   Si algo no cabe (aristas largas, gradientes de un triángulo casi de canto, el plano lejos de la caja), el
   cálculo de 64 bits de antes (depth_plane_wide), que también decide si sirve el recorrido incremental. */
#define DEPTH_EDGE_MAX 16000

static mgl_s32 abs_s32(mgl_s32 v) {
    return v < 0 ? -v : v;
}

/* n 2^16 / area truncado hacia cero, o 0 con *ok = 0 si no cabe en 31 bits. */
static mgl_s32 gradient16(mgl_s32 n, mgl_s32 area, int *ok) {
    mgl_u32 m = (mgl_u32)abs_s32(n), q;
    if ((m >> 15) >= (mgl_u32)area) {
        *ok = 0;
        return 0;
    }
    q = udiv_shift(m, (mgl_u32)area, 16);
    return n < 0 ? -(mgl_s32)q : (mgl_s32)q;
}

void mgr_depth_plane(const mgr_window_vertex_t *a, const mgr_window_vertex_t *b, const mgr_window_vertex_t *c,
    mgl_s32 area, mgl_s32 px, mgl_s32 py, int w, int h, mgr_depth_plane_t *out) {
    mgl_s32 dxb = b->x - a->x, dyb = b->y - a->y, dxc = c->x - a->x, dyc = c->y - a->y;
    mgl_s32 dzb = b->zq - a->zq, dzc = c->zq - a->zq, na, nb, qx, qy, gx, gy, dz, x32;
    mgl_u32 ux, uy;
    long long x;
    int ok = 1;
    if (abs_s32(dxb) >= DEPTH_EDGE_MAX || abs_s32(dyb) >= DEPTH_EDGE_MAX || abs_s32(dxc) >= DEPTH_EDGE_MAX ||
        abs_s32(dyc) >= DEPTH_EDGE_MAX || abs_s32(dzb) > 65600 || abs_s32(dzc) > 65600)
        ok = 0;
    if (ok) {
        na = dzb * dyc - dzc * dyb;
        nb = dzc * dxb - dzb * dxc;
        qx = gradient16(na, area, &ok);
        qy = gradient16(nb, area, &ok);
    }
    if (ok) {
        gx = qx - (qx < 0 ? -(-qx >> 16) : qx >> 16);
        gy = qy - (qy < 0 ? -(-qy >> 16) : qy >> 16);
        /* incremental de depth_plane_wide: |gx| w + |gy| h <= 2^28. En 32 bits: cada producto <= 2^28 (la
           división lo asegura) y la suma no se sale; más corto que dos productos de 64 bits y su suma (que
           además mini-lcc compilaba mal hasta u.lcc 15c63e3, con el par del resultado corrido uno). */
        ux = (mgl_u32)abs_s32(gx);
        uy = (mgl_u32)abs_s32(gy);
        ok = ux <= 268435456U / (mgl_u32)w && uy <= 268435456U / (mgl_u32)h && ux * (mgl_u32)w + uy * (mgl_u32)h <= 268435456U;
    }
    if (ok) {
        x = ((long long)qx * (long long)(px - a->x) + (long long)qy * (long long)(py - a->y)) >> 8;
        x += (long long)a->zq << 8;
        ok = x < 33554432 && x > -33554432; /* |origin| <= 2^29 */
    }
    if (!ok) {
        depth_plane_wide(a, b, c, area, px, py, w, h, out);
        return;
    }
    dz = (gx + 8) >> 4;
    out->dzi = dz > DEPTH_LIMIT ? DEPTH_LIMIT : dz < -DEPTH_LIMIT ? -DEPTH_LIMIT : dz;
    x32 = (mgl_s32)x;
    out->row = (x32 << 4) - ((x32 + 4095) >> 12);
    out->dx = gx;
    out->dy = gy;
    out->incremental = 1;
    out->origin = out->row;
    out->dx64 = gx;
    out->dy64 = gy;
}

#endif /* MGR_FIXED_DEPTH */

#if !MGR_FIXED_GEOMETRY && !MGR_FIXED_DEPTH

typedef int mgr_fixed_off; /* una unidad de traducción no puede estar vacía en C89 */

#endif
