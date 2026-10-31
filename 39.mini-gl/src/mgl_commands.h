#ifndef MGL_COMMANDS_H
#define MGL_COMMANDS_H

/* Contrato binario del command buffer: lo que escribe MiniGL y leen los
   renderers (V1 y V2 en 2D, src/render/3d/ en 3D). Descripción completa, con
   ejemplos, en docs/command-buffer.md.

   Reglas de serialización:
   - Todo es little-endian. Los campos de 16 y 32 bits van alineados a su
     tamaño dentro del comando, y cada comando empieza en un múltiplo de 4.
   - No se copia ninguna estructura C: cada campo se escribe por su offset
     (WR16/WR32 de mgl_bytes.h). Los offsets de este fichero son el contrato.
   - Ningún comando lleva punteros nativos ni handles: las direcciones son de
     32 bits en el espacio de RAM compartida de MiniGPU (mgl_memory.h).
   - Los campos reservados valen 0; un renderer los comprueba para detectar un
     buffer de una versión posterior.

   Cabecera de buffer (16 bytes, offset 0):
     +0 u32 magic  +4 u32 version  +8 u32 used_bytes  +12 u32 capacity
   Cabecera de comando (16 bytes, la tienen todos):
     +0 u16 opcode  +2 u16 flags  +4 u32 size_bytes  +8 u32 arg0  +12 u32 arg1
   Tras ella, size_bytes - 16 bytes de payload. El siguiente comando empieza en
   offset + size_bytes. Un comando de V1 (opcode de 32 bits) es el mismo con
   flags = 0. */

#define MGL_BUFFER_MAGIC 0x4D474C30U /* "0LGM" en memoria */
#define MGL_BUFFER_VERSION 1U        /* solo comandos 2D (CLEAR sin flags, BATCH) */
#define MGL_BUFFER_VERSION_3D 2U     /* algún comando 3D: V1 y V2 no lo aceptan */
#define MGL_BUFFER_HEADER_BYTES 16U
#define MGL_CMD_HEADER_BYTES 16U

/* Offsets de la cabecera de comando. */
#define MGL_CMD_OPCODE 0
#define MGL_CMD_FLAGS 2
#define MGL_CMD_SIZE 4
#define MGL_CMD_ARG0 8
#define MGL_CMD_ARG1 12
#define MGL_CMD_PAYLOAD 16

/* ---- Comandos 2D (versión 1) ---------------------------------------------- */

/* CLEAR, 16 bytes. arg0 = color RGB565. Con flags = MGL_CLEAR_DEPTH (versión 2)
   borra también la profundidad: arg1 = valor en Q16.16 sin signo, de 0 (cerca)
   a 0x10000 (lejos). Sin flags arg1 = 0. Borra todo el destino, sin viewport. */
#define MGL_CMD_CLEAR 1U
#define MGL_CLEAR_BYTES 16U
#define MGL_CLEAR_DEPTH 1U
#define MGL_DEPTH_ONE 0x10000U

/* BATCH, 40 bytes: una primitiva 2D en coordenadas de píxel.
   arg0 = número de primitivas (siempre 1), arg1 = 0.
   +16 u32 tipo (MGL_PRIM_*)  +20 u32 p0  +24 u32 p1  +28 u32 p2
   +32 u16 color de relleno  +34 u16 color de contorno  +36 u16 flags (MGL_BATCH_*)
   +38 u16 grosor del contorno.
   p0..p2 llevan pares (x, y) con PACK; IMAGE lleva en p1 un handle local del
   contexto V1 (no una dirección): el renderer 3D lo rechaza. */
#define MGL_CMD_BATCH 2U
#define MGL_BATCH_BYTES 40U
#define MGL_PRIM_POINT 1U
#define MGL_PRIM_LINE 2U
#define MGL_PRIM_RECT 3U
#define MGL_PRIM_CIRCLE 4U
#define MGL_PRIM_TRIANGLE 5U
#define MGL_PRIM_IMAGE 6U
#define MGL_BATCH_FILL 1U
#define MGL_BATCH_STROKE 2U

/* ---- Comandos 3D (versión 2) ---------------------------------------------- */

