/* Contrato común de plataforma con los dos contextos: entrada, callbacks,
   persistencia del lienzo, cambio de versión y captura antes de ejecutar. */
#include "platform.h"
#include <stdio.h>
#include <stdlib.h>

#ifndef TEST_CONTEXT_3D
#define TEST_CONTEXT_3D 0
#endif
#if TEST_CONTEXT_3D
#include "processing3d.h"
#endif

static int failures, captured;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); failures++; } } while (0)

static void prepare(void) {
#if TEST_CONTEXT_3D
    size(320, 240, P3D);
#else
    size(101, 67);
#endif
    background565(0x1234);
    noStroke();
}

static void paint(void) {
    CHECK(mouseX == 17 && mouseY == 23 && mousePressed && keyPressed && key == 'R');
    fill565(0xabcd);
    rect(2, 3, 5, 4);
}

static void capture(void) {
    mgl_capture_t c;
    const void *ram;
    int r = mgl_context_capture(&c, &ram);
#if TEST_CONTEXT_3D
    CHECK(r == MGL_OK && ram != 0);
    CHECK(c.color == PLATFORM_FB_A && c.width == (mgl_u32)width && c.height == (mgl_u32)height);
#else
    CHECK(r == MGL_ERR_ARGUMENT);
#endif
    captured++;
}

int main(void) {
    mgl_u32 bytes = mgl_context_ram_size();
    unsigned char *ram = bytes ? (unsigned char *)calloc(bytes, 1) : 0;
    mgl_context_info_t info;
    mgl_color_t *pixels;
    int v, last = TEST_CONTEXT_3D ? 0 : 2;
    if (bytes && !ram) return 2;
    CHECK(mgl_context_is3d() == TEST_CONTEXT_3D);
    for (v = 0; v <= last; v++) {
        CHECK(platform_init(ram, v) == MGL_OK);
        CHECK(frameCount == 0 && !keyPressed && !mousePressed);
        CHECK(platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, prepare, capture) == MGL_OK);
        pixels = mgl_context_pixels();
        CHECK(pixels[0] == 0x1234);
        mouseX = 17;
        mouseY = 23;
        mousePressed = keyPressed = 1;
        key = 'R';
        frameCount = 1;
        CHECK(platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, paint, capture) == MGL_OK);
        CHECK(pixels[3 * width + 2] == 0xabcd && pixels[0] == 0x1234);
        mgl_context_info(&info);
        CHECK((info.command_bytes != 0) == (TEST_CONTEXT_3D || v != 0));
#if TEST_CONTEXT_3D
        CHECK(mgl_context_set_version(1) == MGL_ERR_ARGUMENT);
#else
        CHECK(mgl_context_set_version((v + 1) % 3) == MGL_OK);
        CHECK(platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, paint, 0) == MGL_OK);
        CHECK(pixels[0] == 0x1234); /* cambiar V no borra el lienzo */
#endif
        platform_shutdown();
    }
    CHECK(captured == (last + 1) * 2);
    free(ram);
    if (!failures) printf("PASS: plataforma común, contexto %s\n", TEST_CONTEXT_3D ? "3D" : "2D V0/V1/V2");
    return failures != 0;
}
