#include "basic_platform.h"

/* MiniCPU serial port (MMIO v2, see tools/sim_devices.py SerialDevice).
   STATUS: bits 7..0 = bytes waiting in RX, bits 15..8 = free slots in TX.
   Reading DATA takes the byte out of the RX queue. Nothing blocks in hardware,
   so the waiting is done here. */
#define UART_DATA   (*(volatile unsigned int *)0x80100000)
#define UART_STATUS (*(volatile unsigned int *)0x80100004)

int platform_get_char(void *ctx)
{
    (void)ctx;
    while ((UART_STATUS & 0xFF) == 0) {
#ifdef BASIC_UART_EOF
        /* The simulator has all the input queued from the start, so an empty
           queue means it is over. On a board it only means "not yet". */
        return -1;
#endif
    }
    return (int)(UART_DATA & 0xFF);
}

void platform_put_char(char c, void *ctx)
{
    (void)ctx;
    while (((UART_STATUS >> 8) & 0xFF) == 0) {
    }
    UART_DATA = (unsigned int)(unsigned char)c;
}
