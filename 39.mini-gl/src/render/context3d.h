#ifndef MGL_CONTEXT3D_H
#define MGL_CONTEXT3D_H

/* Contexto de render 3D (RAM emulada en host o SDRAM en MiniGPU): mapa de memoria, MiniGL, command buffer y renderer de referencia.
   La interfaz común para los drivers está en context.h. Esta interfaz
   específica expone RAM, comandos y renderer para tests y diagnósticos. */

#include "processing3d.h"
#include "context.h"
#include "minigl3d.h"
#include "mgr.h"

/* La RAM compartida que usa un sketch 3D: las mismas direcciones en el host
   (un bloque del proceso) y en MiniGPU (la SDRAM). Los dos framebuffers y el
   command buffer están donde los pone minigpu.c en 2D. */
#define P3D_RAM_BASE 0x01000000u
#define P3D_RAM_SIZE 0x00100000u
#define P3D_FB_A 0x01000000u        /* 320 * 240 * 2 bytes */
#define P3D_FB_B 0x01025800u
#define P3D_COMMANDS 0x0104B000u
#define P3D_COMMAND_BYTES 0x10000u
#define P3D_DEPTH 0x0105B000u       /* 320 * 240 * 2 bytes, U16 */
#define P3D_HEAP 0x01080800u        /* recursos de MiniGL (la malla del cubo y las de shape()) */
#define P3D_HEAP_BYTES 0x40000u
#define P3D_FRAME_HEAP 0x010C0800u  /* memoria de frame de MiniGL (beginShape/endShape) */
#define P3D_FRAME_HEAP_BYTES 0x10000u
#define P3D_MAX_W 320
#define P3D_MAX_H 240

extern mgl_memory_t context3d_memory;
extern mgr_renderer_t context3d_renderer;
extern mgl_cmd_buffer_t context3d_commands;

/* ram: dónde está P3D_RAM_BASE en este proceso. 0 si va bien. */
int context3d_init(void *ram);

/* Empieza un frame que se dibujará en color_addr (un framebuffer de
   P3D_MAX_W x P3D_MAX_H como mucho). */
int context3d_begin(mgl_u32 color_addr);

/* Cierra el frame y lo ejecuta con el renderer. MGL_OK o el error (de MiniGL,
   o del renderer: MGR_*). Si before_execute no es 0, se le llama justo antes
   de ejecutar (para guardar el command buffer y la RAM). */
int context3d_end(void (*before_execute)(void));

/* Puntero nativo de un framebuffer de la ventana. */
mgl_color_t *context3d_pixels(mgl_u32 addr);

#endif
