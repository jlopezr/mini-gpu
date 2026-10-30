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

API Processing: `size`, `color`, `background`, `fill`, `noFill`, `stroke`, `noStroke`, `strokeWeight`, `point`, `line`, `rect`, `circle` (con **radio**, no diámetro como en Processing), `triangle`, `image`, y `width`/`height`. La aplicación define `setup()`/`draw()`; `size()`, `width`/`height` y el bucle los da la plataforma (en el host, `src/platform_host.c`).

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
El framebuffer se suministra externamente mediante `mgl_bind(pixels,width,height,stride)`; `stride` está en píxeles. El renderizador no fija direcciones físicas ni realiza el swap. La arquitectura prevista usa front/back buffer RGB565 y presenta cambiando la dirección en vblank tras completar el render; no copiando píxeles. La coherencia CPU/GPU, barreras y espera de finalización requieren integración con la plataforma.

## Scheduler
Se incluyen las dos entregas originales del scheduler: `scheduler_v01` y `scheduler_v01_con_ejemplo`. Su diseño contempla jobs, dependencias, prioridades y hasta ocho slots de warp, pero V2 utiliza inicialmente un solo warp. No se ha integrado ni probado el lanzamiento real de V2 desde este scheduler.

## Toolchain
LCC genera ensamblador `.s`; mini-opt combina los módulos, reconoce intrínsecos como `getlane()`, analiza CFG y liveness, propaga constantes, optimiza tail calls e inserta `SSY` para divergencia SIMT. El renderer GPU (V2) se ha escrito en C89 y depende de que `getlane()` se transforme mediante mini-opt. No necesita ensamblador inline de LCC. El inlining de funciones pequeñas se ha discutido como mejora futura de mini-opt, no como característica implementada aquí.
