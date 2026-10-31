#include "context.h"
#include "processing.h"
#include <string.h>

#ifndef MGL_VERSION
#define MGL_VERSION 0
#endif
#if defined(__MINIGPU__) && (MGL_VERSION < 0 || MGL_VERSION > 2)
#error "MiniGPU: MGL_VERSION 0, 1 o 2"
#endif
#if !defined(__MINIGPU__) || MGL_VERSION == 2
#include "gpu_renderer.h"
static mgl_gpu_sprite_t sprites[MGL_GPU_MAX_SPRITES];
#endif
#ifndef __MINIGPU__
#include <stdio.h>
#include <stdlib.h>
static unsigned char command_memory[65536U];
#endif

static mgl_color_t *pixels;
static mgl_cmd_buffer_t commands;
static int version, bad_size;
static unsigned int last_bytes;

/* La plataforma proporciona el destino; el contexto conserva el lienzo 2D. */
void size(int w, int h) {
#ifdef __MINIGPU__
    if (w != 320 || h != 240) bad_size = 1;
#else
    mgl_color_t *p;
    if (w <= 0 || h <= 0) {
        fprintf(stderr, "size(%d,%d): tamaño inválido\n", w, h);
        exit(1);
    }
    p = (mgl_color_t *)calloc((size_t)w * (size_t)h, sizeof *p);
    if (!p) {
        fputs("size: sin memoria\n", stderr);
        exit(1);
    }
    free(pixels);
    pixels = p;
    width = w;
    height = h;
    mouseX = pmouseX = w / 2;
    mouseY = pmouseY = h / 2;
    mgl_bind(pixels, w, h, w);
#endif
}

int mgl_context_is3d(void) { return 0; }
mgl_u32 mgl_context_ram_size(void) { return 0; }
int mgl_context_set_version(int selected_version) {
    if (selected_version < 0 || selected_version > 2) return MGL_ERR_ARGUMENT;
#ifdef __MINIGPU__
    if (selected_version != MGL_VERSION) return MGL_ERR_ARGUMENT;
#endif
    version = selected_version;
    return MGL_OK;
}
int mgl_context_init(void *ram, int selected_version) {
    (void)ram;
    if (selected_version < 0 || selected_version > 2) return MGL_ERR_ARGUMENT;
#ifdef __MINIGPU__
    if (selected_version != MGL_VERSION) return MGL_ERR_ARGUMENT;
#endif
    version = selected_version;
    bad_size = 0;
    last_bytes = 0;
    mgl_set_deferred(0);
#ifdef __MINIGPU__
    width = 320;
    height = 240;
    pixels = (mgl_color_t *)0x01025800u;
    mgl_bind(pixels, width, height, width);
    mgl_set_target(pixels, (const mgl_color_t *)0x01000000u);
#if MGL_VERSION == 2
    {
        extern int gpu_timeout_polls;
        gpu_timeout_polls = 100000000;
    }
#endif
#else
    size(320, 240);
#endif
    mouseX = pmouseX = width / 2;
    mouseY = pmouseY = height / 2;
    return MGL_OK;
}

void mgl_context_shutdown(void) {
    mgl_set_deferred(0);
#ifndef __MINIGPU__
    free(pixels);
    pixels = 0;
#endif
}

int mgl_context_begin(mgl_u32 back, mgl_u32 front) {
    last_bytes = 0;
#ifdef __MINIGPU__
    if (pixels != (mgl_color_t *)back) {
        pixels = (mgl_color_t *)back;
        mgl_set_target(pixels, (const mgl_color_t *)front);
    }
#else
    (void)back;
    (void)front;
#endif
    if (!version) {
        mgl_set_deferred(0);
        return MGL_OK;
    }
#ifdef __MINIGPU__
    if (mgl_cmd_init(&commands, (void *)0x0104B000u, 65536U) != MGL_OK) return MGL_ERR_ARGUMENT;
#else
    if (mgl_cmd_init(&commands, command_memory, sizeof command_memory) != MGL_OK) return MGL_ERR_ARGUMENT;
#endif
    mgl_set_deferred(&commands);
    return MGL_OK;
}

int mgl_context_end(void (*before_execute)(void)) {
    int r = MGL_OK;
    mgl_set_deferred(0);
    if (bad_size) return MGL_ERR_ARGUMENT;
    if (before_execute) before_execute();
    if (version) {
        r = mgl_cmd_status(&commands);
        if (r != MGL_OK) return r;
        last_bytes = commands.used;
#if !defined(__MINIGPU__) || MGL_VERSION == 1
        if (version == 1) r = mgl_cmd_render_cpu(&commands);
#endif
#if !defined(__MINIGPU__) || MGL_VERSION == 2
        if (version == 2) {
            mgl_gpu_job_t job;
            r = mgl_gpu_sprites_from_cmd(&commands, sprites, MGL_GPU_MAX_SPRITES);
            if (r == MGL_OK) {
                mgl_cmd_ready(&commands);
                job.commands = commands.bytes;
                job.command_bytes = commands.used;
                job.framebuffer = pixels;
                job.width = width;
                job.height = height;
                job.pitch = width;
                job.sprites = sprites;
                job.sprite_count = commands.sprite_count;
                r = mgl_gpu_render(&job);
            }
        }
#endif
    }
    if (r == MGL_OK) mgl_finish();
    return r;
}

mgl_color_t *mgl_context_pixels(void) { return pixels; }
void mgl_context_info(mgl_context_info_t *info) {
    memset(info, 0, sizeof *info);
    info->command_bytes = last_bytes;
}
int mgl_context_capture(mgl_capture_t *capture, const void **ram) {
    (void)capture;
    (void)ram;
    return MGL_ERR_ARGUMENT; /* La captura MGLX describe RAM del pipeline 3D. */
}
