/* console.h - destinos de texto serie y consola HDMI de 80x30. */
#ifndef MINI_CONSOLE_H
#define MINI_CONSOLE_H

#include <stdarg.h>

int serial_putc(int c);
int console_putc(int c);
int serial_console_putc(int c);
void console_init(unsigned foreground, unsigned background);
void console_enable(void);
int console_vprintf(const char *fmt, va_list ap);
int console_printf(const char *fmt, ...);
int tee_vprintf(const char *fmt, va_list ap);
int tee_printf(const char *fmt, ...);

#endif
