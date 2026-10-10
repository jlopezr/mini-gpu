/* plane.c - un plano que gira con un logo en cada cara y alfa sobre un fondo degradado: CPU, GPU
 * inocente y GPU buena, con el anfitrion de cube.c (video con doble buffer, metodo que toca, grafica)
 *
 *   python x.tests/cases-cpu-gpu/race/plane/plane_tex.py -o _build/c/plane_tex.bin
 *   build-c x.tests/cases-cpu-gpu/race/plane/plane.c --board --data plane_tex=_build/c/plane_tex.bin
 *   run-board --prototype 36 --program _build/c/plane_board.bin
 *   build-c x.tests/cases-cpu-gpu/race/plane/plane.c --data plane_tex=_build/c/plane_tex.bin   # simulador
 *
 * Delante, los Autobots; detras, los Decepticons (plane_tex.py los saca de plane/logos.png, con
 * su alfa, y `--data` los deja detras del codigo con la etiqueta `plane_tex`). Proyeccion
 * ortografica sobre el eje vertical: u = x / |cos|, v = y, de modo que cada fila lee una sola fila de
 * la textura (ver plane_body.h). Se ve la cara delantera con cos > 0 y la trasera con cos < 0; de canto
 * (|cos| pequeno) el plano no se dibuja.
 */
#include "gpu.h"
#include "mmio.h"

#define PLANE_COLS 160
#define PLANE_ROWS 104
#define PLANE_FB_OFF 20480          /* debajo de la grafica: 32 lineas de 640 bytes */
#define PLANE_LIM 16384             /* 128 texeles en Q7 */
#define PLANE_TEX_WORDS 16384       /* una textura: 128 x 128 palabras */
#define PLANE_SCALE 170             /* v por fila, Q7: 96 filas de celdas cubren los 128 texeles */
#define PLANE_FAR 0x40000000        /* fuera de rango siempre */

#define FB_A 0x01000000
#define FB_B 0x01025800
#define NWARPS 8
#define STRIP_H 32

typedef struct {
    unsigned *tex;
    int u00, ux, v00, vy;
} Plane;

Plane plane_cfg;
unsigned plane_bg[PLANE_ROWS];          /* el fondo de cada fila, en RGB565 abierto (ver plane_body.h) */
extern unsigned plane_tex[];            /* 2 texturas, build-c --data */

/* ---- la CPU ---- */
#define NAME plane_cpu
#define ROW_FIRST 0
#define ROW_STEP 1
#define COL_FIRST 0
#define COL_STEP 1
#include "plane_body.h"
#undef NAME
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- la GPU inocente: un hilo por fila ---- */
#define NAME KERNEL(plane_naive)
#define ROW_FIRST __gpu_tid
#define ROW_STEP __gpu_nthreads
#define COL_FIRST 0
#define COL_STEP 1
#include "plane_body.h"
#undef NAME
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- la GPU buena: un warp por fila, una lane por columna de cada ocho ---- */
#define NAME KERNEL(plane_good)
#define ROW_FIRST __gpu_lwarp
#define ROW_STEP NWARPS
#define COL_FIRST __gpu_lane
#define COL_STEP 8
#include "plane_body.h"
#undef NAME
#undef ROW_FIRST
#undef ROW_STEP
#undef COL_FIRST
#undef COL_STEP

/* ---- datos ---- */
static const int plane_sin[64] = {      /* 128 * sin(2 pi k / 64) */
    0, 13, 25, 37, 49, 60, 71, 81, 91, 99, 106, 113, 118, 122, 126, 127,
    128, 127, 126, 122, 118, 113, 106, 99, 91, 81, 71, 60, 49, 37, 25, 13,
    0, -13, -25, -37, -49, -60, -71, -81, -91, -99, -106, -113, -118, -122, -126, -127,
    -128, -127, -126, -122, -118, -113, -106, -99, -91, -81, -71, -60, -49, -37, -25, -13
};
static const unsigned race_pixels[3] = { 0x07E007E0, 0xFD20FD20, 0x07FF07FF };

#ifndef RACE_PERIOD_VALUE
#define RACE_PERIOD_VALUE 60
#endif
int race_period = RACE_PERIOD_VALUE;    /* fotogramas por metodo */
int race_shift = 18;                    /* ciclos -> altura de la grafica */
int race_cycles[3];                     /* ciclos del ultimo trabajo de cada metodo */
extern int gpu_timeout_polls;           /* gpu_runtime.inc */

/* ---- CPU: el degradado de fondo, una vez (azul oscuro arriba, naranja apagado abajo) ---- */
static void plane_setup(void) {
    int y, r, g, b;
    unsigned c;

    for (y = 0; y < PLANE_ROWS; y++) {
        r = 24 + (176 * y) / (PLANE_ROWS - 1);
        g = 40 + (80 * y) / (PLANE_ROWS - 1);
        b = 96 - (48 * y) / (PLANE_ROWS - 1);
        c = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
        plane_bg[y] = (c | (c << 16)) & 0x07E0F81Fu;
    }
}

/* ---- CPU: el plano de este fotograma ---- */
static void plane_prepare(int frame) {
    int c, ac;

    c = plane_sin[((frame & 63) + 16) & 63];        /* cos */
    ac = c < 0 ? -c : c;
    plane_cfg.tex = plane_tex + (c < 0 ? PLANE_TEX_WORDS : 0);
    plane_cfg.vy = PLANE_SCALE;
    plane_cfg.v00 = 64 * 128 - (PLANE_ROWS / 2) * PLANE_SCALE;
    if (ac < 8) {                                   /* de canto */
        plane_cfg.u00 = PLANE_FAR;
        plane_cfg.ux = 0;
        return;
    }
    plane_cfg.ux = (PLANE_SCALE * 128) / ac;
    plane_cfg.u00 = 64 * 128 - (PLANE_COLS / 2) * plane_cfg.ux;
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
    for (i = 0; i < STRIP_H * PLANE_COLS; i++) {    /* la grafica empieza en blanco */
        clear_a[i] = 0;
        clear_b[i] = 0;
    }
    plane_setup();
    countdown = race_period;

    for (;;) {
        plane_prepare(frame);
        fb = (int *)(REG(VIDEO_FB_BACK) + PLANE_FB_OFF);
        start = bench_now();
        status = GPU_OK;
        if (method == 0)
            plane_cpu(fb);
        else if (method == 1)
            status = GPU_RUN(plane_naive, NWARPS, fb);
        else
            status = GPU_RUN(plane_good, NWARPS, fb);
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
