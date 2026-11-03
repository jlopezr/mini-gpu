#ifndef PLATFORM_H
#define PLATFORM_H

#include "processing.h"
#include "context.h"

#define PLATFORM_DEFAULT_W 320
#define PLATFORM_DEFAULT_H 240
#define PLATFORM_VERSIONS 3
#define PLATFORM_FB_A 0x01000000u
#define PLATFORM_FB_B 0x01025800u

/* Estado Processing y ciclo comunes a host, SDL y MiniGPU, en 2D y 3D. */
int platform_init(void *ram, int version);
int platform_frame(mgl_u32 back, mgl_u32 front, void (*sketch)(void), void (*before_execute)(void));
void platform_shutdown(void);
int platform_parse_version(const char *s);

/* Estado de las 256 teclas por Usage ID de USB HID (Usage Page 0x07), como
   KEY_STATE0..7 de INPUT: la tecla u esta en el bit u & 31 de la palabra
   u >> 5. Lo rellena la plataforma antes de cada draw(); keyIsDown() lo lee. */
extern mgl_u32 platform_keys[8];

/* HID 0x1E (1) a 0x38 (/) en ASCII, distribucion US, sin y con Shift. */
extern const char platform_hid_plain[], platform_hid_shift[];

#endif
