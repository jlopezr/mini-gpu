# MiniDesign

Capa de autoedición sobre [MiniGFX](gfx.md): un documento en memoria, un
motor de layout que compone el texto en columnas y páginas alrededor de las
ilustraciones, y un viewport que lo convierte en una display list de MiniGFX.
Versión actual: v0.5. Especificación de partida: [spec-v0.4.md](spec-v0.4.md).

**Novedades de la v0.5:**

- alineación derecha, centrada y justificada;
- párrafos a todo el ancho de la página, para titulares;
- estilos por rangos de caracteres, como la cursiva dentro de un párrafo;
- texto a los dos lados de una imagen;
- texto legible a cualquier zoom entero (200 %, 300 %…), gracias a la escala
  de `GLYPH_RUN`.

## Uso

```sh
make run-page          # page1-320x240, page1-640x480, page1-100, page1-200, page2-*, page2-100
make run-page PAGE_ARGS="300 20 3"   # imagen al 300 %, 20 párrafos, 3 columnas
make run-page PAGE_ARGS="175 14 1"   # una columna: texto a los dos lados del reloj (page2-100)
make test-design       # test-document, test-layout, test-viewport
make check             # todas las pruebas
sips -s format png page1-640x480.ppm --out page1-640x480.png   # macOS
```

`run-page` usa las fuentes que make extrae de `resources/NEWS.FLB`
([MiniFont](minifont.md)). Lee las ilustraciones 130 ("Newspaper") y 127
("Antique Clock") de `resources/NEWS.SHP` y `NEWS.SDX` directamente desde C
([recursos de NewsMaster](newsmaster.md)). No hace falta Pillow.

## Arquitectura

```text
src/document.h/.c         Documento: unidades, papel, estilos, historias, gráficos
src/layout.h/.c           Layout: bandas de columnas, saltos de línea, alineación, exclusión
src/viewport.h/.c         Viewport: zoom, desplazamiento, unidades -> píxeles
src/document_render.h/.c  Layout + viewport -> display list (CLEAR, SET_CLIP, FILL_RECT,
                          DRAW_LINE, BLIT, GLYPH_RUN)
examples/page_demo.c      Documento A4 de ejemplo generado por programa
        │
        ▼
MiniGFX (src/gfx.h, src/display_list.c, src/renderer_cpu.c)
```

- **Documento** (`MdDocument`): contenido persistente. Guarda:
  - los ajustes de página (`MdPageSettings`: papel, márgenes, número de
    columnas y separación);
  - los estilos de carácter (`MdCharacterStyle`: fuente, `letter_spacing` y
    color);
  - los estilos de párrafo (`MdParagraphStyle`: interlineado, sangría de
    primera línea, espacio antes y después, `align` y `span`);
  - las historias (`MdTextStory`), con sus párrafos (`MdParagraph`). Cada
    párrafo puede tener rangos de estilo (`MdStyleRun`);
  - los objetos gráficos (`MdGraphicObject`, con su modo de rodeo `wrap`).

  No contiene líneas ni coordenadas de glifos.
- **Layout** (`MdLayout`): datos derivados, que se recalculan cuando cambia el
  documento. Contiene:
  - las páginas (`MdPage`);
  - las regiones de flujo (`MdTextFrame`). Las columnas se agrupan en bandas, y
    un párrafo con `MD_SPAN_ALL` tiene un único marco que ocupa todas las
    columnas;
  - las líneas (`MdLine`) y los glifos posicionados (`MdGlyph`, cada uno con
    su estilo de carácter).

  Las páginas las crea el layout a medida que el texto las necesita; el
  documento solo ancla los gráficos a un número de página.
- **Viewport** (`MdViewport`): `px = origen + (unidad - scroll) * num / den`,
  con redondeo hacia abajo. Cada borde de un rectángulo se transforma por
  separado, así que los rectángulos contiguos siguen siendo contiguos.
- **Render:** MiniGFX no conoce páginas, párrafos ni columnas. El único cambio
  en MiniGFX es el campo `scale` de `GLYPH_RUN`; 0 y 1 equivalen a 1x, así que
  el código anterior no cambia de comportamiento.

## Unidades y métricas

- **Unidad de documento:** 1/720 de pulgada. 1 pt son 10 unidades y A4 son
  5953 × 8419 unidades. `md_units_from_mm10()` redondea al entero más cercano.
- **Fuentes:** las de NewsMaster son de pantalla. Se toma 1 px de fuente como
  1/72" (`MD_UNITS_PER_FONT_PX` = 10), así que Park 10 mide 10 pt.
- **Avance de cada glifo:**
  `(advance_x + font_spacing) × 10 + letter_spacing`, con la fuente y el
  estilo del propio carácter.
- **Espacio:** las fuentes no tienen glifo de espacio. Se usa la mitad del
  avance de `n` (mínimo 2 px), más el espaciado.
- **Interlineado:** automático, `(ascent + descent + line_gap) × 10 ×
  leading_percent / 100`, o fijo con `leading`.
  - Si el párrafo usa varios estilos, la altura de línea y el ascent son los
    mayores de entre todos ellos. Se calculan una vez por párrafo, porque la
    altura de la línea se necesita antes de saber qué palabras caben en ella.

