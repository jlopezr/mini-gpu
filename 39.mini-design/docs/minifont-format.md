# Formato MiniFont (`.mf`) v1

Fichero binario con una fuente bitmap monocroma de un solo tamaño.

- **Enteros:** todos son little-endian.
- **Offsets:** absolutos desde el principio del fichero, salvo que se indique
  otra cosa.
- **Lectura:** no depende del empaquetado de structs de C.

Lo leen [`src/minifont.c`](../src/minifont.c) y lo escriben
[`tools/bdf2mf.py`](../tools/bdf2mf.py) y [`tools/flb2mf.py`](../tools/flb2mf.py).

## Cabecera (32 bytes)

| Offset | Tipo | Campo |
|---|---|---|
| +0 | 4 bytes | magic `MFNT` |
| +4 | u16 | versión = 1 |
| +6 | u16 | flags: bit 0 (0x0001) = hay `font_spacing`; el resto, reservados a 0 |
| +8 | u32 | glyph_count |
| +12 | u32 | glyph_table_offset (normalmente 32) |
| +16 | u32 | bitmap_offset |
| +20 | i16 | ascent (píxeles) |
| +22 | i16 | descent (píxeles, no negativo) |
| +24 | i16 | line_gap |
| +26 | u16 | pixel_size |
| +28 | u16 | `font_spacing` si el flag 0x0001 está activo; si no, 0 (en píxeles; provisional, viene del FLB) |
| +30 | u16 | reservado = 0 |

## Tabla de glifos (24 bytes por glifo)

Ordenada por codepoint Unicode.

| Offset | Tipo | Campo |
|---|---|---|
| +0 | u32 | codepoint |
| +4 | u32 | bitmap_offset, relativo a la zona de bitmaps |
| +8 | i16 | bearing_x: píxeles a la derecha del lápiz |
| +10 | i16 | bearing_y: píxeles **hacia arriba** desde la línea base hasta la primera fila |
| +12 | u16 | width |
| +14 | u16 | height |
| +16 | i16 | advance_x |
| +18 | u16 | reservado = 0 |
| +20 | u32 | bitmap_size |

## Bitmaps

- **Organización:** cada glifo ocupa 1 bpp, con las filas de arriba abajo, el
  bit más significativo a la izquierda y cada fila alineada a byte.
- **Tamaño:** un glifo de w×h ocupa `ceil(w/8) * h` bytes. Los bits sobrantes
  al final de cada fila valen 0.
- **Glifos vacíos:** un glifo como el espacio puede tener ancho y alto 0 y un
  avance positivo.

## Dibujo y avance

- **Posición:** la esquina superior izquierda del glifo está en
  `(pen_x + bearing_x, baseline_y - bearing_y)`.
- **Colores:** el bit 1 se pinta con el color del texto y el 0 es
  transparente.
- **Unidades:** todo está en píxeles de raster. El layout de MiniDesign
  trabaja en sus propias unidades físicas, independientes de la resolución.
- **Avance:** `advance_x` no incluye `font_spacing`. Quien hace el layout
  calcula `advance_x + font_spacing + tracking`. Ni `mf_draw_glyph_rgb565` ni
  `GLYPH_RUN` aplican `font_spacing`.

## Compatibilidad

- **Ficheros antiguos:** los v1 con flags = 0 y los bytes reservados a cero
  se leen con `font_spacing = 0`.
- **Ficheros nuevos con lectores antiguos:** un lector anterior al flag
  rechaza los ficheros que lo tienen activo.

## Limitaciones

- **Fuera del formato:** la v1 no tiene kerning, color, alfa, compresión,
  datos de familia ni varios tamaños por fichero. Eso corresponde a un
  catálogo de nivel superior o a versiones posteriores del formato.
- **Datos:** la fuente es de solo lectura y su memoria es del llamador.
- **`font_spacing`:** que el campo +80 del FLB sea el espaciado es una
  interpretación provisional, pendiente de más verificación.
