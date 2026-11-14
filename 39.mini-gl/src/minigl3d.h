#ifndef MINIGL3D_H
#define MINIGL3D_H

/* MiniGL 3D: estado gráfico, recursos y generación de comandos. No transforma
   vértices, no recorta ni rasteriza: eso lo hace quien ejecute el command
   buffer (src/render/3d/, y en el futuro la GPU).

   Usa el mismo command buffer que MiniGL 2D (mgl_cmd_init, mgl_set_deferred) y
   solo en modo diferido: en modo directo las funciones 3D no hacen nada y
   mgl_end_frame devuelve MGL_ERR_STATE. Los comandos 2D y 3D se pueden
   intercalar; se ejecutan en el orden en que se llaman.

   Un frame:
     mgl_begin_frame();                         emite SET_RENDER_TARGET
     mgl_clear_color_depth(color, 1.0f);        o mgl_clear(color)
     mgl_set_viewport(...); mgl_set_matrix(...); mgl_set_depth_test(1); mgl_set_color(c);
     mgl_draw_mesh(mesh);                       emite el estado que haga falta y DRAW_INDEXED
     mgl_end_frame();                           emite END_FRAME
   El estado (viewport, matrices, render state, color) se guarda al llamar y se
   emite en el siguiente draw, solo si cambió desde lo emitido en este frame.
   Al empezar un frame no se da nada por emitido: cada frame lleva todo el
   estado que usa y se puede ejecutar solo. El estado sí persiste en MiniGL de
   un frame al siguiente, como en OpenGL.

   Los errores se acumulan en el command buffer (mgl_cmd_status), como en 2D; el
   primero se queda. */

#include "minigl.h"
#include "mgl_math.h"
#include "mgl_memory.h"

/* Destino: direcciones en la RAM compartida. Strides en píxeles. Sin
   profundidad: depth_addr = 0. */
typedef struct {
    mgl_u32 color_addr, depth_addr;
    int width, height, color_stride, depth_stride;
} mgl_render_target_t;

/* Handle de malla: 0 no es válido. */
typedef mgl_u32 mgl_mesh_t;

/* Descripción de una malla: lo que acaba en DRAW_INDEXED. */
typedef struct {
    mgl_u32 vertex_addr, index_addr;
    mgl_u32 vertex_count, index_count;
    unsigned int vertex_format, index_format, vertex_stride;
} mgl_mesh_desc_t;

/* ---- Recursos (mgl_resources.c) ------------------------------------------ */

/* Prepara los recursos: memory es la RAM compartida (la usa MiniGL para copiar
   datos y comprobar direcciones) y [heap_addr, heap_addr + heap_size), dentro
   de ella, la memoria que administra MiniGL. heap_size puede ser 0 si solo se
   usan recursos con memoria de la aplicación. Destruye todos los recursos. */
int mgl_resources_init(const mgl_memory_t *memory, mgl_u32 heap_addr, mgl_u32 heap_size);

/* Memoria administrada por MiniGL: bump allocator sin liberación individual
   (mgl_resources_init la vacía entera). Devuelve la dirección o 0. */
mgl_u32 mgl_alloc(mgl_u32 bytes, mgl_u32 align);

/* Memoria de frame: para datos que solo valen un frame (las figuras de
   beginShape/endShape). [addr, addr + size) dentro de la RAM de
   mgl_resources_init, que hay que llamar antes. mgl_frame_alloc reparte como
   mgl_alloc, y cada mgl_begin_frame la vacía entera: lo que el frame anterior
   dejó ahí tiene que estar ya ejecutado (hoy lo está: la ejecución es
   síncrona; con frames en vuelo, hará falta una zona por frame y su fence). */
int mgl_frame_memory_init(mgl_u32 addr, mgl_u32 size);
mgl_u32 mgl_frame_alloc(mgl_u32 bytes, mgl_u32 align);

/* Malla sobre memoria de la aplicación: MiniGL no copia nada y solo guarda la
   descripción; la aplicación mantiene los datos válidos y sin cambios mientras
   haya un command buffer pendiente que la use. 0 si la descripción no vale. */
mgl_mesh_t mgl_create_mesh(const mgl_mesh_desc_t *desc);

/* Malla en memoria de MiniGL: copia las posiciones (x, y, z por vértice) como
   POSITION_F32_XYZ con stride 12 y los índices como UINT16. 0 si no vale o no
   cabe. */
mgl_mesh_t mgl_create_mesh_copy(const float *positions, mgl_u32 vertex_count,
    const unsigned short *indices, mgl_u32 index_count);

/* Malla con color por vértice: POSITION_F32_XYZ_RGB565 con stride 16 (x, y, z en float, color RGB565 y dos
   bytes reservados). Cada triángulo se pinta del color de su primer vértice; mgl_set_color no cuenta (salvo
   con mgl_draw_mesh_range_uniform). colors tiene vertex_count colores, o es 0: todos blancos y sin asignar,
   para darlos después con mgl_mesh_color_range. 0 si no vale o no cabe. */
