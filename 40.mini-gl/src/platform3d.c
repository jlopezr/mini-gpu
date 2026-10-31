#include "platform3d.h"

int width = P3D_MAX_W, height = P3D_MAX_H;
int frameCount, mouseX, mouseY, pmouseX, pmouseY, mousePressed;
int keyPressed, key, keyCode;

mgl_memory_t platform3d_memory;
mgr_renderer_t platform3d_renderer;
mgl_cmd_buffer_t platform3d_commands;

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

int platform3d_init(void *ram) {
    void *commands;
    if (mgl_memory_init(&platform3d_memory, ram, P3D_RAM_BASE, P3D_RAM_SIZE)) return 1;
    commands = mgl_memory_ptr(&platform3d_memory, P3D_COMMANDS, P3D_COMMAND_BYTES, 4);
    if (!commands || mgl_cmd_init(&platform3d_commands, commands, P3D_COMMAND_BYTES) != MGL_OK) return 1;
    if (mgl_resources_init(&platform3d_memory, P3D_HEAP, P3D_HEAP_BYTES) != MGL_OK) return 1;
    if (mgr_init(&platform3d_renderer, &platform3d_memory) != MGR_OK) return 1;
    mgl_reset_state3d();
    frameCount = 0;
    width = P3D_MAX_W;
    height = P3D_MAX_H;
    mouseX = pmouseX = width / 2;
    mouseY = pmouseY = height / 2;
    processing3d_size(width, height);
    return 0;
}

int platform3d_begin(mgl_u32 color_addr) {
    color_target = color_addr;
    set_target();
    if (mgl_cmd_reset(&platform3d_commands) != MGL_OK) return MGL_ERR_ARGUMENT;
    mgl_set_deferred(&platform3d_commands);
    mgl_begin_frame();
    processing3d_begin_draw();
    return MGL_OK;
}

int platform3d_end(void (*before_execute)(void)) {
    int r = mgl_end_frame();
    mgl_set_deferred(0);
    if (bad_size) return MGL_ERR_ARGUMENT;
    if (r != MGL_OK) return r;
    if (before_execute) before_execute();
    return mgr_execute(&platform3d_renderer, P3D_COMMANDS);
}

mgl_color_t *platform3d_pixels(mgl_u32 addr) {
    return (mgl_color_t *)mgl_memory_ptr(&platform3d_memory, addr,
        (mgl_u32)(P3D_MAX_W * P3D_MAX_H * 2), 2);
}
