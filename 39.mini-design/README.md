# MiniDesign GFX — GLYPH_RUN + MiniFont

Integración C11 del motor GFX con MiniFont (MFNT v1) y el renderer RGB565 de referencia.

MiniDesign se inspira en NewsMaster 1.5 (de ahí las fuentes `NEWS.FLB` y los
extractores de recursos de `tools/`), pero es un proyecto propio.

Modelo de documento, composición en columnas y páginas y viewport (v0.4):
ver [`docs/README-DESIGN.md`](docs/README-DESIGN.md) (`make run-page`, `make test-design`).

## Uso

```sh
make run
# Con otra fuente .mf (debe contener los glifos ASCII usados por examples/example.c):
./build/example /ruta/a/otra_fuente.mf
```

Genera `demo-320x240.ppm` y `demo-640x480.ppm`. En macOS puedes convertir con `sips -s format png demo-320x240.ppm --out demo-320x240.png`.

## Diseño

`GFX_GLYPH_RUN` referencia por `run_id` un `GfxGlyphRun` en `GfxResources`; cada run contiene ID de fuente y glifos preposicionados (ID de glifo, x, y de la línea base). El backend resuelve `font_id` mediante una tabla de `MfFont`. Por ahora el ID del glifo es el codepoint Unicode, porque MiniFont v1 lo indexa así; otra implementación puede adoptar IDs internos si proporciona la resolución correspondiente.

Las coordenadas están en píxeles de la superficie. GLYPH_RUN es transparente, respeta `SET_CLIP` y conserva orden de composición. Las métricas vienen de la fuente; el backend no parte líneas ni calcula kerning. El comando puede seguir funcionando con un font manager distinto en el futuro; la implementación actual solo admite MFNT monocromo.

`gfx_execute_cpu` original sigue disponible para listas sin recursos. Para glifos se utiliza `gfx_execute_cpu_resources`.

Las fuentes no se guardan sueltas: `make` (o `make flb-fonts`) extrae las 30 fuentes normales de `resources/NEWS.FLB` a `build/fonts/<nombre>.mf` (`park10.mf`, `news12bold.mf`, …). Fuentes originales de NewsMaster: comprobar derechos antes de redistribuirlas.

## NewsMaster graphic extractors (v0.3)

See [`tools/README.md`](tools/README.md). Both scripts are independent of `BLIT`, which remains format-agnostic.

## Notas del prototipo original

Display list portable en C11 + renderer CPU RGB565 de referencia. PPM P6 se
puede ver con la mayoría de visores y convertir a PNG.

Implementados: CLEAR, SET_CLIP, FILL_RECT, DRAW_LINE (1px), BLIT y GLYPH_RUN.
FILL_PATTERN está declarado pero **todavía no implementado**: devuelve error en
lugar de desaparecer silenciosamente.

La superficie es dueña de sus píxeles; la lista es dueña de su array de
comandos. Las coordenadas ya están en píxeles del framebuffer. SET_CLIP
reemplaza el clip actual; CLEAR rellena toda la superficie. La lista de
comandos no incluye el destino.

MiniFont (lector `.mf`, conversores `tools/bdf2mf.py` y `tools/flb2mf.py`,
fuentes en `fonts/`) está integrado en este directorio: ver
[`docs/README-MINIFONT.md`](docs/README-MINIFONT.md) y
[`docs/MINIFONT-FORMAT.md`](docs/MINIFONT-FORMAT.md). Sus objetivos de make son
`test-minifont`, `run-minifont`, `flb-park10` y `test-flb`; salida en `build/`.
