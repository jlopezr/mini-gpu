/* El cubo de MiniProcessing de extremo a extremo (platform3d + processing3d +
   MiniGL + renderer) en varios ángulos, contra una proyección independiente en
   double; el command buffer de un frame de Processing; y reproducción de un
   command buffer guardado. */
#include "context3d.h"
#include "mgl_bytes.h"
#include "../examples/tie_fighter_shape.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
#define CHECK(c)                                                          \
    do {                                                                  \
        if (!(c)) {                                                       \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);           \
            failures++;                                                   \
        }                                                                 \
    } while (0)

#define W 320
#define H 240
#define ORANGE 0xFC65 /* color565(255, 140, 40) */
#define BG 0x10A2     /* color565(20, 20, 20) */

static void draw_cube(float angle) {
    background(20, 20, 20);
    translate(160, 120, 0);
    rotateX(angle * 0.6f);
    rotateY(angle);
    fill(255, 140, 40);
    noStroke();
    box(100);
}

static int render(float angle) {
    if (context3d_begin(P3D_FB_A) != MGL_OK) return -1;
    draw_cube(angle);
    return context3d_end(0);
}

/* La silueta esperada: los 8 vértices con la cámara de Processing, en double.
   Con el ojo en z = e = 120 / tan(30°), un punto (x, y, z) cae en
   (160 + e (x - 160) / (e - z), 120 + e (y - 120) / (e - z)). */
static int hull(double angle, double *hx, double *hy) {
    double px[8], py[8], e = 120.0 / tan(3.14159265358979 / 6.0);
    double cx = cos(angle * 0.6), sx = sin(angle * 0.6), cy = cos(angle), sy = sin(angle);
    int i, n = 0, start = 0, p, q, r;
    for (i = 0; i < 8; i++) {
        double x = (i & 1 ? 50.0 : -50.0), y = (i & 2 ? 50.0 : -50.0), z = (i & 4 ? 50.0 : -50.0), t;
        t = cy * x + sy * z; /* rotateY */
        z = -sy * x + cy * z;
        x = t;
        t = cx * y - sx * z; /* rotateX */
        z = sx * y + cx * z;
        y = t;
        x += 160.0;
        y += 120.0;
        px[i] = 160.0 + e * (x - 160.0) / (e - z);
        py[i] = 120.0 + e * (y - 120.0) / (e - z);
    }
    for (i = 1; i < 8; i++)
        if (px[i] < px[start]) start = i;
    p = start; /* envolvente convexa por gift wrapping */
    do {
        hx[n] = px[p];
        hy[n] = py[p];
        n++;
        q = (p + 1) % 8;
        for (r = 0; r < 8; r++)
            if ((px[q] - px[p]) * (py[r] - py[p]) - (py[q] - py[p]) * (px[r] - px[p]) < 0) q = r;
        p = q;
    } while (p != start && n < 8);
    return n;
}

static void test_angles(void) {
    static const float angles[] = {0.0f, 0.3f, 1.0f, 2.2f, 4.0f, 5.5f};
    double hx[8], hy[8], area, perimeter, minx, maxx, miny, maxy;
    mgl_color_t *fb;
    int a, i, n, x, y, count, other, fminx, fmaxx, fminy, fmaxy;
    for (a = 0; a < (int)(sizeof angles / sizeof angles[0]); a++) {
        CHECK(render(angles[a]) == MGL_OK);
        fb = context3d_pixels(P3D_FB_A);
        count = other = 0;
        fminx = fminy = 10000;
        fmaxx = fmaxy = -1;
        for (y = 0; y < H; y++)
            for (x = 0; x < W; x++) {
                if (fb[y * W + x] == ORANGE) {
                    count++;
                    if (x < fminx) fminx = x;
                    if (x > fmaxx) fmaxx = x;
                    if (y < fminy) fminy = y;
                    if (y > fmaxy) fmaxy = y;
                } else if (fb[y * W + x] != BG)
                    other++;
            }
        n = hull(angles[a], hx, hy);
        area = perimeter = 0.0;
        minx = miny = 1e9;
        maxx = maxy = -1e9;
        for (i = 0; i < n; i++) {
            int j = (i + 1) % n;
            area += hx[i] * hy[j] - hx[j] * hy[i];
            perimeter += sqrt((hx[j] - hx[i]) * (hx[j] - hx[i]) + (hy[j] - hy[i]) * (hy[j] - hy[i]));
            if (hx[i] < minx) minx = hx[i];
            if (hx[i] > maxx) maxx = hx[i];
            if (hy[i] < miny) miny = hy[i];
            if (hy[i] > maxy) maxy = hy[i];
        }
        area = fabs(area) * 0.5;
        printf("  ángulo %.1f: %d píxeles, silueta %.1f (perímetro %.0f), caja x %d..%d (%.1f..%.1f) "
               "y %d..%d (%.1f..%.1f)\n",
            angles[a], count, area, perimeter, fminx, fmaxx, minx, maxx, fminy, fmaxy, miny, maxy);
        CHECK(other == 0);
        /* Cada píxel con el centro dentro: la diferencia con el área es de borde, menos de medio perímetro */
        CHECK(fabs((double)count - area) < perimeter * 0.5);
        /* La caja, a 2 píxeles: junto a un vértice agudo la silueta es una cuña más estrecha que un
           píxel y la primera fila (o columna) con un centro dentro puede quedar algo más lejos */
        CHECK(fabs(fminx + 0.5 - minx) <= 2.0 && fabs(fmaxx + 0.5 - maxx) <= 2.0);
        CHECK(fabs(fminy + 0.5 - miny) <= 2.0 && fabs(fmaxy + 0.5 - maxy) <= 2.0);
    }
    /* De frente: la cara de delante (z = 50) es un cuadrado de 100 * e / (e - 50) = 131.7 píxeles */
    CHECK(render(0.0f) == MGL_OK);
    fb = context3d_pixels(P3D_FB_A);
    count = 0;
    for (x = 0; x < W; x++)
        if (fb[120 * W + x] == ORANGE) count++;
    CHECK(count == 131 || count == 132);
}

