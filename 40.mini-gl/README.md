# MiniGL — paquete consolidado

Este paquete reúne **cinco ZIP históricos** (sin modificarlos), una copia de trabajo basada en V1 con nombres `mgl_` / `MGL_`, el scheduler con ejemplo y documentación de decisiones y roadmap.

## Estructura
- `src/`: versión de trabajo (V0 directa + diferida + renderer V1), con prefijos `mgl_`/`MGL_`. API Processing conserva los nombres originales.
- `scheduler/`: última entrega del scheduler con ejemplo, sin modificaciones.
- `archive/`: las cinco versiones originales extraídas y sus ZIP exactos, sin renombrar símbolos.
- `docs/arquitectura.md`: capas, primitivas, memoria, toolchain y decisiones.
- `docs/command-buffer.md`: formato actual frente a diseño propuesto.
- `docs/roadmap.md`: V0–V4 y tareas pendientes.

## Prueba de host
Desde `src/`:

```sh
gcc -std=c89 -pedantic -Wall -Wextra -O2 -DMGL_GPU_HOST_TEST \
  minigl.c processing.c raster.c gpu_renderer.c gpu_host.c test_gpu.c -o test_gpu
./test_gpu
```

El test compara V0 directa, V0 diferida y V1 host sobre la misma escena. `gpu_host.c` simula ocho lanes de forma funcional; no simula el hardware SIMT real.

## Alcance
No se incluyen ejecutables de MiniGPU ni se afirma validación con LCC/mini-opt, simulador de GPU o FPGA. La conversión `mg_` → `mgl_` es mecánica; se debe revisar cualquier código externo que llame a la API antigua.