mgl_mesh_t mgl_create_mesh_copy_rgb565(const float *positions, const mgl_color_t *colors,
    mgl_u32 vertex_count, const unsigned short *indices, mgl_u32 index_count);

/* Da el color a los vértices de los triángulos [first, first + count) de los índices (first y count
   múltiplos de 3), en una malla de mgl_create_mesh_copy_rgb565: así se pasa de grupos de triángulos de un
   color (un PShape) a color por vértice. MGL_ERR_ARGUMENT, y la malla sin tocar, si algún vértice ya tenía
   asignado otro color (lo comparten triángulos de dos colores: con color por vértice no se puede) o la malla
   no tiene color; MGL_ERR_HANDLE si el handle no vale. Como la ejecución es diferida, el color nuevo lo ven
   también los dibujos de esa malla ya grabados en el frame en curso. */
int mgl_mesh_color_range(mgl_mesh_t mesh, mgl_u32 first, mgl_u32 count, mgl_color_t color);

/* Lo mismo en memoria de frame: los datos valen hasta el siguiente
   mgl_begin_frame. El handle hay que destruirlo igual (se puede en cuanto se
   ha dibujado: el command buffer ya tiene las direcciones). */
mgl_mesh_t mgl_create_mesh_frame(const float *positions, mgl_u32 vertex_count,
    const unsigned short *indices, mgl_u32 index_count);

/* Libera el handle (los siguientes usos dan MGL_ERR_HANDLE). La memoria de
   MiniGL no se recupera hasta mgl_resources_init. */
int mgl_destroy_mesh(mgl_mesh_t mesh);

/* Resuelve un handle a su descripción (direcciones incluidas). MGL_OK o MGL_ERR_HANDLE. */
int mgl_mesh_info(mgl_mesh_t mesh, mgl_mesh_desc_t *desc);

/* ---- Frames y estado (mgl_3d.c) ------------------------------------------ */

/* Vuelve al estado inicial: matrices identidad, viewport a todo el destino,
   MGL_STATE_DEFAULT y color blanco (el mismo con el que empieza el renderer). */
void mgl_reset_state3d(void);

/* Fija el destino. El viewport pasa a ser todo el destino. Dentro de un frame
   emite SET_RENDER_TARGET en el momento (afecta también a lo 2D). */
void mgl_set_render_target(const mgl_render_target_t *target);

/* Empieza un frame en el buffer de mgl_set_deferred: emite SET_RENDER_TARGET y
   olvida lo emitido en frames anteriores. Mientras dure, mgl_clear borra
   también la profundidad (si el destino la tiene). */
void mgl_begin_frame(void);

/* Emite END_FRAME y devuelve el estado del buffer (MGL_OK o el primer error). */
int mgl_end_frame(void);

/* Borra color y profundidad. depth de 0 (cerca) a 1 (lejos). */
void mgl_clear_color_depth(mgl_color_t color, mgl_real_t depth);

/* Borra solo la profundidad: para cuando el frame pinta de todos modos toda la pantalla (cielo, suelo...), y
   borrar el color sería pintarla dos veces. */
void mgl_clear_depth(mgl_real_t depth);

void mgl_set_viewport(int x, int y, int width, int height);
/* which: MGL_MATRIX_MODEL, MGL_MATRIX_VIEW o MGL_MATRIX_PROJECTION. Se copia el valor. */
void mgl_set_matrix(unsigned int which, const mgl_mat4_t *matrix);
void mgl_set_depth_test(int enabled);
void mgl_set_depth_write(int enabled);
/* MGL_CULL_NONE, MGL_CULL_BACK o MGL_CULL_FRONT. */
void mgl_set_cull(int mode);
void mgl_set_color(mgl_color_t color);

void mgl_draw_mesh(mgl_mesh_t mesh);
/* Solo los índices [first, first + count) (múltiplos de 3): para dibujar
   partes de una malla con estado distinto, como un color por cara. */
void mgl_draw_mesh_range(mgl_mesh_t mesh, mgl_u32 first, mgl_u32 count);
/* Como mgl_draw_mesh_range, pero con el color de mgl_set_color aunque la malla tenga color por vértice
   (mgl_create_mesh_copy_rgb565): un DRAW_INDEXED con formato POSITION_F32_XYZ y el stride de la malla. En una
   malla sin color es lo mismo que mgl_draw_mesh_range. */
void mgl_draw_mesh_range_uniform(mgl_mesh_t mesh, mgl_u32 first, mgl_u32 count);

#define MGL_CULL_NONE 0
#define MGL_CULL_BACK 1
#define MGL_CULL_FRONT 2

#endif
