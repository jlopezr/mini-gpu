/* mmio.h - los registros que usan los programas en C (mmio.md)
 *
 *   REG(VIDEO_SWAP) = 1;
 *   while (REG(VIDEO_SWAP)) ;
 *
 * Los numeros salen de mmio_map.h, que se GENERA desde 1.isa/mmio_map.vh
 * (tools/generate-mmio): aqui solo se les pone el nombre corto, el de mmio.inc
 * sin el prefijo MMIO_. Solo lo que hace falta hoy; lo demas, con el nombre largo.
 */
#ifndef MMIO_H
#define MMIO_H

#include "mmio_map.h"

#define REG(address) (*(volatile unsigned *)(address))

#define VIDEO_BASE      MMIO_VIDEO_BASE
#define VIDEO_CTRL      MMIO_VIDEO_CTRL_ADDR
#define VIDEO_FB_FRONT  MMIO_VIDEO_FB_FRONT_ADDR
#define VIDEO_FB_BACK   MMIO_VIDEO_FB_BACK_ADDR
#define VIDEO_SWAP      MMIO_VIDEO_SWAP_ADDR
#define VIDEO_MODE_SCANOUT MMIO_VIDEO_MODE_SCANOUT

#define GPU_BASE        MMIO_GPU_BASE
#define GPU_CONTROL     MMIO_GPU_CONTROL_ADDR
/* bit de GPU_CONTROL (mmio.md §14.1); el mapa no tiene los bits de los registros */
#define GPU_CTRL_RESET  0x10

/* ciclos de CPU en la placa; en el simulador bench_now() devuelve siempre 0 */
extern int bench_now(void);

#endif