/* pushMatrix/popMatrix: tras volver de una pila más honda que P3D_MATRIX_STACK
   la matriz es la de antes, y el cubo sale igual que sin tocarla. */
static void test_matrix_stack(void) {
    static mgl_color_t expected[W * H];
    int i;
    CHECK(render(1.0f) == MGL_OK);
    memcpy(expected, context3d_pixels(P3D_FB_A), sizeof expected);
    CHECK(context3d_begin(P3D_FB_A) == MGL_OK);
    pushMatrix();
    translate(400, 0, 0);
    for (i = 0; i < P3D_MATRIX_STACK + 1; i++) pushMatrix();
    rotateX(1.0f);
    for (i = 0; i < P3D_MATRIX_STACK + 1; i++) popMatrix();
    popMatrix();
    popMatrix(); /* de más: no hace nada */
    draw_cube(1.0f);
    CHECK(context3d_end(0) == MGL_OK);
    CHECK(!memcmp(expected, context3d_pixels(P3D_FB_A), sizeof expected));
    /* perspective() con los valores de size() deja la misma proyección */
    perspective(3.14159265f / 3.0f, (float)W / H, 120.0f * 1.7320508f / 10.0f, 120.0f * 1.7320508f * 10.0f);
    CHECK(render(1.0f) == MGL_OK);
    CHECK(!memcmp(expected, context3d_pixels(P3D_FB_A), sizeof expected));
}

/* El frame de un sketch: el command buffer de docs/3d.md §12. */
static void test_frame_commands(void) {
    static const unsigned int expected[] = {MGL_CMD_SET_RENDER_TARGET, MGL_CMD_CLEAR,
        MGL_CMD_SET_VIEWPORT, MGL_CMD_SET_MATRIX, MGL_CMD_SET_MATRIX, MGL_CMD_SET_MATRIX,
        MGL_CMD_SET_RENDER_STATE, MGL_CMD_SET_COLOR, MGL_CMD_DRAW_INDEXED, MGL_CMD_END_FRAME};
    const unsigned char *b = context3d_commands.bytes, *p;
    mgl_u32 off;
    int i = 0;
    CHECK(render(1.0f) == MGL_OK);
    for (off = 16; off < context3d_commands.used; off += RD32(b + off + 4), i++) {
        p = b + off;
        CHECK(i < 10 && RD16(p) == expected[i]);
        if (RD16(p) == MGL_CMD_SET_RENDER_TARGET)
            CHECK(RD32(p + 8) == P3D_FB_A && RD32(p + 12) == P3D_DEPTH && RD16(p + 16) == W && RD16(p + 18) == H);
        if (RD16(p) == MGL_CMD_CLEAR)
            CHECK(RD16(p + 2) == MGL_CLEAR_DEPTH && RD32(p + 8) == BG && RD32(p + 12) == MGL_DEPTH_ONE);
        if (RD16(p) == MGL_CMD_SET_COLOR) CHECK(RD32(p + 8) == ORANGE);
        if (RD16(p) == MGL_CMD_DRAW_INDEXED)
            CHECK(RD32(p + 8) >= P3D_HEAP && RD32(p + 16) == 8U && RD32(p + 20) == 36U);
    }
    CHECK(i == 10);
}

