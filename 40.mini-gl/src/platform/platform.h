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

#endif
