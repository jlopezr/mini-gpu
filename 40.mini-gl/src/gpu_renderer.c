#include "gpu_renderer.h"

/* C89; unsigned int = 32 bits, unsigned short = 16 bits, long >= 32 bits. */
typedef char mgl_gpu_check_u32[(sizeof(mgl_u32) == 4) ? 1 : -1];
typedef char mgl_gpu_check_u16[(sizeof(mgl_color_t) == 2) ? 1 : -1];

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

#ifdef __MINIGPU__
#include "gpu.h"
#else
#define NOALIAS(p) ((void)0)
#endif

static mgl_u32 rd32(const unsigned char *p) {
    return (mgl_u32)p[0] | ((mgl_u32)p[1] << 8) | ((mgl_u32)p[2] << 16) | ((mgl_u32)p[3] << 24);
}

static unsigned int rd16(const unsigned char *p) {
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8);
}

static int sx16(mgl_u32 n) {
    unsigned int x = (unsigned int)(n & 65535U);
    return x >= 32768U ? (int)x - 65536 : (int)x;
}

static int lo(mgl_u32 n) {
    return sx16(n);
}

static int hi(mgl_u32 n) {
    return sx16(n >> 16);
}

static int min2(int a, int b) {
    return a < b ? a : b;
}

static int max2(int a, int b) {
    return a > b ? a : b;
}

static int abs2(int a) {
    return a < 0 ? -a : a;
}

/* A framebuffer pixel is owned by exactly one lane, even with thick strokes. */
static void put(const mgl_gpu_job_t *j, int lane, int x, int y, unsigned int c) {
    if (x >= 0 && x < j->width && y >= 0 && y < j->height && (x & (MGL_GPU_LANES - 1)) == lane)
        j->framebuffer[y * j->pitch + x] = (mgl_color_t)c;
}

static void brush(const mgl_gpu_job_t *j, int lane, int x, int y, int weight, unsigned int c) {
    int a, b, low = -(weight / 2), high = low + weight;
    for (b = low; b < high; b++)
        for (a = low; a < high; a++) put(j, lane, x + a, y + b, c);
}

