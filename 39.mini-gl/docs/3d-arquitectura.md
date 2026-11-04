# MiniGL 3D — arquitectura, etapas y limitaciones

Primera versión de MiniGL 3D según [3d.md](3d.md): MiniGL genera un command buffer binario y un renderer
software C89, independiente de MiniGL, lo ejecuta. Mismo código en el host y en la CPU de MiniGPU. El
renderer SIMT está por hacer.

```text
sketch (setup/draw)                       examples/rotating_cube.c, boxes.c
   │
MiniProcessing 3D                         src/processing/processing3d.c  (+ processing.c para lo 2D)
   │  size(w, h, P3D), translate, rotateX/Y, box
MiniGL 3D                                 src/mgl_3d.c, mgl_resources.c  (+ minigl.c para lo 2D)
   │  estado, matrices por valor, handles -> direcciones
command buffer (versión 2)                src/mgl_commands.h, docs/command-buffer.md
   │
renderer de referencia                    src/render/3d/  (no incluye minigl.h ni processing.h)
   ├── host: RAM emulada                  src/platform/host.c
   └── CPU de MiniGPU: SDRAM real         src/platform/minigpu.c
```

El contexto 3D (mapa de memoria, comandos y ejecución) está en
[context3d.c](../src/render/context3d.c). Los drivers de host, SDL y MiniGPU son
los mismos que en 2D; el ciclo común está en [platform.c](../src/platform/platform.c),
que usa el contrato [context.h](../src/render/context.h).

## Qué se reutiliza del 2D

- **El command buffer**: el mismo `mgl_cmd_buffer_t`, `mgl_cmd_init`/`reset`/`status` y la misma cabecera.
  Los comandos 2D (`CLEAR`, `BATCH`) son los de siempre, byte a byte; el 3D añade opcodes. Un frame puede
  mezclar 2D y 3D y se ejecuta en orden (`boxes.c` dibuja una barra 2D sobre los cubos).
- **El raster 2D**: el renderer ejecuta los `BATCH` con `src/render/2d/raster.c`, el de V0, V1 y V2
  ([raster2d.c](../src/render/3d/raster2d.c)), así que dan los mismos píxeles.
- **Processing**: `background`, `fill`, `noStroke`... son los de `processing.c`. En un frame 3D,
  `mgl_clear` (y por tanto `background`) borra además la profundidad.

Cambios en lo existente (sin cambiar el formato 2D ni los resultados de V0/V1/V2):

- `minigl.h` toma los tipos de `mgl_types.h` y las constantes del formato de `mgl_commands.h`; los
  `RD`/`WR` de `minigl.c` pasan a `mgl_bytes.h`.
- `minigl.c` expone a `mgl_3d.c` el buffer actual y una reserva de bytes para comandos 3D
  (`mgl_internal.h`), y la API gana `mgl_get_fill`.
- `host.c` usa `ppm.c`, compartido con la plataforma 3D.

## API de MiniGL 3D

[minigl3d.h](../src/minigl3d.h). Respecto a la propuesta de 3d.md, cambia un nombre: `mgl_clear(color)`
ya existía en 2D, así que el borrado con profundidad explícita es `mgl_clear_color_depth(color, depth)`.

```c
mgl_set_render_target(&target);              /* direcciones de color y profundidad */
mgl_begin_frame();                           /* emite SET_RENDER_TARGET */
mgl_clear(color);                            /* o mgl_clear_color_depth(color, 1.0f) */
mgl_set_viewport(0, 0, 320, 240);
mgl_set_matrix(MGL_MATRIX_PROJECTION, &projection);   /* copia el valor */
mgl_set_matrix(MGL_MATRIX_VIEW, &view);
mgl_set_matrix(MGL_MATRIX_MODEL, &model);
mgl_set_depth_test(1);  mgl_set_depth_write(1);  mgl_set_cull(MGL_CULL_NONE);
mgl_set_color(color);
mgl_draw_mesh(mesh);                         /* emite el estado pendiente y DRAW_INDEXED */
mgl_end_frame();                             /* emite END_FRAME; devuelve el primer error */
```

El estado se guarda al llamar y se emite en el siguiente `mgl_draw_mesh`, solo lo que cambió desde lo
emitido en el frame (las matrices se comparan bit a bit). `mgl_begin_frame` olvida lo emitido: cada frame es
autocontenido. El estado de MiniGL sí persiste entre frames, como en OpenGL; `mgl_reset_state3d` lo devuelve
al inicial, que es el mismo con el que empieza el renderer. Solo hay 3D en modo diferido.

