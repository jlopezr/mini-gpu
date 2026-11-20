/* strings.h - extensiones POSIX mínimas de cadenas para mini-lcc. */
#ifndef MINI_STRINGS_H
#define MINI_STRINGS_H

#include <stddef.h>

void bzero(void *dst, size_t n);
int strcasecmp(const char *a, const char *b);
int strncasecmp(const char *a, const char *b, size_t n);

#endif
