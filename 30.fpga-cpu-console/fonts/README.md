# Fuentes iniciales

- `font8x16_pc.hex`: fuente de consola estilo PC, con asignación CP437.
- `font8x16_cpc464.hex`: bitmap derivado de CPC464 Mode 1 de Damian Vila,
  convertido desde 8×8 a 8×16 duplicando cada fila. Los códigos 0..255 usan
  Windows-1252; los códigos indefinidos quedan en blanco.

La fuente CPC procede de
[`CPC464-Mode1.ttf`](https://codeberg.org/Dmian/font-cpc464/src/branch/main/fonts/static/CPC464-Mode1.ttf),
SHA-256 `c97841be709ccbb6e12f2dd33b34d681ee45bf176d738f19c8ddd6736527d370`,
y se distribuye bajo SIL Open Font License 1.1; véase
[`OFL-CPC464.txt`](OFL-CPC464.txt).

Conversión reproducible:

```powershell
python ..\make_font.py --ttf CPC464-Mode1.ttf `
  --output font8x16_cpc464.hex --encoding cp1252 --double-rows
```

`text_console.v` selecciona el fichero mediante el parámetro `FONT_FILE`; el
valor inicial del prototipo 30 es la variante CPC.
