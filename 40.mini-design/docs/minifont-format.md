# Formato MiniFont (`.mf`) v2

Fichero binario con una fuente bitmap monocroma de un solo tamaño.

- **Enteros:** todos son little-endian.
- **Offsets:** absolutos desde el principio del fichero, salvo que se indique
  otra cosa.
- **Lectura:** no depende del empaquetado de structs de C.

Lo leen [`src/minifont.c`](../src/minifont.c) y lo escriben
[`tools/bdf2mf.py`](../tools/bdf2mf.py) y [`tools/flb2mf.py`](../tools/flb2mf.py).

## Cabecera (40 bytes)

| Offset | Tipo | Campo |
|---|---|---|
| +0 | 4 bytes | magic `MFNT` |
| +4 | u16 | versión = 2 |
| +6 | u16 | flags = 0 (reservado) |
| +8 | u32 | glyph_count |
| +12 | u32 | glyph_table_offset (normalmente 40) |
| +16 | u32 | bitmap_offset |
| +20 | i16 | ascent (píxeles) |
| +22 | i16 | descent (píxeles, no negativo) |
| +24 | i16 | line_gap: interlineado extra entre líneas (píxeles) |
| +26 | u16 | pixel_size |
| +28 | i16 | `font_spacing`: píxeles que se suman a cada avance |
| +30 | u16 | res_x: puntos por pulgada en horizontal (> 0) |
| +32 | u16 | res_y: puntos por pulgada en vertical (> 0) |
| +34 | 6 bytes | reservado = 0 |

- **Resolución:** dice qué tamaño físico tiene un píxel de la fuente. Las
  fuentes de NewsMaster son de 120×72 ppp: un píxel es más estrecho que alto.
  `bdf2mf` la toma de `RESOLUTION_X`/`RESOLUTION_Y` o de la línea `SIZE` del
  BDF (72×72 si no hay ninguna).
- **Interlineado:** la distancia entre líneas base es
  `ascent + descent + line_gap`.

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
  avance positivo. `flb2mf` añade así el espacio (32) de las fuentes de
  NewsMaster, que no lo tienen como glifo.

## Dibujo y avance

- **Posición:** la esquina superior izquierda del glifo está en
  `(pen_x + bearing_x, baseline_y - bearing_y)`.
- **Colores:** el bit 1 se pinta con el color del texto y el 0 es
  transparente.
- **Unidades:** todo está en píxeles de raster. El layout de MiniDesign
  trabaja en sus propias unidades físicas y las convierte con `res_x` y
  `res_y`.
- **Avance:** `advance_x` no incluye `font_spacing`. Quien hace el layout
  calcula `advance_x + font_spacing + tracking`. Ni `mf_draw_glyph_rgb565` ni
  `GLYPH_RUN` aplican `font_spacing`.

## Versiones

- **Solo la v2:** el lector rechaza cualquier otra versión, flags distintos de
  0, una resolución 0 o bytes reservados distintos de 0.
- **v1:** tenía una cabecera de 32 bytes, sin resolución, y `font_spacing`
  dependía de un flag. Ya no se lee: todos los `.mf` se generan en el build
  desde BDF o `NEWS.FLB`, así que no quedan ficheros v1 que conservar.

## Limitaciones

- **Fuera del formato:** no hay kerning, color, alfa, compresión, datos de
  familia ni varios tamaños por fichero. Eso corresponde a un catálogo de
  nivel superior o a versiones posteriores del formato.
- **Datos:** la fuente es de solo lectura y su memoria es del llamador.
