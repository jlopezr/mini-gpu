#ifndef MGR_H
#define MGR_H

/* Renderer software de referencia (C89, escalar): ejecuta un command buffer de
   versión 2 (mgl_commands.h) leyendo comandos y recursos por su dirección en la
   RAM compartida. No depende de MiniGL ni de Processing: solo del contrato
   binario, de mgl_memory y de mgl_math. Es el mismo código en el host (RAM
   emulada) y en la CPU de MiniGPU (RAM real); solo cambia el mgl_memory_t.

   Ejecución síncrona: mgr_execute vuelve con el trabajo hecho. Una versión
   asíncrona (GPU, varios frames en vuelo) devolverá una fence en lugar del
   resultado; la del número de frame de END_FRAME es la candidata. */

#include "mgl_commands.h"
#include "mgl_math.h"
#include "mgl_memory.h"

#define MGR_OK 0
#define MGR_ERR_FORMAT (-1)      /* buffer o comando mal formado */
#define MGR_ERR_MEMORY (-2)      /* dirección fuera de la RAM o mal alineada */
#define MGR_ERR_UNSUPPORTED (-3) /* formato o estado reservado */
#define MGR_ERR_STATE (-4)       /* dibujo sin destino */
#define MGR_ERR_LIMIT (-5)       /* tamaño, viewport o índice fuera de rango */

typedef struct {
    mgl_u32 commands;  /* comandos ejecutados */
    mgl_u32 frames;    /* END_FRAME */
    mgl_u32 triangles; /* triángulos leídos de DRAW_INDEXED */
    mgl_u32 rejected;  /* descartados enteros por estar fuera de un plano */
    mgl_u32 clipped;   /* que cruzaban algún plano y se recortaron */
    mgl_u32 culled;    /* descartados por cara o por área nula */
    mgl_u32 rasterized;/* triángulos rasterizados (tras recortar, uno da varios) */
    mgl_u32 fragments; /* píxeles cubiertos, antes de la prueba de profundidad */
} mgr_stats_t;

/* Una matriz en Q16.16, para MGR_FIXED_GEOMETRY (fixed.c). */
typedef struct {
    mgl_s32 m[16];
} mgr_mat4q_t;

/* Estado que fijan los comandos. Lo usan las etapas (mgr_stages.h). */
typedef struct {
    /* SET_RENDER_TARGET: punteros ya traducidos */
    mgl_color_t *color;
    mgl_u16 *depth;
    int width, height, color_stride, depth_stride;
    /* SET_VIEWPORT, y lo que de él usa mgr_viewport_map en cada vértice: la
       esquina en 1/16 de píxel y la mitad del tamaño, en float */
    int vx, vy, vw, vh;
    mgl_s32 view_x, view_y;
    mgl_real_t view_sx, view_sy;
    mgl_s32 view_sxi, view_syi; /* lo mismo en entero (1/16 de píxel), para MGR_FIXED_GEOMETRY */
    /* SET_MATRIX (índice MGL_MATRIX_* - 1) y Projection * View * Model */
    mgl_mat4_t matrix[3];
    mgl_mat4_t mvp;
    int mvp_dirty;
    /* mvp en Q16.16 (MGR_FIXED_GEOMETRY): se convierte cuando cambia mvp, no en cada DRAW_INDEXED */
    mgr_mat4q_t mvp_q;
    int mvp_q_dirty;
    /* SET_RENDER_STATE y SET_COLOR */
    mgl_u32 flags;
    mgl_color_t fill;
} mgr_state_t;

typedef struct {
    mgl_memory_t memory;
    mgr_state_t state;
    mgr_stats_t stats;
    mgl_u32 error_offset; /* offset del comando que falló (0: la cabecera) */
} mgr_renderer_t;

int mgr_init(mgr_renderer_t *r, const mgl_memory_t *memory);

/* Ejecuta el command buffer que empieza en buffer_addr. Empieza con el estado
   inicial (mgr_state_reset), y vuelve a él tras cada END_FRAME. Lo dibujado
   hasta un error se queda; el error dice qué falló y error_offset dónde. */
int mgr_execute(mgr_renderer_t *r, mgl_u32 buffer_addr);

/* Pone a cero las estadísticas (mgr_execute las acumula). */
void mgr_reset_stats(mgr_renderer_t *r);

#endif
