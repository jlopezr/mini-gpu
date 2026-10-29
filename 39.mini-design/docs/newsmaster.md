# Recursos de NewsMaster

MiniDesign se inspira en NewsMaster 1.5 y aprovecha sus recursos originales:
fuentes, ilustraciones e iconos. Los ficheros están en `resources/` y se
convierten en el build. No se guardan versiones convertidas en el repositorio.

| Fichero | Contenido | Se usa con |
|---|---|---|
| `NEWS.FLB` | 34 fuentes bitmap (30 normales y 4 bibliotecas `glyphs`) | `tools/flb2mf.py`; ver [MiniFont](minifont.md) |
| `NEWS.SHP` | 151 ilustraciones de 1 bpp | `tools/shp2png.py`, `examples/page_demo.c` |
| `NEWS.SDX` | Offsets u32 LE de cada ilustración dentro de `NEWS.SHP` | igual que `NEWS.SHP` |
| `NEWS.SDR` | Nombres de las ilustraciones, 16 bytes cada uno | `tools/shp2png.py` |
| `NEWS.ICN` | 59 iconos de 40x20 y 1 bpp | `tools/icn2png.py`, `examples/blit_icons.h` |

## Uso

```sh
make flb-fonts         # fuentes -> build/fonts/*.mf (make ya lo hace)
make shapes            # ilustraciones -> build/shapes (Pillow)
make icons             # iconos -> build/icons y build/icons/corrected (Pillow)
make test-extractors   # comprueba los dos extractores con resources/
make shapes RES=/ruta  # con los originales en otra carpeta
```

A mano:

```sh
python3 tools/shp2png.py resources/NEWS.SHP resources/NEWS.SDX resources/NEWS.SDR --output build/shapes
python3 tools/icn2png.py resources/NEWS.ICN --output build/icons --correct-aspect
python3 tests/test_extractors.py --resources resources
```

`shp2png.py` e `icn2png.py` necesitan Pillow (`python3 -m pip install Pillow`).
`page_demo` lee `NEWS.SHP` directamente desde C, sin Pillow.

## Ilustraciones (`NEWS.SHP`, `NEWS.SDX`, `NEWS.SDR`)

- **Registros:** `NEWS.SDX` contiene un offset u32 little-endian por
  ilustración. Cada registro de `NEWS.SHP` tiene:
  - u8 `row_bytes`, u8 `height` y u16 LE `width`;
  - las filas, con el bit más significativo a la izquierda y **1 = negro**;
  - un byte final.
- **Validación:** el extractor comprueba los offsets, los límites de cada
  registro y las dimensiones del bitmap.
- **Salida:** `shp_000.png` … `shp_150.png`, más `catalog.csv` (índice,
  nombre, ancho, alto y fichero) y `catalog.png`, con todas las ilustraciones
  y su nombre.

## Iconos (`NEWS.ICN`)

- **Píxeles:** **0 = negro**. Tenían proporción 2:1 (más altos que anchos).
- **Salida:** 59 PNG a su tamaño original de 40x20, sin escalar, más
  `catalog.png` con la proporción ya corregida.
- **`--correct-aspect`:** exporta además copias de 40x40 en `corrected/`.
  MiniDesign usa siempre los originales de 40x20 y corrige la proporción al
  dibujarlos, como hace `blit_demo`.

## Limitaciones

- **Derechos:** los originales de NewsMaster están en el repositorio solo para
  estudio. Están sujetos a sus derechos y no se deben redistribuir sin
  autorización.
- **Proporción de píxel:** la de las ilustraciones se toma como cuadrada,
  porque visualmente lo parece; no se ha comprobado con el programa original.
