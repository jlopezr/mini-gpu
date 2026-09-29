#include "basic_platform.h"

#include <stdio.h>

int platform_get_char(void *ctx)
{
    (void)ctx;
    return getchar();
}

void platform_put_char(char c, void *ctx)
{
    (void)ctx;
    putchar(c);
}
