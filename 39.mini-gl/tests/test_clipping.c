/* Recorte en coordenadas homogéneas (clipping.c), sobre todo contra el plano
   cercano, y de extremo a extremo: un suelo que pasa por detrás de la cámara. */
#include "fixture3d.h"
#include "mgr_stages.h"
#include "mgl_bytes.h"
#include <string.h>

#define EPS 1e-5f

static mgl_vec4_t vec(float x, float y, float z, float w) {
    mgl_vec4_t v;
    v.x = x;
    v.y = y;
    v.z = z;
    v.w = w;
    return v;
}

/* Todos dentro del volumen (con margen de redondeo). */
static int all_inside(const mgl_vec4_t *v, int n) {
    int i;
    for (i = 0; i < n; i++)
        if (v[i].w + v[i].z < -EPS || v[i].w - v[i].z < -EPS || v[i].w + v[i].x < -EPS ||
            v[i].w - v[i].x < -EPS || v[i].w + v[i].y < -EPS || v[i].w - v[i].y < -EPS || !(v[i].w > 0.0f))
            return 0;
    return 1;
}

static int same(const mgl_vec4_t *a, const mgl_vec4_t *b) {
    return mgl_real_to_f32(a->x) == mgl_real_to_f32(b->x) && mgl_real_to_f32(a->y) == mgl_real_to_f32(b->y) &&
        mgl_real_to_f32(a->z) == mgl_real_to_f32(b->z) && mgl_real_to_f32(a->w) == mgl_real_to_f32(b->w);
}

/* El vértice de out que está sobre el plano cercano (z = -w), o -1. */
static int on_near(const mgl_vec4_t *v, int n, int skip) {
    int i;
    for (i = 0; i < n; i++)
        if (i != skip && v[i].z + v[i].w > -EPS && v[i].z + v[i].w < EPS) return i;
    return -1;
}

static void test_near(void) {
    mgl_vec4_t in[3], out[MGR_CLIP_MAX], out2[MGR_CLIP_MAX];
    int n, n2, i, j, k, found;
    /* Dentro: sale igual */
    in[0] = vec(-0.5f, -0.5f, 0.0f, 1.0f);
    in[1] = vec(0.5f, -0.5f, 0.5f, 1.0f);
    in[2] = vec(0.0f, 0.5f, -0.5f, 1.0f);
    CHECK(mgr_outcode(&in[0]) == 0 && mgr_outcode(&in[1]) == 0 && mgr_outcode(&in[2]) == 0);
    n = mgr_clip_triangle(in, out);
    CHECK(n == 3 && same(&out[0], &in[0]) && same(&out[1], &in[1]) && same(&out[2], &in[2]));

    /* Un vértice detrás del plano cercano (z < -w): un cuadrilátero */
    in[2] = vec(0.0f, 0.5f, -3.0f, 1.0f);
    CHECK(mgr_outcode(&in[2]) == 1U);
    n = mgr_clip_triangle(in, out);
    CHECK(n == 4 && all_inside(out, n));
    i = on_near(out, n, -1);
    CHECK(i >= 0 && on_near(out, n, i) >= 0); /* dos puntos nuevos sobre el plano */
    /* El corte de la arista (in[1], in[2]) es el punto a t = 1.5 / 3.5 desde in[1] */
    found = 0;
    for (k = 0; k < n; k++)
        if (out[k].z + out[k].w > -EPS && out[k].z + out[k].w < EPS && out[k].x > 0.0f) {
            CHECK(out[k].x > 0.5f - 0.5f * 1.5f / 3.5f - EPS && out[k].x < 0.5f - 0.5f * 1.5f / 3.5f + EPS);
            found = 1;
        }
    CHECK(found);

    /* Dos vértices detrás: un triángulo más pequeño */
    in[0] = vec(-0.5f, -0.5f, -2.0f, 1.0f);
    n = mgr_clip_triangle(in, out);
    CHECK(n == 3 && all_inside(out, n));
    CHECK(same(&out[0], &in[1]) || same(&out[1], &in[1]) || same(&out[2], &in[1])); /* el que estaba dentro */

    /* Los tres detrás: nada */
    in[1] = vec(0.5f, -0.5f, -5.0f, 1.0f);
    CHECK(mgr_clip_triangle(in, out) == 0);

    /* w negativo (detrás del ojo con perspectiva): se recorta igual, sin dividir por w */
    in[0] = vec(0.0f, 0.0f, 0.5f, 1.0f);
    in[1] = vec(0.2f, 0.0f, 0.5f, 1.0f);
    in[2] = vec(0.0f, 0.3f, 2.0f, -2.0f);
    n = mgr_clip_triangle(in, out);
    CHECK(n == 4 && all_inside(out, n));

    /* Arista compartida: los dos triángulos dan el mismo punto de corte, bit a bit */
    in[0] = vec(-0.3f, 0.1f, 0.2f, 1.0f);
    in[1] = vec(0.4f, -0.2f, -2.7f, 1.0f); /* fuera */
    in[2] = vec(0.6f, 0.7f, 0.1f, 1.0f);
    n = mgr_clip_triangle(in, out);
    {
        mgl_vec4_t other[3];
        other[0] = in[1]; /* la arista (in[0], in[1]) al revés */
        other[1] = in[0];
        other[2] = vec(-0.8f, -0.6f, 0.3f, 1.0f);
        n2 = mgr_clip_triangle(other, out2);
    }
    found = 0;
    for (i = 0; i < n; i++)
        for (j = 0; j < n2; j++)
            if (same(&out[i], &out2[j]) && out[i].z + out[i].w < EPS) found++;
    CHECK(found == 1);
}