## Tipos y aritmética

- [mgl_types.h](../src/mgl_types.h): `mgl_u8/u16/s16/u32/s32` sin `stdint.h`, comprobados al compilar
  (`MGL_STATIC_ASSERT`). No se usa `long`.
- [mgl_config.h](../src/mgl_config.h): `mgl_real_t` (el tipo con el que se calcula) es `float` con
  `MGL_REAL_FORMAT = MGL_FORMAT_FLOAT32`. Pedir Q16.16 es un error de compilación hasta que exista la variante.
  El formato **serializado** es aparte: lo lleva cada comando (`SET_MATRIX.arg1`, el formato de vértice), y el
  renderer rechaza Q16.16 con `MGR_ERR_UNSUPPORTED`.
- [mgl_math.c](../src/mgl_math.c): todo el cálculo con `mgl_real_t` (matrices, seno, coseno, raíz, redondeo)
  está aquí, sin `math.h`. Para Q16.16 habrá que reescribir este módulo (multiplicar y dividir reescalan, y
  las constantes cambian), no solo el `typedef`.

### Convenciones

- Matrices 4×4 **column-major** (`m[columna * 4 + fila]`), vectores columna, ángulos en radianes.
- `clip = Projection × View × Model × v`. El renderer calcula `mvp` una vez por cambio de matriz.
- Las funciones que componen (`mgl_mat4_mul`, `mgl_mat4_*_by`) multiplican **por la derecha**: `M = M × T`.
  En un sketch, lo último que se llama es lo primero que se aplica al objeto: `translate(); rotateY(); box();`
  gira el cubo sobre su centro y luego lo lleva a su sitio.
- Proyección de OpenGL: z de `-near` a `-far` va a `[-1, 1]`; en ventana, profundidad `(z + 1) / 2`.

### Mismos bits en el host y en MiniGPU

La CPU de MiniGPU hace `float` por software (IEEE binary32, redondeo al par). Para que el host dé
exactamente lo mismo:

- se compila con `-ffp-contract=off` (sin fusionar multiplicación y suma);
- las constantes se escriben como literales con 9 cifras, sin expresiones que el compilador pliegue (lcc y
  clang podrían redondearlas distinto), y sin literales negativos en operaciones (mini-lcc los deja en
  `double`: ver más abajo);
- seno, coseno y raíz son polinomios y Newton propios, no los de la libc;
- las sumas de las matrices van siempre en el mismo orden.

Resultado: `make check-minigpu3d` da los 76 800 píxeles idénticos (frames 3 y 60 del cubo, frame 3 de
`boxes`, frames 3 y 40 de `colored_cube`).

## MiniProcessing 3D

[processing3d.h](../src/processing/processing3d.h). Lo que usa el cubo: `size(w, h, P3D)`, `translate`, `rotateX`,
`rotateY` y `box`; y `beginShape(QUADS | TRIANGLES)`, `vertex(x, y, z)` y `endShape()` para figuras dadas
vértice a vértice, como el cubo de una cara de cada color (`colored_cube.c`). Como C89 no tiene sobrecarga, `size` con tres argumentos es una macro de
`processing3d.h` (`size_renderer`); los sketches 2D siguen con `size(w, h)`. `background(20)` de Processing se
escribe `background(20, 20, 20)`, como en el resto de MiniProcessing.

La cámara es la de Processing: ojo en `(w/2, h/2, (h/2) / tan(30°))` mirando a `(w/2, h/2, 0)`, 60° de campo
vertical, `near = ojo/10`, `far = ojo*10`. En `z = 0` una unidad es un píxel, con y hacia abajo. Esa y hacia
abajo es una simetría, no un giro: se hace invirtiendo y en la proyección, como Processing (por eso las caras
cambian de sentido de giro en pantalla; el cubo se dibuja sin culling). La matriz del modelo vuelve a la
identidad al empezar cada `draw()`.

Sin `lights()` Processing pinta un `box` de un solo color, y aquí igual: el cubo de `rotating_cube` es una
silueta naranja con perspectiva. Para ver la profundidad, `boxes.c` dibuja dos cubos de colores que se cortan.

`box()` es de un solo color, también en Processing. Para un color por cara, Processing da las caras con
`beginShape(QUADS)` y un `fill()` antes de cada una, y aquí se hace igual. `endShape` copia los vértices a la
**memoria de frame** de MiniGL (`mgl_create_mesh_frame`, que se vacía en cada `mgl_begin_frame`) y dibuja la
malla por tramos de primitivas seguidas del mismo color: un `SET_COLOR` y un `DRAW_INDEXED` por tramo
(`mgl_draw_mesh_range`, que desplaza la dirección de los índices). El contrato binario no cambia. El color es
plano por primitiva (el del primer vértice): Processing interpola si los vértices de una cara tienen colores
distintos, y eso pediría un atributo de color en el formato de vértice.

