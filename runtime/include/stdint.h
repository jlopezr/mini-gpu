/* stdint.h - tipos de anchura fija para mini-lcc
 *
 * La libreria de lcc para MiniISA (u.lcc/include/mini/none) no trae stdint.h, y sin
 * esta cabecera `cc -E` cogeria la del sistema anfitrion, que lcc no sabe leer.
 * En MiniISA: char 8 bits, short 16, int y long 32, long long 64, punteros 32.
 */
#ifndef MINI_STDINT_H
#define MINI_STDINT_H

typedef signed char        int8_t;
typedef short              int16_t;
typedef int                int32_t;
typedef long long          int64_t;
typedef unsigned char      uint8_t;
typedef unsigned short     uint16_t;
typedef unsigned int       uint32_t;
typedef unsigned long long uint64_t;

typedef int                intptr_t;
typedef unsigned int       uintptr_t;

#define INT8_MIN   (-128)
#define INT8_MAX   127
#define INT16_MIN  (-32767-1)
#define INT16_MAX  32767
#define INT32_MIN  (-2147483647-1)
#define INT32_MAX  2147483647
#define INT64_MIN  (-9223372036854775807LL-1)
#define INT64_MAX  9223372036854775807LL
#define UINT8_MAX  255
#define UINT16_MAX 65535
#define UINT32_MAX 4294967295U
#define UINT64_MAX 18446744073709551615ULL

#define INTPTR_MIN  INT32_MIN
#define INTPTR_MAX  INT32_MAX
#define UINTPTR_MAX UINT32_MAX

#endif
