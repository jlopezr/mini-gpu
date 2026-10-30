#ifndef MGL_GPU_RENDERER_H
#define MGL_GPU_RENDERER_H
#include "minigl.h"
#define MGL_GPU_LANES 8
#define MGL_GPU_MAX_SPRITES 256
/* GPU-visible sprite descriptors: on target, all pointers must reference shared RAM. */
typedef struct {
    const mgl_color_t *pixels;
    int width, height, stride;
} mgl_gpu_sprite_t;
typedef struct {
    const unsigned char *commands;
    mgl_u32 command_bytes;
    mgl_color_t *framebuffer;
    int width, height, pitch;
    const mgl_gpu_sprite_t *sprites;
    unsigned int sprite_count;
} mgl_gpu_job_t;
/* Entry point: invoked by all 8 lanes of ONE warp, getlane intrinsic on target. */
int mgl_gpu_render(const mgl_gpu_job_t *job);
/* Host-only functional test adapter: call with lanes 0..7 per command. */
int mgl_gpu_render_host(const mgl_gpu_job_t *job);
/* Host adapter for V0's local sprite registry; descriptors must outlive execution. */
int mgl_gpu_sprites_from_v0(const mgl_cmd_buffer_t *src,
                            mgl_gpu_sprite_t *dst, unsigned int capacity);
#endif
