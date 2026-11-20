/* Doom includes assert.h in sha1.c but does not use assertions there. */
#ifndef MINI_ASSERT_H
#define MINI_ASSERT_H
#define assert(expression) ((void) 0)
#endif
