/* stdlib.h - subconjunto mínimo de la biblioteca C para mini-lcc. */
#ifndef MINI_STDLIB_H
#define MINI_STDLIB_H

#include <stddef.h>

int atoi(const char *s);
int abs(int n);
void exit(int status);
void *malloc(size_t size);
void *calloc(size_t count, size_t size);
void *realloc(void *ptr, size_t size);
void free(void *ptr);

/* El programa entrega una región de RAM al heap antes de su primer malloc(). */
void mini_heap_init(void *base, size_t size);
size_t mini_heap_bytes_free(void);
size_t mini_heap_bytes_used(void);

#endif
