# MiniDesign v0.4: modelo de documento y motor de composición

Primera capa de autoedición sobre MiniGFX: un documento en memoria, un motor
de layout que compone el texto en columnas y páginas alrededor de las
ilustraciones, y un viewport que lo convierte en una display list de MiniGFX.
Especificación: [`MiniDesign v0.4.md`](MiniDesign%20v0.4.md).

```sh
make run-page          # page1-320x240.ppm, page1-640x480.ppm, page1-100.ppm, page2-*.ppm
make run-page PAGE_ARGS="300 20 3"   # imagen al 300 %, 20 párrafos, 3 columnas
make test-design       # test-document, test-layout, test-viewport
make check             # todas las pruebas (v0.3 incluidas)
sips -s format png page1-640x480.ppm --out page1-640x480.png   # macOS
```

`run-page` necesita las fuentes extraídas de `resources/NEWS.FLB` (lo hace el
propio make) y lee la ilustración 130 ("Newspaper") de `resources/NEWS.SHP` y
`NEWS.SDX` directamente desde C. No hace falta Pillow.

## Arquitectura

```text
src/document.h/.c         Documento: unidades, papel, estilos, historias, gráficos
src/layout.h/.c           Layout: columnas, saltos de línea, posición de glifos, exclusión
src/viewport.h/.c         Viewport: zoom, desplazamiento, unidades -> píxeles
src/document_render.h/.c  Layout + viewport -> display list (CLEAR, SET_CLIP, FILL_RECT,
                          DRAW_LINE, BLIT, GLYPH_RUN)
examples/page_demo.c      Documento A4 de ejemplo generado por programa
        │
        ▼
MiniGFX (src/gfx.h, src/display_list.c, src/renderer_cpu.c), sin cambios
```

- **Documento** (`MdDocument`): contenido persistente. Guarda los ajustes de
  página (`MdPageSettings`: papel, márgenes, número de columnas y separación),
  los estilos de carácter (`MdCharacterStyle`: fuente, `letter_spacing`, color),
  los estilos de párrafo (`MdParagraphStyle`: interlineado, sangría de primera
  línea, espacio antes y después), las historias (`MdTextStory`, con sus
  `MdParagraph`) y los objetos gráficos (`MdGraphicObject`). No contiene líneas
  ni coordenadas de glifos.
- **Layout** (`MdLayout`): datos derivados, que se recalculan cuando cambia el
  documento. Contiene las páginas (`MdPage`), las regiones de flujo
  (`MdTextFrame`, una por columna y página), las líneas (`MdLine`) y los glifos
  posicionados (`MdGlyph`). Las páginas las crea el layout a medida que el texto
  las necesita; el documento solo ancla los gráficos a un número de página.
- **Viewport** (`MdViewport`): `px = origen + (unidad - scroll) * num / den`,
  con redondeo hacia abajo. Cada borde de un rectángulo se transforma por
  separado, así que los rectángulos contiguos siguen siendo contiguos.
- **Render**: MiniGFX no conoce páginas, párrafos ni columnas. `GLYPH_RUN` y
  `BLIT` se usan sin cambiar su semántica.

## Unidades y métricas

- **Unidad de documento:** 1/720 de pulgada. 1 pt son 10 unidades y A4 son
  5953 × 8419 unidades. `md_units_from_mm10()` redondea al entero más cercano.
- **Fuentes:** las de NewsMaster son de pantalla. Se toma 1 px de fuente como
  1/72" (`MD_UNITS_PER_FONT_PX` = 10), así que Park 10 mide 10 pt.
- **Avance de cada glifo:**
  `(advance_x + font_spacing) × 10 + letter_spacing`. `font_spacing` es el de
  cada fuente y `letter_spacing` el del estilo; no hay una separación fija
  común a todas las fuentes.
- **Espacio:** las fuentes no tienen glifo de espacio. Se usa la mitad del
  avance de `n` (mínimo 2 px), más el espaciado.
