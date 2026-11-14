#include "minigl3d.h"
#include "mgl_bytes.h"
#include "mgl_internal.h"

/* Lo que pide la aplicación (persiste entre frames) y lo emitido en el frame
   actual (se olvida en mgl_begin_frame). Matrices: índice MGL_MATRIX_* - 1. */
static mgl_render_target_t target;
static int has_target, in_frame;
static mgl_u32 frame_number;

static int viewport[4];
static mgl_mat4_t matrix[3];
static int matrices_ready;
static mgl_u32 state = MGL_STATE_DEFAULT;
static mgl_color_t color = 0xffff;

static int sent_viewport[4], viewport_sent;
/* matrix_sent[k]: matrix[k] ya está en el buffer tal cual. mgl_set_matrix
   compara al llegar (una vez por cambio) y no flush_state en cada dibujo. */
static int matrix_sent[3];
static mgl_u32 sent_state;
static int state_sent;
static mgl_color_t sent_color;
static int color_sent;
/* Lo que la aplicación ha tocado desde el último dibujo: flush_state solo compara eso con lo enviado (antes
   comparaba todo en cada dibujo, ~150 instrucciones en MiniGPU). Se sigue comparando con lo enviado, no solo
   marcando: un estado que cambia y vuelve antes del siguiente dibujo (mgl_set_cull en shape()) no emite nada. */
#define DIRTY_VIEWPORT 1U
#define DIRTY_MATRIX 2U
#define DIRTY_STATE 4U
#define DIRTY_COLOR 8U
#define DIRTY_ALL 15U
static unsigned int dirty = DIRTY_ALL;

static void fail(int error) {
    mgl_cmd_buffer_t *b = mgl_deferred_();
    if (b && !b->error) b->error = error;
}

/* La cabecera común; el payload lo escribe quien llama. 0 si no cabe. */
static unsigned char *command(mgl_u32 opcode, mgl_u32 flags, mgl_u32 size, mgl_u32 arg0, mgl_u32 arg1) {
    unsigned char *p = mgl_reserve3d_(size);
    if (!p) return 0;
    WR16(p + MGL_CMD_OPCODE, opcode);
    WR16(p + MGL_CMD_FLAGS, flags);
    WR32(p + MGL_CMD_SIZE, size);
    WR32(p + MGL_CMD_ARG0, arg0);
    WR32(p + MGL_CMD_ARG1, arg1);
    return p;
}

/* Las matrices empiezan siendo la identidad (no hay inicializador estático para eso). */
static void ensure_matrices(void) {
    if (matrices_ready) return;
    mgl_mat4_identity(&matrix[0]);
    mgl_mat4_identity(&matrix[1]);
    mgl_mat4_identity(&matrix[2]);
    matrices_ready = 1;
}

static void forget_sent(void) {
    viewport_sent = state_sent = color_sent = 0;
    matrix_sent[0] = matrix_sent[1] = matrix_sent[2] = 0;
    dirty = DIRTY_ALL;
}

static void emit_target(void) {
    unsigned char *p;
    int depth = target.depth_addr != 0;
    p = command(MGL_CMD_SET_RENDER_TARGET, 0, MGL_SET_RENDER_TARGET_BYTES, target.color_addr,
        target.depth_addr);
    if (!p) return;
    WR16(p + 16, target.width);
    WR16(p + 18, target.height);
    WR16(p + 20, target.color_stride);
    WR16(p + 22, depth ? target.depth_stride : 0);
    WR16(p + 24, MGL_COLOR_RGB565);
    WR16(p + 26, depth ? MGL_DEPTH_U16 : MGL_DEPTH_NONE);
    WR32(p + 28, 0);
    /* El renderer pone el viewport a todo el destino: lo emitido ya no vale. */
    viewport_sent = 0;
    dirty |= DIRTY_VIEWPORT;
    mgl_clear_flags_ = depth ? MGL_CLEAR_DEPTH : 0;
    mgl_clear_depth_ = depth ? MGL_DEPTH_ONE : 0;
}

void mgl_reset_state3d(void) {
    matrices_ready = 0;
    ensure_matrices();
    matrix_sent[0] = matrix_sent[1] = matrix_sent[2] = 0;
    dirty = DIRTY_ALL;
    state = MGL_STATE_DEFAULT;
    color = 0xffff;
    viewport[0] = viewport[1] = 0;
    viewport[2] = has_target ? target.width : 0;
    viewport[3] = has_target ? target.height : 0;
}