/* SET_RENDER_TARGET, 32 bytes. Destino del color (2D y 3D) y de la profundidad.
   arg0 = dirección del color, arg1 = dirección de la profundidad (0: sin ella).
   +16 u16 ancho  +18 u16 alto  +20 u16 stride del color (píxeles)
   +22 u16 stride de la profundidad (píxeles; 0 sin profundidad)
   +24 u16 formato del color (MGL_COLOR_*)  +26 u16 formato de profundidad
   (MGL_DEPTH_*)  +28 u32 reservado.
   Pone el viewport a todo el destino. */
#define MGL_CMD_SET_RENDER_TARGET 0x10U
#define MGL_SET_RENDER_TARGET_BYTES 32U

/* SET_VIEWPORT, 16 bytes. arg0 = PACK(x, y), arg1 = PACK(ancho, alto), en
   píxeles del destino, con signo. La profundidad va siempre de 0 a 1. */
#define MGL_CMD_SET_VIEWPORT 0x11U
#define MGL_SET_VIEWPORT_BYTES 16U

/* SET_MATRIX, 80 bytes. arg0 = cuál (MGL_MATRIX_*), arg1 = formato de los
   componentes (MGL_FORMAT_*). +16: 16 componentes de 32 bits, column-major
   (m[columna * 4 + fila]), vectores columna. */
#define MGL_CMD_SET_MATRIX 0x12U
#define MGL_SET_MATRIX_BYTES 80U

/* SET_RENDER_STATE, 16 bytes. arg0 = bits MGL_STATE_*, arg1 = reservado. */
#define MGL_CMD_SET_RENDER_STATE 0x13U
#define MGL_SET_RENDER_STATE_BYTES 16U

/* SET_COLOR, 16 bytes. arg0 = color uniforme RGB565 (16 bits bajos), arg1 = reservado. */
#define MGL_CMD_SET_COLOR 0x14U
#define MGL_SET_COLOR_BYTES 16U

/* DRAW_INDEXED, 32 bytes. arg0 = dirección de los vértices, arg1 = dirección
   de los índices.
   +16 u32 número de vértices  +20 u32 número de índices
   +24 u16 formato de vértice (MGL_VERTEX_*)  +26 u16 formato de índice (MGL_INDEX_*)
   +28 u16 stride del vértice (bytes)  +30 u16 topología (MGL_TOPOLOGY_*) */
#define MGL_CMD_DRAW_INDEXED 0x15U
#define MGL_DRAW_INDEXED_BYTES 32U

/* END_FRAME, 16 bytes. arg0 = número de frame (para fences futuras; no cambia
   lo que se dibuja), arg1 = reservado. Tras él el estado vuelve al inicial. */
#define MGL_CMD_END_FRAME 0x16U
#define MGL_END_FRAME_BYTES 16U

/* Formatos numéricos (SET_MATRIX). */
#define MGL_FORMAT_FLOAT32 1U
#define MGL_FORMAT_Q16_16 2U /* reservado: se rechaza */

/* Matrices. */
#define MGL_MATRIX_MODEL 1U
#define MGL_MATRIX_VIEW 2U
#define MGL_MATRIX_PROJECTION 3U

/* Formatos de vértice e índice. */
#define MGL_VERTEX_POSITION_F32_XYZ 1U
#define MGL_VERTEX_POSITION_Q16_16_XYZ 2U /* reservado: se rechaza */
#define MGL_INDEX_UINT16 1U
#define MGL_INDEX_UINT32 2U /* reservado: se rechaza */
#define MGL_TOPOLOGY_TRIANGLES 1U

/* Formatos del destino. */
#define MGL_COLOR_RGB565 1U
#define MGL_DEPTH_NONE 0U
#define MGL_DEPTH_U16 1U /* 0 cerca, 65535 lejos */

/* Estado (SET_RENDER_STATE). La prueba de profundidad es LESS. Front face:
   antihorario en coordenadas normalizadas (y hacia arriba), como OpenGL. */
#define MGL_STATE_DEPTH_TEST 1U
#define MGL_STATE_DEPTH_WRITE 2U
#define MGL_STATE_BLEND 4U /* reservado: se rechaza */
#define MGL_STATE_CULL_BACK 8U
#define MGL_STATE_CULL_FRONT 16U
#define MGL_STATE_DEFAULT MGL_STATE_DEPTH_WRITE

#endif
