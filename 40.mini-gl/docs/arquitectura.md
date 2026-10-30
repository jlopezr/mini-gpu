# MiniGL — arquitectura y decisiones

## Objetivo
API Processing sencilla y desacoplada del hardware, implementada sobre MiniGL. MiniGL dispone de un backend CPU directo (V0), otro CPU diferido (V1) y un prototipo GPU SIMT (V2). Todos escriben en un framebuffer RGB565 (16 bits/píxel). Se persigue comparar alternativas con el mismo programa y, cuando procede, el mismo command buffer.

## Capas

```text
Aplicación (setup/draw)
       ↓
Processing: background, fill, rect, circle, line, triangle, image...
       ↓
MiniGL: estado de dibujo y emisión de primitivas
       ├── V0 directo → rasterizador CPU → framebuffer
       └── diferido → command buffer
                        ├── V1 intérprete CPU → rasterizador CPU
                        └── V2 intérprete GPU (8 lanes) → framebuffer
```

## API y nomenclatura
Se adoptó `mgl_` para funciones y tipos y `MGL_` para macros y constantes. Processing conserva sus nombres sin prefijo (`rect`, `fill`, `background`, etc.). Los originales `mg_` / `MG_` se conservan intactos en `archive/`. El cambio en `src/` es mecánico, no una redefinición de semántica.

API actual: `mgl_bind`, `mgl_set_deferred`, `mgl_cmd_init`, `mgl_cmd_reset`, `mgl_cmd_render_cpu`, `mgl_cmd_status`, `mgl_clear`, `mgl_fill`, `mgl_no_fill`, `mgl_stroke`, `mgl_no_stroke`, `mgl_stroke_weight`, `mgl_point`, `mgl_line`, `mgl_rect`, `mgl_circle`, `mgl_triangle`, `mgl_image`. Renderer GPU: `mgl_gpu_render`, adaptador host `mgl_gpu_render_host` y `mgl_gpu_sprites_from_cmd`.

API Processing: `size`, `background`/`fill`/`stroke` con `(r, g, b)` 0–255 (como Arduino TFT), sus variantes RGB565 `background565`/`fill565`/`stroke565`, `color565` (como Adafruit_GFX), `noFill`, `noStroke`, `strokeWeight`, `point`, `line`, `rect`, `circle` (diámetro, como en Processing; `mgl_circle` usa radio), `triangle`, `image`, `width`/`height`, `frameCount`, `mouseX`/`mouseY` y `mousePressed`. La aplicación define `setup()`/`draw()`; `size()`, esas variables y el bucle los da la plataforma: `src/platform_host.c` (un frame a PPM) o `src/platform_sdl.c` (ventana SDL2, `draw()` a 60 fps). Lo común, incluida la ejecución de un frame con V0, V1 o V2, está en `src/platform.c`.

## Algoritmos y opciones
- CLEAR: rellenar framebuffer RGB565.
- POINT: escribir píxel, o brocha según grosor.
- LINE: Bresenham con enteros.
- RECT: spans horizontales y clipping.
- CIRCLE: prueba de distancia cuadrática para relleno; contorno por algoritmo incremental del punto medio. Optimización futura: spans incrementales sin multiplicaciones por píxel.
- TRIANGLE: funciones de borde en bounding box. Optimización futura: evaluación incremental y regla top-left definida.
- IMAGE: sprite RGB565 opaco con clipping.

No hay antialiasing ni transformaciones en la versión actual. Para el hardware real conviene medir stores de 16 bits frente a stores de 32 bits (dos píxeles), alineación y tráfico SDRAM.

## Memoria y presentación
El framebuffer se suministra externamente mediante `mgl_bind(pixels,width,height,stride)`; `stride` está en píxeles. El renderizador no fija direcciones físicas ni realiza el swap. La arquitectura prevista usa front/back buffer RGB565 y presenta cambiando la dirección en vblank tras completar el render; no copiando píxeles. Para cambiar de buffer sin perder el estado de dibujo está `mgl_set_target(pixels, previous)`: como en Processing el lienzo se conserva entre frames y el trasero tiene lo de hace dos, deja pendiente copiar `previous` (el delantero) y solo la hace si se dibuja algo antes de un `mgl_clear`, que lo tapa todo; `mgl_cmd_render_cpu` empieza por el último CLEAR del buffer. `mgl_finish` hace la copia si el frame no dibujó nada. Así lo usa la plataforma MiniGPU. La coherencia CPU/GPU, barreras y espera de finalización requieren integración con la plataforma.

## Scheduler
Se incluyen las dos entregas originales del scheduler: `scheduler_v01` y `scheduler_v01_con_ejemplo`. Su diseño contempla jobs, dependencias, prioridades y hasta ocho slots de warp, pero V2 utiliza inicialmente un solo warp. No se ha integrado ni probado el lanzamiento real de V2 desde este scheduler.

## Toolchain
LCC genera ensamblador `.s`; mini-opt lo optimiza unidad a unidad: convierte los intrínsecos (`__gpu_lane`, `__gpu_tid`... de `t.tests/inc/gpu.h`, leídos como variables) en su instrucción, convierte cada `KERNEL(nombre)` en el punto de entrada de una lane, analiza CFG y liveness, propaga constantes, optimiza tail calls, inserta `SSY` para divergencia SIMT y borra las funciones que no se usan. `build-c` encadena LCC, mini-opt y el ensamblador (ver `platform_minigpu.c` y el Makefile). El renderer GPU (V2) todavía usa `getlane()`: para MiniGPU hay que pasarlo a `__gpu_lane` y a un `KERNEL`. Sus funciones auxiliares sí valen: la GPU del simulador y de la 36 no tiene `JAL`, pero el pase `kernelcalls` de mini-opt expande en el kernel cada llamada a una función de la misma unidad (y `inline` expande las hojas pequeñas en el código de CPU). No necesita ensamblador inline de LCC.
