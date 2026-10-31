#ifndef MGL_CONTEXT_H
#define MGL_CONTEXT_H

#include "minigl.h"
#include "mgl_capture.h"

/* Contrato de render usado por las plataformas. Cada ejecutable enlaza el
   contexto 2D (V0/V1/V2) o el pipeline 3D, que admite también comandos 2D.
   Ventana, entrada, bucle y swap pertenecen a platform/, no al contexto. */
typedef struct {
    mgl_u32 command_bytes, commands, triangles, rejected, clipped, culled;
    mgl_u32 rasterized, fragments, error_offset;
} mgl_context_info_t;

int mgl_context_is3d(void);
mgl_u32 mgl_context_ram_size(void);
int mgl_context_init(void *ram, int version);
int mgl_context_set_version(int version);
void mgl_context_shutdown(void);
int mgl_context_begin(mgl_u32 back, mgl_u32 front);
int mgl_context_end(void (*before_execute)(void));
mgl_color_t *mgl_context_pixels(void);
void mgl_context_info(mgl_context_info_t *info);
/* Describe una captura antes de ejecutar; no hace E/S de archivos. */
int mgl_context_capture(mgl_capture_t *capture, const void **ram);

#endif
