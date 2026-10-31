#ifndef MGL_TYPES_H
#define MGL_TYPES_H

/* Tipos enteros de tamaño fijo sin stdint.h (C99). Lo que se supone se comprueba
   al compilar (MGL_STATIC_ASSERT): unsigned short de 16 bits e int de 32, en el
   host y en MiniGPU (mini-lcc). No se usa long: en el host de 64 bits mide 64. */
typedef unsigned char mgl_u8;
typedef unsigned short mgl_u16;
typedef short mgl_s16;
typedef unsigned int mgl_u32;
typedef int mgl_s32;

/* Un píxel RGB565. */
typedef mgl_u16 mgl_color_t;

#define MGL_STATIC_ASSERT(name, cond) typedef char mgl_assert_##name[(cond) ? 1 : -1]

MGL_STATIC_ASSERT(u8, sizeof(mgl_u8) == 1);
MGL_STATIC_ASSERT(u16, sizeof(mgl_u16) == 2);
MGL_STATIC_ASSERT(u32, sizeof(mgl_u32) == 4);
MGL_STATIC_ASSERT(s32, sizeof(mgl_s32) == 4);

#endif
