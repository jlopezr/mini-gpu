# race

Demos que hacen **el mismo trabajo con tres métodos** y los turnan cada 60
fotogramas: la CPU sola, la GPU "ingenua" (un hilo por fila: las 8 lanes de un warp
tocan 8 filas distintas) y la GPU "bien puesta" (un warp por fila, con las lanes en
columnas seguidas: 8 palabras contiguas por instrucción). El estado se pasa de un
método al otro sin tocarlo, así que la animación sigue donde estaba y solo cambia lo
deprisa que va.

Las 32 primeras líneas de la pantalla son una **gráfica de tiempos**: una columna por
fotograma, tan alta como lo que tardó el trabajo (en la placa, con `CYCLES` de la
CPU) y de color verde (CPU), naranja (GPU ingenua) o cian (GPU bien puesta). En el
simulador sale plana: los simuladores cuentan instrucciones, no ciclos.

| Demo | Qué hace | Memoria por celda |
|---|---|---|
| `life` | juego de la vida, 160 x 104 celdas | 9 lecturas, 3 escrituras |
| `blur` | difusión de calor: 3 puntos que se mueven y un desenfoque 3 x 3 | 9 lecturas, 3 escrituras, algo más de cálculo |
| `rotate` | una textura que gira y se acerca (un gather por celda) | 1 lectura, 2 escrituras |
| `cube` | un cubo sólido con una textura por cara, girando sobre dos ejes (ortográfico) | 1 lectura, 2 escrituras, mucho cálculo y divergencia |

Cada uno es un solo `.asm` (`life.asm`) para el simulador y para la placa: `run-board` lo ensambla con
`-D BOARD` (runtime con `RUN` y `CYCLES`). El anfitrión es `race_host.inc`
y el trabajo de cada demo, `life.inc`, `blur.inc` o `rotate.inc`. Los tests
comprueban los tres métodos contra una referencia en Python con la imagen entera, y
el cambio de método en cada fotograma hace que un solo método que calcule algo
distinto rompa la comparación.

Medido en la placa (80 MHz), tiempo por fotograma:

| Demo | CPU | GPU ingenua | GPU bien puesta | bien puesta frente a ingenua |
|---|---:|---:|---:|---:|
| `life` | 172,7 ms | 138,7 ms | 45,1 ms | 3,1 x |
| `blur` | 190,9 ms | 138,7 ms | 45,4 ms | 3,1 x |
| `rotate` | 42,0 ms | 29,5 ms | 12,2 ms | 2,4 x |
| `cube` | 89,6 ms | 27,4 ms | 15,6 ms | 1,8 x |

- **La GPU ingenua apenas gana a la CPU** (1,3 x a 1,4 x): sus lecturas y escrituras
  no se pueden juntar, y la GPU, que va a 25 MHz, se pasa el tiempo en la memoria.
- **Colocar las lanes bien es lo que mueve la aguja**: 3,1 x en los dos demos de
  rejilla, donde las 9 lecturas y las 3 escrituras se coalescen, y 2,4 x en la
  rotación, donde solo se junta la escritura y la lectura es un gather.
- **`cube` es el que más gana la GPU a la CPU** (3,3 x la ingenua, 5,7 x la bien puesta)
  porque tiene mucho cálculo por celda y lo reparte entre las lanes, pero la
  diferencia entre las dos GPU es la menor (1,8 x): el cálculo pesa más y la lectura
  de textura es un gather. Las lanes de un warp pueden tomar caminos distintos en
  cada celda (tres caras y el fondo), y ahí la ingenua pierde más.
- **`life` y `blur` dan lo mismo en la GPU** (138,7 y 45,1 / 45,4 ms): la memoria
  manda y el cálculo de más del desenfoque queda tapado. En la CPU, que sí paga el
  cálculo, `blur` tarda un 10 % más.

| Programa | Versiones |
|---|---|
| [life](life/) | `life.asm` + `life.inc`, `life.c` + `life_body.h`, `life_ptr.c` |
| [blur](blur/) | `blur.asm` + `blur.inc`, `blur.c` + `blur_body.h` |
| [rotate](rotate/) | `rotate.asm` + `rotate.inc`, `rotate.c` + `rotate_body.h` |
| [cube](cube/) | `cube.asm` + `cube.inc`, `cube.c` + `cube_body.h`: el demo entero, anfitrión incluido |
| [plane](plane/) | solo en C: `plane.c` + `plane_body.h` |

`race_host.inc` es el anfitrión en ensamblador (vídeo con doble buffer, método que toca, gráfica de tiempos),
compartido por los `.asm`.
