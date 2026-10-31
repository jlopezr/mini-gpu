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

API actual: `mgl_bind`, `mgl_set_deferred`, `mgl_cmd_init`, `mgl_cmd_reset`, `mgl_cmd_render_cpu`, `mgl_cmd_status`, `mgl_clear`, `mgl_fill`, `mgl_no_fill`, `mgl_stroke`, `mgl_no_stroke`, `mgl_stroke_weight`, `mgl_point`, `mgl_line`, `mgl_rect`, `mgl_circle`, `mgl_triangle`, `mgl_image`. Para V2: `mgl_cmd_ready` (la copia pendiente del lienzo antes de que otro interprete el buffer), `mgl_gpu_render` (valida el trabajo y lo ejecuta: en MiniGPU lanza `KERNEL(mgl_render)` en un warp; en el host, las 8 lanes una tras otra) y `mgl_gpu_sprites_from_cmd`.

API Processing: `size`, `background`/`fill`/`stroke` con `(r, g, b)` 0–255 (como Arduino TFT), sus variantes RGB565 `background565`/`fill565`/`stroke565`, `color565` (como Adafruit_GFX), `noFill`, `noStroke`, `strokeWeight`, `point`, `line`, `rect`, `circle` (diámetro, como en Processing; `mgl_circle` usa radio), `triangle`, `image`, `width`/`height`, `frameCount`, `mouseX`/`mouseY` y `mousePressed`. La aplicación define `setup()`/`draw()`; `size()`, esas variables y el bucle los da la plataforma: `src/platform_host.c` (un frame a PPM) o `src/platform_sdl.c` (ventana SDL2, `draw()` a 60 fps). Lo común, incluida la ejecución de un frame con V0, V1 o V2, está en `src/platform.c`.

## Algoritmos y opciones
- CLEAR: rellenar framebuffer RGB565.
- POINT: escribir píxel, o el cuadrado del pincel según grosor.
- LINE: Bresenham con enteros, recorrida por tramos de la misma y; con grosor, un span por fila (los mismos píxeles que un cuadrado por punto, una vez cada uno).
- RECT: spans horizontales y clipping.
- CIRCLE: relleno por spans (en cada fila, de -dx a dx, ajustando dx desde la fila anterior con sumas, sin multiplicar); contorno por el algoritmo incremental del punto medio, con el pincel en cada punto.
- TRIANGLE: funciones de borde: en cada fila, el tramo de dentro sale de recortar con las tres aristas con divisiones exactas, sin recorrer la fila, y las aristas se actualizan con sumas al bajar. Pendiente: una regla top-left definida.
- IMAGE: sprite RGB565 opaco con clipping.

No hay antialiasing ni transformaciones en la versión actual. En MiniGPU, V0 y V1 escriben los tramos largos de dos en dos píxeles (`STORE` de 32 bits); V2, de uno en uno (ver [v2-dos-pixeles.md](v2-dos-pixeles.md)). En la placa queda por medir el tráfico SDRAM.

## Memoria y presentación
El framebuffer se suministra externamente mediante `mgl_bind(pixels,width,height,stride)`; `stride` está en píxeles. El renderizador no fija direcciones físicas ni realiza el swap. La arquitectura prevista usa front/back buffer RGB565 y presenta cambiando la dirección en vblank tras completar el render; no copiando píxeles. Para cambiar de buffer sin perder el estado de dibujo está `mgl_set_target(pixels, previous)`: como en Processing el lienzo se conserva entre frames y el trasero tiene lo de hace dos, deja pendiente copiar `previous` (el delantero) y solo la hace si se dibuja algo antes de un `mgl_clear`, que lo tapa todo; `mgl_cmd_render_cpu` empieza por el último CLEAR del buffer. `mgl_finish` hace la copia si el frame no dibujó nada. Así lo usa la plataforma MiniGPU. En MiniGPU, la CPU lanza el kernel de V2 y espera a que acabe antes de pedir el swap (`platform_minigpu.c`): la CPU y la GPU no trabajan a la vez.

## Scheduler
Se incluyen las dos entregas originales del scheduler: `scheduler_v01` y `scheduler_v01_con_ejemplo`. Su diseño contempla jobs, dependencias, prioridades y hasta ocho slots de warp, pero V2 utiliza inicialmente un solo warp. No se ha integrado ni probado el lanzamiento real de V2 desde este scheduler.

## Toolchain
LCC genera ensamblador `.s`; mini-opt lo optimiza unidad a unidad: convierte los intrínsecos (`__gpu_lane`, `__gpu_tid`... de `t.tests/inc/gpu.h`, leídos como variables) en su instrucción, convierte cada `KERNEL(nombre)` en el punto de entrada de una lane, analiza CFG y liveness, propaga constantes, optimiza tail calls, inserta `SSY` para divergencia SIMT y borra las funciones que no se usan. `build-c` encadena LCC, mini-opt y el ensamblador (ver `platform_minigpu.c` y el Makefile). El renderer GPU (V2) es `KERNEL(mgl_render)` en `gpu_renderer.c`: interpreta el buffer como `mgl_cmd_render_cpu` (V1) y dibuja con el mismo `raster.c` de V0, que incluye con `MGL_RASTER_LANES`. Así cada lane dibuja lo mismo que V0 pero solo en sus columnas (`x & 7 == __gpu_lane`): cambian solo los sitios que escriben píxeles (`put`, `row_fill`, la columna de `box`, `sw_image`), y V2 da los mismos píxeles que V0 por construcción. Para que el kernel no crezca (cada llamada se copia), los bordes de líneas, rectángulos y triángulos los dibuja un único bucle del renderer, y el del círculo, un bucle de ocho octantes. Los kernels se compilan para la GPU de la 36, que no tiene `JAL` (el simulador y la 37 sí): el pase `kernelcalls` de mini-opt expande en el kernel cada llamada a una función de la misma unidad (y `inline` expande las hojas pequeñas en el código de CPU). Los parámetros que esas funciones reciben por la pila no cuentan como divergentes: `ssy` sigue lo que se guarda en cada hueco. Por eso el código del kernel no toma la dirección de variables locales (ver [punteros-a-locales.md](punteros-a-locales.md)). mini-opt comprueba al compilar que las regiones SIMT anidadas no pasan de 8 (`ssy`) y que los marcos de las funciones expandidas caben en la pila de cada lane (`lanestack`). No necesita ensamblador inline de LCC.
