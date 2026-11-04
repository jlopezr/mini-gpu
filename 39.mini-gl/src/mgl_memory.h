#ifndef MGL_MEMORY_H
#define MGL_MEMORY_H

#include "mgl_types.h"

/* La RAM compartida de MiniGPU (SDRAM de CPU y GPU) vista desde un programa:
   una ventana [addr, addr + size) de direcciones lógicas de 32 bits y dónde
   está en la memoria de este proceso.
   - En MiniGPU la dirección es la física: base = (unsigned char *)addr.
   - En el host la ventana es un bloque de memoria del proceso (RAM emulada).
   Los comandos y los recursos usan las mismas direcciones en los dos casos.

   Se traduce una vez por recurso (al decodificar un comando), no por píxel: el
   renderer guarda el puntero del framebuffer y escribe directamente.

   Los datos en la ventana son little-endian. El host debe serlo también para
   que los píxeles y la profundidad, que se escriben como enteros nativos,
   tengan ese orden (mgl_memory_init lo comprueba).

   Coherencia: CPU y GPU no comparten cachés. Hoy todo lo ejecuta la misma CPU y
   no hace falta nada; cuando lo lea la GPU, quien escriba un recurso o un
   command buffer tendrá que volcarlo antes de lanzar el trabajo, y la CPU
   tendrá que invalidar lo que la GPU escriba antes de leerlo. Ver
   docs/3d-recursos.md. */
typedef struct {
    unsigned char *base;
    mgl_u32 addr, size;
} mgl_memory_t;

/* MGL_OK (0) o -1 si los argumentos no valen o el host no es little-endian. */
int mgl_memory_init(mgl_memory_t *m, void *base, mgl_u32 addr, mgl_u32 size);

/* El puntero nativo de [addr, addr + bytes), o 0 si se sale de la ventana, si
   addr no es múltiplo de align (potencia de 2) o si addr es 0, que no es una
   dirección válida para ningún recurso. */
void *mgl_memory_ptr(const mgl_memory_t *m, mgl_u32 addr, mgl_u32 bytes, mgl_u32 align);

/* La dirección de p (que debe estar en la ventana), o 0. */
mgl_u32 mgl_memory_addr(const mgl_memory_t *m, const void *p);

#endif
