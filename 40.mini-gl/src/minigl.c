#include "minigl.h"
#include "raster.h"
#include <string.h>

/* Evita depender de stdint.h (C99). */
typedef char check_u32[(sizeof(mgl_u32) == 4) ? 1 : -1];
typedef char check_u16[(sizeof(mgl_color_t) == 2) ? 1 : -1];

#define OP_CLEAR 1U
#define OP_BATCH 2U

#define PR_POINT 1U
#define PR_LINE 2U
#define PR_RECT 3U
#define PR_CIRCLE 4U
#define PR_TRIANGLE 5U
#define PR_IMAGE 6U

#define FLAG_FILL 1U
#define FLAG_STROKE 2U

static mgl_cmd_buffer_t *current;
static mgl_color_t fill_color = 0xffff, stroke_color = 0xffff;
static unsigned int flags = FLAG_FILL, weight = 1;

/* El framebuffer (mgl_bind, mgl_set_target) y, si no tiene el lienzo, de dónde
   copiarlo antes de dibujar encima. */
static mgl_color_t *target;
static int target_w, target_h, target_stride;
static const mgl_color_t *previous;

/* El formato es little-endian. En el host se lee y escribe byte a byte, que vale
   en cualquier máquina y con cualquier alineación. En MiniGPU, que es
   little-endian, con accesos de 16 y 32 bits: los campos están alineados (la
   memoria del buffer también, lo pide mgl_cmd_init) y lcc no aplica strict
   aliasing ni expande funciones en línea, por eso son macros. */
#ifdef __MINIGPU__
#define WR16(p, v) (*(unsigned short *)(p) = (unsigned short)(v))
#define WR32(p, v) (*(mgl_u32 *)(p) = (mgl_u32)(v))
#define RD16(p) ((unsigned int)*(const unsigned short *)(p))
#define RD32(p) (*(const mgl_u32 *)(p))
#define LOW(p) ((int)((p) << 16) >> 16) /* lcc desplaza un int con signo */
#define HIGH(p) ((int)(p) >> 16)
#else
static void wr16(unsigned char *p, unsigned int v) {
    p[0] = (unsigned char)v;
    p[1] = (unsigned char)(v >> 8);
}

static void wr32(unsigned char *p, mgl_u32 v) {
    p[0] = (unsigned char)v;
    p[1] = (unsigned char)(v >> 8);
    p[2] = (unsigned char)(v >> 16);
    p[3] = (unsigned char)(v >> 24);
}

static unsigned int rd16(const unsigned char *p) {
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8);
}

static mgl_u32 rd32(const unsigned char *p) {
    return (mgl_u32)p[0] | ((mgl_u32)p[1] << 8) | ((mgl_u32)p[2] << 16) | ((mgl_u32)p[3] << 24);
}

static int low(mgl_u32 p) {
    unsigned int v = (unsigned int)(p & 65535U);
    return v >= 32768U ? (int)v - 65536 : (int)v;
}

static int high(mgl_u32 p) {
    return low(p >> 16);
}

#define WR16 wr16
#define WR32 wr32
#define RD16 rd16
#define RD32 rd32
#define LOW low
#define HIGH high
#endif


/* Macros y no funciones: se usan por cada coordenada y lcc no expande en línea. */
#define PACK(a, b) ((mgl_u32)((unsigned int)(a) & 65535U) | ((mgl_u32)((unsigned int)(b) & 65535U) << 16))
#define FIT(v) ((v) >= -32768 && (v) <= 32767)

static void header(mgl_cmd_buffer_t *b) {
    WR32(b->bytes, MGL_BUFFER_MAGIC);
    WR32(b->bytes + 4, MGL_BUFFER_VERSION);
    WR32(b->bytes + 8, b->used);
    WR32(b->bytes + 12, b->capacity);
}