/* Un command buffer guardado se reproduce igual: después de otros frames, dos
   veces seguidas y con un renderer nuevo (sin nada de lo anterior). */
static void test_replay(void) {
    static unsigned char saved[4096];
    static mgl_color_t first[W * H];
    mgl_u32 used;
    mgr_renderer_t fresh;
    mgl_color_t *fb = context3d_pixels(P3D_FB_A);
    unsigned char *commands = context3d_commands.bytes;
    CHECK(render(1.0f) == MGL_OK);
    used = context3d_commands.used;
    CHECK(used <= sizeof saved);
    memcpy(saved, commands, used);
    memcpy(first, fb, sizeof first);
    CHECK(render(2.2f) == MGL_OK);
    CHECK(memcmp(first, fb, sizeof first) != 0);
    memcpy(commands, saved, used);
    CHECK(mgr_execute(&context3d_renderer, P3D_COMMANDS) == MGR_OK);
    CHECK(memcmp(first, fb, sizeof first) == 0);
    CHECK(mgr_execute(&context3d_renderer, P3D_COMMANDS) == MGR_OK);
    CHECK(memcmp(first, fb, sizeof first) == 0);
    memset(fb, 0, sizeof first);
    CHECK(mgr_init(&fresh, &context3d_memory) == MGR_OK);
    CHECK(mgr_execute(&fresh, P3D_COMMANDS) == MGR_OK);
    CHECK(memcmp(first, fb, sizeof first) == 0);
}


/* ---- Cubo con una cara de cada color (beginShape(QUADS)) ------------------ */

static const int face_rgb[6][3] = {
    {230, 40, 40}, {40, 200, 60}, {40, 90, 230}, {240, 220, 40}, {40, 220, 220}, {220, 60, 220}};
/* Las cuatro esquinas de cada cara (+z, -z, +x, -x, +y, -y), en el orden de colored_cube.c. */
static const float face_xyz[6][4][3] = {
    {{-50, -50, 50}, {50, -50, 50}, {50, 50, 50}, {-50, 50, 50}},
    {{50, -50, -50}, {-50, -50, -50}, {-50, 50, -50}, {50, 50, -50}},
    {{50, -50, 50}, {50, -50, -50}, {50, 50, -50}, {50, 50, 50}},
    {{-50, -50, -50}, {-50, -50, 50}, {-50, 50, 50}, {-50, 50, -50}},
    {{-50, 50, 50}, {50, 50, 50}, {50, 50, -50}, {-50, 50, -50}},
    {{-50, -50, -50}, {50, -50, -50}, {50, -50, 50}, {-50, -50, 50}}};

static void draw_colored_cube(float angle) {
    int f, v;
    background(20, 20, 20);
    translate(160, 120, 0);
    rotateX(angle * 0.6f);
    rotateY(angle);
    noStroke();
    beginShape(QUADS);
    for (f = 0; f < 6; f++) {
        fill(face_rgb[f][0], face_rgb[f][1], face_rgb[f][2]);
        for (v = 0; v < 4; v++) vertex(face_xyz[f][v][0], face_xyz[f][v][1], face_xyz[f][v][2]);
    }
    endShape();
}

/* Un punto del cubo girado como en el sketch, en el mundo (double). */
static void world(double angle, const float *p, double *out) {
    double cx = cos(angle * 0.6), sx = sin(angle * 0.6), cy = cos(angle), sy = sin(angle);
    double x = p[0], y = p[1], z = p[2], t;
    t = cy * x + sy * z; /* rotateY */
    z = -sy * x + cy * z;
    x = t;
    t = cx * y - sx * z; /* rotateX */
    z = sx * y + cx * z;
    y = t;
    out[0] = x + 160.0;
    out[1] = y + 120.0;
    out[2] = z;
}

