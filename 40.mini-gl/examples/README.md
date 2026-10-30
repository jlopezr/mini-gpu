# Ejemplos

Cada ejemplo es un sketch Processing, `examples/<nombre>.c`, que solo define
`setup()` y `draw()`. El `main()`, `size()` y el bucle los pone la plataforma
host ([src/platform_host.c](../src/platform_host.c)), que dibuja un frame con la
versión de MiniGL elegida y lo guarda como PPM.

| Ejemplo | Qué muestra |
|---|---|
| [`shapes.c`](shapes.c) | Todas las primitivas: relleno, contorno, grosores, recorte en los bordes y un sprite |
| [`pattern.c`](pattern.c) | Rejilla de figuras con bucles: muchas primitivas, command buffer más grande |

## Elegir versión

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

## Añadir un ejemplo

1. Crea `examples/<nombre>.c` con `setup()` (empieza por `size(w, h)`) y `draw()`.
2. Añade `build/<nombre>` a `EXAMPLES` en el [Makefile](../Makefile).
3. `make run-<nombre>`.

Notas sobre la API:
- `circle(cx, cy, r)` recibe el **radio**.
- Los colores son RGB565; usa `color(r, g, b)` con canales de 0 a 255.
- Por ahora se dibuja un único frame: no hay animación (`frameCount`) ni eventos.