void mgl_set_render_target(const mgl_render_target_t *t) {
    if (!t || !t->color_addr || t->width <= 0 || t->height <= 0 || t->width > MGL_MAX_TARGET_DIM ||
        t->height > MGL_MAX_TARGET_DIM || t->color_stride < t->width ||
        t->color_stride > MGL_MAX_TARGET_DIM ||
        (t->depth_addr && (t->depth_stride < t->width || t->depth_stride > MGL_MAX_TARGET_DIM))) {
        fail(MGL_ERR_ARGUMENT);
        return;
    }
    target = *t;
    has_target = 1;
    viewport[0] = viewport[1] = 0;
    viewport[2] = t->width;
    viewport[3] = t->height;
    dirty |= DIRTY_VIEWPORT;
    if (in_frame) emit_target();
}

void mgl_begin_frame(void) {
    if (!mgl_deferred_()) return;
    if (in_frame) fail(MGL_ERR_STATE);
    in_frame = 1;
    frame_number++;
    mgl_frame_reset_();
    forget_sent();
    ensure_matrices();
    if (has_target)
        emit_target();
    else
        fail(MGL_ERR_STATE);
}

int mgl_end_frame(void) {
    mgl_cmd_buffer_t *b = mgl_deferred_();
    mgl_clear_flags_ = mgl_clear_depth_ = 0;
    if (!b) return MGL_ERR_STATE;
    if (!in_frame) fail(MGL_ERR_STATE);
    in_frame = 0;
    command(MGL_CMD_END_FRAME, 0, MGL_END_FRAME_BYTES, frame_number, 0);
    return b->error;
}

static void clear_depth(mgl_color_t c, mgl_real_t depth, mgl_u32 flags) {
    mgl_u32 d;
    if (!mgl_deferred_()) return;
    if (!in_frame || !target.depth_addr) {
        fail(MGL_ERR_STATE);
        return;
    }
    if (!(depth > 0.0f))
        d = 0;
    else if (depth >= 1.0f)
        d = MGL_DEPTH_ONE;
    else
        d = (mgl_u32)mgl_round(depth * 65536.0f);
    command(MGL_CMD_CLEAR, flags, MGL_CLEAR_BYTES, c, d);
}

void mgl_clear_color_depth(mgl_color_t c, mgl_real_t depth) {
    clear_depth(c, depth, MGL_CLEAR_DEPTH);
}

void mgl_clear_depth(mgl_real_t depth) {
    clear_depth(0, depth, MGL_CLEAR_DEPTH | MGL_CLEAR_KEEP_COLOR);
}

void mgl_set_viewport(int x, int y, int w, int h) {
    if (x < -MGL_MAX_VIEWPORT_POS || x > MGL_MAX_VIEWPORT_POS || y < -MGL_MAX_VIEWPORT_POS ||
        y > MGL_MAX_VIEWPORT_POS || w <= 0 || h <= 0 || w > MGL_MAX_TARGET_DIM ||
        h > MGL_MAX_TARGET_DIM) {
        fail(MGL_ERR_ARGUMENT);
        return;
    }
    viewport[0] = x;
    viewport[1] = y;
    viewport[2] = w;
    viewport[3] = h;
    dirty |= DIRTY_VIEWPORT;
}

/* Bit a bit: 0.0f y -0.0f son distintos para el command buffer. Processing fija las tres matrices en cada
   dibujo, así que se compara mucho: en MiniGPU como palabras (lcc no tiene strict aliasing), sin llamar a
   mgl_real_to_f32 por elemento. */
static int same_matrix(const mgl_mat4_t *a, const mgl_mat4_t *b) {
    int i;
#ifdef __MINIGPU__
    const mgl_u32 *p = (const mgl_u32 *)a->m, *q = (const mgl_u32 *)b->m;
    for (i = 0; i < 16; i += 4, p += 4, q += 4)
        if (p[0] != q[0] || p[1] != q[1] || p[2] != q[2] || p[3] != q[3]) return 0;
#else
    for (i = 0; i < 16; i++)
        if (mgl_real_to_f32(a->m[i]) != mgl_real_to_f32(b->m[i])) return 0;
#endif
    return 1;
}

void mgl_set_matrix(unsigned int which, const mgl_mat4_t *m) {
    if (which < MGL_MATRIX_MODEL || which > MGL_MATRIX_PROJECTION || !m) {
        fail(MGL_ERR_ARGUMENT);
        return;
    }
    ensure_matrices();
    if (same_matrix(&matrix[which - 1U], m)) return;
    matrix[which - 1U] = *m;
    matrix_sent[which - 1U] = 0;
    dirty |= DIRTY_MATRIX;
}

static void set_bit(mgl_u32 bit, int on) {
    if (on)
        state |= bit;
    else
        state &= ~bit;
    dirty |= DIRTY_STATE;
}

void mgl_set_depth_test(int on) {
    set_bit(MGL_STATE_DEPTH_TEST, on);
}

void mgl_set_depth_write(int on) {
    set_bit(MGL_STATE_DEPTH_WRITE, on);
}

