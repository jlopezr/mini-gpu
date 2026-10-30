#include "minigl.h"

static mgl_color_t *fb;
static int fw, fh, pitch;
static mgl_color_t fc = 0xffff, sc = 0xffff;
static int fill_on = 1, stroke_on = 0, sw = 1;

static int min2(int a, int b) {
    return a < b ? a : b;
}

static int max2(int a, int b) {
    return a > b ? a : b;
}

static int abs2(int a) {
    return a < 0 ? -a : a;
}

static void put(int x, int y, mgl_color_t c) {
    if (fb && x >= 0 && y >= 0 && x < fw && y < fh) fb[y * pitch + x] = c;
}

/* De x0 a x1 - 1 en la fila que empieza en row, recortado en x; desenrollado
   porque lcc no lo hace. Quien recorre filas seguidas recorta y una vez y
   avanza row en pitch: sin multiplicar ni leer fb por fila.
   En MiniGPU, de dos en dos píxeles con escrituras de 32 bits: lcc no aplica
   strict aliasing. En el host no se puede (escribir un mgl_color_t con un
   unsigned no está definido y -O2 lo aprovecha), y el compilador ya vectoriza
   el bucle de píxeles. */
static void row_fill(mgl_color_t *row, int x0, int x1, mgl_color_t c) {
    mgl_color_t *p;
    int n; /* un contador y no restas de punteros: lcc las divide en cada vuelta */
    if (x0 < 0) x0 = 0; /* sin min2/max2: es caliente y lcc no expande en línea */
    if (x1 > fw) x1 = fw;
    n = x1 - x0;
    if (n <= 0) return;
    p = row + x0;
#ifdef __MINIGPU__
    if (n >= 8) { /* con menos, preparar las palabras cuesta más que lo que ahorra */
        unsigned pair = c | (unsigned)c << 16, *w;
        if ((unsigned)p & 2) { /* hasta alinear a 4 */
            *p++ = c;
            n--;
        }
        w = (unsigned *)p;
        for (; n >= 8; n -= 8, w += 4) {
            w[0] = pair;
            w[1] = pair;
            w[2] = pair;
            w[3] = pair;
        }
        for (; n >= 2; n -= 2) *w++ = pair;
        p = (mgl_color_t *)w;
    }
#else
    for (; n >= 8; n -= 8, p += 8) {
        p[0] = c;
        p[1] = c;
        p[2] = c;
        p[3] = c;
        p[4] = c;
        p[5] = c;
        p[6] = c;
        p[7] = c;
    }
#endif
    for (; n > 0; n--) *p++ = c;
}

/* La fila y de x0 a x1 - 1, recortada (las líneas, que no van por filas seguidas). */
static void span(int y, int x0, int x1, mgl_color_t c) {
    if (y >= 0 && y < fh) row_fill(fb + y * pitch, x0, x1, c);
}

/* El rectángulo de x0 a x1 - 1 y de y0 a y1 - 1, recortado: un span por fila,
   o si es de una columna, bajando por ella. */
static void box(int x0, int y0, int x1, int y1, mgl_color_t c) {
    mgl_color_t *p;
    if (y0 < 0) y0 = 0;
    if (y1 > fh) y1 = fh;
    if (y0 >= y1) return;
    p = fb + y0 * pitch;
    if (x1 - x0 == 1) {
        if (x0 < 0 || x0 >= fw) return;
        for (p += x0; y0 < y1; y0++, p += pitch) *p = c;
    } else
        for (; y0 < y1; y0++, p += pitch) row_fill(p, x0, x1, c);
}

static void brush(int x, int y, mgl_color_t c) {
    int j, lo = -(sw / 2), hi = lo + sw;
    if (sw == 1)
        put(x, y, c);
    else
        for (j = lo; j < hi; j++) span(y + j, x + lo, x + hi, c);
}

/* Una línea de Bresenham recorrida por tramos: los puntos seguidos con la misma
   y. Los puntos son los de siempre (avanza igual); solo se agrupan. WALK_RUN
   avanza un tramo de un recorrido (X, Y, ERR) y deja en F y L la x de su primer
   punto y del último. Es una macro sobre variables locales y no una función con
   su estado en una estructura: en las líneas empinadas cada tramo es un punto,
   y lcc ni expande la llamada ni deja en registros lo que va por un puntero.
   Usa dx, dy, sx, sy, x1, y1 y e de quien la llama. */
#define WALK_RUN(X, Y, ERR, F, L)                     \
    do {                                              \
        int y_ = (Y);                                 \
        (F) = (X);                                    \
        for (;;) {                                    \
            (L) = (X);                                \
            if ((X) == x1 && (Y) == y1) break;        \
            e = 2 * (ERR);                            \
            if (e > -dy) {                            \
                (ERR) -= dy;                          \
                (X) += sx;                            \
            }                                         \
            if (e < dx) {                             \
                (ERR) += dx;                          \
                (Y) += sy;                            \
            }                                         \
            if ((Y) != y_) break;                     \
        }                                             \
    } while (0)

