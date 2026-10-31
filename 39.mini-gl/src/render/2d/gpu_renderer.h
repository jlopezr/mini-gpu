#ifndef MGL_GPU_RENDERER_H
#define MGL_GPU_RENDERER_H
#include "minigl.h"
#define MGL_GPU_LANES 8
#define MGL_GPU_MAX_SPRITES 256

/* GPU-visible sprite descriptors: on target, all pointers must reference shared RAM. Son los mismos campos que
   mgl_sprite_t: el renderer los pasa tal cual a sw_image. */
typedef mgl_sprite_t mgl_gpu_sprite_t;

typedef struct {
    const unsigned char *commands;
    mgl_u32 command_bytes;
    mgl_color_t *framebuffer;
    int width, height, pitch;
    const mgl_gpu_sprite_t *sprites;
    unsigned int sprite_count;
} mgl_gpu_job_t;

/* Valida el trabajo y lo ejecuta: en MiniGPU, un warp de 8 lanes (KERNEL(mgl_render), compilado con mini-lcc);
   en el host, las 8 lanes una tras otra en la CPU (emulacion funcional, no SIMT). MGL_OK o MGL_ERR_ARGUMENT. */
int mgl_gpu_render(const mgl_gpu_job_t *job);

/* Host adapter for the command buffer's local sprite registry (V1); descriptors must outlive execution. */
int mgl_gpu_sprites_from_cmd(
    const mgl_cmd_buffer_t *src, mgl_gpu_sprite_t *dst, unsigned int capacity);

#endif
