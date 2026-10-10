/* cube.c - el cubo con texturas de examples/asm/race/cube.inc, en C: CPU, GPU inocente y GPU buena
 * y el anfitrion de race_host.inc (video con doble buffer, método que toca, grafica de tiempos)
 *
 *   build-c 32.cpu-gpu-func-sim/examples/c/race/cube.c --board     # -> _build/c/cube_board.bin
 *   run-board --prototype 36 --program _build/c/cube_board.bin
 *   build-c 32.cpu-gpu-func-sim/examples/c/race/cube.c             # simulador (mini-dbg --gpu)
 *
 * La geometria esta en cube.inc (proyeccion ortografica, tres caras visibles, una division por
 * cara y eje); aqui `cube_prepare` la calcula igual. El cuerpo de la celda esta en
 * cube_body.h, una vez, y se incluye tres veces con otro reparto de trabajo.
 */
#include "gpu.h"
#include "mmio.h"

#define CUBE_COLS 160
#define CUBE_ROWS 104
#define CUBE_TEX 0x010A0000         /* 6 texturas de 64 x 64 palabras */
#define CUBE_FB_OFF 20480           /* debajo de la grafica: 32 lineas de 640 bytes */
#define CUBE_LIM 8704               /* 8192 + 2 * 256 */
#define CUBE_EPS 256
#define CUBE_BG 0x10A210A2

#define FB_A 0x01000000
#define FB_B 0x01025800
#define NWARPS 8
#define STRIP_H 32

typedef struct {
    int tex, u00, v00, ux, vx, uy, vy, pad;         /* 32 bytes, como cube_faces de cube.inc */
} Face;

Face cube_faces[3];

/* ---- la CPU ---- */
#define NAME cube_cpu
#define ROW_FIRST 0
#define ROW_STEP 1
#define COL_FIRST 0
#define COL_STEP 1
#include "cube_body.h"
#undef NAME
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- la GPU inocente: un hilo por fila ---- */
#define NAME KERNEL(cube_naive)
#define ROW_FIRST __gpu_tid
#define ROW_STEP __gpu_nthreads
#define COL_FIRST 0
#define COL_STEP 1
#include "cube_body.h"
#undef NAME
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- la GPU buena: un warp por fila, una lane por columna de cada ocho ---- */
#define NAME KERNEL(cube_good)
#define ROW_FIRST __gpu_lwarp
#define ROW_STEP NWARPS
#define COL_FIRST __gpu_lane
#define COL_STEP 8
#include "cube_body.h"
#undef NAME
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- datos ---- */
static const int cube_sin[64] = {       /* 128 * sin(2 pi k / 64) */
    0, 13, 25, 37, 49, 60, 71, 81, 91, 99, 106, 113, 118, 122, 126, 127,
    128, 127, 126, 122, 118, 113, 106, 99, 91, 81, 71, 60, 49, 37, 25, 13,
    0, -13, -25, -37, -49, -60, -71, -81, -91, -99, -106, -113, -118, -122, -126, -127,
    -128, -127, -126, -122, -118, -113, -106, -99, -91, -81, -71, -60, -49, -37, -25, -13
};
static const int cube_pal[12] = {       /* dos colores por textura */
    0xF800, 0xFFFF, 0x7800, 0x8410, 0x07E0, 0xFFE0,
    0x03E0, 0x8400, 0x001F, 0x07FF, 0x000F, 0x0410
};
static const unsigned race_pixels[3] = { 0x07E007E0, 0xFD20FD20, 0x07FF07FF };

int race_period = 60;                   /* fotogramas por metodo */
int race_shift = 18;                    /* ciclos -> altura de la grafica */
int race_cycles[3];                     /* ciclos del ultimo trabajo de cada metodo */
extern int gpu_timeout_polls;           /* gpu_runtime.inc */

/* ---- CPU: las seis texturas, una vez ---- */
static void cube_setup(void) {
    unsigned *t = (unsigned *)CUBE_TEX;
    int id, tx, ty, v;
    unsigned c;

    for (id = 0; id < 6; id++)
        for (ty = 0; ty < 64; ty++)
            for (tx = 0; tx < 64; tx++) {
                if (id < 2)
                    v = ((tx >> 3) ^ (ty >> 3)) & 1;
                else if (id < 4)
                    v = ((tx + ty) >> 3) & 1;
                else
                    v = ((tx >> 2) & (ty >> 2)) & 1;
                c = cube_pal[2 * id + v];
                if ((unsigned)(tx - 2) >= 60 || (unsigned)(ty - 2) >= 60)
                    c = 0;                          /* el borde negro */
                *t++ = c * 65537;                   /* dos pixeles por palabra */
            }
}

