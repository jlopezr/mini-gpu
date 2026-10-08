/* mmio.h - los registros de la placa 36 que usan los programas en C (mmio.md)
 *
 *   REG(VIDEO_SWAP) = 1;
 *   while (REG(VIDEO_SWAP)) ;
 *
 * Solo lo que hace falta hoy; los nombres son los de mmio.inc sin el prefijo MMIO_.
 */
#ifndef MMIO_H
#define MMIO_H

#define REG(address) (*(volatile unsigned *)(address))

#define VIDEO_BASE      0x80200000
#define VIDEO_CTRL      (VIDEO_BASE + 0x00)
#define VIDEO_FB_FRONT  (VIDEO_BASE + 0x04)
#define VIDEO_FB_BACK   (VIDEO_BASE + 0x08)
#define VIDEO_SWAP      (VIDEO_BASE + 0x0C)
#define VIDEO_MODE_SCANOUT 2

#define GPU_BASE        0x82000000
#define GPU_CONTROL     (GPU_BASE + 0x18)
#define GPU_CTRL_RESET  0x10

/* ciclos de CPU en la placa; en el simulador bench_now() devuelve siempre 0 */
extern int bench_now(void);

#endif
