/* Minimal math surface needed by the Doom core.  Its trigonometric table is
 * precomputed in tables.c; the only live floating operation is fabs(). */
#ifndef MINI_MATH_H
#define MINI_MATH_H

#define fabs(value) ((value) < 0 ? -(value) : (value))

#endif
