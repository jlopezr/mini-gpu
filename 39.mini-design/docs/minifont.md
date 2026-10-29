# MiniFont

Lector de fuentes bitmap en C11 y rasterizador RGB565, más los conversores
desde BDF y desde el formato `NEWS.FLB` de NewsMaster 1.5. MiniFont no
depende de MiniGFX ni de la MiniGPU. El formato de fichero `.mf` está en
[minifont-format.md](minifont-format.md).

Código: [`src/minifont.h`](../src/minifont.h), [`src/minifont.c`](../src/minifont.c),
[`tools/bdf2mf.py`](../tools/bdf2mf.py) y [`tools/flb2mf.py`](../tools/flb2mf.py).

## Uso

```sh
make test-minifont         # lector .mf con la fuente de prueba fonts/test.bdf
make run-minifont          # minifont.ppm
make flb-fonts             # las 30 fuentes de NEWS.FLB -> build/fonts/*.mf (make ya lo hace)
make flb-park10            # minifont-park10.ppm con build/fonts/park10.mf
make flb-sheets            # además una hoja de muestra por fuente, build/fonts/*.png (Pillow)
make test-flb              # regresión del conversor FLB
make test-flb-spacing      # font_spacing y compatibilidad con .mf antiguos
make run-spacing           # spacing.ppm: sin (azul) y con (negro) font_spacing
```

`FLB=/ruta/a/NEWS.FLB` cambia el fichero de origen; por defecto es
`resources/NEWS.FLB`.

## Conversor BDF

```sh
python3 tools/bdf2mf.py /ruta/a/6x13.bdf build/fixed13.mf
./build/minifont_demo build/fixed13.mf fixed13.ppm
```

- **Métricas:** `BBX width height xoff yoff` de BDF pasa a ser
  `bearing_x = xoff` y `bearing_y = yoff + height`.
- **Comprobaciones:** el conversor conserva las filas del bitmap, ordena por
  codepoint y rechaza glifos con altura o relleno de fila incorrectos.
- **`fonts/test.bdf`:** es una fuente de prueba mínima hecha a mano. No es la
  X11 Fixed ni una fuente de NewsMaster.
- **Validación pendiente:** el conversor aún no se ha probado con el
  `6x13.bdf` real de X11, que no se pudo descargar. Se puede conseguir aparte,
  por ejemplo de las fuentes de Debian `xfonts-base`, y convertir con el
  comando de arriba.

## Conversor de NewsMaster (`NEWS.FLB`)

```sh
python3 tools/flb2mf.py resources/NEWS.FLB --list
python3 tools/flb2mf.py resources/NEWS.FLB --font 'park 10' --output build/park10.mf --sheet build/park10.png
python3 tools/flb2mf.py resources/NEWS.FLB --all build/fonts [--sheets]
```

- **Catálogo:** `NEWS.FLB` contiene 34 fuentes. Las 30 normales se convierten;
  las cuatro bibliotecas `glyphs` usan un formato especial todavía sin
  interpretar, y el conversor da error con ellas en lugar de producir basura.
- **Nombres:** `--all` las guarda como `<nombre sin espacios>.mf`, por ejemplo
  `park10.mf` o `news12bold.mf`.
- **Caracteres:** los códigos se interpretan como ASCII 33..126 (127 en
  Bremen). Se han revisado a ojo los de Park 10.
- **Hojas de muestra:** `--sheet` y `--sheets` generan PNG y necesitan Pillow
  (`python3 -m pip install pillow`).

## Espaciado por fuente (`font_spacing`)

`flb2mf.py` lee el campo u16 little-endian del offset +80 de cada fuente y lo
guarda como `font_spacing` en la cabecera `.mf`.

- **Valor por fuente:** cada una tiene el suyo. Park 10 = 2, News 10 = 1 y
  Twig = 3; `flb2mf.py --list` los muestra todos.
- **No toca `advance_x`:** es quien coloca los glifos quien suma
  `font_spacing` a cada avance. Lo hacen el layout de MiniDesign,
  `glyph_demo` y `minifont_demo`; GLYPH_RUN y el renderer no, porque reciben
  las posiciones ya calculadas.
- **Compatibilidad:** los `.mf` antiguos, sin el flag, siguen siendo válidos y
  dan `font_spacing = 0`.

## Limitaciones

- **Métricas:** aún no se han comparado todas con el programa original. Que el
  campo +80 sea el espaciado es una interpretación provisional, aunque la
  comparación visual (`run-spacing`) la respalda.
- **Espacio:** las fuentes no tienen glifo de espacio (32). Lo tiene que
  sintetizar la capa de texto.
- **Tabla "atlas":** la tabla preliminar del FLB no se utiliza.
- **Derechos:** las fuentes originales de NewsMaster están sujetas a sus
  derechos y no se deben redistribuir sin autorización.
