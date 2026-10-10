# Biblioteca de `.include`

Trozos de ensamblador (y cabeceras de C) compartidos entre programas. Existe porque `drawline` y
`putpixel` estaban copiados **literalmente en tres sitios** —
`bresenham_lines.asm`, `bresenham_circles.asm` y `cube.asm` — y una corrección
en Bresenham había que hacerla tres veces. El riesgo real no era el trabajo,
era que los casos de vídeo que comparan contra el abanico pasaran mientras el
cubo se quedaba con la versión vieja.

| Fichero | Qué define | Depende de |
|---|---|---|
| [`putpixel.inc`](putpixel.inc) | `putpixel` | `R1` = buffer trasero, `R24` = 640 |
| [`drawline.inc`](drawline.inc) | `drawline`, Bresenham de ocho octantes | `putpixel.inc`, que incluye él solo |
| [`sin256.inc`](sin256.inc) | `sin_table`, 256 entradas Q16.16 en `.rodata` | — |
| [`gpu_runtime.inc`](gpu_runtime.inc) | `gpu_run`: la CPU lanza un job en la GPU y lo espera | `mmio.inc`; con `BOARD`, la placa 36 |
| [`bench.inc`](bench.inc) | `bench_init`, `bench_now`: los ciclos de CPU (cero en los simuladores) | `mmio.inc`; con `BOARD`, la placa |
| [`gpu.h`](gpu.h), [`mmio.h`](mmio.h) | Cabeceras de C: `KERNEL`, `GPU_RUN`, `NOALIAS`; el mapa MMIO | las usa `build-c`; `gpu.c` está en `../runtime/gpu/` |

`gpu_runtime.inc` y `bench.inc` tienen una rama para la placa 36 y otra para los simuladores. Se elige con el
símbolo `BOARD`, antes del `.include`: `-D BOARD` en la línea de órdenes del ensamblador (así lo hacen `run-board`, siempre, y `build-c --board`) o
`.define BOARD` en el propio `.asm`. Un `.asm` que valga para el simulador y para la placa no necesita variante
`_board`: usa `.ifdef BOARD` para lo que sea solo de la placa y no repite el `.define`.

## Cómo se buscan

Primero la carpeta del fichero que incluye, y **después** las carpetas de `-I`.
Ese orden importa: un trozo local con el mismo nombre tiene que ganar al
compartido, o cambiar algo aquí rompería programas ajenos en silencio.

Los lanzadores (`run-board`, `capture-frame-sim`, `run_tests.py`) ya pasan esta
carpeta, así que desde un `.asm` del repo basta con el nombre:

```asm
    .include "drawline.inc"     ; arrastra putpixel.inc por su cuenta
```

A mano, o desde fuera de los lanzadores:

```bash
python 1.isa/mini_asm.py mi_programa.asm -I x.tests/inc
```

## Dos cosas que hay que tener en la cabeza

**No hay espacios de nombres.** Las etiquetas de lo incluido son globales para
todo el programa: `drawline`, `dx_ready`, `line_step`, `putpixel`, `sin_table`…
Cada `.inc` las lista en su cabecera. Un choque no pasa desapercibido — el
ensamblador dice los dos sitios:

```text
cube.asm:212: label duplicado: putpixel (ya definido en putpixel.inc:23)
```

**Los tres llevan `.once`**, así que un `.inc` puede arrastrar sus dependencias
sin chocar con el programa que también las incluya. `.once` lo pone el fichero
incluido, no quien lo incluye: ser idempotente es una propiedad suya, y así no
hay que acordarse en cada sitio.

Siguen siendo dos ficheros y no uno porque `bresenham_circles.asm` usa
`putpixel` pero no `drawline`, y así no se lleva código muerto.

## Al cambiar algo de aquí

Estos ficheros están en el camino de los casos de `x.tests`, así que un cambio
se comprueba con la suite entera, no sólo con el programa que se estaba
tocando:

```bash
python x.tests/run_tests.py --backend cpusim cases-cpu/video cases-cpu/programs
test-board --prototype 21 -y x.tests/cases-cpu/video
```

Cuando el cambio pretende **no** alterar el código generado —como el que creó
esta carpeta— lo que hay que verificar es que el binario sale idéntico, que es
más fuerte que pasar los tests:

```bash
python 1.isa/mini_asm.py <programa>.asm -o nuevo.bin -I x.tests/inc
# y comparar nuevo.bin contra el de antes
```
