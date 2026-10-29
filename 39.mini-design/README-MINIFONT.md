# MiniFont v1

Portable C11 font reader and RGB565 rasterizer; Python 3 BDF converter. No MiniGPU dependency.

```
make test-minifont
make run-minifont
python3 tools/bdf2mf.py /path/to/6x13.bdf build/fixed13.mf
./build/minifont_demo build/fixed13.mf build/fixed13.ppm
```

The included `fonts/test.bdf` is an original **tiny test fixture**, not X11 Fixed and not NewsMaster. This environment could not retrieve the X11 `6x13.bdf`, so the converter has **not yet been validated against that external source**. Download the real X11 BDF separately (e.g. Debian `xfonts-base` source) and convert it with the command above. See `MINIFONT-FORMAT.md`.

BDF uses `BBX width height xoff yoff`, which maps to `bearing_x=xoff`, `bearing_y=yoff+height`. The converter preserves bitmap rows, sorts Unicode codepoints, and rejects malformed glyph heights/row padding.

No original NewsMaster fonts are included.

## Importar las fuentes originales de NewsMaster

El conversor experimental `tools/flb2mf.py` trabaja con el formato concreto
`NEWS.FLB` de NewsMaster 1.5, que está en `resources/` junto al resto de originales.

```sh
python3 tools/flb2mf.py resources/NEWS.FLB --list
python3 tools/flb2mf.py resources/NEWS.FLB --font 'park 10' \
    --output build/park10.mf --sheet build/park10.png
python3 tools/flb2mf.py resources/NEWS.FLB --all build/fonts [--sheets]
./build/minifont_demo build/fonts/park10.mf build/park10.ppm
# Alternativamente, tras `make`:
make flb-fonts             # todas las fuentes -> build/fonts/*.mf
make flb-park10            # demo con build/fonts/park10.mf
make flb-park10 FLB=/ruta/a/NEWS.FLB
make test-flb              # tests de regresión del conversor
make flb-sheets            # además build/fonts/*.png
```

La hoja de muestras PNG requiere Pillow (`python3 -m pip install pillow`).
Se han verificado visualmente los caracteres 33..126 de `park 10`.
La estructura de registros y mapas es consistente para 30 fuentes normales,
pero las cuatro bibliotecas `glyphs` tienen un formato especial todavía sin
interpretar; el conversor da error en ellas en vez de producir basura.

**Limitaciones conocidas**: todavía no se han comprobado todas las métricas
contra el programa original; la correspondencia de códigos se interpreta
como ASCII para 33..126 (127 para Bremen). No hay glifo para el espacio (32),
que debe ser sintetizado por la capa de texto con una anchura adecuada.
La tabla 'atlas' preliminar no se utiliza. Fuentes originales sujetas a
los derechos correspondientes: no redistribuir sin autorización.
