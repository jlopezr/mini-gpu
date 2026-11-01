# Ejemplos

Cada ejemplo es un sketch Processing, `examples/<nombre>.c`, que solo define
`setup()` y `draw()`. El `main()` y el bucle los pone el driver de plataforma; `size()` configura el contexto de render.
Cada sketch se compila para tres:

| Plataforma | Binario | Qué hace |
|---|---|---|
| Host ([host.c](../src/platform/host.c)) | `build/<nombre>` | `setup()` y un solo `draw()`; guarda el frame como PPM |
| SDL ([sdl.c](../src/platform/sdl.c)) | `build/<nombre>-sdl` | Ventana: `setup()` y `draw()` en bucle a 60 fps |
| MiniGPU ([minigpu.c](../src/platform/minigpu.c)) | `build/minigpu/v<N>/<nombre>.bin` | La máquina del repo (CPU + GPU, vídeo 320×240): en su simulador o en las placas 36/37. V0, V1 y V2 |

Host y SDL ejecutan MiniGL con la versión elegida; su parte común está en
[platform.c](../src/platform/platform.c).

| Ejemplo | Qué muestra |
|---|---|
| [`shapes.c`](shapes.c) | Todas las primitivas: relleno, contorno, grosores, recorte en los bordes y un sprite |
| [`pattern.c`](pattern.c) | Rejilla de figuras con bucles: muchas primitivas, command buffer más grande |
| [`bounce.c`](bounce.c) | Animación: pelotas que rebotan, círculo que sigue al ratón (más grande al pulsar) |
| [`trail.c`](trail.c) | Estela: `draw()` no borra y dibuja encima de los frames anteriores |
| [`paint.c`](paint.c) | Pintar con el ratón; colores, grosor y borrar con el teclado |

Sketches 3D (incluyen `processing3d.h`, `size(320, 240, P3D)`), con los mismos drivers y el contexto 3D: el host
([host.c](../src/platform/host.c)) graba cada frame con MiniGL 3D y lo ejecuta con el renderer
de referencia sobre RAM emulada; en MiniGPU ([minigpu.c](../src/platform/minigpu.c)) el mismo
renderer corre en la CPU. En una ventana, [sdl.c](../src/platform/sdl.c): `make sdl-rotating_cube`
(SDL solo muestra el framebuffer; rasteriza el renderer). No tienen versiones.

| Ejemplo | Qué muestra |
|---|---|
| [`rotating_cube.c`](rotating_cube.c) | Cubo giratorio con perspectiva y Z-buffer; sin luces, una silueta de un color, como en Processing |
| [`boxes.c`](boxes.c) | Dos cubos de colores que se cortan (lo dibuja el Z-buffer) y una barra 2D encima |
| [`colored_cube.c`](colored_cube.c) | Cubo con una cara de cada color, como en Processing: `beginShape(QUADS)` y un `fill()` por cara |
| [`tie_fighter.c`](tie_fighter.c) | Un modelo OBJ ([`low-poly-tie-fighter/`](low-poly-tie-fighter/)) convertido a `PShape` con `tools/obj2shape.py`: 2150 triángulos, un color por cara sacado de la textura. Modelo de tolotedesign, CC BY 4.0 ([créditos](low-poly-tie-fighter/README.md)) |

```sh
make run-rotating_cube                     # 60 frames; guarda el último y uno de cada 15
./build/boxes -f 90 -e 30 -o boxes.ppm     # a mano: frames, cada cuántos guardar, salida
make check-minigpu-rotating_cube FRAMES=60 # el frame 60 en el simulador de MiniGPU, frente al host
make sdl-rotating_cube                     # en una ventana SDL a 60 fps (SCALE=4: otra escala; Esc cierra)
```

### Modelos OBJ

No hay `loadShape()`: en MiniGPU no hay ficheros. [`tools/obj2shape.py`](../tools/obj2shape.py) convierte el
OBJ en un `.h` con un `PShape` (posiciones `float` x, y, z, índices `u16` y grupos de triángulos del mismo
color), y el sketch lo incluye y lo dibuja con `shape(&modelo)`. La malla se copia al heap de MiniGL en el
primer `shape()`, como el cubo de `box()`, y cada frame es un `SET_COLOR` y un `DRAW_INDEXED` por grupo.

- El renderer no tiene texturas ni luces: cada cara toma el color medio de la textura bajo su polígono UV
  (`--texture`) o uno fijo (`--color r,g,b`), y esos colores se reducen a `--colors` (8) por k-means.
- El modelo se centra, se escala a [-1, 1] (en el sketch, `scale()`) y pasa de y hacia arriba a y hacia
  abajo como en Processing, girándolo 180° en x.
- Solo la biblioteca estándar de Python (el PNG se decodifica en el propio script). `make` regenera
  `tie_fighter_shape.h` si cambian el OBJ, la textura o el conversor.

```sh
python3 tools/obj2shape.py modelo.obj --texture textura.png --colors 8 --name modelo -o examples/modelo_shape.h
```

## Host: imágenes PPM

```sh
make run-shapes          # V=all por defecto: V0, V1 y V2, y comprueba que coinciden
make run-shapes V=0      # V0: directo, la CPU rasteriza al llamar
make run-shapes V=1      # V1: diferido, la CPU interpreta el command buffer
make run-shapes V=2      # V2: diferido, la GPU (emulada, 8 lanes) interpreta el command buffer
make run                 # todos los ejemplos

./build/shapes -v 2 -o salida.ppm    # lo mismo a mano
```

Las imágenes quedan en la carpeta del proyecto como `<nombre>-v<N>.ppm`.
`make clean` las borra. En macOS se abren con `open shapes-v0.ppm`.

