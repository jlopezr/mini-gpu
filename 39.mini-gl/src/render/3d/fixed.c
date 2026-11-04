#include "mgr_stages.h"
#include "mgl_bytes.h"

/* Geometría en Q16.16 (MGR_FIXED_GEOMETRY=1): transformar, outcode y viewport de los triángulos sin recortar.
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

#endif

#if MGR_FIXED_GEOMETRY

/* Los bits de un float32 a Q16.16 sin pasar por soft-float: trunca hacia cero y satura. */
static mgl_s32 q_from_f32(mgl_u32 bits) {
    mgl_u32 mag = bits & 0x7fffffffU, e = mag >> 23, m = (mag & 0x7fffffU) | 0x800000U, q;
    int shift = (int)e - 134; /* valor * 2^16 = m * 2^(e - 127 - 23 + 16) */
    if (e == 0) return 0;
    if (shift > 7) q = 0x7fffffffU;
    else if (shift >= 0) q = m << shift;
    else if (shift > -32) q = m >> -shift;
    else q = 0;
    return (bits >> 31) ? -(mgl_s32)q : (mgl_s32)q;
}

void mgr_mat4q_from_float(const mgl_mat4_t *f, mgr_mat4q_t *q) {
    int i;
    for (i = 0; i < 16; i++)
        q->m[i] = q_from_f32(mgl_real_to_f32(f->m[i]));
}

void mgr_transform_vertex_q(const mgr_vertices_t *v, mgl_u32 index, const mgr_mat4q_t *mvp,
    mgr_vec4q_t *clip) {
    const unsigned char *p = v->base + index * v->stride;
    const mgl_s32 *m = mvp->m;
    mgl_s32 x = q_from_f32(RD32(p)), y = q_from_f32(RD32(p + 4)), z = q_from_f32(RD32(p + 8));
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
        r = q_div(0x40000000, v->w);
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

/* Para el camino de recorte, que sigue en float. */
void mgr_vec4q_to_float(const mgr_vec4q_t *q, mgl_vec4_t *f) {
    f->x = (mgl_real_t)q->x * (1.0f / 65536.0f);
    f->y = (mgl_real_t)q->y * (1.0f / 65536.0f);
    f->z = (mgl_real_t)q->z * (1.0f / 65536.0f);
    f->w = (mgl_real_t)q->w * (1.0f / 65536.0f);
}

#endif /* MGR_FIXED_GEOMETRY */

#if MGR_FIXED_DEPTH

/* Ceros iniciales de x != 0. */
static int clz32(mgl_u32 x) {
    int n = 0;
    if (!(x & 0xffff0000U)) { n += 16; x <<= 16; }
    if (!(x & 0xff000000U)) { n += 8; x <<= 8; }
    if (!(x & 0xf0000000U)) { n += 4; x <<= 4; }
    if (!(x & 0xc0000000U)) { n += 2; x <<= 2; }
    if (!(x & 0x80000000U)) n += 1;
    return n;
}

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
void mgr_depth_plane(const mgr_window_vertex_t *a, const mgr_window_vertex_t *b, const mgr_window_vertex_t *c,
    mgl_s32 area, mgl_s32 px, mgl_s32 py, int w, int h, mgr_depth_plane_t *out) {
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

#endif /* MGR_FIXED_DEPTH */

#if !MGR_FIXED_GEOMETRY && !MGR_FIXED_DEPTH

typedef int mgr_fixed_off; /* una unidad de traducción no puede estar vacía en C89 */

#endif
