# Demos

Cada demo es `examples/<tema>_demo.c`. Se compila en `build/<tema>_demo`, se
lanza con `make run-<tema>` desde la carpeta del proyecto y deja sus imágenes
`<tema>-….ppm` en esa carpeta. `make run` las lanza todas y `make clean` borra
lo que generan.

| Demo | `make` | Salida | Qué muestra |
|---|---|---|---|
| [`glyph_demo.c`](glyph_demo.c) | `run-glyph` | `glyph-320x240.ppm`, `glyph-640x480.ppm` | GLYPH_RUN: tres líneas de texto en Park 10 colocadas a mano, con recorte |
| [`blit_demo.c`](blit_demo.c) | `run-blit` | `blit-320x240.ppm`, `blit-640x480.ppm` | BLIT: iconos de NewsMaster escalados, con transparencia, color y recorte |
| [`spacing_demo.c`](spacing_demo.c) | `run-spacing` | `spacing.ppm` | 12 fuentes de NewsMaster sin (azul) y con (negro) `font_spacing` |
| [`minifont_demo.c`](minifont_demo.c) | `run-minifont`, `flb-park10` | `minifont.ppm`, `minifont-park10.ppm` | El lector MiniFont solo, sin MiniGFX |
| [`page_demo.c`](page_demo.c) | `run-page` | `page1-*.ppm`, `page2-*.ppm` | MiniDesign: documento A4 compuesto por el layout ([docs/design.md](../docs/design.md)) |

[`blit_icons.h`](blit_icons.h) contiene los cinco iconos de `NEWS.ICN` que usa
`blit_demo`.

## Argumentos

Todos tienen valores por defecto, así que basta con `make run-<tema>`:

```sh
./build/glyph_demo [fuente.mf]                  # build/fonts/park10.mf
./build/spacing_demo [dir_fuentes] [salida.ppm]  # build/fonts, spacing.ppm
./build/minifont_demo fuente.mf salida.ppm
./build/page_demo [dir_fuentes] [dir_recursos] [imagen_%] [párrafos] [columnas]
make run-page PAGE_ARGS="300 20 3"              # lo mismo desde make
```

**Qué necesita cada una:**
- `glyph_demo`, `spacing_demo` y `page_demo` usan las fuentes que make extrae
  de `resources/NEWS.FLB` en `build/fonts/`.
- `page_demo` lee además las ilustraciones de `resources/NEWS.SHP` y
  `NEWS.SDX`.
- Ninguna necesita Pillow.

## Ver las imágenes

Son PPM (P6). En macOS:

```sh
open page1-640x480.ppm
sips -s format png page1-640x480.ppm --out page1-640x480.png
```