## Composición

Para cada párrafo:

1. **Banda de columnas.**
   - Un párrafo `MD_SPAN_ALL` abre un marco a todo el ancho en la posición
     actual de la primera columna. Si el texto ya ha pasado a otra columna, lo
     abre en una página nueva.
   - El primer párrafo normal que viene después abre una banda de columnas
     nueva, debajo del titular.
   - La banda anterior se recorta a esa altura, o se elimina si estaba vacía.
2. **Cada línea:**
   - Si no cabe en el marco, pasa a la columna siguiente y, después de la
     última, a una página nueva (máximo 256).
   - La franja `[y, y + interlineado)` del marco se divide en trozos libres,
     quitando los rectángulos de exclusión de los gráficos de esa página. Los
     trozos de menos de 1/2" se descartan.
   - `MD_WRAP_LARGEST` (el valor 1, el de la v0.4) deja solo el trozo más
     ancho. `MD_WRAP_BOTH` usa todos los trozos de izquierda a derecha: el
     texto continúa al otro lado de la imagen a la misma altura.
3. **En cada trozo** coloca tantas palabras enteras como quepan y las alinea:
   - izquierda;
   - derecha;
   - centrada;
   - justificada: el espacio libre se reparte entre los huecos entre palabras,
     y el resto va a los primeros. La última línea del párrafo, las líneas de
     una sola palabra y las de desbordamiento se alinean a la izquierda.
4. **Si la palabra no cabe en ningún trozo:**
   - si un gráfico recorta la franja, baja una línea, manteniendo la retícula
     del interlineado;
   - si la palabra es más ancha que toda la columna, la parte por caracteres,
     y la línea se marca como `overflow` si ni siquiera cabe un glifo.

Cualquier cambio en el texto, los estilos, las imágenes o el número de
columnas recompone todo de nuevo, sin tocar ninguna coordenada.

## Viewport y render

- **Página completa** (`md_viewport_fit_page`): la página se centra y conserva
  sus proporciones. Los píxeles se consideran cuadrados (320×240 y 640×480).
- **Zoom entero** (`md_viewport_actual_size` para el 100 %,
  `md_viewport_text_zoom` para 200 %, 300 %…): `md_viewport_text_scale()`
  devuelve k.
  - Cada tramo de línea con el mismo estilo de carácter se dibuja como un
    `GLYPH_RUN` con escala k: cada píxel del glifo es un bloque de k×k y las
    posiciones vienen del layout.
- **Cualquier otro zoom:** cada palabra se dibuja como una barra gris
  (`FILL_RECT`). Es el mismo "greeking" que el Full Page View de NewsMaster.
- **Ilustraciones:** se dibujan con `BLIT` (vecino más próximo) a cualquier
  zoom.
- **Guías** (`show_guides`): dibujan con `DRAW_LINE` el contorno de los marcos
  (azul) y de las exclusiones (rojo). La demo las activa en `page1-100` y
  `page2-100`.

El layout se calcula una sola vez y no depende del viewport. Los tests
comprueban que renderizar a 320×240, a 640×480, al 100 % o al 200 % no lo
modifica.

## Limitaciones

- **Tipografía:** no hay kerning ni silabeo. Sin silabeo, la justificación en
  columnas estrechas deja huecos grandes entre palabras.
- **Texto junto a las imágenes:** en dos columnas A4, con las fuentes de
  NewsMaster, los huecos junto a una imagen se quedan en unos 95 px. Una
  palabra que no cabe en ningún hueco baja de línea y deja la franja vacía. El
  rodeo por los dos lados luce con marcos anchos (`PAGE_ARGS="175 14 1"`).
- **Titulares:** un titular a mitad de página solo se coloca debajo de la
  primera columna. Si el texto ya llegó a la segunda, pasa a la página
  siguiente, porque no hay equilibrado de columnas. Y ocupa todas las
  columnas, no un número intermedio.
- **Zoom:** el texto real solo se ve a zoom entero. A 50 % o 150 % hay
  greeking. Para que fuera legible haría falta reducir los glifos, o tener
  varias resoluciones de cada fuente.
- **Exclusiones:** solo rectangulares.
- **Historias:** cada llamada al layout compone una historia
  (`md_layout_story`). No hay marcos encadenados ni varias historias en la
  misma página.
- **Caracteres:** solo ASCII. Un carácter sin glifo se sustituye por `?` o se
  omite.
- No hay edición, persistencia, páginas maestras ni renderer MiniGPU.

## Archivos

| Módulo | |
|---|---|
| `src/document.h`, `src/document.c` | Modelo de documento |
| `src/layout.h`, `src/layout.c` | Motor de composición |
| `src/viewport.h`, `src/viewport.c` | Transformación documento → pantalla |
| `src/document_render.h`, `src/document_render.c` | Generación de la display list |
| `examples/page_demo.c` | Demostración A4 |
| `tests/test_document.c`, `tests/test_layout.c`, `tests/test_viewport.c` | Pruebas |
| `tests/test_fonts.h` | Fuente MiniFont sintética para las pruebas |
