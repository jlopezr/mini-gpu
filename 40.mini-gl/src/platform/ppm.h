#ifndef PPM_H
#define PPM_H

#include "mgl_types.h"

/* Guardar un framebuffer RGB565 (host). 0 si va bien.
   ppm_write: imagen PPM (P6) de 8 bits por canal.
   ppm_write_raw: RGB565 crudo little-endian, el formato de `sim-sys --frame-output`. */
int ppm_write(const char *path, const mgl_color_t *pixels, int width, int height, int stride);
int ppm_write_raw(const char *path, const mgl_color_t *pixels, int width, int height, int stride);
/* 1 si path termina en .bin (y se guarda crudo). */
int ppm_is_raw(const char *path);

#endif
