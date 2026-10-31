/* El cubo de MiniProcessing de extremo a extremo (platform3d + processing3d +
   MiniGL + renderer) en varios ángulos, contra una proyección independiente en
   double; el command buffer de un frame de Processing; y reproducción de un
   command buffer guardado. */
#include "platform3d.h"
#include "mgl_bytes.h"
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
    if (platform3d_begin(P3D_FB_A) != MGL_OK) return -1;
    draw_cube(angle);
    return platform3d_end(0);
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
        fb = platform3d_pixels(P3D_FB_A);
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
    fb = platform3d_pixels(P3D_FB_A);
    count = 0;
    for (x = 0; x < W; x++)
        if (fb[120 * W + x] == ORANGE) count++;
    CHECK(count == 131 || count == 132);
}

/* El frame de un sketch: el command buffer de docs/3d.md §12. */
static void test_frame_commands(void) {
    static const unsigned int expected[] = {MGL_CMD_SET_RENDER_TARGET, MGL_CMD_CLEAR,
        MGL_CMD_SET_VIEWPORT, MGL_CMD_SET_MATRIX, MGL_CMD_SET_MATRIX, MGL_CMD_SET_MATRIX,
        MGL_CMD_SET_RENDER_STATE, MGL_CMD_SET_COLOR, MGL_CMD_DRAW_INDEXED, MGL_CMD_END_FRAME};
    const unsigned char *b = platform3d_commands.bytes, *p;
    mgl_u32 off;
    int i = 0;
    CHECK(render(1.0f) == MGL_OK);
    for (off = 16; off < platform3d_commands.used; off += RD32(b + off + 4), i++) {
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
    mgl_color_t *fb = platform3d_pixels(P3D_FB_A);
    unsigned char *commands = platform3d_commands.bytes;
    CHECK(render(1.0f) == MGL_OK);
    used = platform3d_commands.used;
    CHECK(used <= sizeof saved);
    memcpy(saved, commands, used);
    memcpy(first, fb, sizeof first);
    CHECK(render(2.2f) == MGL_OK);
    CHECK(memcmp(first, fb, sizeof first) != 0);
    memcpy(commands, saved, used);
    CHECK(mgr_execute(&platform3d_renderer, P3D_COMMANDS) == MGR_OK);
    CHECK(memcmp(first, fb, sizeof first) == 0);
    CHECK(mgr_execute(&platform3d_renderer, P3D_COMMANDS) == MGR_OK);
    CHECK(memcmp(first, fb, sizeof first) == 0);
    memset(fb, 0, sizeof first);
    CHECK(mgr_init(&fresh, &platform3d_memory) == MGR_OK);
    CHECK(mgr_execute(&fresh, P3D_COMMANDS) == MGR_OK);
    CHECK(memcmp(first, fb, sizeof first) == 0);
}

int main(void) {
    unsigned char *ram = (unsigned char *)calloc(P3D_RAM_SIZE, 1);
    if (!ram || platform3d_init(ram)) {
        puts("FAIL: platform3d_init");
        return 1;
    }
    test_angles();
    test_frame_commands();
    test_replay();
    free(ram);
    if (failures) {
        printf("FAIL: test_cube, %d comprobaciones fallidas\n", failures);
        return 1;
    }
    puts("PASS: test_cube: cubo en 6 ángulos frente a la proyección en double, frame y reproducción");
    return 0;
}