int mgl_cmd_init(mgl_cmd_buffer_t *b, void *memory, mgl_u32 capacity) {
    if (!b || !memory || capacity < 16U) return MGL_ERR_ARGUMENT;
#ifdef __MINIGPU__
    if ((unsigned)memory & 3U) return MGL_ERR_ARGUMENT; /* se accede por palabras */
#endif
    memset(b, 0, sizeof(*b));
    b->bytes = (unsigned char *)memory;
    b->capacity = capacity;
    return mgl_cmd_reset(b);
}

int mgl_cmd_reset(mgl_cmd_buffer_t *b) {
    if (!b || !b->bytes || b->capacity < 16U) return MGL_ERR_ARGUMENT;
    b->used = 16;
    b->sprite_count = 0;
    b->error = MGL_OK;
    header(b);
    return MGL_OK;
}

int mgl_cmd_status(const mgl_cmd_buffer_t *b) {
    return b ? b->error : MGL_ERR_ARGUMENT;
}

void mgl_set_deferred(mgl_cmd_buffer_t *b) {
    current = b;
    if (!b) {
        if (flags & FLAG_FILL)
            sw_fill(fill_color);
        else
            sw_no_fill();
        if (flags & FLAG_STROKE)
            sw_stroke(stroke_color);
        else
            sw_no_stroke();
        sw_stroke_weight((int)weight);
    }
}

void mgl_bind(mgl_color_t *p, int w, int h, int stride) {
    sw_bind(p, w, h, stride);
    target = p && w > 0 && h > 0 && stride >= w ? p : 0; /* como sw_bind */
    target_w = w;
    target_h = h;
    target_stride = stride;
    previous = 0;
    fill_color = stroke_color = 0xffff;
    flags = FLAG_FILL;
    weight = 1;
}

void mgl_set_target(mgl_color_t *p, const mgl_color_t *prev) {
    if (!target || !p) return;
    sw_set_target(p);
    target = p;
    previous = prev != p ? prev : 0;
}

/* Antes de dibujar encima: trae el lienzo si el framebuffer no lo tiene. */
static void ready(void) {
    int y;
    if (!previous) return;
    if (target_stride == target_w)
        memcpy(target, previous, (size_t)target_w * target_h * sizeof *target);
    else
        for (y = 0; y < target_h; y++)
            memcpy(target + y * target_stride, previous + y * target_stride,
                (size_t)target_w * sizeof *target);
    previous = 0;
}

void mgl_finish(void) {
    ready();
}

static void emit_clear(mgl_color_t color) {
    unsigned char *p;
    mgl_cmd_buffer_t *b = current;
    if (b->error) return;
    if (b->capacity - b->used < 16U) {
        b->error = MGL_ERR_SPACE;
        return;
    }
    p = b->bytes + b->used;
    WR32(p, OP_CLEAR);
    WR32(p + 4, 16);
    WR32(p + 8, color);
    WR32(p + 12, 0);
    b->used += 16;
    WR32(b->bytes + 8, b->used); /* de la cabecera solo cambia used */
}

static void emit(mgl_u32 type, mgl_u32 p0, mgl_u32 p1, mgl_u32 p2) {
    unsigned char *p;
    mgl_cmd_buffer_t *b = current;
    if (b->error) return;
    if (b->capacity - b->used < 40U) {
        b->error = MGL_ERR_SPACE;
        return;
    }
    p = b->bytes + b->used;
    WR32(p, OP_BATCH);
    WR32(p + 4, 40);
    WR32(p + 8, 1);
    WR32(p + 12, 0);
    WR32(p + 16, type);
    WR32(p + 20, p0);
    WR32(p + 24, p1);
    WR32(p + 28, p2);
    WR16(p + 32, fill_color);
    WR16(p + 34, stroke_color);
    WR16(p + 36, flags);
    WR16(p + 38, weight);
    b->used += 40;
    WR32(b->bytes + 8, b->used);
}

