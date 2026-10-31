# MiniGL — paquete consolidado

Este paquete reúne **cinco ZIP históricos** (sin modificarlos), una copia de trabajo con nombres `mgl_` / `MGL_`, el scheduler con ejemplo, sketches de ejemplo y documentación de decisiones y roadmap.

## Versiones

| Versión | Qué hace | Entrega original en `archive/` |
|---|---|---|
| V0 | Directo: la CPU rasteriza al llamar | `minigl_v0_direct` |
| V1 | Diferido: command buffer interpretado por la CPU | `minigl_v0_deferred` |
| V2 | Diferido: command buffer interpretado por la GPU (8 lanes, un warp) | `minigl_v1_gpu` |
| V3–V5 | Triángulos, shaders, tiles (diseño) | — |

Los nombres de `archive/` conservan la numeración antigua; ver [docs/roadmap.md](docs/roadmap.md).

## Estructura

- `src/`: versión de trabajo (V0 + V1 + renderer V2), con prefijos `mgl_`/`MGL_`. La API Processing conserva sus nombres originales. Plataformas para los sketches: `platform_host.c` (imagen PPM), `platform_sdl.c` (ventana SDL2), con la parte común en `platform.c`, y `platform_minigpu.c` (la máquina del repo, compilada con `build-c`).
- `examples/`: sketches Processing (`setup()`/`draw()`) que se ejecutan con cualquier versión, como imagen o en una ventana SDL. Ver [examples/README.md](examples/README.md).
- `tests/`: comparación píxel a píxel V0/V1/V2 sobre escenas fijas, y V2 contra V0 en escenas al azar (`test_fuzz_v2`).
- `scheduler/`: última entrega del scheduler con ejemplo, sin modificaciones.
- `archive/`: las cinco versiones originales extraídas y sus ZIP exactos, sin renombrar símbolos.
- `docs/arquitectura.md`: capas, primitivas, memoria, toolchain y decisiones.
- `docs/command-buffer.md`: formato actual frente a diseño propuesto.
- `docs/roadmap.md`: V0–V5 y tareas pendientes.
- `docs/validacion.md`: qué está validado y cuánto cuesta cada versión.
- `docs/punteros-a-locales.md`: por qué el código de un kernel no toma direcciones de variables locales.
- `docs/v2-dos-pixeles.md`: por qué V2 escribe un píxel por acceso y no dos.

## Uso en el host

```sh
make                    # todo en build/
make test               # V0 == V1 == V2 en las escenas de tests/
make run                # todos los ejemplos con las tres versiones
make run-shapes V=2     # un ejemplo con una versión concreta
make sdl-bounce         # en una ventana SDL (F1/F2/F3: versión)
make sim-bounce V=2     # en el simulador de MiniGPU (V=0, 1 o 2; por defecto 0)
make check-minigpu V=2  # MiniGPU frente al host, píxel a píxel
```

En el host, `mgl_gpu_render` ejecuta las ocho lanes una tras otra en la CPU: es una emulación funcional, no SIMT. En MiniGPU lanza `KERNEL(mgl_render)` en un warp de la GPU.

El simulador es Python y va lento (unos segundos por frame). Si PyPy está instalado (`uv python install pypy@3.11`), el Makefile lo usa para el simulador, que va de 4 a 10 veces más rápido; la ventana se sigue abriendo con CPython. `SIM_PYTHON=python3` vuelve a CPython.

## Alcance
V0, V1 y V2 están validados en MiniGPU: compilados con LCC/mini-opt (`build-c`) y ejecutados en el simulador de CPU + GPU dan los mismos píxeles que en el host (`make check-minigpu V=0|1|2`). En instrucciones, la GPU de V2 dibuja con menos que la CPU de V0, pero va a 25 MHz y la CPU a 80, así que en tiempo V2 aún es más lenta (ver [docs/validacion.md](docs/validacion.md)). La FPGA está pendiente. La conversión `mg_` → `mgl_` es mecánica; se debe revisar cualquier código externo que llame a la API antigua.