static void test_colored_faces(void) {
    static const float angles[] = {0.0f, 0.4f, 1.0f, 2.2f, 3.3f, 5.0f};
    double e = 120.0 / tan(3.14159265358979 / 6.0), w[4][3], cx, cy, n[3], c[3], area;
    mgl_color_t colors[6], *fb;
    const unsigned char *b = context3d_commands.bytes, *p;
    mgl_u32 off, last_index = 0;
    int a, f, v, k, count[6], visible, seen, draws, sets;
    for (f = 0; f < 6; f++) colors[f] = color565(face_rgb[f][0], face_rgb[f][1], face_rgb[f][2]);
    for (a = 0; a < (int)(sizeof angles / sizeof angles[0]); a++) {
        if (context3d_begin(P3D_FB_A) != MGL_OK) break;
        draw_colored_cube(angles[a]);
        CHECK(context3d_end(0) == MGL_OK);
        fb = context3d_pixels(P3D_FB_A);
        for (f = 0; f < 6; f++) count[f] = 0;
        for (k = 0; k < W * H; k++)
            for (f = 0; f < 6; f++)
                if (fb[k] == colors[f]) count[f]++;
        seen = 0;
        for (f = 0; f < 6; f++) {
            for (v = 0; v < 4; v++) world(angles[a], face_xyz[f][v], w[v]);
            /* Normal hacia fuera (el centro de la cara menos el del cubo) y vector hacia el ojo */
            c[0] = (w[0][0] + w[2][0]) * 0.5;
            c[1] = (w[0][1] + w[2][1]) * 0.5;
            c[2] = (w[0][2] + w[2][2]) * 0.5;
            n[0] = c[0] - 160.0;
            n[1] = c[1] - 120.0;
            n[2] = c[2];
            visible = n[0] * (160.0 - c[0]) + n[1] * (120.0 - c[1]) + n[2] * (e - c[2]) > 0.0;
            /* Su centro en pantalla y su área proyectada */
            cx = 160.0 + e * (c[0] - 160.0) / (e - c[2]);
            cy = 120.0 + e * (c[1] - 120.0) / (e - c[2]);
            area = 0.0;
            for (v = 0; v < 4; v++) {
                double x0 = 160.0 + e * (w[v][0] - 160.0) / (e - w[v][2]);
                double y0 = 120.0 + e * (w[v][1] - 120.0) / (e - w[v][2]);
                double x1 = 160.0 + e * (w[(v + 1) % 4][0] - 160.0) / (e - w[(v + 1) % 4][2]);
                double y1 = 120.0 + e * (w[(v + 1) % 4][1] - 120.0) / (e - w[(v + 1) % 4][2]);
                area += x0 * y1 - x1 * y0;
            }
            area = fabs(area) * 0.5;
            if (visible && area > 300.0) { /* las que se ven de lado son una línea: no se miran */
                CHECK(fb[(int)cy * W + (int)cx] == colors[f]);
                CHECK(fabs(count[f] - area) < 0.1 * area + 150.0);
                seen++;
            }
            /* El Z-buffer la tapa salvo algún píxel de las aristas que comparte con una visible: ahí las
               dos tienen la misma profundidad y con LESS gana la que se dibuja antes (como en OpenGL sin
               culling, que Processing no activa) */
            if (!visible) CHECK(count[f] <= 3);
        }
        CHECK(seen >= 1);
        printf("  caras de colores, ángulo %.1f: %d visibles (píxeles por cara %d %d %d %d %d %d)\n", angles[a],
            seen, count[0], count[1], count[2], count[3], count[4], count[5]);
    }
    /* Un SET_COLOR y un DRAW_INDEXED de 6 índices por cara, seguidos en la misma malla */
    draws = sets = 0;
    for (off = 16; off < context3d_commands.used; off += RD32(b + off + 4)) {
        p = b + off;
        if (RD16(p) == MGL_CMD_SET_COLOR) CHECK(RD32(p + 8) == colors[sets++ % 6]);
        if (RD16(p) == MGL_CMD_DRAW_INDEXED) {
            CHECK(RD32(p + 8) >= P3D_FRAME_HEAP && RD32(p + 16) == 24U && RD32(p + 20) == 6U);
            CHECK(draws == 0 || RD32(p + 12) == last_index + 12U);
            last_index = RD32(p + 12);
            draws++;
        }
    }
    CHECK(draws == 6 && sets == 6);
}

/* Un PShape con cull: el caza TIE, de malla abierta pero con los huecos tapados por otras piezas, da la
   misma imagen sin las caras traseras desde cualquier lado, rasterizando la mitad. Casi: alguna costura
   entre piezas deja una grieta de un píxel que tapaba una cara trasera (girando en x, y y z, un píxel en
   1 de 1000 frames, el del ángulo 5.3). Si se descartaran las de delante (el convenio de la y invertida
   al revés), cambiarían miles. */
