#ifndef MGL_INTERNAL_H
#define MGL_INTERNAL_H

/* Entre minigl.c (2D y el command buffer) y mgl_3d.c. No es API pública. */
#include "minigl.h"

/* El buffer de mgl_set_deferred, o 0 en modo directo. */
mgl_cmd_buffer_t *mgl_deferred_(void);

/* Reserva bytes para un comando 3D al final del buffer y pasa la cabecera a
   MGL_BUFFER_VERSION_3D. 0 si no hay buffer, ya tenía un error o no cabe (y
   entonces el error es MGL_ERR_SPACE). */
unsigned char *mgl_reserve3d_(mgl_u32 bytes);

/* Flags y arg1 del CLEAR de mgl_clear: los pone mgl_3d.c mientras hay un frame
   3D con profundidad (MGL_CLEAR_DEPTH y lejos); fuera, 0 y 0. */
extern mgl_u32 mgl_clear_flags_, mgl_clear_depth_;

#endif
