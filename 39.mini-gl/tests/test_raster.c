/* Rasterización (raster3d.c): cobertura y regla top-left, sin huecos ni dobles
   en aristas compartidas; viewport; prueba y escritura de profundidad
   (fragment.c); culling; y comandos 2D y 3D intercalados. */
#include "fixture3d.h"
#include "mgr_stages.h"
#include <string.h>

static mgl_color_t local[T_W * T_H];
static int counts[T_W * T_H];

static mgr_window_vertex_t wv(mgl_s32 x, mgl_s32 y) {
    mgr_window_vertex_t v;
    v.x = x;
    v.y = y;
    v.z = 0.5f;
    return v;
}

/* Rasteriza un triángulo en local[] (sin profundidad) y suma 1 en counts[] por píxel cubierto. */
static mgl_s32 raster_count(mgr_window_vertex_t a, mgr_window_vertex_t b, mgr_window_vertex_t c) {
    mgr_fragment_t f;
    mgr_rect_t clip;
    mgl_s32 n;
    int i;
    memset(local, 0, sizeof local);
    f.color = local;
    f.depth = 0;
    f.color_stride = T_W;
    f.depth_stride = 0;
    f.flags = 0;
    f.fill = 1;
    clip.x0 = clip.y0 = 0;
    clip.x1 = T_W;
    clip.y1 = T_H;
    n = mgr_raster_triangle(&a, &b, &c, &clip, &f);
    for (i = 0; i < T_W * T_H; i++) counts[i] += local[i];
    return n;
}

#define P(i) ((i) * MGR_SUBPIXEL + MGR_SUBPIXEL / 2) /* centro del píxel i */

static void test_top_left(void) {
    mgl_s32 a, b;
    int x, y, ok = 1;
    memset(counts, 0, sizeof counts);
    /* Cuadrado de píxeles [0, 10) partido por la diagonal, con los vértices en centros de píxel:
       las aristas pasan exactamente por centros. Arriba e izquierda cuentan; abajo y derecha, no. */
    a = raster_count(wv(P(0), P(0)), wv(P(10), P(0)), wv(P(0), P(10)));
    b = raster_count(wv(P(10), P(0)), wv(P(10), P(10)), wv(P(0), P(10)));
    CHECK(a == 55 && b == 45);
    for (y = 0; y < T_H; y++)
        for (x = 0; x < T_W; x++)
            if (counts[y * T_W + x] != (x < 10 && y < 10)) ok = 0;
    CHECK(ok);
    /* El mismo cuadrado con los vértices en esquinas de píxel: 100 píxeles, ninguna arista toca centros */
    memset(counts, 0, sizeof counts);
    a = raster_count(wv(0, 0), wv(160, 0), wv(160, 160));
    b = raster_count(wv(0, 0), wv(160, 160), wv(0, 160));
    CHECK(a + b == 100);
    /* El orden de los vértices no cambia nada */
    memset(counts, 0, sizeof counts);
    a = raster_count(wv(P(0), P(0)), wv(P(0), P(10)), wv(P(10), P(0)));
    CHECK(a == 55);
    /* Área nula */
    CHECK(raster_count(wv(0, 0), wv(80, 80), wv(160, 160)) == -1);
}

/* Un polígono convexo con vértices en posiciones arbitrarias de subpíxel, en
   abanico desde un punto interior: cada píxel una vez como mucho, y cubiertos
   todos los que tienen el centro estrictamente dentro. */
static void test_fan_watertight(void) {
    static const mgl_s32 px[] = {37, 401, 893, 950, 701, 260, 21};
    static const mgl_s32 py[] = {121, 18, 89, 459, 731, 702, 397};
    const int n = 7;
    mgr_window_vertex_t center = wv(477, 363);
    int i, j, x, y, twice = 0, missing = 0, inside, total = 0;
    double e;
    memset(counts, 0, sizeof counts);
    for (i = 0; i < n; i++)
        raster_count(center, wv(px[i], py[i]), wv(px[(i + 1) % n], py[(i + 1) % n]));
    for (y = 0; y < T_H; y++)
        for (x = 0; x < T_W; x++) {
            if (counts[y * T_W + x] > 1) twice++;
            inside = 1;
            for (j = 0; j < n; j++) {
                double ax = px[j], ay = py[j], bx = px[(j + 1) % n], by = py[(j + 1) % n];
                e = (bx - ax) * (P(y) - ay) - (by - ay) * (P(x) - ax);
                if (e <= 0) inside = 0; /* el polígono va en sentido horario en pantalla */
            }
            if (inside && counts[y * T_W + x] != 1) missing++;
            total += inside;
        }
    CHECK(twice == 0 && missing == 0);
    CHECK(total > 1500); /* que la prueba de dentro no sea trivial (el polígono ocupa unos 2000 píxeles) */
}

/* Un cuadrado de pantalla completa (dos triángulos) a profundidad z en NDC. */
static void quad(mgl_u32 offset, float z, mgl_color_t c) {
    mgl_set_color(c);
    t_triangle(offset, -1.0f, -1.0f, z, 1.0f, -1.0f, z, 1.0f, 1.0f, z);
    t_triangle(offset + 64, -1.0f, -1.0f, z, 1.0f, 1.0f, z, -1.0f, 1.0f, z);
}

