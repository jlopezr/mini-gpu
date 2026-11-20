/* stdio.h - salida formateada mínima para mini-lcc.
 *
 * printf escribe en la cola serie. La consola HDMI es un destino explícito en
 * console.h, de modo que una aplicación gráfica no recibe logs superpuestos.
 */
#ifndef MINI_STDIO_H
#define MINI_STDIO_H

#include <stdarg.h>
#include <stddef.h>

int putchar(int c);
int puts(const char *s);
int vprintf(const char *fmt, va_list ap);
int printf(const char *fmt, ...);
int vsnprintf(char *dst, size_t size, const char *fmt, va_list ap);
int snprintf(char *dst, size_t size, const char *fmt, ...);

#endif
