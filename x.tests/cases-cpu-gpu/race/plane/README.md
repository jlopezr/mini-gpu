# plane

`plane.c` es el mismo anfitrión que el cubo con otro dibujo: un plano que gira sobre el eje vertical,
los Autobots delante, los Decepticons detrás, mezclados con alfa sobre un degradado vertical. El cuerpo
(`plane_body.h`) se incluye tres veces, como los otros. Como el plano solo gira sobre un eje, `v` no
depende de la columna: cada fila lee una sola fila de textura y solo `u` avanza.

```text
python x.tests/cases-cpu-gpu/race/plane/plane_tex.py -o _build/c/plane_tex.bin
build-c x.tests/cases-cpu-gpu/race/plane/plane.c --board --data plane_tex=_build/c/plane_tex.bin
                                                                  # -> _build/c/plane_board.bin
```

Las texturas salen de `logos.png` con `plane_tex.py` (dos de 128 × 128 palabras, 128 KiB). Es un
paso aparte porque `build-c` no ejecuta generadores: `--data` solo las deja tras el código con la etiqueta
`plane_tex`, que el C declara `extern`.
Cada palabra es un texel con su alfa: el RGB565 «abierto» (rojo y azul abajo, verde arriba, con huecos) y el
alfa de 0 a 32 en el hueco entre azul y rojo. Así `texel & 0x07E0F81F` ya está abierto y la mezcla con el
fondo de la fila es **una sola multiplicación** para los tres canales. El alfa sale del fondo negro de la
imagen (relleno desde el borde, suavizado al reducir). `python x.tests/cases-cpu-gpu/race/plane/plane_tex.py --preview v.png`
deja las dos texturas sobre el degradado. La imagen entra completa en el programa: el `.bin` pasa de 170 KiB.

`CPlaneRaceTest` comprueba en el simulador que los tres métodos dibujan, fotograma a fotograma, lo que el
modelo en Python.
