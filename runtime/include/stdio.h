/* stdio.h - salida formateada mínima para mini-lcc.
 *
 * printf escribe en la cola serie. La consola HDMI es un destino explícito en
 * console.h, de modo que una aplicación gráfica no recibe logs superpuestos.
 */
#ifndef MINI_STDIO_H
#define MINI_STDIO_H

#include <stdarg.h>
#include <stddef.h>

/* Console streams only.  They are not backed by a filesystem. */
typedef struct MiniFile FILE;
extern FILE *stdout;
extern FILE *stderr;

int putchar(int c);
int puts(const char *s);
int vprintf(const char *fmt, va_list ap);
int printf(const char *fmt, ...);
int vfprintf(FILE *stream, const char *fmt, va_list ap);
int fprintf(FILE *stream, const char *fmt, ...);
int fflush(FILE *stream);
FILE *fopen(const char *path, const char *mode);
int fclose(FILE *stream);
size_t fread(void *ptr, size_t size, size_t count, FILE *stream);
size_t fwrite(const void *ptr, size_t size, size_t count, FILE *stream);
int fseek(FILE *stream, long offset, int whence);
long ftell(FILE *stream);
int feof(FILE *stream);
int fscanf(FILE *stream, const char *fmt, ...);
int sscanf(const char *text, const char *fmt, ...);
int remove(const char *path);
int rename(const char *oldpath, const char *newpath);

#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2
int vsnprintf(char *dst, size_t size, const char *fmt, va_list ap);
int snprintf(char *dst, size_t size, const char *fmt, ...);

#endif
