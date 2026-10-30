#include "platform.h"
#include "gpu_renderer.h"
#include <stdio.h>
#include <stdlib.h>

#define CMD_BYTES 65536U

int width, height;
int frameCount, mouseX, mouseY, mousePressed;
mgl_color_t *platform_frame;

static unsigned char cmd_memory[CMD_BYTES];
static mgl_cmd_buffer_t cmd;
static mgl_gpu_sprite_t gpu_sprites[MGL_GPU_MAX_SPRITES];
static int recording;
static unsigned int last_bytes;

void size(int w, int h) {
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
    free(platform_frame);
    platform_frame = p;
    width = w;
    height = h;
    mgl_bind(platform_frame, w, h, w);
}

void platform_reset(void) {
    frameCount = mouseX = mouseY = mousePressed = 0;
    mgl_set_deferred(0);
    size(PLATFORM_DEFAULT_W, PLATFORM_DEFAULT_H);
}

int platform_begin(int version) {
    recording = version > 0;
    last_bytes = 0;
    if (!recording) {
        mgl_set_deferred(0);
        return MGL_OK;
    }
    if (mgl_cmd_init(&cmd, cmd_memory, CMD_BYTES) != MGL_OK) return MGL_ERR_ARGUMENT;
    mgl_set_deferred(&cmd);
    return MGL_OK;
}

int platform_end(int version) {
    mgl_gpu_job_t job;
    int r;
    if (!recording) return MGL_OK;
    recording = 0;
    mgl_set_deferred(0);
    if ((r = mgl_cmd_status(&cmd)) != MGL_OK) {
        fprintf(stderr, "V%d: error %d al grabar el command buffer\n", version, r);
        return r;
    }
    last_bytes = (unsigned int)cmd.used;
    if (version == 1)
        r = mgl_cmd_render_cpu(&cmd);
    else {
        r = mgl_gpu_sprites_from_cmd(&cmd, gpu_sprites, MGL_GPU_MAX_SPRITES);
        if (r == MGL_OK) {
            job.commands = cmd.bytes;
            job.command_bytes = cmd.used;
            job.framebuffer = platform_frame;
            job.width = width;
            job.height = height;
            job.pitch = width;
            job.sprites = gpu_sprites;
            job.sprite_count = cmd.sprite_count;
            r = mgl_gpu_render_host(&job);
        }
    }
    if (r != MGL_OK) fprintf(stderr, "V%d: error %d al renderizar\n", version, r);
    return r;
}

unsigned int platform_command_bytes(void) {
    return last_bytes;
}

int platform_parse_version(const char *s) {
    if (s[0] >= '0' && s[0] < '0' + PLATFORM_VERSIONS && s[1] == 0) return s[0] - '0';
    return -1;
}