## SDL: ventana

Necesita SDL2 (`sdl2-config` en el `PATH`; en macOS, `port install libsdl2`
o `brew install sdl2`).

```sh
make sdl-bounce          # V0 por defecto
make sdl-bounce V=2      # empieza con V2
make sdl                 # solo compilar todos

./build/bounce-sdl -v 1 -s 4         # a mano: versión y escala (por defecto 3)
```

En la ventana, **F1**, **F2** y **F3** cambian a V0, V1 y V2 en marcha y **Esc**
cierra; el resto de teclas y el ratón son del sketch. El título muestra la versión, los fps y los bytes de comandos
de cada frame.

## MiniGPU: simulador (y placa)

Se compila con `build-c` (`mini-lcc` y `mini-opt` del repo) y se ejecuta en el
simulador de CPU + GPU (`32.cpu-gpu-func-sim`). Es un simulador funcional en
Python: un frame son millones de instrucciones, varios segundos.

```sh
make minigpu                         # V0: build/minigpu/v0/<nombre>.bin
make minigpu V=1                     # V1: build/minigpu/v1/<nombre>.bin (todos los objetivos aceptan V)
make sim-bounce                      # en la ventana del simulador (con su ratón y teclado)

# entrada de un guion (tools/input_script.py) en vez de la ventana; deja el frame 40 en paint.bin
../tools/sim-sys build/minigpu/v0/paint.bin --input-script examples/paint.input \
    --halt-after-swaps 40 --frame-output paint.bin --run-limit 100000000000
make check-minigpu                   # cada ejemplo, píxel a píxel contra la misma versión en el host
make check-minigpu-bounce FRAMES=5   # el frame 5 de uno solo
make profile-minigpu-shapes          # instrucciones por función C hasta el frame FRAMES
```

`profile-minigpu-<nombre>` usa `--profile` del simulador: instrucciones propias de cada función C (`put`,
`sw_clear`, `edge`...), llamadas y total con lo que llama. En V2, el kernel sale como un árbol de las funciones
expandidas en él (`render` > `primitive` > `segment` > `brush` > `put`), con la ocupación de lanes de cada una.
Deja además `<sketch>-anotado.txt` en la carpeta de la versión: el `.asm` con la cuenta de cada instrucción.

`check-minigpu` guarda el frame del host (`-f FRAMES -o x.bin`) y el del
simulador (`--halt-after-swaps FRAMES --frame-output`) en RGB565 crudo y los
compara con `tools/compare-frames.py`, que dice dónde están las diferencias.

La versión se elige al compilar (`V=0`, la de por defecto, `V=1` o `V=2`): en V1, cada
`draw()` se graba en un command buffer en RAM y la CPU lo interpreta antes del swap; en V2 lo interpreta un warp
de la GPU (`KERNEL(mgl_render)`), que la CPU lanza y espera. `size()` solo acepta 320×240, el tamaño del vídeo. Se dibuja directamente en el
buffer trasero, que tiene lo de hace dos frames. Para que, como en Processing, el
lienzo se conserve de un frame al siguiente, tras cada swap `mgl_set_target`
cambia de buffer sin tocar el estado de dibujo y deja pendiente copiar el
delantero. MiniGL solo hace la copia si se dibuja algo antes de un `background()`:
en los sketches que borran cada frame no se copia nunca. `trail` es el que no borra.

El ratón y el teclado salen del periférico INPUT (`1.isa/mmio.md` §25), que en el
simulador dan la ventana (`--window`, lo pone `make sim-*`) o un guion
(`--input-script`, como [`paint.input`](paint.input)); sin ninguno, la entrada no
cambia. El ratón de INPUT es relativo: empieza en el centro (igual que en las otras
plataformas, para que `check-minigpu` coincida) y se mueve en medios píxeles, porque
la ventana enseña el framebuffer a doble tamaño. Las teclas se traducen de USB HID
a ASCII con la distribución US.

## Añadir un ejemplo

1. Crea `examples/<nombre>.c` con `setup()` (empieza por `size(w, h)`) y `draw()`.
2. Añade `<nombre>` a `SKETCHES` en el [Makefile](../Makefile).
3. `make run-<nombre>`, `make sdl-<nombre>` o `make sim-<nombre>`.

Notas sobre la API:

- `circle(cx, cy, d)` recibe el diámetro, como en Processing. Los círculos
  quedan centrados en un píxel, así que un diámetro par sale un píxel más ancho.
- Colores como en Arduino TFT: `background`, `fill` y `stroke` reciben
  `(r, g, b)` de 0 a 255. Para RGB565 directo están `background565`, `fill565`
  y `stroke565`, y `color565(r, g, b)` convierte (como en Adafruit_GFX).
- `frameCount` vale 0 en `setup()` y 1, 2, 3… en cada `draw()`.
- Entrada como en Processing, actualizada antes de cada `draw()` en SDL y
  MiniGPU (en el host no cambia): `mouseX`, `mouseY` (empiezan en el centro),
  `pmouseX`, `pmouseY` (los del frame anterior) y `mousePressed`; `keyPressed`
  mientras haya una tecla pulsada, y `key`, la última: su carácter, o `CODED` y
  entonces `keyCode` es `UP`, `DOWN`, `LEFT` o `RIGHT`. No hay funciones de
  evento (`keyPressed()` chocaría en C con la variable): un sketch mira si `key`
  ha cambiado, como `paint`.
- Como en Processing, el framebuffer no se borra entre frames: si quieres
  borrarlo, empieza `draw()` con `background()`.
- No hay teclado (`key`, `keyPressed`) ni `frameRate()`: SDL va fijo a 60 fps.
