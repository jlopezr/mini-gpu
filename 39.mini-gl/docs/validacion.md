# Validación realizada

Compilación GCC C89: PASS

`make test`:

- `test_cpu`: PASS: V0 direct == V1 deferred CPU, bytes=312; y PASS: doble buffer (mgl_set_target) == un lienzo,
  directo y diferido
- `test_gpu`: PASS: V0 direct == V1 deferred CPU == V2 GPU host 8 lanes, 528 command bytes
- `test_fuzz_v2`: PASS: 3000 escenas, V0 == V2 (escenas al azar con bordes gruesos, círculos, triángulos, líneas,
  puntos, imágenes y recortes por los cuatro lados, en un framebuffer de 101x67: un `pitch` impar)

`make run` (ejemplos, `-v all`): `shapes` y `pattern` dan PASS: V0 == V1 == V2

`make check-minigpu` (compilado con `build-c` y ejecutado en `32.cpu-gpu-func-sim`): los cinco ejemplos dan los
76 800 píxeles idénticos al host con la misma versión, en V0, V1 y V2, en el frame 3; `trail` también en el frame 121
(V0 y V1). La entrada (INPUT) se ha probado con el guion `examples/paint.input`, que da el mismo frame en V0 y en V1.

## Coste

Instrucciones hasta el frame 3 (`make profile-minigpu-<nombre>`), incluido el arranque: borrar la pantalla y, en el
primer frame, copiar el lienzo. En V2, la CPU de la tabla es la que trabaja: sin contar lo que espera a la GPU
(`gpu_run_check` y `gpu_run_poll`). El tiempo supone una instrucción por ciclo, con la CPU a 80 MHz y la GPU a
25 MHz, y en V2 suma las dos, porque la CPU espera mientras la GPU dibuja.

| | V0 (CPU) | V1 (CPU) | V2 (CPU + GPU, instrucciones de warp) |
|---|---|---|---|
| `shapes` | 826 000 (10,3 ms) | 839 000 (10,5 ms) | 211 591 + 504 693 (2,6 + 20,2 = 22,8 ms) |
| `pattern` | 1 369 000 (17,1 ms) | 1 475 000 (18,4 ms) | 366 650 + 1 044 162 (4,6 + 41,8 = 46,4 ms) |

V0 y V1 salen redondeados a miles: el simulador para por lotes. En instrucciones, la GPU de V2 dibuja con menos que
la CPU de V0; en tiempo es más lenta porque va a menos de un tercio de la frecuencia y hoy usa un solo warp.

No se ha validado nada en la FPGA.

## 3D

