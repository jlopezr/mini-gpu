#ifndef PLATFORM_H
#define PLATFORM_H

#include "processing.h"

/* Parte común de las plataformas (host PPM, SDL): framebuffer de size(),
   command buffer y ejecución de un frame con la versión de MiniGL elegida.
     V0: directo, la CPU rasteriza al llamar
     V1: diferido, command buffer interpretado por la CPU
     V2: diferido, command buffer interpretado por la GPU (8 lanes, emulación host)
   Uso: platform_begin(v); setup() o draw(); platform_end(v). */

#define PLATFORM_DEFAULT_W 320
#define PLATFORM_DEFAULT_H 240
#define PLATFORM_VERSIONS 3

extern mgl_color_t *platform_frame;

/* Reinicia el estado: framebuffer por defecto y frameCount/ratón a cero. */
void platform_reset(void);

/* Empieza a grabar (V1/V2) o deja MiniGL en modo directo (V0). */
int platform_begin(int version);

/* V1/V2: renderiza lo grabado en platform_frame. Devuelve MGL_OK o un error. */
int platform_end(int version);

/* Bytes del command buffer del último frame (0 en V0). */
unsigned int platform_command_bytes(void);

/* "0", "1" o "2" -> versión; -1 si no es válida. */
int platform_parse_version(const char *s);

#endif
