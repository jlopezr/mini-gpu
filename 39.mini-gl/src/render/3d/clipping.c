#include "mgr_stages.h"

/* Los seis planos del volumen de visión en coordenadas de recorte: el punto v
   está dentro del plano k si dist(k, v) >= 0. El cercano (z >= -w) es el que
   importa en perspectiva: detrás de él w se acerca a 0 o cambia de signo y la
   división de perspectiva no tiene sentido. Los demás dejan los vértices dentro
   del viewport, y así los enteros de raster3d.c no desbordan. */
#define PLANES 6

static mgl_real_t dist(int k, const mgl_vec4_t *v) {
    switch (k) {
    case 0:
        return v->w + v->z; /* cercano */
    case 1:
        return v->w - v->z; /* lejano */
    case 2:
        return v->w + v->x; /* izquierdo */
    case 3:
        return v->w - v->x; /* derecho */
    case 4:
        return v->w + v->y; /* inferior */
    default:
        return v->w - v->y; /* superior */
    }
}

/* dist(k, v) < 0 sin calcular dist: w + c < 0 es c < -w, y w - c < 0 es w < c. Dan lo mismo porque una suma
   redondeada tiene el signo de la exacta (una suma de floats distinta de cero es múltiplo de 2^-149 y no se
   redondea a 0; x + -x da +0; el desbordamiento conserva el signo), y con un NaN las dos son falsas. Una
   comparación en vez de una suma y una comparación: con float por software es lo más caro del vértice. */
unsigned int mgr_outcode(const mgl_vec4_t *v) {
    mgl_real_t w = v->w, nw = -v->w;
    unsigned int code = 0;
    if (v->z < nw) code |= 1U;  /* cercano */
    if (w < v->z) code |= 2U;   /* lejano */
    if (v->x < nw) code |= 4U;  /* izquierdo */
    if (w < v->x) code |= 8U;   /* derecho */
    if (v->y < nw) code |= 16U; /* inferior */
    if (w < v->y) code |= 32U;  /* superior */
    return code;
}

/* El punto de la arista de inside (dentro) a outside (fuera) que está en el
   plano k. Siempre desde el vértice de dentro: el resultado no depende del
   sentido en que la recorra el triángulo. */
static void intersect(int k, const mgl_vec4_t *inside, const mgl_vec4_t *outside, mgl_vec4_t *out) {
    mgl_real_t di = dist(k, inside), d_o = dist(k, outside), t = di / (di - d_o);
    out->x = inside->x + (outside->x - inside->x) * t;
    out->y = inside->y + (outside->y - inside->y) * t;
    out->z = inside->z + (outside->z - inside->z) * t;
    out->w = inside->w + (outside->w - inside->w) * t;
}

int mgr_clip_triangle(const mgl_vec4_t in[3], mgl_vec4_t out[MGR_CLIP_MAX]) {
    mgl_vec4_t buffer[2][MGR_CLIP_MAX];
    const mgl_vec4_t *src;
    mgl_vec4_t *dst;
    int n = 3, k, i, m, which = 0;
    unsigned int all = 0;
    for (i = 0; i < 3; i++) {
        buffer[0][i] = in[i];
        all |= mgr_outcode(&in[i]);
    }
    /* El polígono no sale de la envolvente convexa del triángulo: si ningún
       vértice original está fuera de un plano, los cortes tampoco. */
    for (k = 0; k < PLANES; k++) {
        if (!(all & (1U << k))) continue;
        src = buffer[which];
        dst = buffer[which ^ 1];
        m = 0;
        for (i = 0; i < n; i++) {
            const mgl_vec4_t *a = &src[i], *b = &src[(i + 1) % n];
            int a_in = dist(k, a) >= 0.0f, b_in = dist(k, b) >= 0.0f;
            if (a_in) dst[m++] = *a;
            if (a_in != b_in) intersect(k, a_in ? a : b, a_in ? b : a, &dst[m++]);
        }
        which ^= 1;
        n = m;
        if (n < 3) return 0;
    }
    for (i = 0; i < n; i++) out[i] = buffer[which][i];
    return n;
}
