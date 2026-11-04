#ifndef MGR_STAGES_H
#define MGR_STAGES_H

/* Interfaces entre las etapas del renderer. Cada una es un fichero y solo ve lo
   que recibe; ninguna guarda listas completas de la anterior: un triángulo pasa
   por todas antes de leer el siguiente (draw.c).

     commands.c   decodifica y valida el buffer; llama a state, draw y raster2d
     state.c      estado de los comandos SET_* y su valor inicial
     draw.c       DRAW_INDEXED: por triángulo, fetch -> transform -> clip -> viewport -> raster3d
     transform.c  lee posiciones de la RAM y las pasa a coordenadas de recorte
     clipping.c   recorta contra el volumen de visión, en coordenadas homogéneas
     viewport.c   división de perspectiva y paso a píxeles (punto fijo)
     raster3d.c   cobertura con funciones de borde enteras; entrega spans
     fragment.c   profundidad y color de un span; también los CLEAR
     raster2d.c   comandos 2D (BATCH) con el raster de V0 (src/render/2d/raster.c)

   Las candidatas a hardware son transform, viewport, raster3d y fragment: cada
   una recibe un lote de trabajo pequeño y sin punteros a estado ajeno. */

#include "mgr.h"

/* ---- state.c ------------------------------------------------------------ */
void mgr_state_reset(mgr_state_t *s);
int mgr_state_target(mgr_state_t *s, const mgl_memory_t *m, const unsigned char *cmd);
int mgr_state_viewport(mgr_state_t *s, const unsigned char *cmd);
int mgr_state_matrix(mgr_state_t *s, const unsigned char *cmd);
int mgr_state_flags(mgr_state_t *s, const unsigned char *cmd);
int mgr_state_color(mgr_state_t *s, const unsigned char *cmd);
/* Projection * View * Model, recalculada solo si cambió alguna. */
const mgl_mat4_t *mgr_state_mvp(mgr_state_t *s);

/* ---- draw.c ------------------------------------------------------------- */
int mgr_draw_indexed(mgr_state_t *s, mgr_stats_t *st, const mgl_memory_t *m, const unsigned char *cmd);

/* ---- transform.c -------------------------------------------------------- */
/* Un flujo de vértices ya validado: posiciones F32 XYZ little-endian. */
typedef struct {
    const unsigned char *base;
    mgl_u32 stride, count;
} mgr_vertices_t;

/* Lee el vértice index (< count, lo comprueba quien llama) y lo transforma:
   clip = mvp * (x, y, z, 1). */
void mgr_transform_vertex(const mgr_vertices_t *v, mgl_u32 index, const mgl_mat4_t *mvp,
    mgl_vec4_t *clip);

/* ---- clipping.c --------------------------------------------------------- */
/* Un triángulo recortado por los seis planos es un polígono convexo de hasta
   3 + 6 vértices. */
#define MGR_CLIP_MAX 9

/* Bits de los planos que deja fuera (0: dentro de todos). */
unsigned int mgr_outcode(const mgl_vec4_t *v);

/* Recorta el triángulo in contra -w <= x, y, z <= w (Sutherland-Hodgman, plano
   a plano) y deja el polígono en out. Devuelve el número de vértices: 0 o de 3
   a MGR_CLIP_MAX. Los puntos de corte de una arista se calculan siempre desde
   su vértice interior, así que dos triángulos que la comparten obtienen el
   mismo punto (sin grietas). */
int mgr_clip_triangle(const mgl_vec4_t in[3], mgl_vec4_t out[MGR_CLIP_MAX]);

/* ---- viewport.c --------------------------------------------------------- */
#define MGR_SUBPIXEL_BITS 4
#define MGR_SUBPIXEL (1 << MGR_SUBPIXEL_BITS)

/* Un vértice en el destino: x, y en 1/16 de píxel (el centro del píxel (i, j)
   está en (16 i + 8, 16 j + 8)), y hacia abajo; z de 0 (cerca) a 1 (lejos). */
typedef struct {
    mgl_s32 x, y;
    mgl_real_t z;
    mgl_s32 zq; /* z en Q16.16 (0..65536), solo con MGR_FIXED_DEPTH */
} mgr_window_vertex_t;

/* Profundidad del triángulo en enteros (fixed.c) en vez de float por triángulo (raster3d.c). Necesita
   MGR_INCREMENTAL_DEPTH=1. Experimental: los redondeos difieren de float. */
#ifndef MGR_FIXED_DEPTH
#define MGR_FIXED_DEPTH 0
#endif

/* División de perspectiva y viewport. v debe estar dentro del volumen (w > 0). */
void mgr_viewport_map(const mgr_state_t *s, const mgl_vec4_t *v, mgr_window_vertex_t *out);

