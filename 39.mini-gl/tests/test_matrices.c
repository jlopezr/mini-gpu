/* mgl_math: funciones, multiplicación y composición de matrices, convención
   column-major, y transformación de vértices leídos de la RAM (transform.c). */
#include "fixture3d.h"
#include "mgr_stages.h"
#include <math.h>

#define NEAR(a, b, eps) (fabs((double)(a) - (double)(b)) <= (eps))

static void check_point(const mgl_mat4_t *m, float x, float y, float z, float ex, float ey, float ez,
    float ew, double eps) {
    mgl_vec4_t v;
    mgl_mat4_transform_point(m, x, y, z, &v);
    CHECK(NEAR(v.x, ex, eps) && NEAR(v.y, ey, eps) && NEAR(v.z, ez, eps) && NEAR(v.w, ew, eps));
    if (!(NEAR(v.x, ex, eps) && NEAR(v.y, ey, eps) && NEAR(v.z, ez, eps) && NEAR(v.w, ew, eps)))
        printf("  (%g, %g, %g) -> (%g, %g, %g, %g), esperado (%g, %g, %g, %g)\n", x, y, z, v.x, v.y, v.z,
            v.w, ex, ey, ez, ew);
}

static void test_functions(void) {
    double a, worst_sin = 0, worst_cos = 0;
    for (a = -20.0; a <= 20.0; a += 0.001) {
        double es = fabs(mgl_sin((float)a) - sin((double)(float)a));
        double ec = fabs(mgl_cos((float)a) - cos((double)(float)a));
        if (es > worst_sin) worst_sin = es;
        if (ec > worst_cos) worst_cos = ec;
    }
    CHECK(worst_sin < 2e-6 && worst_cos < 2e-6);
    CHECK(mgl_sin(0.0f) == 0.0f);
    CHECK(NEAR(mgl_sqrt(2.0f), 1.41421356, 1e-6) && NEAR(mgl_sqrt(1e6f), 1000.0, 1e-3));
    CHECK(NEAR(mgl_sqrt(0.0001f), 0.01, 1e-8) && mgl_sqrt(-1.0f) == 0.0f);
    CHECK(mgl_round(2.5f) == 3 && mgl_round(-2.5f) == -3 && mgl_round(2.49f) == 2 && mgl_round(-0.4f) == 0);
    CHECK(mgl_round(1e20f) == 2147483647 && mgl_round(-1e20f) == -2147483647);
    CHECK(mgl_real_to_f32(1.0f) == 0x3F800000U && mgl_real_from_f32(0xC0000000U) == -2.0f);
}

static void test_mul(void) {
    mgl_mat4_t a, b, c, id, ab_c, a_bc;
    int i;
    for (i = 0; i < 16; i++) {
        a.m[i] = (float)(i + 1);
        b.m[i] = (float)(16 - i) * 0.5f;
        c.m[i] = (float)((i * 7) % 5) - 2.0f;
    }
    mgl_mat4_identity(&id);
    mgl_mat4_mul(&ab_c, &a, &id);
    for (i = 0; i < 16; i++) CHECK(ab_c.m[i] == a.m[i]);
    mgl_mat4_mul(&ab_c, &id, &a);
    for (i = 0; i < 16; i++) CHECK(ab_c.m[i] == a.m[i]);
    /* column-major: (a * b)[fila 0, columna 0] = sum_k a[0][k] * b[k][0] = a.m[k*4] * b.m[k] */
    mgl_mat4_mul(&ab_c, &a, &b);
    CHECK(ab_c.m[0] == a.m[0] * b.m[0] + a.m[4] * b.m[1] + a.m[8] * b.m[2] + a.m[12] * b.m[3]);
    /* asociativa (enteros pequeños: exacta) */
    mgl_mat4_mul(&ab_c, &ab_c, &c);
    mgl_mat4_mul(&a_bc, &b, &c);
    mgl_mat4_mul(&a_bc, &a, &a_bc);
    for (i = 0; i < 16; i++) CHECK(ab_c.m[i] == a_bc.m[i]);
}

