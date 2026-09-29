#ifndef BASIC_PLATFORM_H
#define BASIC_PLATFORM_H

/* The only two things the BASIC needs from the machine it runs on. Each target
   provides them in its own file (basic_platform_host.c, basic_platform_mini.c);
   basic_main.c does not know which one it got. They have the shape of the
   MBReplIO callbacks. */

/* Next input byte, or a negative value when there will be no more. */
int platform_get_char(void *ctx);

void platform_put_char(char c, void *ctx);

#endif