- **Interlineado:**
  - automático: `(ascent + descent + line_gap) × 10 × leading_percent / 100`;
  - fijo: `leading`, que tiene prioridad sobre el automático.

## Composición

Para cada párrafo y cada línea:

1. Comprueba si la línea cabe en la columna. Si no, pasa a la columna
   siguiente y, después de la última, a una página nueva (máximo 256 páginas).
2. Calcula la franja horizontal libre a la altura `[y, y + interlineado)`:
   - a la columna se le restan los rectángulos de exclusión de los gráficos
     de esa página;
   - de los trozos que quedan se usa el más ancho, y en caso de empate el de
     la izquierda;
   - los trozos de menos de 1/2" se descartan.
3. Coloca tantas palabras enteras como quepan (alineación izquierda).
4. Si no cabe ninguna palabra:
   - si la franja está recortada por un gráfico, baja una línea, manteniendo
     la retícula del interlineado;
   - si la palabra es más ancha que toda la columna, la parte por caracteres.
     Si un solo glifo no cabe, la línea se marca como `overflow`.

El espacio antes del párrafo no se aplica al principio de una columna.
Cualquier cambio en el texto, en los estilos, en el tamaño o la posición de
una imagen o en el número de columnas recompone todo de nuevo. No hay que
tocar ninguna coordenada.

## Viewport y render

- **Página completa** (`md_viewport_fit_page`): la página se centra y conserva
  sus proporciones. Los píxeles se consideran cuadrados (320×240 y 640×480).
- **100 %** (`md_viewport_actual_size`): 1 px de fuente = 1 px de pantalla.
  Cada línea se dibuja como un `GLYPH_RUN`, con las posiciones del layout
  transformadas.
- **Cualquier otro zoom:** `GLYPH_RUN` no escala bitmaps, así que cada palabra
  se dibuja como una barra gris (`FILL_RECT`). Es el mismo "greeking" que el
  Full Page View de NewsMaster.
- **Ilustraciones:** se dibujan con `BLIT` (vecino más próximo) a cualquier
  zoom.
- **Guías** (`show_guides`): dibujan con `DRAW_LINE` el contorno de las
  columnas (azul) y de las exclusiones (rojo). La demo las activa en
  `page1-100.ppm`.

El layout se calcula una sola vez y no depende del viewport. Los tests
comprueban que renderizar a 320×240, a 640×480 o al 100 % no lo modifica.

## Limitaciones

- Solo alineación izquierda. No hay justificación, kerning, silabeo ni estilos
  por rangos de caracteres.
- Al 100 % el texto es real; en otros zooms solo hay greeking. Para tener
  texto a otros tamaños harían falta varias resoluciones de cada fuente o un
  GLYPH_RUN que escale.
- La exclusión es rectangular y el texto solo usa un lado del gráfico (el
  trozo libre más ancho). Si una palabra no cabe en ese hueco, el texto baja
  hasta debajo de la imagen y el hueco queda vacío.
- **Historias:** cada llamada al layout compone una historia
  (`md_layout_story`). No hay todavía marcos encadenados ni varias historias
  en la misma página.
- **Caracteres:** solo ASCII. Un carácter sin glifo se sustituye por `?` o se
  omite.
- No hay edición, persistencia, páginas maestras ni renderer MiniGPU.

## Archivos

| Nuevo | |
|---|---|
| `src/document.h`, `src/document.c` | Modelo de documento |
| `src/layout.h`, `src/layout.c` | Motor de composición |
| `src/viewport.h`, `src/viewport.c` | Transformación documento → pantalla |
| `src/document_render.h`, `src/document_render.c` | Generación de la display list |
| `examples/page_demo.c` | Demostración A4 |
| `tests/test_document.c`, `tests/test_layout.c`, `tests/test_viewport.c` | Pruebas |
| `tests/test_fonts.h` | Fuente MiniFont sintética para las pruebas |
| `docs/README-DESIGN.md` | Este documento |

Modificados: `Makefile` (`run-page`, `test-design` y `check`) y `README.md`
(enlace a este documento).