void mgl_clear(mgl_color_t c) {
    if (current)
        emit_clear(c);
    else {
        previous = 0;
        sw_clear(c);
    }
}

void mgl_fill(mgl_color_t c) {
    fill_color = c;
    flags |= FLAG_FILL;
    if (!current) sw_fill(c);
}

void mgl_no_fill(void) {
    flags &= ~FLAG_FILL;
    if (!current) sw_no_fill();
}

void mgl_stroke(mgl_color_t c) {
    stroke_color = c;
    flags |= FLAG_STROKE;
    if (!current) sw_stroke(c);
}

void mgl_no_stroke(void) {
    flags &= ~FLAG_STROKE;
    if (!current) sw_no_stroke();
}

void mgl_stroke_weight(int w) {
    weight = (unsigned int)(w > 0 ? w : 1);
    if (weight > 65535U) weight = 65535U;
    if (!current) sw_stroke_weight((int)weight);
}

void mgl_point(int x, int y) {
    if (current) {
        if (FIT(x) && FIT(y))
            emit(PR_POINT, PACK(x, y), 0, 0);
        else
            current->error = MGL_ERR_ARGUMENT;
    } else {
        ready();
        sw_point(x, y);
    }
}

void mgl_line(int x, int y, int a, int b) {
    if (current) {
        if (FIT(x) && FIT(y) && FIT(a) && FIT(b))
            emit(PR_LINE, PACK(x, y), PACK(a, b), 0);
        else
            current->error = MGL_ERR_ARGUMENT;
    } else {
        ready();
        sw_line(x, y, a, b);
    }
}

void mgl_rect(int x, int y, int w, int h) {
    if (current) {
        if (FIT(x) && FIT(y) && FIT(w) && FIT(h))
            emit(PR_RECT, PACK(x, y), PACK(w, h), 0);
        else
            current->error = MGL_ERR_ARGUMENT;
    } else {
        ready();
        sw_rect(x, y, w, h);
    }
}

void mgl_circle(int x, int y, int r) {
    if (current) {
        if (FIT(x) && FIT(y) && FIT(r))
            emit(PR_CIRCLE, PACK(x, y), PACK(r, 0), 0);
        else
            current->error = MGL_ERR_ARGUMENT;
    } else {
        ready();
        sw_circle(x, y, r);
    }
}

void mgl_triangle(int x, int y, int a, int b, int c, int d) {
    if (current) {
        if (FIT(x) && FIT(y) && FIT(a) && FIT(b) && FIT(c) && FIT(d))
            emit(PR_TRIANGLE, PACK(x, y), PACK(a, b), PACK(c, d));
        else
            current->error = MGL_ERR_ARGUMENT;
    } else {
        ready();
        sw_triangle(x, y, a, b, c, d);
    }
}

void mgl_image(const mgl_sprite_t *s, int x, int y) {
    unsigned int i;
    mgl_cmd_buffer_t *b = current;
    if (!b) {
        ready();
        sw_image(s, x, y);
        return;
    }
    if (b->error) return;
    if (!s || !FIT(x) || !FIT(y)) {
        b->error = MGL_ERR_ARGUMENT;
        return;
    }
    for (i = 0; i < b->sprite_count; i++)
        if (b->sprites[i] == s) break;
    if (i == b->sprite_count) {
        if (i >= 256U) {
            b->error = MGL_ERR_SPRITES;
            return;
        }
        b->sprites[i] = s;
        b->sprite_count++;
    }
    emit(PR_IMAGE, PACK(x, y), (mgl_u32)i, 0);
}

static void apply(unsigned int f, mgl_color_t fc, mgl_color_t sc, int w) {
    if (f & FLAG_FILL)
        sw_fill(fc);
    else
        sw_no_fill();
    if (f & FLAG_STROKE)
        sw_stroke(sc);
    else
        sw_no_stroke();
    sw_stroke_weight(w);
}