/* Una línea con el pincel en cada punto: el cuadrado de sw x sw (filas y
   columnas de lo a hi - 1 alrededor). La fila r la tocan los puntos con y entre
   r - (hi - 1) y r - lo: unos tramos seguidos de la línea, que como avanza
   siempre hacia el mismo lado en x cubren de la x del primero a la del último.
   Cada fila es un span; dos recorridos de la línea dan el primer tramo y el
   último de la ventana. Mismos píxeles que un cuadrado por punto, una vez cada
   uno. */
static void segment(int x0, int y0, int x1, int y1, mgl_color_t c) {
    int lo = -(sw / 2), hi = lo + sw, dx = abs2(x1 - x0), dy = abs2(y1 - y0);
    int sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, runs = dy + 1, e;
    int x_first = x0, y_first = y0, err_first = dx - dy, x_last, y_last, err_last;
    int before, after, t, k_first = 0, k_last = 0, f_first, l_first, f_last, l_last;
    if (x0 == x1 || y0 == y1) { /* horizontal o vertical (los bordes de rect): un rectángulo */
        box(min2(x0, x1) + lo, min2(y0, y1) + lo, max2(x0, x1) + hi, max2(y0, y1) + hi, c);
        return;
    }
    WALK_RUN(x_first, y_first, err_first, f_first, l_first);
    if (sw == 1) { /* la ventana es un tramo; de un punto en las líneas empinadas */
        for (t = 0;; t++) {
            if (f_first == l_first)
                put(f_first, y0 + sy * t, c); /* más barato que un span */
            else
                span(y0 + sy * t, min2(f_first, l_first), max2(f_first, l_first) + 1, c);
            if (t == runs - 1) return;
            WALK_RUN(x_first, y_first, err_first, f_first, l_first);
        }
    }
    /* La ventana de la fila y0 + sy * t, en tramos (el tramo k está en y0 + sy * k). */
    before = sy > 0 ? hi - 1 : -lo;
    after = sy > 0 ? -lo : hi - 1;
    x_last = x_first;
    y_last = y_first;
    err_last = err_first;
    f_last = f_first;
    l_last = l_first;
    for (t = -after; t <= runs - 1 + before; t++) {
        for (; k_first < t - before; k_first++) WALK_RUN(x_first, y_first, err_first, f_first, l_first);
        for (; k_last < t + after && k_last < runs - 1; k_last++) WALK_RUN(x_last, y_last, err_last, f_last, l_last);
        span(y0 + sy * t, min2(f_first, l_last) + lo, max2(f_first, l_last) + hi, c);
    }
}

static long edge(int ax, int ay, int bx, int by, int px, int py) {
    return (long)(px - ax) * (by - ay) - (long)(py - ay) * (bx - ax);
}

void sw_bind(mgl_color_t *pixels, int width, int height, int stride) {
    if (!pixels || width <= 0 || height <= 0 || stride < width) {
        fb = 0;
        fw = fh = pitch = 0;
        return;
    }
    fb = pixels;
    fw = width;
    fh = height;
    pitch = stride;
    fc = 0xffff;
    sc = 0xffff;
    fill_on = 1;
    stroke_on = 0;
    sw = 1;
}

/* Otro framebuffer del mismo tamaño, con el mismo estado. */
void sw_set_target(mgl_color_t *pixels) {
    if (fb && pixels) fb = pixels;
}

void sw_clear(mgl_color_t c) {
    if (fb) box(0, 0, fw, fh, c);
}

void sw_fill(mgl_color_t c) {
    fc = c;
    fill_on = 1;
}

void sw_no_fill(void) {
    fill_on = 0;
}

void sw_stroke(mgl_color_t c) {
    sc = c;
    stroke_on = 1;
}

void sw_no_stroke(void) {
    stroke_on = 0;
}

void sw_stroke_weight(int w) {
    sw = w > 0 ? w : 1;
}

void sw_point(int x, int y) {
    if (stroke_on) brush(x, y, sc);
}

void sw_line(int x0, int y0, int x1, int y1) {
    if (stroke_on) segment(x0, y0, x1, y1, sc);
}

void sw_rect(int x, int y, int w, int h) {
    if (w <= 0 || h <= 0 || !fb) return;
    if (fill_on) box(x, y, x + w, y + h, fc);
    if (stroke_on) {
        segment(x, y, x + w - 1, y, sc);
        segment(x + w - 1, y, x + w - 1, y + h - 1, sc);
        segment(x + w - 1, y + h - 1, x, y + h - 1, sc);
        segment(x, y + h - 1, x, y, sc);
    }
}

