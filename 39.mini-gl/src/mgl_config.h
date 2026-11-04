#ifndef MGL_CONFIG_H
#define MGL_CONFIG_H

#include "mgl_types.h"
#include "mgl_commands.h"

/* Formato con el que MiniGL calcula (mgl_real_t) y con el que serializa
   matrices y posiciones. Son cosas distintas: el formato serializado es parte
   del contrato binario (mgl_commands.h) y lo lleva cada comando; el de cálculo
   es interno de cada lado. De momento los dos son FLOAT32.

   Q16.16 está reservado: cambiar el typedef no basta (multiplicar y dividir
   necesitan reescalar, y las constantes y conversiones son otras), así que
   pedirlo es un error de compilación hasta que mgl_math.c tenga esa variante. */
#ifndef MGL_REAL_FORMAT
#define MGL_REAL_FORMAT MGL_FORMAT_FLOAT32
#endif

#if MGL_REAL_FORMAT == MGL_FORMAT_FLOAT32
typedef float mgl_real_t;
#else
#error "MGL_REAL_FORMAT: solo esta implementado MGL_FORMAT_FLOAT32"
#endif

MGL_STATIC_ASSERT(f32, sizeof(float) == 4);

/* Límites de MiniGL y del renderer de referencia. */
#define MGL_MAX_MESHES 96
#define MGL_MAX_TARGET_DIM 1024 /* ancho, alto y stride; ver raster3d.c */
#define MGL_MAX_VIEWPORT_POS 4096

#endif
