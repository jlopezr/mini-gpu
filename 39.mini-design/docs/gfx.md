# MiniGFX

Display list portable en C11 y renderer CPU de referencia sobre un framebuffer
RGB565. Es la capa que en el futuro también ejecutará la MiniGPU, así que no
sabe nada de documentos, páginas ni párrafos: solo dibuja primitivas ya
colocadas en píxeles.

Código: [`src/gfx.h`](../src/gfx.h), [`src/display_list.c`](../src/display_list.c)
y [`src/renderer_cpu.c`](../src/renderer_cpu.c).

## Uso

```sh
make test          # GLYPH_RUN, escala y recorte (tests/test_gfx.c)
make check-blit    # BLIT: escala, color, transparencia, recorte, origen inválido
make run-glyph     # glyph-320x240.ppm, glyph-640x480.ppm
make run-blit      # blit-320x240.ppm, blit-640x480.ppm
```

```c
GfxDisplayList dl;
gfx_list_init(&dl);
gfx_list_add(&dl, (GfxCommand){.opcode = GFX_CLEAR, .data.clear = {0xFFFF}});
gfx_execute_cpu_resources(&dl, &surface, &resources);
gfx_write_ppm("salida.ppm", &surface);
gfx_list_destroy(&dl);
```

## Modelo

- **Superficie** (`GfxSurface`): framebuffer RGB565, con ancho, alto y
  `stride` en píxeles. Los píxeles son del llamador.
- **Display list** (`GfxDisplayList`): array de comandos que la lista copia y
  libera. No incluye la superficie de destino.
- **Recursos** (`GfxResources`): tablas de fuentes (`MfFont`), de glyph runs y
  de bitmaps, que los comandos referencian por índice. Son del llamador.
- **Coordenadas:** en píxeles de la superficie. Los rectángulos de recorte son
  semiabiertos.
- **Sin recursos:** `gfx_execute_cpu()` sirve para listas que no los usan.
  Para glifos y bitmaps se usa `gfx_execute_cpu_resources()`.
- **Salida:** `gfx_write_ppm()` guarda la superficie en PPM (P6), que abre
  casi cualquier visor.

## Comandos

| Comando | Efecto |
|---|---|
| `GFX_CLEAR` | Rellena toda la superficie |
| `GFX_SET_CLIP` | Sustituye el recorte actual por su intersección con la superficie (no con el recorte anterior) |
| `GFX_FILL_RECT` | Rectángulo relleno |
| `GFX_DRAW_LINE` | Línea de 1 px (Bresenham) |
| `GFX_BLIT` | Bitmap de 1 bpp escalado; ver abajo |
| `GFX_GLYPH_RUN` | Glifos MiniFont ya colocados; ver abajo |
| `GFX_FILL_PATTERN` | Declarado, **sin implementar**: devuelve error en lugar de no dibujar nada |

### GLYPH_RUN

`run_id` apunta a un `GfxGlyphRun` de `GfxResources.runs`. Cada run lleva su
`font_id` (índice en la tabla de `MfFont`) y una lista de glifos, cada uno con
su ID y su posición `(x, y)` sobre la línea base.

- **ID de glifo:** de momento es el codepoint Unicode, porque MiniFont v1
  indexa así los glifos. Otro gestor de fuentes podría usar IDs internos,
  siempre que los resuelva él.
- **Dibujo:** es transparente, respeta `SET_CLIP` y mantiene el orden de la
  lista.
- **`scale`:** con `scale` = k (0 y 1 equivalen a 1x) cada píxel del glifo se
  dibuja como un bloque de k×k y los bearings se multiplican por k. Las
  posiciones siguen en píxeles de la superficie. Máximo:
  `GFX_GLYPH_MAX_SCALE` (64).
- **Lo que no hace:** no parte líneas, no calcula kerning y no aplica el
  `font_spacing` de la fuente. Eso es tarea de quien coloca los glifos, como
  el layout de [MiniDesign](design.md).
- **Formato de fuente:** de momento solo MiniFont monocromo
  ([formato](minifont-format.md)).

### BLIT

Copia `src` de `GfxResources.bitmaps[resource_id]` en `dst`, escalando por
vecino más próximo en el centro de cada píxel de destino.

- **Bitmaps:** 1 bpp, filas de arriba abajo, bit más significativo a la
  izquierda (`GFX_BITMAP_MONO1`).
- **Rectángulos:** `src` tiene que estar entero dentro del bitmap; `dst` puede
  salirse de la pantalla. El recorte se aplica en el destino y no deforma la
  escala.
- **Modos:**
  - `GFX_BLIT_OPAQUE`: el 1 se pinta con `foreground` y el 0 con `background`;
  - `GFX_BLIT_TRANSPARENT_ZERO`: el 1 se pinta con `foreground` y el 0 no se
    dibuja.

`blit_demo` dibuja los iconos de NewsMaster, de 40x20, con un destino cuadrado
para corregir sus píxeles originales de proporción 1:2.

## Limitaciones

- `FILL_PATTERN` no está implementado.
- Los bitmaps solo pueden ser de 1 bpp. RGB565 y ALPHA8 serían lo siguiente.
- No hay backend MiniGPU, solo el renderer CPU.
- **Iconos de la demo:** los de `examples/blit_icons.h` se extrajeron del
  `NEWS.ICN` original y están solo para estudio local. No se deben
  redistribuir.