static void test_transforms(void) {
    mgl_mat4_t m, t, r;
    mgl_vec4_t v;
    float near_z = 2.0f, far_z = 50.0f;
    mgl_mat4_translation(&m, 1.0f, 2.0f, 3.0f);
    CHECK(m.m[12] == 1.0f && m.m[13] == 2.0f && m.m[14] == 3.0f); /* traslación en la última columna */
    check_point(&m, 1.0f, 1.0f, 1.0f, 2.0f, 3.0f, 4.0f, 1.0f, 0.0);
    mgl_mat4_scaling(&m, 2.0f, 3.0f, 4.0f);
    check_point(&m, 1.0f, 1.0f, 1.0f, 2.0f, 3.0f, 4.0f, 1.0f, 0.0);
    /* rotaciones de 90 grados, mano derecha */
    mgl_mat4_rotation_x(&m, 1.57079633f);
    check_point(&m, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 1.0f, 1e-6);
    mgl_mat4_rotation_y(&m, 1.57079633f);
    check_point(&m, 0.0f, 0.0f, 1.0f, 1.0f, 0.0f, 0.0f, 1.0f, 1e-6);
    check_point(&m, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, -1.0f, 1.0f, 1e-6);
    mgl_mat4_rotation_z(&m, 1.57079633f);
    check_point(&m, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 1.0f, 1e-6);
    /* Composición por la derecha: T * R gira primero y traslada después */
    mgl_mat4_translation(&t, 10.0f, 0.0f, 0.0f);
    mgl_mat4_rotate_z_by(&t, 1.57079633f);
    check_point(&t, 1.0f, 0.0f, 0.0f, 10.0f, 1.0f, 0.0f, 1.0f, 1e-5);
    mgl_mat4_identity(&m);
    mgl_mat4_translate_by(&m, 10.0f, 0.0f, 0.0f);
    mgl_mat4_rotate_z_by(&m, 1.57079633f);
    mgl_mat4_scale_by(&m, 2.0f, 2.0f, 2.0f);
    check_point(&m, 1.0f, 0.0f, 0.0f, 10.0f, 2.0f, 0.0f, 1.0f, 1e-5);
    mgl_mat4_rotation_z(&r, 1.57079633f);
    mgl_mat4_mul(&r, &r, &t); /* R * T: traslada y luego gira */
    check_point(&r, 0.0f, 0.0f, 0.0f, 0.0f, 10.0f, 0.0f, 1.0f, 1e-5);
    /* Perspectiva: z = -near va a -1 y z = -far a +1 tras dividir por w */
    mgl_mat4_perspective(&m, 1.04719755f, 1.0f, near_z, far_z);
    mgl_mat4_transform_point(&m, 0.0f, 0.0f, -near_z, &v);
    CHECK(NEAR(v.z / v.w, -1.0, 1e-6) && NEAR(v.w, near_z, 1e-6));
    mgl_mat4_transform_point(&m, 0.0f, 0.0f, -far_z, &v);
    CHECK(NEAR(v.z / v.w, 1.0, 1e-5));
    /* el borde del campo vertical (30 grados por encima del eje) va a y = 1 */
    mgl_mat4_transform_point(&m, 0.0f, 0.577350269f * 10.0f, -10.0f, &v);
    CHECK(NEAR(v.y / v.w, 1.0, 1e-5));
    /* look_at: el ojo al origen, el centro sobre -z, up sobre +y */
    mgl_mat4_look_at(&m, 5.0f, 5.0f, 5.0f, 5.0f, 5.0f, 0.0f, 0.0f, 1.0f, 0.0f);
    check_point(&m, 5.0f, 5.0f, 5.0f, 0.0f, 0.0f, 0.0f, 1.0f, 1e-5);
    check_point(&m, 5.0f, 5.0f, 0.0f, 0.0f, 0.0f, -5.0f, 1.0f, 1e-5);
    check_point(&m, 5.0f, 6.0f, 5.0f, 0.0f, 1.0f, 0.0f, 1.0f, 1e-5);
    check_point(&m, 6.0f, 5.0f, 5.0f, 1.0f, 0.0f, 0.0f, 1.0f, 1e-5);
}

/* transform.c: lee posiciones little-endian con stride de la RAM y aplica la matriz. */
static void test_vertex_fetch(void) {
    static const float xyz[9] = {1.0f, 2.0f, 3.0f, 99.0f, -4.0f, 0.5f, 8.0f, 99.0f, 0.0f};
    static const unsigned short idx[3] = {0, 1, 0};
    mgr_vertices_t v;
    mgl_mesh_desc_t d;
    mgl_mat4_t m;
    mgl_vec4_t out;
    mgl_mesh_t mesh;
    t_init(4096);
    /* dos vértices con stride 16: el cuarto float de cada uno no es de la posición */
    mesh = t_mesh(0, xyz, 3, idx, 3); /* escribe los 9 floats seguidos: 36 bytes >= 2 * 16 */
    CHECK(mgl_mesh_info(mesh, &d) == MGL_OK);
    v.base = (const unsigned char *)mgl_memory_ptr(&t_mem, d.vertex_addr, 32, 4);
    v.stride = 16;
    v.count = 2;
    mgl_mat4_translation(&m, 10.0f, 20.0f, 30.0f);
    mgr_transform_vertex(&v, 0, &m, &out);
    CHECK(out.x == 11.0f && out.y == 22.0f && out.z == 33.0f && out.w == 1.0f);
    mgr_transform_vertex(&v, 1, &m, &out);
    CHECK(out.x == 6.0f && out.y == 20.5f && out.z == 38.0f && out.w == 1.0f);
}

/* El MVP del renderer es Projection * View * Model. */
static void test_mvp_order(void) {
    mgr_state_t s;
    mgl_vec4_t v;
    mgr_state_reset(&s);
    mgl_mat4_translation(&s.matrix[MGL_MATRIX_MODEL - 1], 1.0f, 0.0f, 0.0f);
    mgl_mat4_rotation_z(&s.matrix[MGL_MATRIX_VIEW - 1], 1.57079633f);
    mgl_mat4_scaling(&s.matrix[MGL_MATRIX_PROJECTION - 1], 2.0f, 3.0f, 1.0f);
    s.mvp_dirty = 1;
    mgl_mat4_transform_point(mgr_state_mvp(&s), 0.0f, 0.0f, 0.0f, &v);
    /* (0,0,0) -> modelo (1,0,0) -> vista (0,1,0) -> proyección (0,3,0) */
    CHECK(NEAR(v.x, 0.0, 1e-6) && NEAR(v.y, 3.0, 1e-6));
}

int main(void) {
    test_functions();
    test_mul();
    test_transforms();
    test_vertex_fetch();
    test_mvp_order();
    return t_report("test_matrices: funciones, multiplicación, composición y transformación de vértices");
}