/* Fuera de varios planos a la vez: hasta 3 + 6 vértices, todos dentro. */
static void test_many_planes(void) {
    mgl_vec4_t in[3], out[MGR_CLIP_MAX];
    int n;
    in[0] = vec(-3.0f, -3.0f, 0.0f, 1.0f);
    in[1] = vec(3.0f, -3.0f, 0.0f, 1.0f);
    in[2] = vec(0.0f, 4.0f, 0.0f, 1.0f);
    n = mgr_clip_triangle(in, out); /* contiene entero el cuadrado de visión: queda el cuadrado */
    CHECK(n == 4 && all_inside(out, n));
    /* Sale por los cuatro lados sin contener el cuadrado: más de 4 vértices */
    in[0] = vec(-1.6f, -0.2f, 0.0f, 1.0f);
    in[1] = vec(1.6f, -1.4f, 0.0f, 1.0f);
    in[2] = vec(0.6f, 2.2f, 0.0f, 1.0f);
    n = mgr_clip_triangle(in, out);
    CHECK(n > 4 && n <= MGR_CLIP_MAX && all_inside(out, n));
    in[0] = vec(-3.0f, -3.0f, -3.0f, 1.0f);
    in[1] = vec(3.0f, -3.0f, 3.0f, 1.0f);
    in[2] = vec(0.0f, 4.0f, 0.0f, 1.0f);
    n = mgr_clip_triangle(in, out);
    CHECK(n >= 3 && n <= MGR_CLIP_MAX && all_inside(out, n));
    /* Fuera de un mismo plano: lo descarta draw.c sin recortar (outcode común) */
    in[0] = vec(2.0f, 0.0f, 0.0f, 1.0f);
    in[1] = vec(3.0f, 1.0f, 0.0f, 1.0f);
    in[2] = vec(2.5f, -1.0f, 0.0f, 1.0f);
    CHECK((mgr_outcode(&in[0]) & mgr_outcode(&in[1]) & mgr_outcode(&in[2])) != 0);
}

/* Un suelo (y = -1) que va de detrás de la cámara (z = +5, w < 0) hasta z = -50.
   Los dos triángulos cruzan el plano cercano: si se descartaran en vez de
   recortarse, no se vería nada. Con recorte cubre la mitad de abajo de la
   pantalla, entera desde la fila de abajo hasta casi el horizonte, y nada encima. */
static void test_floor(void) {
    static const float floor_xyz[12] = {-20.0f, -1.0f, 5.0f, 20.0f, -1.0f, 5.0f, 20.0f, -1.0f, -50.0f,
        -20.0f, -1.0f, -50.0f};
    static const unsigned short floor_idx[6] = {0, 1, 2, 0, 2, 3};
    mgl_mat4_t proj, id;
    mgl_mesh_t mesh;
    int x, y, row_full, above = 0, bottom_rows = 1;
    t_init(4096);
    mesh = t_mesh(0, floor_xyz, 4, floor_idx, 6);
    mgl_mat4_perspective(&proj, 1.04719755f, (float)T_W / (float)T_H, 1.0f, 100.0f);
    mgl_mat4_identity(&id);
    t_begin();
    mgl_clear(0);
    mgl_set_matrix(MGL_MATRIX_PROJECTION, &proj);
    mgl_set_matrix(MGL_MATRIX_VIEW, &id);
    mgl_set_matrix(MGL_MATRIX_MODEL, &id);
    mgl_set_depth_test(1);
    mgl_set_color(0x07e0);
    mgl_draw_mesh(mesh);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_rnd.stats.triangles == 2U && t_rnd.stats.clipped == 2U && t_rnd.stats.rasterized >= 2U);
    for (y = 0; y < T_H / 2; y++)
        for (x = 0; x < T_W; x++)
            if (t_pixel(x, y)) above++;
    CHECK(above == 0);
    for (y = T_H - 1; y > T_H / 2 + 1; y--) {
        row_full = 1;
        for (x = 0; x < T_W; x++)
            if (t_pixel(x, y) != 0x07e0) row_full = 0;
        if (!row_full) bottom_rows = 0;
    }
    CHECK(bottom_rows); /* de la fila de abajo hasta dos por debajo del horizonte, todas enteras */
}

int main(void) {
    test_near();
    test_many_planes();
    test_floor();
    return t_report("test_clipping: plano cercano, varios planos, aristas compartidas y suelo");
}
