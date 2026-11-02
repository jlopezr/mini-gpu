#include "mgl_math.h"

/* Constantes con 9 cifras: el literal se redondea a float igual en los dos
   compiladores. Nada de 1.0f / 6.0f: lcc y el host podrían plegarlo distinto.
   El polinomio va con restas, de cuando mini-lcc dejaba -1.5f como double (ya
   no: u.lcc test 169); en IEEE a + (-b) es exactamente a - b, así que da lo
   mismo bit a bit. */
#define TWO_PI 6.28318531f
#define INV_TWO_PI 0.159154943f
#define HALF_PI 1.57079633f

typedef union {
    mgl_u32 u;
    float f;
} f32_bits;

mgl_u32 mgl_real_to_f32(mgl_real_t v) {
    f32_bits b;
    b.f = v;
    return b.u;
}

mgl_real_t mgl_real_from_f32(mgl_u32 bits) {
    f32_bits b;
    b.u = bits;
    return b.f;
}

/* (int)(v + 0.5f) para v >= 0, -(int)(-v + 0.5f) para v < 0, y saturado desde |v| >= 2147483520 (el float
   anterior a 2^31). Las comparaciones van sobre los bits, en enteros: fuera del NaN, el orden de |v| es el de
   sus bits, 2147483520.0f es 0x4effffff, y -0 da 0 por los dos lados. Con float por software, dos
   comparaciones menos en cada redondeo. El NaN sigue el camino de los negativos, como con v >= 0.0f. */
mgl_s32 mgl_round(mgl_real_t v) {
    mgl_u32 bits = mgl_real_to_f32(v), mag = bits & 0x7fffffffU;
    if (mag > 0x7f800000U) return -(mgl_s32)(-v + 0.5f); /* NaN */
    if (mag >= 0x4effffffU) return bits >> 31 ? -2147483647 : 2147483647;
    if (!(bits >> 31)) return (mgl_s32)(v + 0.5f);
    return -(mgl_s32)(-v + 0.5f);
}

/* Reduce a [-pi, pi] restando vueltas enteras, lleva a [-pi/2, pi/2] con
   sin(pi - r) = sin(r) y usa Taylor hasta r^11 (error < 1e-7 en el intervalo).
   La reducción pierde precisión con ángulos de miles de radianes. */
mgl_real_t mgl_sin(mgl_real_t a) {
    mgl_real_t r, r2;
    r = a - (mgl_real_t)mgl_round(a * INV_TWO_PI) * TWO_PI;
    if (r > HALF_PI)
        r = MGL_PI - r;
    else if (-r > HALF_PI)
        r = -(MGL_PI + r);
    r2 = r * r;
    return r * (1.0f -
                   r2 * (0.166666667f -
                            r2 * (0.00833333333f -
                                     r2 * (0.000198412698f - r2 * (2.75573192e-6f - r2 * 2.50521084e-8f)))));
}

mgl_real_t mgl_cos(mgl_real_t a) {
    return mgl_sin(a + HALF_PI);
}

/* Newton desde una estimación sacada del exponente (error < 4%): cuatro pasos
   dan la precisión de float. */
mgl_real_t mgl_sqrt(mgl_real_t v) {
    mgl_real_t y;
    int i;
    if (!(v > 0.0f)) return 0.0f;
    y = mgl_real_from_f32((mgl_real_to_f32(v) >> 1) + 0x1fbb67a8U);
    for (i = 0; i < 4; i++) y = 0.5f * (y + v / y);
    return y;
}

void mgl_mat4_identity(mgl_mat4_t *out) {
    int i;
    for (i = 0; i < 16; i++) out->m[i] = (i % 5) == 0 ? 1.0f : 0.0f;
}

/* Siempre en el mismo orden (k de 0 a 3), para que el resultado sea el mismo bit a bit en
   cualquier compilador. */
void mgl_mat4_mul(mgl_mat4_t *out, const mgl_mat4_t *a, const mgl_mat4_t *b) {
    mgl_mat4_t t;
    int c, r;
    for (c = 0; c < 4; c++)
        for (r = 0; r < 4; r++)
            t.m[c * 4 + r] = a->m[r] * b->m[c * 4] + a->m[4 + r] * b->m[c * 4 + 1] +
                a->m[8 + r] * b->m[c * 4 + 2] + a->m[12 + r] * b->m[c * 4 + 3];
    *out = t;
}

void mgl_mat4_translation(mgl_mat4_t *out, mgl_real_t x, mgl_real_t y, mgl_real_t z) {
    mgl_mat4_identity(out);
    out->m[12] = x;
    out->m[13] = y;
    out->m[14] = z;
}

void mgl_mat4_scaling(mgl_mat4_t *out, mgl_real_t x, mgl_real_t y, mgl_real_t z) {
    mgl_mat4_identity(out);
    out->m[0] = x;
    out->m[5] = y;
    out->m[10] = z;
}

void mgl_mat4_rotation_x(mgl_mat4_t *out, mgl_real_t angle) {
    mgl_real_t c = mgl_cos(angle), s = mgl_sin(angle);
    mgl_mat4_identity(out);
    out->m[5] = c;
    out->m[6] = s;
    out->m[9] = -s;
    out->m[10] = c;
}