static void segment(
    const mgl_gpu_job_t *j, int lane, int x0, int y0, int x1, int y1, int weight, unsigned int c) {
    int dx = abs2(x1 - x0), dy = abs2(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    int err = dx - dy, e;
    for (;;) {
        brush(j, lane, x0, y0, weight, c);
        if (x0 == x1 && y0 == y1) break;
        e = 2 * err;
        if (e > -dy) {
            err -= dy;
            x0 += sx;
        }
        if (e < dx) {
            err += dx;
            y0 += sy;
        }
    }
}

static long edge(int ax, int ay, int bx, int by, int px, int py) {
    return (long)(px - ax) * (by - ay) - (long)(py - ay) * (bx - ax);
}

static void primitive(const mgl_gpu_job_t *j, int lane, mgl_u32 type, mgl_u32 p0, mgl_u32 p1,
    mgl_u32 p2, unsigned int fc, unsigned int sc, unsigned int flags, int weight) {
    int x, y, a, b, c, d, i, k, x0, x1, y0, y1, r, xx, yy, dd;
    long rr, aa, bb, cc, area;
    const mgl_gpu_sprite_t *s;
    x = lo(p0);
    y = hi(p0);
    a = lo(p1);
    b = hi(p1);
    if (type == PR_POINT) {
        if (flags & FLAG_STROKE) brush(j, lane, x, y, weight, sc);
    } else if (type == PR_LINE) {
        if (flags & FLAG_STROKE) segment(j, lane, x, y, a, b, weight, sc);
    } else if (type == PR_RECT) {
        if (a <= 0 || b <= 0) return;
        x0 = max2(0, x);
        y0 = max2(0, y);
        x1 = min2(j->width, x + a);
        y1 = min2(j->height, y + b);
        if (flags & FLAG_FILL) {
            /* Start at first owned column; every iteration writes one pixel. */
            i = x0 + ((lane - (x0 & 7) + 8) & 7);
            for (k = y0; k < y1; k++)
                for (dd = i; dd < x1; dd += MGL_GPU_LANES) j->framebuffer[k * j->pitch + dd] = (mgl_color_t)fc;
        }
        if (flags & FLAG_STROKE) {
            segment(j, lane, x, y, x + a - 1, y, weight, sc);
            segment(j, lane, x + a - 1, y, x + a - 1, y + b - 1, weight, sc);
            segment(j, lane, x + a - 1, y + b - 1, x, y + b - 1, weight, sc);
            segment(j, lane, x, y + b - 1, x, y, weight, sc);
        }
    } else if (type == PR_CIRCLE) {
        r = a;
        if (r < 0) return;
        rr = (long)r * r;
        if (flags & FLAG_FILL) {
            x0 = max2(0, x - r);
            x1 = min2(j->width - 1, x + r);
            y0 = max2(0, y - r);
            y1 = min2(j->height - 1, y + r);
            i = x0 + ((lane - (x0 & 7) + 8) & 7);
            for (k = y0; k <= y1; k++)
                for (dd = i; dd <= x1; dd += MGL_GPU_LANES) {
                    long dx = (long)dd - x, dy = (long)k - y;
                    if (dx * dx + dy * dy <= rr) put(j, lane, dd, k, fc);
                }
        }
        if (flags & FLAG_STROKE) {
            xx = r;
            yy = 0;
            dd = 1 - r;
            while (xx >= yy) {
                brush(j, lane, x + xx, y + yy, weight, sc);
                brush(j, lane, x + yy, y + xx, weight, sc);
                brush(j, lane, x - yy, y + xx, weight, sc);
                brush(j, lane, x - xx, y + yy, weight, sc);
                brush(j, lane, x - xx, y - yy, weight, sc);
                brush(j, lane, x - yy, y - xx, weight, sc);
                brush(j, lane, x + yy, y - xx, weight, sc);
                brush(j, lane, x + xx, y - yy, weight, sc);
                yy++;
                if (dd < 0)
                    dd += 2 * yy + 1;
                else {
                    xx--;
                    dd += 2 * (yy - xx) + 1;
                }
            }
        }
    } else if (type == PR_TRIANGLE) {
        c = lo(p2);
        d = hi(p2);
        area = edge(x, y, a, b, c, d);
        if ((flags & FLAG_FILL) && area != 0) {
            x0 = max2(0, min2(x, min2(a, c)));
            x1 = min2(j->width - 1, max2(x, max2(a, c)));
            y0 = max2(0, min2(y, min2(b, d)));
            y1 = min2(j->height - 1, max2(y, max2(b, d)));
            i = x0 + ((lane - (x0 & 7) + 8) & 7);
            for (k = y0; k <= y1; k++)
                for (dd = i; dd <= x1; dd += MGL_GPU_LANES) {
                    aa = edge(x, y, a, b, dd, k);
                    bb = edge(a, b, c, d, dd, k);
                    cc = edge(c, d, x, y, dd, k);
                    if ((aa >= 0 && bb >= 0 && cc >= 0) || (aa <= 0 && bb <= 0 && cc <= 0))
                        put(j, lane, dd, k, fc);
                }
        }
        if (flags & FLAG_STROKE) {
            segment(j, lane, x, y, a, b, weight, sc);
            segment(j, lane, a, b, c, d, weight, sc);
            segment(j, lane, c, d, x, y, weight, sc);
        }
    } else if (type == PR_IMAGE) {
        if (p1 >= j->sprite_count) return;
        s = &j->sprites[p1];
        if (!s->pixels || s->width <= 0 || s->height <= 0 || s->stride < s->width) return;
        x0 = max2(0, x);
        x1 = min2(j->width, x + s->width);
        y0 = max2(0, y);
        y1 = min2(j->height, y + s->height);
        i = x0 + ((lane - (x0 & 7) + 8) & 7);
        for (k = y0; k < y1; k++)
            for (dd = i; dd < x1; dd += MGL_GPU_LANES)
                j->framebuffer[k * j->pitch + dd] = s->pixels[(k - y) * s->stride + (dd - x)];
    }
}

static int validate(const mgl_gpu_job_t *j) {
    mgl_u32 off, size, op, t;
    const unsigned char *p;
    if (!j || !j->commands || !j->framebuffer || j->width <= 0 || j->height <= 0 ||
        j->pitch < j->width || j->command_bytes < 16U || (j->sprite_count && !j->sprites) ||
        j->sprite_count > MGL_GPU_MAX_SPRITES)
        return MGL_ERR_ARGUMENT;
    p = j->commands;
    if (rd32(p) != MGL_BUFFER_MAGIC || rd32(p + 4) != MGL_BUFFER_VERSION ||
        rd32(p + 8) != j->command_bytes || rd32(p + 12) < j->command_bytes)
        return MGL_ERR_ARGUMENT;
    for (off = 16; off < j->command_bytes; off += size) {
        if (j->command_bytes - off < 16U) return MGL_ERR_ARGUMENT;
        p = j->commands + off;
        op = rd32(p);
        size = rd32(p + 4);
        if (size < 16U || size > j->command_bytes - off) return MGL_ERR_ARGUMENT;
        if (op == OP_CLEAR) {
            if (size != 16U) return MGL_ERR_ARGUMENT;
        } else if (op == OP_BATCH) {
            if (size != 40U || rd32(p + 8) != 1U) return MGL_ERR_ARGUMENT;
            t = rd32(p + 16);
            if (t < PR_POINT || t > PR_IMAGE) return MGL_ERR_ARGUMENT;
            if (t == PR_IMAGE && rd32(p + 24) >= j->sprite_count) return MGL_ERR_ARGUMENT;
        } else
            return MGL_ERR_ARGUMENT;
    }
    return MGL_OK;
}

/* Lo que hace una lane: todos los comandos, cada uno en las columnas que son suyas. Las lanes no comparten
   pixeles, asi que da igual que vayan a la vez (un warp en la GPU) o una tras otra (el host). */
static void render(const mgl_gpu_job_t *j, int lane) {
    mgl_u32 off, op, size, p0, p1, p2;
    const unsigned char *p;
    int x, y;
    NOALIAS(j); /* nadie escribe el trabajo: mini-opt saca de los bucles lo que se lee de el */
    for (off = 16; off < j->command_bytes; off += size) {
        p = j->commands + off;
        op = rd32(p);
        size = rd32(p + 4);
        if (op == OP_CLEAR) {
            mgl_color_t color = (mgl_color_t)rd32(p + 8);
            for (y = 0; y < j->height; y++)
                for (x = lane; x < j->width; x += MGL_GPU_LANES)
                    j->framebuffer[y * j->pitch + x] = color;
        } else {
            p0 = rd32(p + 20);
            p1 = rd32(p + 24);
            p2 = rd32(p + 28);
            primitive(j, lane, rd32(p + 16), p0, p1, p2, rd16(p + 32), rd16(p + 34), rd16(p + 36),
                (int)rd16(p + 38));
        }
    }
}

#ifdef __MINIGPU__
/* Un warp de 8 lanes; el trabajo ya esta validado por la CPU. */
void KERNEL(mgl_render)(const mgl_gpu_job_t *j) {
    render(j, __gpu_lane);
}

int mgl_gpu_render(const mgl_gpu_job_t *j) {
    if (validate(j) != MGL_OK) return MGL_ERR_ARGUMENT;
    return GPU_RUN(mgl_render, 1, j) == GPU_OK ? MGL_OK : MGL_ERR_ARGUMENT;
}
#else
int mgl_gpu_render(const mgl_gpu_job_t *j) {
    int lane;
    if (validate(j) != MGL_OK) return MGL_ERR_ARGUMENT;
    for (lane = 0; lane < MGL_GPU_LANES; lane++) render(j, lane);
    return MGL_OK;
}
#endif

int mgl_gpu_sprites_from_cmd(
    const mgl_cmd_buffer_t *src, mgl_gpu_sprite_t *dst, unsigned int capacity) {
    unsigned int i;
    if (!src || (src->sprite_count && !dst) || capacity < src->sprite_count)
        return MGL_ERR_ARGUMENT;
    for (i = 0; i < src->sprite_count; i++) {
        if (!src->sprites[i]) return MGL_ERR_ARGUMENT;
        dst[i].pixels = src->sprites[i]->pixels;
        dst[i].width = src->sprites[i]->width;
        dst[i].height = src->sprites[i]->height;
        dst[i].stride = src->sprites[i]->stride;
    }
    return MGL_OK;
}
