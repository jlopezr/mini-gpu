#include "context3d.h"


mgl_memory_t context3d_memory;
mgr_renderer_t context3d_renderer;
mgl_cmd_buffer_t context3d_commands;

static mgl_u32 color_target;
static int bad_size;

static void set_target(void) {
    mgl_render_target_t t;
    t.color_addr = color_target;
    t.depth_addr = P3D_DEPTH;
    t.width = width;
    t.height = height;
    t.color_stride = width;
    t.depth_stride = width;
    mgl_set_render_target(&t);
}

/* size(w, h, P3D) en un sketch (processing3d.h). Como mucho P3D_MAX_W x
   P3D_MAX_H: es lo que cabe en el mapa de memoria. */
void size_renderer(int w, int h, int renderer) {
    if (w <= 0 || h <= 0 || w > P3D_MAX_W || h > P3D_MAX_H || (renderer != P2D && renderer != P3D)) {
        bad_size = 1;
        return;
    }
    width = w;
    height = h;
    mouseX = pmouseX = w / 2;
    mouseY = pmouseY = h / 2;
    processing3d_size(w, h);
    set_target(); /* dentro del frame de setup(): emite SET_RENDER_TARGET */
}

int context3d_init(void *ram) {
    void *commands;
    bad_size = 0;
    if (mgl_memory_init(&context3d_memory, ram, P3D_RAM_BASE, P3D_RAM_SIZE)) return 1;
    commands = mgl_memory_ptr(&context3d_memory, P3D_COMMANDS, P3D_COMMAND_BYTES, 4);
    if (!commands || mgl_cmd_init(&context3d_commands, commands, P3D_COMMAND_BYTES) != MGL_OK) return 1;
    if (mgl_resources_init(&context3d_memory, P3D_HEAP, P3D_HEAP_BYTES) != MGL_OK ||
        mgl_frame_memory_init(P3D_FRAME_HEAP, P3D_FRAME_HEAP_BYTES) != MGL_OK)
        return 1;
    if (mgr_init(&context3d_renderer, &context3d_memory) != MGR_OK) return 1;
    mgl_reset_state3d();
    frameCount = 0;
    width = P3D_MAX_W;
    height = P3D_MAX_H;
    mouseX = pmouseX = width / 2;
    mouseY = pmouseY = height / 2;
    processing3d_size(width, height);
    return 0;
}

int context3d_begin(mgl_u32 color_addr) {
    color_target = color_addr;
    set_target();
    if (mgl_cmd_reset(&context3d_commands) != MGL_OK) return MGL_ERR_ARGUMENT;
    mgl_set_deferred(&context3d_commands);
    mgl_begin_frame();
    processing3d_begin_draw();
    return MGL_OK;
}

int context3d_end(void (*before_execute)(void)) {
    int r = mgl_end_frame();
    mgl_set_deferred(0);
    if (bad_size) return MGL_ERR_ARGUMENT;
    if (r != MGL_OK) return r;
    if (before_execute) before_execute();
    return mgr_execute(&context3d_renderer, P3D_COMMANDS);
}

mgl_color_t *context3d_pixels(mgl_u32 addr) {
    return (mgl_color_t *)mgl_memory_ptr(&context3d_memory, addr,
        (mgl_u32)(P3D_MAX_W * P3D_MAX_H * 2), 2);
}

/* Adaptación al ciclo común de plataforma. */
int mgl_context_is3d(void) { return 1; }
int mgl_context_set_version(int version) { return version == 0 ? MGL_OK : MGL_ERR_ARGUMENT; }
mgl_u32 mgl_context_ram_size(void) { return P3D_RAM_SIZE; }
int mgl_context_init(void *ram, int version) {
    if (version != 0) return MGL_ERR_ARGUMENT;
    return context3d_init(ram) ? MGL_ERR_ARGUMENT : MGL_OK;
}
void mgl_context_shutdown(void) { mgl_set_deferred(0); }
int mgl_context_begin(mgl_u32 back, mgl_u32 front) {
    (void)front; /* El pipeline 3D no copia el lienzo entre buffers. */
    return context3d_begin(back);
}
int mgl_context_end(void (*before_execute)(void)) {
    return context3d_end(before_execute);
}
mgl_color_t *mgl_context_pixels(void) { return context3d_pixels(color_target); }
void mgl_context_info(mgl_context_info_t *info) {
    info->command_bytes = context3d_commands.used;
    info->commands = context3d_renderer.stats.commands;
    info->triangles = context3d_renderer.stats.triangles;
    info->rejected = context3d_renderer.stats.rejected;
    info->clipped = context3d_renderer.stats.clipped;
    info->culled = context3d_renderer.stats.culled;
    info->rasterized = context3d_renderer.stats.rasterized;
    info->fragments = context3d_renderer.stats.fragments;
    info->error_offset = context3d_renderer.error_offset;
}
int mgl_context_capture(mgl_capture_t *capture, const void **ram) {
    capture->ram_addr = P3D_RAM_BASE;
    capture->ram_size = P3D_RAM_SIZE;
    capture->commands = P3D_COMMANDS;
    capture->color = color_target;
    capture->width = (mgl_u32)width;
    capture->height = (mgl_u32)height;
    *ram = context3d_memory.base;
    return MGL_OK;
}