void mgl_mat4_rotation_y(mgl_mat4_t *out, mgl_real_t angle) {
    mgl_real_t c = mgl_cos(angle), s = mgl_sin(angle);
    mgl_mat4_identity(out);
    out->m[0] = c;
    out->m[2] = -s;
    out->m[8] = s;
    out->m[10] = c;
}

void mgl_mat4_rotation_z(mgl_mat4_t *out, mgl_real_t angle) {
    mgl_real_t c = mgl_cos(angle), s = mgl_sin(angle);
    mgl_mat4_identity(out);
    out->m[0] = c;
    out->m[1] = s;
    out->m[4] = -s;
    out->m[5] = c;
}

void mgl_mat4_perspective(mgl_mat4_t *out, mgl_real_t fovy, mgl_real_t aspect, mgl_real_t near_z,
    mgl_real_t far_z) {
    mgl_real_t half = fovy * 0.5f, f = mgl_cos(half) / mgl_sin(half), depth = near_z - far_z;
    mgl_mat4_identity(out);
    out->m[0] = f / aspect;
    out->m[5] = f;
    out->m[10] = (far_z + near_z) / depth;
    out->m[11] = -1.0f;
    out->m[14] = 2.0f * far_z * near_z / depth;
    out->m[15] = 0.0f;
}

static void normalize3(mgl_real_t *v) {
    mgl_real_t n = mgl_sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (n > 0.0f) {
        v[0] = v[0] / n;
        v[1] = v[1] / n;
        v[2] = v[2] / n;
    }
}

static void cross3(mgl_real_t *out, const mgl_real_t *a, const mgl_real_t *b) {
    out[0] = a[1] * b[2] - a[2] * b[1];
    out[1] = a[2] * b[0] - a[0] * b[2];
    out[2] = a[0] * b[1] - a[1] * b[0];
}

void mgl_mat4_look_at(mgl_mat4_t *out, mgl_real_t ex, mgl_real_t ey, mgl_real_t ez, mgl_real_t cx,
    mgl_real_t cy, mgl_real_t cz, mgl_real_t ux, mgl_real_t uy, mgl_real_t uz) {
    mgl_real_t f[3], s[3], u[3], up[3];
    f[0] = cx - ex;
    f[1] = cy - ey;
    f[2] = cz - ez;
    up[0] = ux;
    up[1] = uy;
    up[2] = uz;
    normalize3(f);
    cross3(s, f, up);
    normalize3(s);
    cross3(u, s, f);
    mgl_mat4_identity(out);
    out->m[0] = s[0];
    out->m[4] = s[1];
    out->m[8] = s[2];
    out->m[1] = u[0];
    out->m[5] = u[1];
    out->m[9] = u[2];
    out->m[2] = -f[0];
    out->m[6] = -f[1];
    out->m[10] = -f[2];
    out->m[12] = -(s[0] * ex + s[1] * ey + s[2] * ez);
    out->m[13] = -(u[0] * ex + u[1] * ey + u[2] * ez);
    out->m[14] = f[0] * ex + f[1] * ey + f[2] * ez;
}

void mgl_mat4_translate_by(mgl_mat4_t *m, mgl_real_t x, mgl_real_t y, mgl_real_t z) {
    mgl_mat4_t t;
    mgl_mat4_translation(&t, x, y, z);
    mgl_mat4_mul(m, m, &t);
}

void mgl_mat4_scale_by(mgl_mat4_t *m, mgl_real_t x, mgl_real_t y, mgl_real_t z) {
    mgl_mat4_t t;
    mgl_mat4_scaling(&t, x, y, z);
    mgl_mat4_mul(m, m, &t);
}

void mgl_mat4_rotate_x_by(mgl_mat4_t *m, mgl_real_t angle) {
    mgl_mat4_t t;
    mgl_mat4_rotation_x(&t, angle);
    mgl_mat4_mul(m, m, &t);
}

void mgl_mat4_rotate_y_by(mgl_mat4_t *m, mgl_real_t angle) {
    mgl_mat4_t t;
    mgl_mat4_rotation_y(&t, angle);
    mgl_mat4_mul(m, m, &t);
}

void mgl_mat4_rotate_z_by(mgl_mat4_t *m, mgl_real_t angle) {
    mgl_mat4_t t;
    mgl_mat4_rotation_z(&t, angle);
    mgl_mat4_mul(m, m, &t);
}

void mgl_mat4_transform_point(const mgl_mat4_t *m, mgl_real_t x, mgl_real_t y, mgl_real_t z,
    mgl_vec4_t *out) {
    out->x = m->m[0] * x + m->m[4] * y + m->m[8] * z + m->m[12];
    out->y = m->m[1] * x + m->m[5] * y + m->m[9] * z + m->m[13];
    out->z = m->m[2] * x + m->m[6] * y + m->m[10] * z + m->m[14];
    out->w = m->m[3] * x + m->m[7] * y + m->m[11] * z + m->m[15];
}