static mgl_u32 draw_tie(const PShape *s, float angle, mgl_color_t *out) {
    mgl_u32 rasterized;
    mgr_reset_stats(&context3d_renderer);
    if (context3d_begin(P3D_FB_A) != MGL_OK) return 0;
    background(150, 170, 200);
    translate(160, 120, 0);
    rotateX(angle * 0.7f);
    rotateY(angle);
    rotateZ(angle * 0.45f);
    scale(80);
    shape(s);
    CHECK(context3d_end(0) == MGL_OK);
    rasterized = context3d_renderer.stats.rasterized;
    memcpy(out, context3d_pixels(P3D_FB_A), W * H * sizeof *out);
    return rasterized;
}

static void test_shape_cull(void) {
    static const float angles[] = {0.0f, 0.9f, 1.7f, 2.6f, 3.4f, 4.4f, 5.3f};
    static mgl_color_t culled[W * H], full[W * H];
    PShape both = tie_fighter;
    mgl_u32 n_culled, n_full, i, k, ship, diff;
    CHECK(tie_fighter.cull);
    both.cull = 0;
    for (i = 0; i < sizeof angles / sizeof angles[0]; i++) {
        n_culled = draw_tie(&tie_fighter, angles[i], culled);
        n_full = draw_tie(&both, angles[i], full);
        for (k = diff = 0; k < W * H; k++)
            diff += culled[k] != full[k];
        CHECK(diff <= 4U);
        CHECK(n_culled * 10U < n_full * 6U); /* menos del 60 % */
        for (k = ship = 0; k < W * H; k++)
            ship += full[k] != color565(150, 170, 200);
        CHECK(ship > 2000U);
    }
}

/* resetShapes: cuatro PShape de 84 KB no caben a la vez en la memoria de MiniGL
   (256 KB); vaciándola antes de cada uno, sí, y el mismo PShape con otros
   datos se dibuja con los nuevos. */
#define BIG_VERTICES 7000
static float big_xyz[BIG_VERTICES * 3];
static const unsigned short big_indices[3] = {0, 1, 2};
static const PShapeGroup big_group = {255, 0, 0, 3};

static int draw_big(const PShape *s, int reset) {
    if (context3d_begin(P3D_FB_A) != MGL_OK) return -1;
    if (reset) resetShapes();
    background(0, 0, 0);
    shape(s);
    return context3d_end(0);
}

static void test_reset_shapes(void) {
    PShape s[4];
    mgl_color_t *px;
    int i;
    big_xyz[0] = 100.0f; /* un triángulo rojo en el centro; el resto, en (0, 0, 0) */
    big_xyz[1] = 100.0f;
    big_xyz[3] = 220.0f;
    big_xyz[4] = 100.0f;
    big_xyz[6] = 160.0f;
    big_xyz[7] = 160.0f;
    for (i = 0; i < 4; i++) {
        s[i].positions = big_xyz;
        s[i].vertex_count = BIG_VERTICES;
        s[i].indices = big_indices;
        s[i].index_count = 3;
        s[i].groups = &big_group;
        s[i].group_count = 1;
        s[i].cull = 0;
    }
    resetShapes();
    CHECK(draw_big(&s[0], 0) == MGL_OK && draw_big(&s[1], 0) == MGL_OK && draw_big(&s[2], 0) == MGL_OK);
    CHECK(draw_big(&s[3], 0) != MGL_OK); /* ya no cabe */
    for (i = 0; i < 4; i++) CHECK(draw_big(&s[i], 1) == MGL_OK);
    px = context3d_pixels(P3D_FB_A);
    CHECK(px[130 * W + 160] == color565(255, 0, 0));
    big_xyz[6] = 160.0f; /* el mismo PShape, más abajo: sin resetShapes se vería el de antes */
    big_xyz[7] = 220.0f;
    CHECK(draw_big(&s[3], 0) == MGL_OK && px[190 * W + 160] != color565(255, 0, 0));
    CHECK(draw_big(&s[3], 1) == MGL_OK && px[190 * W + 160] == color565(255, 0, 0));
    resetShapes();
}

int main(void) {
    unsigned char *ram = (unsigned char *)calloc(P3D_RAM_SIZE, 1);
    if (!ram || context3d_init(ram)) {
        puts("FAIL: context3d_init");
        return 1;
    }
    test_angles();
    test_matrix_stack();
    test_frame_commands();
    test_replay();
    test_colored_faces();
    test_shape_cull();
    test_reset_shapes();
    free(ram);
    if (failures) {
        printf("FAIL: test_cube, %d comprobaciones fallidas\n", failures);
        return 1;
    }
    puts("PASS: test_cube: cubo en 6 ángulos frente a la proyección en double, frame, reproducción, caras de colores, PShape con cull, resetShapes, pila de matrices y perspective");
    return 0;
}
