# Ejemplos

Cada ejemplo es un sketch Processing, `examples/<nombre>.c`, que solo define
`setup()` y `draw()`. El `main()`, `size()` y el bucle los pone la plataforma.
Cada sketch se compila para tres:

| Plataforma | Binario | Qué hace |
|---|---|---|
| Host ([platform_host.c](../src/platform_host.c)) | `build/<nombre>` | `setup()` y un solo `draw()`; guarda el frame como PPM |
| SDL ([platform_sdl.c](../src/platform_sdl.c)) | `build/<nombre>-sdl` | Ventana: `setup()` y `draw()` en bucle a 60 fps |
| MiniGPU ([platform_minigpu.c](../src/platform_minigpu.c)) | `build/minigpu/<nombre>.bin` | La máquina del repo (CPU + GPU, vídeo 320×240): en su simulador o en las placas 36/37. De momento solo V0 |

Host y SDL ejecutan MiniGL con la versión elegida; su parte común está en
[platform.c](../src/platform.c).

| Ejemplo | Qué muestra |
|---|---|
| [`shapes.c`](shapes.c) | Todas las primitivas: relleno, contorno, grosores, recorte en los bordes y un sprite |
| [`pattern.c`](pattern.c) | Rejilla de figuras con bucles: muchas primitivas, command buffer más grande |
| [`bounce.c`](bounce.c) | Animación: pelotas que rebotan, círculo que sigue al ratón (más grande al pulsar) |
| [`trail.c`](trail.c) | Estela: `draw()` no borra y dibuja encima de los frames anteriores |

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

En la ventana, las teclas **0**, **1** y **2** cambian de versión en marcha y
**Esc** cierra. El título muestra la versión, los fps y los bytes de comandos
de cada frame.

## MiniGPU: simulador (y placa)

Se compila con `build-c` (`mini-lcc` y `mini-opt` del repo) y se ejecuta en el
simulador de CPU + GPU (`32.cpu-gpu-func-sim`). Es un simulador funcional en
Python: un frame son millones de instrucciones, varios segundos.

```sh
make minigpu                         # build/minigpu/<nombre>.bin
make sim-bounce                      # en la ventana del simulador
make check-minigpu                   # cada ejemplo, píxel a píxel contra V0 en el host
make check-minigpu-bounce FRAMES=5   # el frame 5 de uno solo
make profile-minigpu-shapes          # instrucciones por función C hasta el frame FRAMES
```

`profile-minigpu-<nombre>` usa `--profile` del simulador: instrucciones propias de cada función C (`put`,
`sw_clear`, `edge`...), llamadas y total con lo que llama.

`check-minigpu` guarda el frame del host (`-f FRAMES -o x.bin`) y el del
simulador (`--halt-after-swaps FRAMES --frame-output`) en RGB565 crudo y los
compara con `tools/compare-frames.py`, que dice dónde están las diferencias.

Por ahora solo hay V0 (la CPU rasteriza al llamar): no hay ratón ni teclado, y
`size()` solo acepta 320×240, el tamaño del vídeo. Se dibuja directamente en el
buffer trasero, que tiene lo de hace dos frames. Para que, como en Processing, el
lienzo se conserve de un frame al siguiente, tras cada swap `mgl_set_target`
cambia de buffer sin tocar el estado de dibujo y deja pendiente copiar el
delantero. MiniGL solo hace la copia si se dibuja algo antes de un `background()`:
en los sketches que borran cada frame no se copia nunca. `trail` es el que no borra.

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
- `frameCount` vale 0 en `setup()` y 1, 2, 3… en cada `draw()`. `mouseX`,
  `mouseY` y `mousePressed` solo cambian en SDL; en el host valen 0.
- Como en Processing, el framebuffer no se borra entre frames: si quieres
  borrarlo, empieza `draw()` con `background()`.
- No hay teclado (`key`, `keyPressed`) ni `frameRate()`: SDL va fijo a 60 fps.
