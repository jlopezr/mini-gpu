#ifndef MGL_CAPTURE_H
#define MGL_CAPTURE_H

#include "mgl_types.h"

/* Captura de un frame (host): la RAM compartida entera justo antes de ejecutar
   su command buffer, y dónde está cada cosa. Con ella el renderer reproduce el
   frame sin MiniGL ni el sketch (mgl-replay). Formato, little-endian:
     +0 "MGLX"  +4 u32 versión (1)  +8 u32 dirección de la RAM  +12 u32 tamaño
     +16 u32 dirección del command buffer  +20 u32 dirección del framebuffer
     +24 u32 ancho  +28 u32 alto  +32 la RAM (tamaño bytes) */
typedef struct {
    mgl_u32 ram_addr, ram_size, commands, color, width, height;
} mgl_capture_t;

int mgl_capture_save(const char *path, const mgl_capture_t *c, const void *ram);
/* Lee la cabecera en c y la RAM en ram (de capacity bytes). 0 si va bien. */
int mgl_capture_load(const char *path, mgl_capture_t *c, void *ram, mgl_u32 capacity);

#endif
