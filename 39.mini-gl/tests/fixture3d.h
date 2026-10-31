#ifndef FIXTURE3D_H
#define FIXTURE3D_H

/* Lo común de los tests 3D: una RAM compartida emulada pequeña con el command
   buffer, un destino de T_W x T_H con profundidad, la memoria de MiniGL y una
   zona para mallas de la aplicación; MiniGL y el renderer preparados sobre
   ella. */

#include "minigl3d.h"
#include "mgr.h"
#include <stdio.h>

#define T_W 64
#define T_H 48
#define T_RAM_ADDR 0x01000000u
#define T_RAM_SIZE 0x00040000u
#define T_CMD_ADDR 0x01000000u   /* 16 KB */
#define T_FB_ADDR 0x01004000u    /* T_W * T_H * 2 */
#define T_DEPTH_ADDR 0x01006000u /* T_W * T_H * 2 */
#define T_HEAP_ADDR 0x01008000u  /* 32 KB de MiniGL */
#define T_HEAP_BYTES 0x8000u
#define T_APP_ADDR 0x01010000u   /* mallas de la aplicación */
#define T_FRAME_ADDR 0x01018000u /* 32 KB de memoria de frame de MiniGL */
#define T_FRAME_BYTES 0x8000u

extern unsigned char *t_ram;
extern mgl_memory_t t_mem;
extern mgl_cmd_buffer_t t_cmd;
extern mgr_renderer_t t_rnd;
extern int t_failures;

#define CHECK(c)                                                          \
    do {                                                                  \
        if (!(c)) {                                                       \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);           \
            t_failures++;                                                 \
        }                                                                 \
    } while (0)

/* RAM a cero; command buffer de cmd_capacity bytes; recursos y renderer. */
void t_init(mgl_u32 cmd_capacity);
/* Buffer vacío y en modo diferido, destino T_W x T_H con profundidad, mgl_begin_frame. */
void t_begin(void);
/* mgl_end_frame y, si va bien, mgr_execute. El error de MiniGL o del renderer. */
int t_end_and_run(void);
/* Ejecuta lo que haya en el buffer (ya cerrado). */
int t_run(void);

mgl_color_t t_pixel(int x, int y);
mgl_u16 t_depth(int x, int y);
/* Cuántos píxeles tienen el color c. */
int t_count(mgl_color_t c);

/* El comando número nth (desde 0) con ese opcode en t_cmd, o 0. */
const unsigned char *t_find(unsigned int opcode, int nth);
/* El opcode del comando número i del buffer (o 0 si no hay tantos). */
unsigned int t_opcode_at(int i);

/* Una malla en memoria de la aplicación (desde T_APP_ADDR + offset). */
mgl_mesh_t t_mesh(mgl_u32 offset, const float *xyz, mgl_u32 vertices, const unsigned short *indices,
    mgl_u32 index_count);

/* Un triángulo directamente en coordenadas de recorte (todas las matrices identidad). */
void t_triangle(mgl_u32 offset, float x0, float y0, float z0, float x1, float y1, float z1, float x2,
    float y2, float z2);

int t_report(const char *name);

#endif