/* El offset del último CLEAR, o 0: lo de antes no se ve. Sin validar: si el
   buffer está mal, lo dice el recorrido de mgl_cmd_render_cpu. */
static mgl_u32 last_clear(const mgl_cmd_buffer_t *b) {
    mgl_u32 off, size, last = 0;
    for (off = 16; b->used - off >= 16U; off += size) {
        size = RD32(b->bytes + off + 4);
        if (size < 16U || size > b->used - off) break;
        if (RD32(b->bytes + off) == OP_CLEAR) last = off;
    }
    return last;
}

int mgl_cmd_render_cpu(const mgl_cmd_buffer_t *b) {
    mgl_u32 off, op, size, t, p0, p1, p2, first, colors, style, last_colors = 0, last_style = 0;
    int applied = 0; /* los atributos (dos palabras) solo se aplican si cambian */
    const unsigned char *p;
    mgl_cmd_buffer_t *saved = current;
    if (!b || !b->bytes || b->used < 16U || b->used > b->capacity || b->error)
        return MGL_ERR_ARGUMENT;
    if (RD32(b->bytes) != MGL_BUFFER_MAGIC || RD32(b->bytes + 4) != MGL_BUFFER_VERSION ||
        RD32(b->bytes + 8) != b->used || RD32(b->bytes + 12) != b->capacity)
        return MGL_ERR_ARGUMENT;
    first = last_clear(b);
    current = 0;
    for (off = 16; off < b->used; off += size) {
        if (b->used - off < 16U) {
            current = saved;
            return MGL_ERR_ARGUMENT;
        }
        p = b->bytes + off;
        op = RD32(p);
        size = RD32(p + 4);
        if (size < 16U || size > b->used - off) {
            current = saved;
            return MGL_ERR_ARGUMENT;
        }
        if (op == OP_CLEAR) {
            if (size != 16U) {
                current = saved;
                return MGL_ERR_ARGUMENT;
            }
            if (off < first) continue;
            previous = 0;
            sw_clear((mgl_color_t)RD32(p + 8));
        } else if (op == OP_BATCH) {
            if (size != 40U || RD32(p + 8) != 1U) {
                current = saved;
                return MGL_ERR_ARGUMENT;
            }
            t = RD32(p + 16);
            p0 = RD32(p + 20);
            p1 = RD32(p + 24);
            p2 = RD32(p + 28);
            if (t < PR_POINT || t > PR_IMAGE || (t == PR_IMAGE && p1 >= b->sprite_count)) {
                current = saved;
                return MGL_ERR_ARGUMENT;
            }
            if (off < first) continue;
            colors = RD32(p + 32); /* fill y stroke */
            style = RD32(p + 36);  /* flags y grosor */
            if (!applied || colors != last_colors || style != last_style) {
                apply(RD16(p + 36), (mgl_color_t)RD16(p + 32), (mgl_color_t)RD16(p + 34),
                    (int)RD16(p + 38));
                applied = 1;
                last_colors = colors;
                last_style = style;
            }
            ready();
            if (t == PR_POINT)
                sw_point(LOW(p0), HIGH(p0));
            else if (t == PR_LINE)
                sw_line(LOW(p0), HIGH(p0), LOW(p1), HIGH(p1));
            else if (t == PR_RECT)
                sw_rect(LOW(p0), HIGH(p0), LOW(p1), HIGH(p1));
            else if (t == PR_CIRCLE)
                sw_circle(LOW(p0), HIGH(p0), LOW(p1));
            else if (t == PR_TRIANGLE)
                sw_triangle(LOW(p0), HIGH(p0), LOW(p1), HIGH(p1), LOW(p2), HIGH(p2));
            else
                sw_image(b->sprites[p1], LOW(p0), HIGH(p0));
        } else {
            current = saved;
            return MGL_ERR_ARGUMENT;
        }
    }
    current = saved;
    return MGL_OK;
}