static void test_viewport(void) {
    int x, y, ok = 1;
    t_init(4096);
    t_begin();
    mgl_clear(0);
    mgl_set_viewport(16, 8, 32, 24);
    quad(0, 0.0f, 0xffff);
    CHECK(t_end_and_run() == MGR_OK);
    for (y = 0; y < T_H; y++)
        for (x = 0; x < T_W; x++)
            if ((t_pixel(x, y) == 0xffff) != (x >= 16 && x < 48 && y >= 8 && y < 32)) ok = 0;
    CHECK(ok);
    /* Viewport que se sale del destino: se recorta al destino */
    t_begin();
    mgl_clear(0);
    mgl_set_viewport(-40, 30, 200, 100);
    quad(0, 0.0f, 0xffff);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0xffff) == T_W * (T_H - 30));
}

static void test_depth(void) {
    t_init(4096);
    /* El cercano primero o el lejano primero: gana el cercano */
    t_begin();
    mgl_clear(0);
    mgl_set_depth_test(1);
    quad(0, -0.5f, 0x001f);
    quad(256, 0.5f, 0xf800);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0x001f) == T_W * T_H);
    /* z = -0.5 en NDC es 0.25 en ventana: 0.25 * 65535 */
    CHECK(t_depth(5, 5) >= 16383 && t_depth(5, 5) <= 16385);
    t_begin();
    mgl_clear(0);
    quad(0, 0.5f, 0xf800);
    quad(256, -0.5f, 0x001f);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0x001f) == T_W * T_H);
    /* Sin prueba: el último */
    t_begin();
    mgl_clear(0);
    mgl_set_depth_test(0);
    quad(0, -0.5f, 0x001f);
    quad(256, 0.5f, 0xf800);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0xf800) == T_W * T_H);
    /* Prueba sin escritura: el cercano no deja profundidad y el lejano pasa */
    t_begin();
    mgl_clear(0);
    mgl_set_depth_test(1);
    mgl_set_depth_write(0);
    quad(0, -0.5f, 0x001f);
    quad(256, 0.5f, 0xf800);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0xf800) == T_W * T_H && t_depth(3, 3) == 65535);
    /* Profundidad borrada a 0: nada pasa LESS */
    t_begin();
    mgl_set_depth_write(1);
    mgl_clear_color_depth(0x1234, 0.0f);
    quad(0, -0.9f, 0x001f);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0x1234) == T_W * T_H && t_depth(0, 0) == 0);
    /* Solo profundidad: el color de antes se queda y el cuadrado lejano pasa */
    t_begin();
    mgl_clear_depth(1.0f);
    quad(0, 0.5f, 0x001f);
    quad(256, 0.9f, 0xf800);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0x001f) == T_W * T_H && t_depth(0, 0) < 65535);
    t_begin();
    mgl_clear_depth(1.0f);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0x001f) == T_W * T_H && t_depth(0, 0) == 65535);
    /* Plano inclinado: la profundidad crece de izquierda a derecha y está en [0, 65535] */
    t_begin();
    mgl_clear(0);
    mgl_set_color(0xffff);
    t_triangle(0, -1.0f, -1.0f, -1.0f, 1.0f, -1.0f, 1.0f, 1.0f, 1.0f, 1.0f);
    t_triangle(64, -1.0f, -1.0f, -1.0f, 1.0f, 1.0f, 1.0f, -1.0f, 1.0f, -1.0f);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_depth(0, 20) < 1100 && t_depth(T_W - 1, 20) > 64400);
    CHECK(t_depth(10, 20) < t_depth(11, 20) && t_depth(40, 5) < t_depth(41, 5));
    mgl_set_depth_test(0);
}

static void test_cull(void) {
    t_init(4096);
    /* Antihorario en NDC (y hacia arriba): de frente */
    t_begin();
    mgl_clear(0);
    mgl_set_cull(MGL_CULL_BACK);
    t_triangle(0, -0.5f, -0.5f, 0.0f, 0.5f, -0.5f, 0.0f, 0.0f, 0.5f, 0.0f);
    t_triangle(64, -0.5f, -0.5f, 0.0f, 0.0f, 0.5f, 0.0f, 0.5f, -0.5f, 0.0f);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_rnd.stats.rasterized == 1U && t_rnd.stats.culled == 1U && t_count(0xffff) > 0);
    mgr_reset_stats(&t_rnd);
    t_begin();
    mgl_clear(0);
    mgl_set_cull(MGL_CULL_FRONT);
    t_triangle(0, -0.5f, -0.5f, 0.0f, 0.5f, -0.5f, 0.0f, 0.0f, 0.5f, 0.0f);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_rnd.stats.culled == 1U && t_count(0xffff) == 0);
    mgl_set_cull(MGL_CULL_NONE);
}

/* 2D y 3D en el mismo buffer, en orden; lo 2D no mira la profundidad. */
static void test_interleaved(void) {
    t_init(4096);
    t_begin();
    mgl_clear(0);
    mgl_fill(0xf800);
    mgl_no_stroke();
    mgl_rect(0, 0, T_W, T_H); /* 2D: todo rojo */
    mgl_set_depth_test(1);
    quad(0, -0.9f, 0x001f);   /* 3D: azul, muy cerca */
    mgl_fill(0x07e0);
    mgl_rect(10, 10, 5, 5);   /* 2D encima: verde aunque el azul esté más cerca */
    mgl_set_viewport(0, 0, T_W / 2, T_H);
    quad(256, 0.9f, 0xffff);  /* 3D lejos: no pasa la prueba */
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0x07e0) == 25 && t_pixel(12, 12) == 0x07e0);
    CHECK(t_count(0x001f) == T_W * T_H - 25 && t_count(0xffff) == 0);
    mgl_set_depth_test(0);
}

int main(void) {
    test_top_left();
    test_fan_watertight();
    test_viewport();
    test_depth();
    test_cull();
    test_interleaved();
    return t_report("test_raster: cobertura, top-left, viewport, profundidad, culling y 2D/3D");
}