/* ---- CPU: la matriz y las tres caras de este fotograma ---- */
static void cube_prepare(int frame) {
    int m[9], i, k, axis, a, b, sa, ca, sb, cb, r, s, q, cx, cy, ux, uy, start;
    Face *f;

    b = frame & 63;
    a = ((3 * frame) >> 2) & 63;
    sb = cube_sin[b];
    cb = cube_sin[(b + 16) & 63];
    sa = cube_sin[a];
    ca = cube_sin[(a + 16) & 63];
    m[0] = cb;  m[1] = 0;   m[2] = sb;
    m[3] = (sa * sb) >> 7;  m[4] = ca;  m[5] = -(sa * cb) >> 7;
    m[6] = -(ca * sb) >> 7; m[7] = sa;  m[8] = (ca * cb) >> 7;

    for (i = 0; i < 3; i++) {
        f = &cube_faces[i];
        r = m[6 + i];                               /* R[2][i] */
        if (r == 0) {                               /* de canto: fuera de rango siempre */
            f->tex = 0;
            f->u00 = f->v00 = 0x40000000;
            f->ux = f->vx = f->uy = f->vy = 0;
            continue;
        }
        s = r > 0 ? 1 : -1;
        f->tex = CUBE_TEX + ((2 * i + (s < 0)) << 14);
        for (k = 1; k <= 2; k++) {
            axis = (i + k) % 3;
            q = (m[6 + axis] << 14) / r;
            cx = (m[axis] << 7) - ((q * m[i]) >> 7);
            cy = (m[3 + axis] << 7) - ((q * m[3 + i]) >> 7);
            ux = cx >> 7;
            uy = cy >> 7;
            start = 4096 + CUBE_EPS + ((s * q) >> 2) - 80 * ux - 52 * uy;
            if (k == 1) {
                f->u00 = start;  f->ux = ux;  f->uy = uy;
            } else {
                f->v00 = start;  f->vx = ux;  f->vy = uy;
            }
        }
    }
}

/* ---- la columna de la grafica: altura = ciclos >> race_shift, color = metodo ---- */
static void race_strip(int cycles, int method, int column) {
    int height = cycles >> race_shift, first, line;
    unsigned short *a, *b, color = (unsigned short)race_pixels[method], value;

    if (height > STRIP_H)
        height = STRIP_H;
    first = STRIP_H - height;                       /* primera linea con color, desde arriba */
    a = (unsigned short *)FB_A + column;
    b = (unsigned short *)FB_B + column;
    for (line = 0; line < STRIP_H; line++) {
        value = line < first ? 0 : color;
        *a = value;
        *b = value;
        a += 320;
        b += 320;
    }
}

int main(void) {
    int frame = 0, method = 0, countdown, column = 0, start, cycles, status;
    int *fb, *clear_a = (int *)FB_A, *clear_b = (int *)FB_B, i;

    REG(VIDEO_FB_FRONT) = FB_A;
    REG(VIDEO_FB_BACK) = FB_B;
    REG(VIDEO_CTRL) = VIDEO_MODE_SCANOUT;
    REG(GPU_CONTROL) = GPU_CTRL_RESET;              /* la placa conserva el estado de la GPU */
    gpu_timeout_polls = 1000000;
    for (i = 0; i < STRIP_H * CUBE_COLS; i++) {     /* la grafica empieza en blanco */
        clear_a[i] = 0;
        clear_b[i] = 0;
    }
    cube_setup();
    countdown = race_period;

    for (;;) {
        cube_prepare(frame);
        fb = (int *)(REG(VIDEO_FB_BACK) + CUBE_FB_OFF);
        start = bench_now();
        status = GPU_OK;
        if (method == 0)
            cube_cpu(fb);
        else if (method == 1)
            status = GPU_RUN(cube_naive, NWARPS, fb);
        else
            status = GPU_RUN(cube_good, NWARPS, fb);
        if (status != GPU_OK)
            return 1;                               /* crt0 hace HALT */
        cycles = bench_now() - start;
        race_cycles[method] = cycles;
        race_strip(cycles, method, column);
        if (++column == 320)
            column = 0;

        REG(VIDEO_SWAP) = 1;                        /* pedir el intercambio y esperar */
        while (REG(VIDEO_SWAP))
            ;
        frame++;
        if (--countdown == 0) {
            countdown = race_period;
            if (++method == 3)
                method = 0;
        }
    }
}
