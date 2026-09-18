# Biblioteca de `.include`

Trozos de ensamblador compartidos entre programas. Existe porque `drawline` y
`putpixel` estaban copiados **literalmente en tres sitios** —
`bresenham_lines.asm`, `bresenham_circles.asm` y `cube.asm` — y una corrección
en Bresenham había que hacerla tres veces. El riesgo real no era el trabajo,
era que los casos de vídeo que comparan contra el abanico pasaran mientras el
cubo se quedaba con la versión vieja.

| Fichero | Qué define | Depende de |
|---|---|---|
| [`putpixel.inc`](putpixel.inc) | `putpixel` | `R1` = buffer trasero, `R24` = 640 |
| [`drawline.inc`](drawline.inc) | `drawline`, Bresenham de ocho octantes | `putpixel.inc` |
| [`sin256.inc`](sin256.inc) | `sin_table`, 256 entradas Q16.16 en `.rodata` | — |

## Cómo se buscan

Primero la carpeta del fichero que incluye, y **después** las carpetas de `-I`.
Ese orden importa: un trozo local con el mismo nombre tiene que ganar al
compartido, o cambiar algo aquí rompería programas ajenos en silencio.

Los lanzadores (`run-board`, `capture-frame-sim`, `run_tests.py`) ya pasan esta
carpeta, así que desde un `.asm` del repo basta con el nombre:

```asm
    .include "drawline.inc"
    .include "putpixel.inc"
```

A mano, o desde fuera de los lanzadores:

```bash
python 1.isa/miniisa_asm.py mi_programa.asm -I x.tests/inc
```

## Dos cosas que hay que tener en la cabeza

**No hay espacios de nombres.** Las etiquetas de lo incluido son globales para
todo el programa: `drawline`, `dx_ready`, `line_step`, `putpixel`, `sin_table`…
Cada `.inc` las lista en su cabecera. Un choque no pasa desapercibido — el
ensamblador dice los dos sitios:

```
cube.asm:212: label duplicado: putpixel (ya definido en putpixel.inc:23)
```

**Tampoco hay guardas de inclusión.** Por eso `drawline.inc` **no** incluye
`putpixel.inc` por su cuenta, aunque lo necesite: si lo hiciera, un programa que
incluyera los dos —lo natural— chocaría consigo mismo. Se incluyen los dos a
mano, y así `bresenham_circles.asm`, que usa `putpixel` pero no `drawline`, no
se lleva código muerto.

## Al cambiar algo de aquí

Estos ficheros están en el camino de los casos de `x.tests`, así que un cambio
se comprueba con la suite entera, no sólo con el programa que se estaba
tocando:

```bash
python x.tests/run_tests.py --backend cpusim cases/video cases/programs
test-board --prototype 21 -y x.tests/cases/video
```

Cuando el cambio pretende **no** alterar el código generado —como el que creó
esta carpeta— lo que hay que verificar es que el binario sale idéntico, que es
más fuerte que pasar los tests:

```bash
python 1.isa/miniisa_asm.py <programa>.asm -o nuevo.bin -I x.tests/inc
# y comparar nuevo.bin contra el de antes
```