/* ---- fixed.c ------------------------------------------------------------ */
/* Geometría en Q16.16 en vez de float (transformar, outcode y viewport de los triángulos sin recortar);
   el recorte sigue en float. Experimental: no da los mismos bits que float. */
#ifndef MGR_FIXED_GEOMETRY
#define MGR_FIXED_GEOMETRY 0
#endif

#if MGR_FIXED_GEOMETRY
typedef struct {
    mgl_s32 x, y, z, w;
} mgr_vec4q_t;

typedef struct {
    mgl_s32 m[16];
} mgr_mat4q_t;

void mgr_mat4q_from_float(const mgl_mat4_t *f, mgr_mat4q_t *q);
void mgr_transform_vertex_q(const mgr_vertices_t *v, mgl_u32 index, const mgr_mat4q_t *mvp,
    mgr_vec4q_t *clip);
unsigned int mgr_outcode_q(const mgr_vec4q_t *v);
void mgr_viewport_map_q(const mgr_state_t *s, const mgr_vec4q_t *v, mgr_window_vertex_t *out);
void mgr_vec4q_to_float(const mgr_vec4q_t *q, mgl_vec4_t *f);
#endif

#if MGR_FIXED_DEPTH
/* El plano de profundidad de un triángulo, en las unidades de raster3d.c: row es la profundidad (Q12 sobre
   MGR_DEPTH_FRAC) en el píxel (px, py), dx y dy lo que cambia por píxel y por fila, y dzi lo que cambia por píxel
   dentro de un span (acotado). incremental: dx * w + dy * h y row caben en 32 bits; si no, solo vale origin. */
typedef struct {
    mgl_s32 dzi, row, dx, dy;
    int incremental;
    long long origin, dx64, dy64;
} mgr_depth_plane_t;

/* area > 0 (de raster3d.c), (px, py) en 1/16 de píxel y w, h el tamaño en píxeles de la caja del triángulo. */
void mgr_depth_plane(const mgr_window_vertex_t *a, const mgr_window_vertex_t *b, const mgr_window_vertex_t *c,
    mgl_s32 area, mgl_s32 px, mgl_s32 py, int w, int h, mgr_depth_plane_t *out);
#endif

/* ---- fragment.c --------------------------------------------------------- */
/* Lo que necesita la etapa de fragmentos para un dibujo: destino, estado y color. */
typedef struct {
    mgl_color_t *color;
    mgl_u16 *depth; /* 0: sin profundidad */
    int color_stride, depth_stride;
    mgl_u32 flags;
    mgl_color_t fill;
} mgr_fragment_t;

/* La profundidad interpolada: unidades del buffer (0..65535) con 8 bits de fracción. */
#define MGR_DEPTH_FRAC 8
#define MGR_DEPTH_MAX ((mgl_s32)65535 << MGR_DEPTH_FRAC)

/* Plano incremental por defecto. Definir a 0 al compilar recupera el inicio
   float por fila anterior para diagnósticos de precisión y rendimiento. */
#ifndef MGR_INCREMENTAL_DEPTH
#define MGR_INCREMENTAL_DEPTH 1
#endif

/* Los píxeles de x0 a x1 - 1 de la fila y (ya dentro del destino). z es la
   profundidad en x0 y dz lo que cambia por píxel. */
void mgr_fragment_span(const mgr_fragment_t *f, int y, int x0, int x1, mgl_s32 z, mgl_s32 dz);

void mgr_clear_color(const mgr_state_t *s, mgl_color_t c);
void mgr_clear_depth(const mgr_state_t *s, mgl_u16 d);

/* ---- raster3d.c --------------------------------------------------------- */
/* Rectángulo de píxeles donde se puede escribir: [x0, x1) x [y0, y1). */
typedef struct {
    int x0, y0, x1, y1;
} mgr_rect_t;

/* Rasteriza un triángulo: aplica culling (flags de f), cubre los píxeles cuyo
   centro está dentro (regla top-left en las aristas) y entrega cada fila a
   mgr_fragment_span. Devuelve el número de píxeles cubiertos, o -1 si se
   descartó por cara o área nula. */
mgl_s32 mgr_raster_triangle(const mgr_window_vertex_t *a, const mgr_window_vertex_t *b,
    const mgr_window_vertex_t *c, const mgr_rect_t *clip, const mgr_fragment_t *f);

/* ---- raster2d.c --------------------------------------------------------- */
/* Comandos 2D en el destino actual (sin profundidad, como V0). */
void mgr_raster2d_target(const mgr_state_t *s);
int mgr_raster2d_batch(const mgr_state_t *s, const unsigned char *cmd);

#endif
