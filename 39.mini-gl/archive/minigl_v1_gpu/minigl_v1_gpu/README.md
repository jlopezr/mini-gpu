# MiniGL V1 — renderer SIMT en C89 (prototipo funcional)

Extiende el código real de V0 (incluido en este paquete). El renderer GPU se encuentra en `gpu_renderer.c` y su entrada es `mg_gpu_render(const mg_gpu_job_t *)`. La aplicación usa la misma API Processing y el mismo command buffer de V0 diferida (versión 1, comandos `CLEAR` de 16 B y `BATCH` de 40 B, un descriptor por batch).

## Qué está implementado

- `CLEAR`, `POINT`, `LINE`, `RECT`, `CIRCLE`, `TRIANGLE`, `IMAGE` RGB565 opaco.
- Relleno, contorno, `strokeWeight`, clipping y orden de comandos, reproduciendo los algoritmos de V0.
- **Un warp de ocho lanes**. Cada lane posee las columnas cuyo `x & 7` coincide con `getlane()`. No hay escrituras concurrentes al mismo píxel entre lanes; el orden entre primitivas se conserva siempre que el warp complete/reconverja cada comando antes del siguiente.
- Un intérprete de comandos en C89. Los datos del command buffer son little-endian y se decodifican por bytes, sin depender de la alineación de los punteros.
- Tabla de descriptores de sprites `mg_gpu_sprite_t`, indexada por el mismo handle de V0. En la GPU real, tanto la tabla como los píxeles deben residir en memoria accesible por GPU.
- Validador del buffer antes de dibujar, para no dibujar un prefijo de comandos corruptos.

## Compilación de prueba en host

```sh
gcc -std=c89 -pedantic -Wall -Wextra -O2 -DMG_GPU_HOST_TEST \
  minigl.c processing.c raster.c gpu_renderer.c gpu_host.c test_gpu.c -o test_gpu
./test_gpu
```

La prueba compara **V0 directa, V0 diferida y V1 host** píxel a píxel. El adaptador host (`gpu_host.c`) procesa cada comando para las ocho lanes antes de pasar al siguiente: esto simula la distribución de trabajo y el orden, **no** la ejecución SIMT real, los ciclos, la divergencia, ni el controlador SDRAM.

## Integración en MiniGPU

Compilar `gpu_renderer.c` **sin** `MG_GPU_HOST_TEST`, con LCC y mini-opt. `getlane()` es el intrínseco ya soportado por mini-opt; aquí se declara `extern int getlane(void);` para que LCC emita su llamada y mini-opt la reemplace. El punto de entrada de shader es `mg_gpu_render`; el código de arranque/dispatcher debe pasarle el puntero a `mg_gpu_job_t` a todas las lanes y arrancar un único warp de ocho lanes. No se incluye todavía el código de lanzamiento de warp porque no está fijada aquí su ABI ni la ubicación de los parámetros.

El programa de CPU prepara en SDRAM:

1. El command buffer V0 completo, con `used_bytes` en la cabecera.
2. El framebuffer de destino y sus dimensiones/stride (en píxeles).
3. La tabla de sprites (para comandos `IMAGE`) y sus datos RGB565.
4. Una estructura `mg_gpu_job_t` con punteros válidos **en el espacio de direcciones de MiniGPU**, no punteros del proceso host.

**Importante:** `mg_gpu_sprites_from_v0()` solo convierte los handles a descriptores; no copia los píxeles a SDRAM ni convierte punteros host en direcciones GPU. La tabla se debe construir con direcciones compartidas reales. No ejecutar `mg_gpu_sprites_from_v0` en el shader; es una ayuda del lado CPU.

## Límites y trabajo pendiente

- No está verificado con el compilador LCC, mini-opt, simulador MiniGPU ni FPGA. Es una **implementación C89 funcional con test de host**, no un binario GPU validado.
- El ABI de `mg_gpu_job_t` se basa en punteros C; para compatibilidad entre CPU y GPU se requiere el mismo layout de 32 bits y alineación, o definir una versión de parámetros serializada de 32 bits.
- La asignación de columnas hace que segmentos y contornos repitan cálculo en las ocho lanes (se filtra la escritura en `put`). Es una elección de corrección para V1, no una optimización de rendimiento.
- Las operaciones de círculo y triángulo utilizan multiplicaciones `long`; en MiniISA de 32 bits hay que limitar rangos para evitar overflow, tal como sucede con V0. El test de host no valida esos límites.
- `validate()` recorre todo el command buffer en cada lane; es redundante, pero evita requerir comunicación entre lanes. Podrá trasladarse al lado CPU una vez fijado el contrato de buffers.
- Se mantiene la limitación V0 de un `BATCH` por primitiva y sprites por handles. El formato de V1 no está cerrado para futuras versiones.
- Antes de utilizar múltiples warps sobre un mismo command buffer hay que diseñar un mecanismo de orden/sincronización; **V1 usa un único warp**.
