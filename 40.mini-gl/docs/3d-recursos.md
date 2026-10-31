# MiniGL 3D — recursos, memoria y vida útil

## Handles en la API, direcciones en los comandos

La aplicación identifica las mallas por **handles** (`mgl_mesh_t`); los comandos llevan **direcciones** de la
RAM compartida. MiniGL guarda la descripción de cada malla y resuelve el handle al emitir `DRAW_INDEXED`:

```c
mesh = mgl_create_mesh_copy(positions, 8, indices, 36);   /* handle */
mgl_draw_mesh(mesh);    /* DRAW_INDEXED con vertex_addr, index_addr, formatos y stride */
```

Así el renderer de referencia, la CPU de MiniGPU o (en el futuro) la GPU ejecutan los mismos comandos sin
la tabla de handles de MiniGL. `mgl_mesh_info(mesh, &desc)` devuelve la resolución (lo usan los tests).

El handle es `(generación << 16) | (hueco + 1)`. Al destruir una malla su hueco cambia de generación, así
que un handle viejo da `MGL_ERR_HANDLE` aunque el hueco se haya reutilizado. Hay `MGL_MAX_MESHES` (32) huecos.
`0` no es nunca un handle válido.

## Dos modelos de memoria

| | Crear | Quién tiene la memoria | Copia |
|---|---|---|---|
| Aplicación | `mgl_create_mesh(&desc)` | la aplicación: le da a MiniGL las direcciones | ninguna |
| MiniGL | `mgl_create_mesh_copy(pos, n, idx, m)` | MiniGL, en su heap | una, al crear |

- **Memoria de la aplicación**: para programas que ya gestionan sus buffers en SDRAM. MiniGL solo comprueba
  la descripción (formatos admitidos, stride, que los rangos estén dentro de la RAM compartida y alineados) y
  la guarda.
- **Memoria de MiniGL**: `mgl_resources_init(memoria, heap_addr, heap_size)` le da una zona de la RAM
  compartida. Es un *bump allocator* (`mgl_alloc`): no libera piezas sueltas; `mgl_resources_init` lo vacía
  entero y destruye todas las mallas. La copia escribe el **formato serializado** (floats IEEE
  little-endian, índices `u16`), no la representación del host. Si la malla no cabe, no queda nada a medias.

MiniProcessing crea el cubo con la segunda: una vez, en el primer `box()`; el tamaño va en la matriz del
modelo.

Para lo que solo vale un frame (las figuras de `beginShape`/`endShape`) hay una tercera zona, la **memoria
de frame**: `mgl_frame_memory_init(addr, size)` y `mgl_frame_alloc`, o `mgl_create_mesh_frame` para copiar
una malla ahí. `mgl_begin_frame` la vacía entera, así que lo del frame anterior tiene que estar ya ejecutado;
hoy lo está (ejecución síncrona). El handle se puede destruir en cuanto se ha dibujado: el command buffer ya
tiene las direcciones.

## Memoria compartida y su emulación

CPU y GPU de MiniGPU comparten la SDRAM. Un programa la ve a través de un `mgl_memory_t`
([mgl_memory.h](../src/mgl_memory.h)): una ventana `[addr, addr + size)` de direcciones lógicas y dónde está
en el proceso.

| Plataforma | Ventana | Traducción |
|---|---|---|
| MiniGPU (`platform3d_minigpu.c`) | la SDRAM real | `base = (unsigned char *)addr`: identidad |
| Host (`platform3d_host.c`, tests) | un bloque de `calloc` | `base + (dirección - addr)` |

Las dos plataformas usan **las mismas direcciones** ([platform3d.h](../src/platform3d.h)), las de
`platform_minigpu.c` para los framebuffers y el command buffer:

| Dirección | Qué | Tamaño |
|---|---|---|
| `0x01000000` | framebuffer A (RGB565) | 320×240×2 |
| `0x01025800` | framebuffer B | 320×240×2 |
| `0x0104B000` | command buffer | 64 KB |
| `0x0105B000` | profundidad (U16) | 320×240×2 |
| `0x01080800` | heap de MiniGL | 64 KB |
| `0x01090800` | memoria de frame de MiniGL | 64 KB |

El host emula 1 MB desde `0x01000000`; una captura (`-c`) guarda esa ventana entera.

`mgl_memory_ptr(m, addr, bytes, align)` valida rango y alineación y devuelve el puntero nativo, o 0. Se llama
**una vez por recurso**, al decodificar el comando (el framebuffer al recibir `SET_RENDER_TARGET`, la malla al
recibir `DRAW_INDEXED`), nunca por píxel: el renderer escribe después directamente con ese puntero, sin
callbacks. La dirección 0 nunca es válida.

Los datos de la ventana son little-endian. Comandos y vértices se leen por bytes en el host (funciona en
cualquiera), pero píxeles y profundidad se escriben como enteros nativos: `mgl_memory_init` rechaza un host
big-endian.

## Vida útil

Un recurso que use un command buffer tiene que seguir válido **y sin cambios** hasta que ese buffer se haya
ejecutado. Hoy la ejecución es síncrona (`mgr_execute` vuelve con el trabajo hecho), así que basta con no
tocar los datos entre `mgl_draw_mesh` y el final de `platform3d_end`. Con mallas de la aplicación es
responsabilidad suya; destruir el handle no libera ni invalida la memoria, solo el handle.

No hay seguimiento automático de dependencias. Lo previsto para cuando haga falta:

- **Ejecución asíncrona y fences.** `mgr_execute` devolverá el control antes de terminar; `END_FRAME` ya lleva
  el número de frame, que puede ser el valor de la fence que se señaliza al acabar.
- **Varios frames en vuelo.** Varios command buffers (uno por frame en vuelo) en lugar del único de
  `platform3d.c`, y no reutilizar uno hasta que su fence se haya señalizado.
- **Reutilizar buffers de vértices.** Lo mismo con los recursos: la aplicación espera a la fence del último
  frame que los usó, o usa memoria nueva (el bump allocator encaja bien con un heap por frame que se vacía al
  señalizar).

## Coherencia de cachés

No se supone coherencia automática entre CPU y GPU. Hoy todo lo ejecuta una CPU y no hace falta nada. Cuando
la GPU lea los comandos:

1. Antes de lanzar el trabajo, la CPU tiene que hacer visibles en la SDRAM el command buffer y los recursos
   que haya escrito (volcar sus líneas de caché, si las hay). Los sitios son `mgl_create_mesh_copy` (al
   copiar) y `platform3d_end` (antes de `mgr_execute`).
2. Antes de que la CPU lea algo que escribió la GPU (el framebuffer para copiarlo, una captura), tiene que
   invalidar lo que tenga en caché de esa zona.
3. La presentación (swap en vblank) tiene que esperar a la fence del frame.

Estos puntos son de diseño: no hay todavía operaciones de volcado ni de invalidación en `mgl_memory`.
