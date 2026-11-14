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

#if TEST_CONTEXT_3D
/* hint(): un cubo rojo delante, dibujado primero, y uno azul detrás. Con
   profundidad gana el rojo; sin test, el último (azul); y si el rojo no escribe
   profundidad (DISABLE_DEPTH_MASK), el azul tampoco queda tapado. */
static int hint_case;

static void two_boxes(void) {
    background565(0x0000);
    if (hint_case == 1) hint(DISABLE_DEPTH_TEST);
    if (hint_case == 2) hint(DISABLE_DEPTH_MASK);
    fill(255, 0, 0);
    pushMatrix();
    translate(160, 120, 60);
    box(40);
    popMatrix();
    if (hint_case == 2) hint(ENABLE_DEPTH_MASK);
    fill(0, 0, 255);
    translate(160, 120, -60);
    box(40);
    if (hint_case == 1) hint(ENABLE_DEPTH_TEST);
}
#endif

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
        CHECK(frameCount == 0 && !keyPressed && !mousePressed && !keyIsDown('w') && !keyIsDown(UP));
        platform_keys[0x1A >> 5] |= 1u << (0x1A & 31); /* W */
        platform_keys[0x52 >> 5] |= 1u << (0x52 & 31); /* flecha arriba */
        platform_keys[0x2C >> 5] |= 1u << (0x2C & 31); /* espacio */
        platform_keys[0x1E >> 5] |= 1u << (0x1E & 31); /* 1 */
        CHECK(keyIsDown('w') && keyIsDown('W') && keyIsDown(UP) && keyIsDown(' ') && keyIsDown('!'));
        CHECK(!keyIsDown('s') && !keyIsDown(DOWN) && !keyIsDown(CODED) && !keyIsDown(0) && !keyIsDown(SHIFT));
        platform_keys[0xE5 >> 5] |= 1u << (0xE5 & 31); /* Shift derecho */
        CHECK(keyIsDown(SHIFT));
        CHECK(platform_hid_usage('-') == 0x2D && platform_hid_usage('+') == 0x2E && platform_hid_usage('~') == 0x35);
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
        for (hint_case = 0; hint_case < 3; hint_case++) {
            CHECK(platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, two_boxes, 0) == MGL_OK);
            CHECK(pixels[120 * width + 160] == (hint_case ? 0x001F : 0xF800));
        }
        /* Los ENABLE_* del frame anterior siguen valiendo. */
        hint_case = 0;
        CHECK(platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, two_boxes, 0) == MGL_OK);
        CHECK(pixels[120 * width + 160] == 0xF800);
#else
        CHECK(mgl_context_set_version((v + 1) % 3) == MGL_OK);
        CHECK(platform_frame(PLATFORM_FB_A, PLATFORM_FB_A, paint, 0) == MGL_OK);
        CHECK(pixels[0] == 0x1234); /* cambiar V no borra el lienzo */
#endif
        platform_shutdown();
        CHECK(platform_init(ram, v) == MGL_OK && !keyIsDown('w'));
        platform_shutdown();
    }
    CHECK(captured == (last + 1) * 2);
    free(ram);
    if (!failures) printf("PASS: plataforma común, contexto %s\n", TEST_CONTEXT_3D ? "3D" : "2D V0/V1/V2");
    return failures != 0;
}
