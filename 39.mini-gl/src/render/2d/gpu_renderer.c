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

/* El raster de V0, compilado aqui por lanes: cada lane dibuja solo sus columnas (raster.c). En la GPU, la lane
   es __gpu_lane; en el host las lanes van una tras otra y es una variable. */
#define MGL_RASTER_LANES
#ifdef __MINIGPU__
#include "gpu.h"
#define RASTER_LANE __gpu_lane
#else
#define NOALIAS(p) ((void)0)
static int host_lane;
#define RASTER_LANE host_lane
#endif
#include "raster.c"

static mgl_u32 rd32(const unsigned char *p) {
    return (mgl_u32)p[0] | ((mgl_u32)p[1] << 8) | ((mgl_u32)p[2] << 16) | ((mgl_u32)p[3] << 24);
}

static unsigned int rd16(const unsigned char *p) {
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8);
}

static int lo(mgl_u32 n) {
    return (int)(n << 16) >> 16;
}

static int hi(mgl_u32 n) {
    return (int)n >> 16;
}

/* El punto k de un borde de hasta cinco puntos (el ultimo repite el primero si es cerrado). */
#define PICK(k, a, b, c, d, e) ((k) == 0 ? (a) : (k) == 1 ? (b) : (k) == 2 ? (c) : (k) == 3 ? (d) : (e))

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

/* Lo que hace cada lane: lo mismo que mgl_cmd_render_cpu (V1), con el raster por lanes. Las lanes no comparten
   pixeles, asi que da igual que vayan a la vez (un warp en la GPU) o una tras otra (el host). */
static void render(const mgl_gpu_job_t *j) {
    mgl_u32 off, op, size, t, p0, p1, p2, colors, style, last_colors = 0, last_style = 0;
    unsigned int flags;
    int applied = 0, n, k, x0, y0, x1, y1, x2, y2, x3, y3;
    const unsigned char *p;
    NOALIAS(j); /* nadie escribe el trabajo: mini-opt saca de los bucles lo que se lee de el */
    sw_bind(j->framebuffer, j->width, j->height, j->pitch);
    for (off = 16; off < j->command_bytes; off += size) {
        p = j->commands + off;
        op = rd32(p);
        size = rd32(p + 4);
        if (op == OP_CLEAR) {
            sw_clear((mgl_color_t)rd32(p + 8));
            continue;
        }
        colors = rd32(p + 32); /* fill y stroke */
        style = rd32(p + 36);  /* flags y grosor */
        if (!applied || colors != last_colors || style != last_style) {
            flags = rd16(p + 36);
            if (flags & FLAG_FILL)
                sw_fill((mgl_color_t)rd16(p + 32));
            else
                sw_no_fill();
            if (flags & FLAG_STROKE)
                sw_stroke((mgl_color_t)rd16(p + 34));
            else
                sw_no_stroke();
            sw_stroke_weight((int)rd16(p + 38));
            applied = 1;
            last_colors = colors;
            last_style = style;
        }
        t = rd32(p + 16);
        p0 = rd32(p + 20);
        p1 = rd32(p + 24);
        p2 = rd32(p + 28);
        /* Los bordes de line, rect y triangle van aparte (raster.c): n lados, del punto k al k + 1. */
        n = 0;
        x0 = lo(p0);
        y0 = hi(p0);
        x1 = lo(p1);
        y1 = hi(p1);
        x2 = x3 = x0;
        y2 = y3 = y0;
        if (t == PR_POINT)
            sw_point(x0, y0);
        else if (t == PR_LINE)
            n = 1;
        else if (t == PR_RECT) {
            sw_rect(x0, y0, x1, y1);
            if (x1 > 0 && y1 > 0) { /* (x, y), (x + w - 1, y), (x + w - 1, y + h - 1), (x, y + h - 1) */
                n = 4;
                x3 = x0;
                y3 = y0 + y1 - 1;
                x2 = x0 + x1 - 1;
                y2 = y3;
                x1 = x2;
                y1 = y0;
            }
        } else if (t == PR_CIRCLE)
            sw_circle(x0, y0, x1);
        else if (t == PR_TRIANGLE) {
            x2 = lo(p2);
            y2 = hi(p2);
            sw_triangle(x0, y0, x1, y1, x2, y2);
            n = 3;
            x3 = x0;
            y3 = y0;
        } else
            sw_image(&j->sprites[p1], x0, y0);
        if (stroke_on) /* un solo sitio que llama a segment: el kernel lleva una copia */
            for (k = 0; k < n; k++)
                segment(PICK(k, x0, x1, x2, x3, x0), PICK(k, y0, y1, y2, y3, y0),
                    PICK(k + 1, x0, x1, x2, x3, x0), PICK(k + 1, y0, y1, y2, y3, y0), sc);
    }
}

#ifdef __MINIGPU__
/* Un warp de 8 lanes; el trabajo ya esta validado por la CPU. */
void KERNEL(mgl_render)(const mgl_gpu_job_t *j) {
    render(j);
}

int mgl_gpu_render(const mgl_gpu_job_t *j) {
    if (validate(j) != MGL_OK) return MGL_ERR_ARGUMENT;
    return GPU_RUN(mgl_render, 1, j) == GPU_OK ? MGL_OK : MGL_ERR_ARGUMENT;
}
#else
int mgl_gpu_render(const mgl_gpu_job_t *j) {
    int lane;
    if (validate(j) != MGL_OK) return MGL_ERR_ARGUMENT;
    for (lane = 0; lane < MGL_GPU_LANES; lane++) {
        host_lane = lane;
        render(j);
    }
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
