# Fuentes iniciales

Las dos fuentes usan la **asignación CP437** completa (la que espera
`z.tui/console_mini.c` y decodifica `tools/sim_devices.py`): ASCII en
0x20..0x7E, los glifos gráficos de PC en 0x01..0x1F y 0x7F, y en 0xB0..0xDF
las sombras, los bloques y las cajas simples, dobles y mixtas. Los códigos 0x00,
0x20 y 0xFF (NUL, espacio y NBSP) quedan en blanco.

- `font8x16_pc.hex`: todo desde [Unscii-16](https://github.com/viznut/unscii)
  (`unscii-16.hex`, de Viznut). Dominio público / CC0; el repositorio de Unscii
  excluye de esa dedicación solo los ficheros derivados de GNU Unifont
  (`unifont.hex`, `unscii-16-full.*`), que aquí no se usan.
  SHA-256 de `unscii-16.hex`:
  `2642c8b748fa81f24d76772d70c55faa720d98fadfec8133daf89136c5c8bfb1`.
- `font8x16_cpc464.hex`: el texto sale de CPC464 Mode 1 de Damian Vila,
  convertido de 8×8 a 8×16 duplicando cada fila. El bloque 0xB0..0xDF sale de
  Unscii para que todas las uniones de caja encajen entre sí (la TTF solo trae
  las cajas simples, y con trazos más gruesos). Los 19 códigos de texto que la
  TTF no tiene (símbolos de 0x01..0x1F y letras griegas y símbolos matemáticos
  de 0xE0..0xFF) también salen de Unscii.

Cuatro glifos no existen en ninguna de las dos fuentes y están dibujados a mano
en `make_font.py`: `☼` (0x0F), `⌂` (0x7F), `⌐` (0xA9) y `∙` (0xF9).

La fuente CPC procede de
[`CPC464-Mode1.ttf`](https://codeberg.org/Dmian/font-cpc464/src/branch/main/fonts/static/CPC464-Mode1.ttf),
SHA-256 `c97841be709ccbb6e12f2dd33b34d681ee45bf176d738f19c8ddd6736527d370`,
y se distribuye bajo SIL Open Font License 1.1; véase
[`OFL-CPC464.txt`](OFL-CPC464.txt).

Conversión reproducible (desde esta carpeta; hace falta Pillow):

```powershell
python ..\make_font.py --profile pc --unscii unscii-16.hex
python ..\make_font.py --profile cpc464 --unscii unscii-16.hex --ttf CPC464-Mode1.ttf
```

`unscii-16.hex` se descarga de
`https://raw.githubusercontent.com/viznut/unscii/master/fontfiles/unscii-16.hex`.
El script imprime de dónde sale cada glifo (`ttf`, `unscii`, `hand`, `blank`).

`text_console.v` selecciona el fichero mediante el parámetro `FONT_FILE`; el
valor inicial del prototipo 30 es la variante CPC. Cambiar el contenido de un
`.hex` invalida el bitstream: hay que reconstruir.
