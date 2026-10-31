#ifndef MG_GPU_RENDERER_H
#define MG_GPU_RENDERER_H
#include "minigl.h"
#define MG_GPU_LANES 8
#define MG_GPU_MAX_SPRITES 256
/* GPU-visible sprite descriptors: on target, all pointers must reference shared RAM. */
typedef struct {
    const mg_color_t *pixels;
    int width, height, stride;
} mg_gpu_sprite_t;
typedef struct {
    const unsigned char *commands;
    mg_u32 command_bytes;
    mg_color_t *framebuffer;
    int width, height, pitch;
    const mg_gpu_sprite_t *sprites;
    unsigned int sprite_count;
} mg_gpu_job_t;
/* Entry point: invoked by all 8 lanes of ONE warp, getlane intrinsic on target. */
int mg_gpu_render(const mg_gpu_job_t *job);
/* Host-only functional test adapter: call with lanes 0..7 per command. */
int mg_gpu_render_host(const mg_gpu_job_t *job);
/* Host adapter for V0's local sprite registry; descriptors must outlive execution. */
int mg_gpu_sprites_from_v0(const mg_cmd_buffer_t *src,
                            mg_gpu_sprite_t *dst, unsigned int capacity);
#endif