void mgl_set_cull(int mode) {
    if (mode < MGL_CULL_NONE || mode > MGL_CULL_FRONT) {
        fail(MGL_ERR_ARGUMENT);
        return;
    }
    set_bit(MGL_STATE_CULL_BACK, mode == MGL_CULL_BACK);
    set_bit(MGL_STATE_CULL_FRONT, mode == MGL_CULL_FRONT);
}

void mgl_set_color(mgl_color_t c) {
    color = c;
    dirty |= DIRTY_COLOR;
}

static void flush_state(void) {
    unsigned char *p;
    unsigned int i, k, d = dirty; /* en local: mini-lcc recargaba la global en cada comprobación */
    if (!d) return;
    if ((d & DIRTY_VIEWPORT) && (!viewport_sent || sent_viewport[0] != viewport[0] || sent_viewport[1] != viewport[1] ||
        sent_viewport[2] != viewport[2] || sent_viewport[3] != viewport[3])) {
        if (!command(MGL_CMD_SET_VIEWPORT, 0, MGL_SET_VIEWPORT_BYTES, PACK(viewport[0], viewport[1]),
                PACK(viewport[2], viewport[3])))
            return;
        for (i = 0; i < 4; i++) sent_viewport[i] = viewport[i];
        viewport_sent = 1;
    }
    /* Projection, View y Model: el orden en que se componen. */
    if (d & DIRTY_MATRIX)
        for (k = 3; k >= 1; k--) {
            if (matrix_sent[k - 1]) continue;
            p = command(MGL_CMD_SET_MATRIX, 0, MGL_SET_MATRIX_BYTES, k, MGL_FORMAT_FLOAT32);
            if (!p) return;
            for (i = 0; i < 16; i++) WR32(p + 16 + 4 * i, mgl_real_to_f32(matrix[k - 1].m[i]));
            matrix_sent[k - 1] = 1;
        }
    if ((d & DIRTY_STATE) && (!state_sent || sent_state != state)) {
        if (!command(MGL_CMD_SET_RENDER_STATE, 0, MGL_SET_RENDER_STATE_BYTES, state, 0)) return;
        sent_state = state;
        state_sent = 1;
    }
    if ((d & DIRTY_COLOR) && (!color_sent || sent_color != color)) {
        if (!command(MGL_CMD_SET_COLOR, 0, MGL_SET_COLOR_BYTES, color, 0)) return;
        sent_color = color;
        color_sent = 1;
    }
    dirty = 0;
}

/* Un tramo [first, first + count) de los índices: la misma malla, con la
   dirección de los índices desplazada. Así se dibuja cada parte de una malla
   con su propio estado (un color por cara) sin cambiar DRAW_INDEXED. */
static void draw_range(mgl_mesh_t mesh, mgl_u32 first, mgl_u32 count, int uniform) {
    mgl_mesh_desc_t d;
    unsigned char *p;
    if (!mgl_deferred_()) return;
    if (!in_frame || !has_target) {
        fail(MGL_ERR_STATE);
        return;
    }
    if (mgl_mesh_info(mesh, &d) != MGL_OK) {
        fail(MGL_ERR_HANDLE);
        return;
    }
    if (first % 3U || count % 3U || first > d.index_count || count > d.index_count - first) {
        fail(MGL_ERR_ARGUMENT);
        return;
    }
    if (!count) return;
    flush_state();
    p = command(MGL_CMD_DRAW_INDEXED, 0, MGL_DRAW_INDEXED_BYTES, d.vertex_addr, d.index_addr + first * 2U);
    if (!p) return;
    WR32(p + 16, d.vertex_count);
    WR32(p + 20, count);
    /* uniform: los mismos datos como solo posición (el stride salta el color), y el color de SET_COLOR. */
    WR16(p + 24, uniform ? MGL_VERTEX_POSITION_F32_XYZ : d.vertex_format);
    WR16(p + 26, d.index_format);
    WR16(p + 28, d.vertex_stride);
    WR16(p + 30, MGL_TOPOLOGY_TRIANGLES);
}

void mgl_draw_mesh_range(mgl_mesh_t mesh, mgl_u32 first, mgl_u32 count) {
    draw_range(mesh, first, count, 0);
}

void mgl_draw_mesh_range_uniform(mgl_mesh_t mesh, mgl_u32 first, mgl_u32 count) {
    draw_range(mesh, first, count, 1);
}

void mgl_draw_mesh(mgl_mesh_t mesh) {
    mgl_mesh_desc_t d;
    if (mgl_mesh_info(mesh, &d) != MGL_OK) d.index_count = 0; /* el error lo da mgl_draw_mesh_range */
    mgl_draw_mesh_range(mesh, 0, d.index_count);
}