void sw_circle(int cx, int cy, int r) {
    int x, y, xx, last, dx;
    long dy, g, up, down;
    mgl_color_t *row;
    if (r < 0 || !fb) return;
    if (fill_on) {
        /* Cada fila es un tramo: los dx con dx*dx + dy*dy <= r*r van de -dx a dx.
           dx crece hasta el centro y luego decrece: se ajusta desde la fila
           anterior, llevando g = dx*dx + dy*dy - r*r con sumas (en la placa, MUL
           tarda decenas de ciclos): up = 2*dx + 1 es lo que suma subir dx y down =
           2*dy + 1, bajar de fila. Solo las filas de la pantalla: en la primera,
           dx sube desde 0. */
        dy = max2(-r, -cy);
        last = min2(r, fh - 1 - cy);
        dx = 0;
        up = 1;
        g = dy * dy - (long)r * r;
        down = 2 * dy + 1;
        row = dy <= last ? fb + (cy + (int)dy) * pitch : fb; /* sin filas: ni se usa */
        for (; dy <= last; dy++, row += pitch) {
            while (g + up <= 0) {
                g += up;
                up += 2;
                dx++;
            }
            while (g > 0) {
                up -= 2;
                g -= up;
                dx--;
            }
            row_fill(row, cx - dx, cx + dx + 1, fc);
            g += down;
            down += 2;
        }
    }
    if (stroke_on) {
        x = r;
        y = 0;
        xx = 1 - r;
        while (x >= y) {
            brush(cx + x, cy + y, sc);
            brush(cx + y, cy + x, sc);
            brush(cx - y, cy + x, sc);
            brush(cx - x, cy + y, sc);
            brush(cx - x, cy - y, sc);
            brush(cx - y, cy - x, sc);
            brush(cx + y, cy - x, sc);
            brush(cx + x, cy - y, sc);
            y++;
            if (xx < 0)
                xx += 2 * y + 1;
            else {
                x--;
                xx += 2 * (y - x) + 1;
            }
        }
    }
}

/* Recorta [*from, *to] a las x (desde left) en que una arista que vale v en
   left y crece d por x da >= 0. Con divisiones exactas, sin recorrer la fila.
   (Llevar cociente y resto por sumas cuesta más instrucciones que las tres
   divisiones por fila; solo compensaría con un divisor mucho más lento.) */
static void clip_edge(long v, long d, int left, int *from, int *to) {
    long x;
    if (d > 0) {
        if (v >= 0) return;
        x = left + (-v + d - 1) / d; /* la primera x con v + d * (x - left) >= 0 */
        if (x > *from) *from = x > *to ? *to + 1 : (int)x;
    } else if (d < 0) {
        if (v < 0) {
            *to = *from - 1;
            return;
        }
        x = left + v / -d; /* la última */
        if (x < *to) *to = (int)x;
    } else if (v < 0)
        *to = *from - 1;
}

void sw_triangle(int x0, int y0, int x1, int y1, int x2, int y2) {
    int y, left, right, top, bottom, from, to, bx = x1, by = y1, cx = x2, cy = y2;
    long area = edge(x0, y0, x1, y1, x2, y2), a, b, c;
    mgl_color_t *row;
    if (!fb) return;
    if (fill_on && area != 0) {
        /* Con el triángulo en sentido positivo (area > 0), un píxel está dentro si
           las tres aristas dan >= 0: como a + b + c = area, nunca dan las tres <= 0.
           Cada arista es lineal en x, así que en cada fila lo de dentro es un
           tramo (el triángulo es convexo) que sale de recortar con las tres. */
        if (area < 0) { /* b y c son copias: el contorno va en el orden de la llamada */
            bx = x2, by = y2;
            cx = x1, cy = y1;
        }
        left = max2(0, min2(x0, min2(x1, x2)));
        right = min2(fw - 1, max2(x0, max2(x1, x2)));
        top = max2(0, min2(y0, min2(y1, y2)));
        bottom = min2(fh - 1, max2(y0, max2(y1, y2)));
        a = edge(x0, y0, bx, by, left, top);
        b = edge(bx, by, cx, cy, left, top);
        c = edge(cx, cy, x0, y0, left, top);
        row = top <= bottom ? fb + top * pitch : fb; /* sin filas: ni se usa */
        for (y = top; y <= bottom; y++, row += pitch) {
            from = left;
            to = right;
            clip_edge(a, by - y0, left, &from, &to);
            clip_edge(b, cy - by, left, &from, &to);
            clip_edge(c, y0 - cy, left, &from, &to);
            row_fill(row, from, to + 1, fc);
            a -= bx - x0; /* cada arista cambia en una cantidad fija por y */
            b -= cx - bx;
            c -= x0 - cx;
        }
    }
    if (stroke_on) {
        segment(x0, y0, x1, y1, sc);
        segment(x1, y1, x2, y2, sc);
        segment(x2, y2, x0, y0, sc);
    }
}

void sw_image(const mgl_sprite_t *s, int x, int y) {
    int i, j, x0, y0, x1, y1;
    if (!fb || !s || !s->pixels || s->width <= 0 || s->height <= 0 || s->stride < s->width) return;
    x0 = max2(0, x);
    y0 = max2(0, y);
    x1 = min2(fw, x + s->width);
    y1 = min2(fh, y + s->height);
    for (j = y0; j < y1; j++)
        for (i = x0; i < x1; i++) put(i, j, s->pixels[(j - y) * s->stride + (i - x)]);
}