## Etapas del renderer

[src/render/3d/mgr_stages.h](../src/render/3d/mgr_stages.h) declara la interfaz de cada etapa. Un triángulo pasa por
todas antes de leer el siguiente; ninguna guarda listas completas de la anterior y no hay memoria dinámica.

| Fichero | Etapa | Recibe | Entrega |
|---|---|---|---|
| `commands.c` | decodificación | dirección del buffer | valida y despacha cada comando |
| `state.c` | estado | un comando `SET_*` | `mgr_state_t` (punteros ya traducidos, `mvp`) |
| `draw.c` | `DRAW_INDEXED` | el comando | por triángulo: las etapas siguientes |
| `transform.c` | transformación | flujo de vértices + índice + `mvp` | vértice en coordenadas de recorte (`mgl_vec4_t`) |
| `clipping.c` | recorte | 3 vértices homogéneos | polígono de 0 o 3..9 vértices, dentro del volumen |
| `viewport.c` | viewport | vértice de recorte | x, y en 1/16 de píxel (enteros), z en [0, 1] |
| `raster3d.c` | rasterización | 3 vértices de ventana + rectángulo + fragmento | spans: `mgr_fragment_span` por fila |
| `fragment.c` | fragmentos | un span (fila, x0..x1, z y dz en punto fijo) | profundidad y color escritos |
| `raster2d.c` | 2D | un `BATCH` | lo dibuja `src/render/2d/raster.c` |

Detalles:

- **Recorte**: Sutherland-Hodgman en coordenadas homogéneas contra los seis planos (`-w ≤ x, y, z ≤ w`),
  incluido el cercano: un triángulo que lo cruza se recorta, no se descarta, y los vértices con `w < 0`
  (detrás del ojo) no se dividen nunca. El punto de corte de una arista se calcula siempre desde su vértice
  interior, así que dos triángulos que la comparten obtienen el mismo punto. Antes se descartan los
  triángulos fuera de un mismo plano (outcodes) y se dejan pasar sin recortar los que están dentro de todos.
- **Rasterización**: funciones de borde en enteros con 4 bits de subpíxel, muestreo en el centro del píxel y
  regla top-left (la de Direct3D, también con y hacia abajo): sin huecos ni píxeles dobles en aristas
  compartidas. Al recortar contra todos los planos, las coordenadas quedan dentro del viewport (≤ 1024
  píxeles) y las funciones de borde caben en 32 bits.