`make test3d` (host, `-std=c89 -pedantic -Wall -Wextra`, sin avisos): `test_commands`, `test_matrices`,
`test_clipping`, `test_raster`, `test_resources` y `test_cube` dan PASS, y `mgl-replay` reproduce la captura
del frame 40 del cubo con el mismo PPM que el sketch. Qué comprueba cada una: [3d-arquitectura.md](3d-arquitectura.md#validación).

`make check-minigpu3d FRAMES=3`: `rotating_cube` y `boxes` dan los 76 800 píxeles idénticos en el simulador de
MiniGPU (el renderer en su CPU, compilado con `build-c`) y en el host; `rotating_cube` también en el frame 60.
Tras los arreglos de toolchain que hizo falta (mini-lcc, mini-opt, build-c), `make check-minigpu V=0|1|2
FRAMES=3` sigue dando los cinco sketches 2D idénticos, y `u.lcc/run-mini-tst.py --simulate` pasa los 168 tests.

No se ha probado el 3D en la FPGA.

### Optimización de borrados 3D

En MiniGPU, los borrados de color RGB565 y profundidad U16 escriben dos valores
por palabra de 32 bits, con el bucle desenrollado en grupos de ocho valores.
Se alinea cada fila y se resuelve la cola con escrituras de 16 bits; el padding
no se toca. En el host se mantienen accesos de 16 bits para respetar strict aliasing.

Perfil hasta el frame 3, incluido el arranque, con el mismo simulador funcional
y las mismas escenas antes y después (las cuentas totales paran por lotes de
1000 instrucciones):

| Escena | Antes, instrucciones CPU | Después | Reducción |
|---|---:|---:|---:|
| `rotating_cube` | 11 219 000 | 9 321 000 | 16,9% |
| `colored_cube` | 11 214 000 | 9 317 000 | 16,9% |
| `boxes` | 21 444 000 | 19 546 000 | 8,9% |

Los dos borrados juntos pasan de 2 319 879 a 422 118 instrucciones en tres
frames: **81,8% menos**. La cuenta posterior incluye las llamadas al helper
compartido `clear_buffer`; no se suma su coste otra vez. Son instrucciones,
no tiempos medidos en FPGA.

El frame 3 de las tres escenas coincide con el host: 76 800 píxeles idénticos
por escena. `make test3d` pasa. `test_clear` comprueba color y profundidad con centinelas:
anchos de 1 a 19, ambas alineaciones de 16 bits, tres filas y padding de 0 a 3
valores. Pasa en el host y compilado con `build-c` en `sim-cpu` (retorno 0),
ejercitando también la ruta de 32 bits. Para reproducir esta última prueba,
desde la raíz del repositorio:

```sh
tools/build-c 40.mini-gl/tests/test_clear.c 40.mini-gl/src/render/3d/fragment.c \
    -I 40.mini-gl/src -I 40.mini-gl/src/render/3d \
    --outdir 40.mini-gl/build/minigpu/3d/test_clear \
    -o 40.mini-gl/build/minigpu/3d/test_clear.bin
tools/sim-cpu 40.mini-gl/build/minigpu/3d/test_clear.bin --run-limit 5000000
```

### Bucles especializados de profundidad

`mgr_fragment_span` elige una vez por span entre test y escritura, solo test,
solo escritura o solo color. Se eliminan las comprobaciones de modo por píxel,
conservando LESS estricto, saturación y el mismo avance entero de profundidad.

Perfil hasta el frame 3, incluido el arranque, tomando como base la versión
con los borrados optimizados de la sección anterior:

| Escena | Antes, instrucciones CPU | Después | Reducción adicional |
|---|---:|---:|---:|
| `rotating_cube` | 9 321 000 | 9 174 000 | 1,6% |
| `colored_cube` | 9 317 000 | 9 169 000 | 1,6% |
| `boxes` | 19 546 000 | 19 259 000 | 1,5% |

En los cubos individuales, `mgr_fragment_span` baja de 1 834 230 a 1 686 948
instrucciones: 8,0% menos en esa función. Las cuentas totales tienen granularidad
de 1000 instrucciones; no son medidas de tiempo en FPGA.
El frame 3 de cada una de las tres escenas conserva los 76 800 píxeles
idénticos a la referencia host previa al cambio del Z-buffer.

`make test3d` incluye `test_fragment`, que compara los cuatro modos contra
el bucle escalar previo, con y sin buffer, spans vacíos, saturación, gradientes
de ambos signos y strides distintos de color y profundidad. Pasa en el host
y en `sim-cpu` compilado con `build-c` (retorno 0). Se reproduce con los mismos
comandos de `test_clear`, sustituyendo `test_clear` por `test_fragment`.

### Profundidad incremental (por defecto)

`MGR_INCREMENTAL_DEPTH=1` es el modo por defecto. Conserva el cálculo float del plano por triángulo,
pero avanza el inicio de profundidad entre filas con sumas enteras y calcula
el inicio del span con un desplazamiento entero en x. Usa 12 bits de fracción
en unidades U16, cuatro más que los spans; mantiene el incremento por píxel
anterior. La conversión de vuelta a los 8 bits fraccionarios de los spans se
redondea al más cercano y se satura al rango de profundidad.

Para evitar desbordamientos en cajas que extrapolan muy lejos del interior
de triángulos estrechos, se acotan el origen y la variación total del plano
en la caja. Si no pasan las cotas, se usa el cálculo float original por fila.
También rechazan la ruta incremental los valores no finitos. Este fallback
protege el rango entero; no garantiza igualdad de redondeo en la ruta rápida.

Perfil hasta el frame 3, incluido el arranque, sobre la versión con borrados
optimizados y bucles especializados del Z-buffer:

| Escena | Referencia, instrucciones CPU | Incremental | Reducción adicional |
|---|---:|---:|---:|
| `rotating_cube` | 9 174 000 | 5 313 000 | 42,1% |
| `colored_cube` | 9 169 000 | 5 308 000 | 42,1% |
| `boxes` | 19 259 000 | 10 738 000 | 44,2% |

Son instrucciones del simulador funcional, no tiempos medidos en FPGA.
En el frame 3, los tres colores coinciden exactamente con la referencia.
Los buffers de profundidad tienen respectivamente 108, 108 y 104 diferencias
de una unidad U16. Host y simulador de MiniGPU producen exactamente los mismos
buffers de color y profundidad de la variante incremental en ese frame.

La comparación diferencial de 120 frames por escena (restaurando la misma RAM
antes de cada renderer) detecta diferencias que el frame 3 no revela:

| Escena | Diferencias de color acumuladas | Diferencias U16 acumuladas | Máxima diferencia U16 |
|---|---:|---:|---:|
| `rotating_cube` | 0 | 11 244 | 1 |
| `colored_cube` | 4 | 10 849 | 1 |
| `boxes` | 7 | 14 459 | 1 |

Se adopta como variante por defecto aceptando estas diferencias de redondeo.
`MGR_INCREMENTAL_DEPTH=0` conserva la variante float anterior para comparación.
Los diagnósticos diferenciales de escenas devuelven 1 cuando detectan cambios
de color: `boxes` y `colored_cube` no cumplen igualdad exacta con la variante
anterior. No se garantiza una cota de error universal de una unidad U16.

`test_depth_triangles` contrasta además 1000 triángulos deterministas en un
destino de 128x96 y dos triángulos estrechos en uno de 1024x1024: cobertura
idéntica, 2313 diferencias de profundidad con máximo de una unidad U16; los
2048 píxeles de los casos estrechos coinciden exactamente gracias al fallback.
`make test3d` pasa con el renderer incremental por defecto e incluye
`test_depth_triangles`. `make check-minigpu3d FRAMES=3` comprueba los 76 800
píxeles por escena entre host y simulador con la misma variante incremental.

Desde `40.mini-gl`, los diagnósticos se construyen y ejecutan por separado:

```sh
make build/test_depth_triangles build/test_depth_rotating_cube \
    build/test_depth_boxes build/test_depth_colored_cube
./build/test_depth_triangles
./build/test_depth_rotating_cube
./build/test_depth_boxes          # retorna 1: hay diferencias de color
./build/test_depth_colored_cube   # retorna 1: hay diferencias de color
```

Un argumento opcional a los tests de escenas es el prefijo de cuatro volcados
del frame 3 (color y profundidad de referencia e incremental). Para reproducir
el perfil en MiniGPU con la configuración por defecto:

```sh
make minigpu3d
python3 ../tools/sim-sys build/minigpu/3d/boxes.bin \
    --halt-after-swaps 3 --run-limit 100000000000 \
    --profile build/minigpu/3d/boxes-profile.txt \
    --symbols build/minigpu/3d/boxes/minigpu.asm \
    --frame-output build/minigpu/3d/boxes-sim.bin \
    --dump 0x0105B000 153600 build/minigpu/3d/boxes-depth.bin
```

Para compilar la variante float anterior en un directorio separado:

```sh
make minigpu3d MG3=build/minigpu/3d-float \
    BUILD_C='python3 ../tools/build-c -D MGR_INCREMENTAL_DEPTH=0'
```

## Reorganización de fuentes y plataforma común

La reorganización en `src/render/{2d,3d}`, `src/processing`, `src/platform` y
`apps/replay.c` se verificó primero sin cambios de comportamiento: los binarios
MiniGPU existentes conservaron sus bytes y los 18 frames host de referencia
coincidieron (cinco sketches × V0/V1/V2 en el frame 3, `trail` en el 121;
las tres escenas 3D en el 120).

Después se unificaron los drivers por entorno en `host.c`, `sdl.c` y `minigpu.c`.
Los contextos 2D y 3D mantienen sus reglas de comandos, profundidad y conservación
del lienzo. Los 18 frames de referencia siguieron siendo idénticos.

- `make test all sdl`: suites 2D/3D, replay de captura y compilación de los ocho
  ejecutables SDL. La ventana SDL no se ha validado visualmente en esta pasada.
- `make check-minigpu V=0|1|2 FRAMES=3`: los cinco sketches en cada versión dan
  76 800 píxeles idénticos al host (15 comparaciones).
- `make check-minigpu3d FRAMES=3`: las tres escenas dan otros tres frames idénticos.
- `test_platform2d` y `test_platform3d`: inicialización, paso de teclado/ratón a
  draw, callbacks, captura 3D, persistencia del lienzo y cambio de versión 2D.

Las medidas de instrucciones de las optimizaciones anteriores se tomaron antes
de extraer los contextos y unificar los drivers; el nuevo ciclo puede añadir
instrucciones de coordinación y entrada. No son perfiles de esta reorganización.
