#ifndef MGL_BYTES_H
#define MGL_BYTES_H

#include "mgl_types.h"

/* Lectura y escritura del formato binario, que es little-endian. En el host se
   lee y escribe byte a byte, que vale en cualquier máquina y con cualquier
   alineación. En MiniGPU, que es little-endian, con accesos de 16 y 32 bits:
   los campos están alineados (la memoria del buffer también, lo pide
   mgl_cmd_init) y lcc no aplica strict aliasing ni expande funciones en línea,
   por eso son macros. LOW y HIGH: las dos mitades con signo de una palabra. */
#ifdef __MINIGPU__
#define WR16(p, v) (*(unsigned short *)(p) = (unsigned short)(v))
#define WR32(p, v) (*(mgl_u32 *)(p) = (mgl_u32)(v))
#define RD16(p) ((unsigned int)*(const unsigned short *)(p))
#define RD32(p) (*(const mgl_u32 *)(p))
#define LOW(p) ((int)((p) << 16) >> 16) /* lcc desplaza un int con signo */
#define HIGH(p) ((int)(p) >> 16)
#else
/* Macros también en el host (una función static sin usar en una unidad es un aviso): p es un
   unsigned char * y ni p ni v pueden tener efectos laterales. */
#define WR16(p, v) ((p)[0] = (unsigned char)(v), (p)[1] = (unsigned char)((unsigned int)(v) >> 8))
#define WR32(p, v)                                                                       \
    ((p)[0] = (unsigned char)(v), (p)[1] = (unsigned char)((mgl_u32)(v) >> 8),           \
        (p)[2] = (unsigned char)((mgl_u32)(v) >> 16), (p)[3] = (unsigned char)((mgl_u32)(v) >> 24))
#define RD16(p) ((unsigned int)(p)[0] | ((unsigned int)(p)[1] << 8))
#define RD32(p) ((mgl_u32)(p)[0] | ((mgl_u32)(p)[1] << 8) | ((mgl_u32)(p)[2] << 16) | ((mgl_u32)(p)[3] << 24))
#define LOW(p) ((int)(((mgl_u32)(p) & 65535U) ^ 32768U) - 32768)
#define HIGH(p) LOW((mgl_u32)(p) >> 16)
#endif

/* Dos enteros de 16 bits con signo en una palabra: a en la mitad baja. */
#define PACK(a, b) ((mgl_u32)((unsigned int)(a) & 65535U) | ((mgl_u32)((unsigned int)(b) & 65535U) << 16))
#define FIT(v) ((v) >= -32768 && (v) <= 32767)

#endif
