# MiniDesign

Programa de autoedición para el ecosistema MiniCPU/MiniGPU, inspirado en
NewsMaster 1.5. Está escrito en C11, sin dependencias externas. Se divide en
tres capas:

- **[MiniDesign](docs/design.md):** el documento y el motor de composición en
  columnas y páginas, con alineación, titulares, estilos e imágenes rodeadas
  de texto.
- **[MiniGFX](docs/gfx.md):** la display list y el renderer CPU RGB565, que
  más adelante tendrá un backend para la MiniGPU.
- **[MiniFont](docs/minifont.md):** las fuentes bitmap, con conversores desde
  BDF y desde las fuentes originales de NewsMaster.

## Uso

```sh
make            # compila todo y extrae las fuentes de resources/NEWS.FLB
make run        # todas las demos -> *.ppm en esta carpeta
make run-page   # solo la página A4 de MiniDesign
make check      # todas las pruebas
make clean
```

Las imágenes son PPM. En macOS se abren con `open page1-640x480.ppm`, o se
convierten con `sips -s format png page1-640x480.ppm --out page1-640x480.png`.
La lista de demos está en [`examples/README.md`](examples/README.md).

**Requisitos:**

- `cc`, `make` y `python3`.
- Pillow, solo para generar PNG desde Python: `make flb-sheets`, `shapes`,
  `icons` y `test-extractors`. Este último forma parte de `make check`.

## Estructura

```text
src/        librería: MiniGFX, MiniFont y MiniDesign (.c y .h)
examples/   demos (<tema>_demo.c)
tests/      pruebas en C y Python
tools/      conversores de recursos en Python
docs/       documentación (índice en docs/README.md)
fonts/      fuentes BDF de prueba
resources/  originales de NewsMaster (NEWS.FLB, .SHP, .SDX, .SDR, .ICN)
build/      objetos, binarios y fuentes .mf generadas (make clean lo borra)
```

Los originales de NewsMaster están aquí solo para estudio; ver
[docs/newsmaster.md](docs/newsmaster.md).
