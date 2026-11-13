#ifndef MGL_EXT_H
#define MGL_EXT_H

/* MIN/MAX y CLZ. Con MGL_EXT=1 en MiniGPU (make EXT=1) son las instrucciones EXT
   de la 38 (capabilities `minmax` y `clz`), mediante los intrínsecos de lcc
   (mini_ext.h): una instrucción y sin saltos. Si no, el C de siempre, escrito
   como `if` sobre la propia variable y no con ?: , que mini-lcc pasa por una
   temporal en la pila. Mismos resultados en los dos casos. */
#if defined(__MINIGPU__) && defined(MGL_EXT) && MGL_EXT
#include "mini_ext.h"
#define MGL_EXT_NATIVE 1
#define MGL_SET_MIN(var, v) ((var) = __mini_min((var), (v)))
#define MGL_SET_MAX(var, v) ((var) = __mini_max((var), (v)))
#define MGL_CLZ(x) __mini_clz(x)
#else
#define MGL_EXT_NATIVE 0
#define MGL_SET_MIN(var, v) do { if ((v) < (var)) (var) = (v); } while (0)
#define MGL_SET_MAX(var, v) do { if ((v) > (var)) (var) = (v); } while (0)
#endif

#endif