- **Profundidad**: plano `z(x, y)` con gradientes en float por triángulo e inicios de fila
  incrementales en punto fijo (unidades U16 con 12 bits de fracción); dentro del span,
  suma con 8 bits de fracción. Buffer `U16`, prueba `LESS`. Las pendientes que exceden
  las cotas enteras usan el cálculo float por fila. `MGR_INCREMENTAL_DEPTH=0` recupera
  la variante anterior; los cambios de redondeo aceptados se detallan en
  [validacion.md](validacion.md#profundidad-incremental-por-defecto).
- **Fragmentos**: prueba y escritura de profundidad, color uniforme. Sin blending.

Lo que podría pasar a hardware son `transform`, `viewport`, `raster3d` y `fragment`: reciben lotes pequeños,
sin punteros a estado ajeno. La separación es lógica: no hay FIFOs ni MMIO.

## MiniGPU (fase E)

`make minigpu3d` compila con `build-c` (mini-lcc + mini-opt) los mismos fuentes que el host, y
`make sim-rotating_cube` lo abre en el simulador. El renderer corre en la CPU de MiniGPU sobre la SDRAM; la
GPU no se usa. Coste medido (`make profile-minigpu-rotating_cube`): unos 3,7 M de instrucciones por frame,
unos 0,8 s a 4,5 MIPS. Un 40 % es soft-float (por fila de cada triángulo y por vértice) y un 20 % los dos
borrados.

Llevarlo a MiniGPU destapó tres fallos de la toolchain, que se han corregido fuera de `40.mini-gl`:

1. **mini-lcc** pasaba mal los argumentos calculados en `float`: los colocaba en R1..R4 y después llamaba al
   runtime (`__mulsf3`...) para calcular los siguientes, que los pisaba. Ahora `hascall()` cuenta esas
   operaciones como llamadas y `call()` pasa esos argumentos por un temporal (`u.lcc/src/expr.c`, `enode.c`).
   Test `u.lcc/mini-tst/168_softfloat_call_args.c`.
2. **mini-opt** tomaba por funciones las etiquetas internas del soft-float desde que `build-c` les añade el
   nombre de la unidad (`__sf.N.<unidad>`): el pase `stackslots` usaba registros «libres» que no lo eran.
   Arreglado en `tools/mini_opt/model.py` (y en `tools/sim_profile.py`).
3. **build-c** no podía enlazar dos unidades que usaran `float`: cada una trae el runtime con `.globl`.
   `share_runtime` (`tools/build_c.py`) deja una sola copia.

Y una peculiaridad que queda: mini-lcc deja en `double` los literales `float` negativos (`-1.5f`), así que
comparar o sumar con ellos pasa por el runtime de `double`. En `mgl_math.c` y `raster3d.c` se evita.

## Validación

| Prueba | Qué comprueba |
|---|---|
| `test_commands` | cabeceras, compatibilidad 2D, la secuencia del cubo campo a campo, `SET_MATRIX` ida y vuelta bit a bit, `DRAW_INDEXED`, estado redundante, capacidad, errores de API y todo lo que el renderer rechaza |
| `test_matrices` | seno/coseno/raíz frente a libm, multiplicación y asociatividad, rotaciones, composición por la derecha, perspectiva, `look_at`, lectura de vértices con stride, orden P×V×M |
| `test_clipping` | plano cercano con 1, 2 y 3 vértices fuera, `w < 0`, aristas compartidas bit a bit, varios planos, un suelo que pasa por detrás de la cámara |
| `test_raster` | top-left con aristas sobre centros de píxel, estanqueidad de un abanico, viewport, profundidad (orden, sin prueba, sin escritura, borrado a 0, plano inclinado), culling, 2D/3D intercalados |
| `test_resources` | memoria de la aplicación y de MiniGL, formato serializado, handles inválidos y viejos, formatos rechazados, heap agotado, tabla llena |
| `test_cube` | el cubo en 6 ángulos frente a una proyección independiente en double (área y caja), el command buffer de un frame de Processing, reproducir un buffer guardado, y el cubo de caras de colores: cada cara visible con su color en su sitio y las ocultas tapadas |
| `mgl-replay` | una captura (RAM + buffer) reproducida solo con el renderer da el mismo PPM que el sketch |
| `check-minigpu3d` | MiniGPU frente al host, píxel a píxel |

## Limitaciones y pendiente

- **Sin renderer SIMT.** El contrato está pensado para él (direcciones, sin handles, frames autocontenidos),
  pero no hay kernel de GPU.
- **Q16.16** reservado y rechazado en todos los formatos; tampoco `INDEX_UINT32`.
- **Sin blending** (el bit se rechaza), sin texturas, sin iluminación, un solo color por dibujo, sin atributos
  de vértice además de la posición.
- **IMAGE (sprites 2D)** en el renderer 3D: rechazado, porque lleva un handle de V1 y no una dirección.
- **MiniProcessing**: sin `pushMatrix`/`popMatrix`, `rotateZ`, `scale`, `box(w, h, d)`, `stroke` en 3D,
  `background(gris)` de un argumento, `lights()` ni cámara configurable. `beginShape` solo con `TRIANGLES` y
  `QUADS`, hasta 256 vértices, color plano por primitiva.
- **Aristas compartidas entre caras delanteras y traseras**: sin culling, en la arista de la silueta las dos
  tienen la misma profundidad y con `LESS` gana la primera que se dibuja; puede asomar algún píxel suelto de
  una cara oculta (lo mismo que OpenGL sin culling).
- **Recursos**: el heap de MiniGL no libera piezas; no hay fences ni ejecución asíncrona; sin operaciones de
  coherencia de caché.
- **Plataforma MiniGPU 3D**: solo 320×240; teclado y ratón mediante el driver común,
  si existe INPUT. El trasero no recibe copia del delantero (un sketch 3D
  tiene que borrar en cada `draw()`). No probado en la FPGA.
- **Rendimiento**: borrados de 32 bits en MiniGPU, bucles especializados de profundidad y
  profundidad incremental por defecto. Quedan como candidatos el seguimiento de bordes
  y la reutilización de vértices transformados. Medidas en [validacion.md](validacion.md).
- Límites: destino y viewport de hasta 1024 píxeles, `MGL_MAX_MESHES` = 96, 65 536 vértices por malla.
