#include "mgr_stages.h"
#include "mgl_bytes.h"

/* Decodificador: recorre el buffer por size_bytes, valida cada comando (tamaño
   exacto, flags, reservados) y lo pasa a su etapa. Un comando que no se
   entiende detiene la ejecución: es preferible a dibujar algo a medias con un
   estado equivocado. */

int mgr_init(mgr_renderer_t *r, const mgl_memory_t *m) {
    if (!r || !m || !m->base) return MGR_ERR_FORMAT;
    r->memory = *m;
    mgr_state_reset(&r->state);
    mgr_reset_stats(r);
    r->error_offset = 0;
    return MGR_OK;
}

void mgr_reset_stats(mgr_renderer_t *r) {
    r->stats.commands = r->stats.frames = r->stats.triangles = r->stats.rejected = 0;
    r->stats.clipped = r->stats.culled = r->stats.rasterized = r->stats.fragments = 0;
}

/* El tamaño que debe tener cada opcode (0: desconocido). */
static mgl_u32 expected_size(unsigned int op) {
    switch (op) {
    case MGL_CMD_CLEAR:
        return MGL_CLEAR_BYTES;
    case MGL_CMD_BATCH:
        return MGL_BATCH_BYTES;
    case MGL_CMD_SET_RENDER_TARGET:
        return MGL_SET_RENDER_TARGET_BYTES;
    case MGL_CMD_SET_VIEWPORT:
        return MGL_SET_VIEWPORT_BYTES;
    case MGL_CMD_SET_MATRIX:
        return MGL_SET_MATRIX_BYTES;
    case MGL_CMD_SET_RENDER_STATE:
        return MGL_SET_RENDER_STATE_BYTES;
    case MGL_CMD_SET_COLOR:
        return MGL_SET_COLOR_BYTES;
    case MGL_CMD_DRAW_INDEXED:
        return MGL_DRAW_INDEXED_BYTES;
    case MGL_CMD_END_FRAME:
        return MGL_END_FRAME_BYTES;
    default:
        return 0;
    }
}

static int clear(mgr_state_t *s, const unsigned char *p, unsigned int flags) {
    mgl_u32 color = RD32(p + MGL_CMD_ARG0), depth = RD32(p + MGL_CMD_ARG1);
    if (color > 0xffffU || (flags & ~MGL_CLEAR_DEPTH) || depth > MGL_DEPTH_ONE ||
        (!(flags & MGL_CLEAR_DEPTH) && depth))
        return MGR_ERR_FORMAT;
    if (!s->color) return MGR_ERR_STATE;
    mgr_clear_color(s, (mgl_color_t)color);
    /* Q16.16 en [0, 1] a 0..65535, redondeando. */
    if (flags & MGL_CLEAR_DEPTH) mgr_clear_depth(s, (mgl_u16)((depth * 65535U + 0x8000U) >> 16));
    return MGR_OK;
}

static int execute(mgr_renderer_t *r, const unsigned char *p, unsigned int op, unsigned int flags) {
    mgr_state_t *s = &r->state;
    int result;
    if (flags && op != MGL_CMD_CLEAR) return MGR_ERR_FORMAT;
    switch (op) {
    case MGL_CMD_CLEAR:
        return clear(s, p, flags);
    case MGL_CMD_BATCH:
        return mgr_raster2d_batch(s, p);
    case MGL_CMD_SET_RENDER_TARGET:
        result = mgr_state_target(s, &r->memory, p);
        if (result == MGR_OK) mgr_raster2d_target(s);
        return result;
    case MGL_CMD_SET_VIEWPORT:
        return mgr_state_viewport(s, p);
    case MGL_CMD_SET_MATRIX:
        return mgr_state_matrix(s, p);
    case MGL_CMD_SET_RENDER_STATE:
        return mgr_state_flags(s, p);
    case MGL_CMD_SET_COLOR:
        return mgr_state_color(s, p);
    case MGL_CMD_DRAW_INDEXED:
        return mgr_draw_indexed(s, &r->stats, &r->memory, p);
    default: /* END_FRAME */
        if (RD32(p + MGL_CMD_ARG1)) return MGR_ERR_FORMAT;
        r->stats.frames++;
        mgr_state_reset(s);
        return MGR_OK;
    }
}

int mgr_execute(mgr_renderer_t *r, mgl_u32 addr) {
    const unsigned char *p;
    mgl_u32 used, off, size;
    unsigned int op;
    int result;
    if (!r) return MGR_ERR_FORMAT;
    r->error_offset = 0;
    mgr_state_reset(&r->state);
    p = (const unsigned char *)mgl_memory_ptr(&r->memory, addr, MGL_BUFFER_HEADER_BYTES, 4);
    if (!p) return MGR_ERR_MEMORY;
    used = RD32(p + 8);
    if (RD32(p) != MGL_BUFFER_MAGIC || RD32(p + 4) != MGL_BUFFER_VERSION_3D || used < 16U ||
        used > RD32(p + 12) || (used & 3U))
        return MGR_ERR_FORMAT;
    p = (const unsigned char *)mgl_memory_ptr(&r->memory, addr, used, 4);
    if (!p) return MGR_ERR_MEMORY;
    for (off = MGL_BUFFER_HEADER_BYTES; off < used; off += size) {
        r->error_offset = off;
        if (used - off < MGL_CMD_HEADER_BYTES) return MGR_ERR_FORMAT;
        op = RD16(p + off + MGL_CMD_OPCODE);
        size = RD32(p + off + MGL_CMD_SIZE);
        if (size < MGL_CMD_HEADER_BYTES || (size & 3U) || size > used - off ||
            size != expected_size(op))
            return MGR_ERR_FORMAT;
        result = execute(r, p + off, op, RD16(p + off + MGL_CMD_FLAGS));
        if (result != MGR_OK) return result;
        r->stats.commands++;
    }
    r->error_offset = 0;
    return MGR_OK;
}
