Quiero diseñar el uso de una GPU sencilla como **motor DMA/blitter programable**, controlado desde una CPU mediante una pequeña librería en C.

La idea principal es que el programador de CPU vea operaciones de alto nivel como `memcpy`, `memset`, blits, fills y conversiones, sin conocer detalles internos de la GPU como número de warps, distribución del trabajo o scheduling interno.

## Contexto de la GPU

La GPU ejecuta warps SIMD/SIMT y dispone de:

- varios warps concurrentes;
- `lane_id` dentro de cada warp;
- un `logical_warp_id` independiente del slot físico donde se ejecute el warp;
- loads y stores;
- coalescer de memoria;
- capacidad de ocultar latencia ejecutando otros warps mientras uno espera memoria;
- dispatcher/scheduler de warps;
- posibilidad de notificar a la CPU mediante IRQ y/o una cola de completions.

La intención es reutilizar esta infraestructura para que la GPU actúe también como DMA engine, evitando inicialmente construir un DMA o blitter hardware separado.

El patrón general para repartir una operación lineal entre N warps puede ser algo parecido a:

```c
offset = logical_warp_id * bytes_per_warp;

while (offset < size) {
    process(offset + lane_id * bytes_per_lane);
    offset += num_warps * bytes_per_warp;
}
```

El número de warps es un detalle interno. La aplicación C que pide una copia no debería conocerlo.

Por ejemplo:

```c
gpu_memcpy(dst, src, size);
```

podría internamente ejecutarse con 1, 2, 4, 8 o N warps según tamaño, disponibilidad de recursos o resultados de benchmarking.

## Kernels de sistema

Quiero estudiar una pequeña colección de kernels GPU que funcionen como servicios del sistema.

### 1. MEMCPY

```c
gpu_memcpy(dst, src, size);
```

Copia lineal de memoria.

Cada lane realiza loads/stores sobre posiciones contiguas y el coalescer intenta convertirlos en accesos eficientes a memoria.

Debe poder ejecutarse mediante varios warps.

### 2. MEMSET / CLEAR

```c
gpu_memset(dst, value, size);
```

Rellena memoria con un valor.

Es especialmente interesante porque solo genera tráfico de escritura: el valor puede mantenerse en registros y escribirse repetidamente.

Puede utilizarse para:

- limpiar buffers;
- limpiar framebuffer;
- limpiar depth buffers;
- inicializar memoria;
- generar patrones sencillos.

### 3. FILL_2D

```c
gpu_fill_rect(
    dst,
    dst_pitch,
    x,
    y,
    width,
    height,
    value
);
```

Equivalente 2D de un `memset`.

`pitch` es la distancia, normalmente expresada en bytes, entre el comienzo de una fila y el comienzo de la siguiente.

Por ejemplo:

```c
addr = base + y * pitch + x * bytes_per_pixel;
```

`width` indica cuánto procesar dentro de cada fila, mientras que `pitch` indica cuánto avanzar para llegar a la siguiente.

### 4. BLIT_2D

```c
gpu_blit(
    dst,
    dst_pitch,
    src,
    src_pitch,
    width,
    height
);
```

Copia un rectángulo entre dos superficies.

Los pitches de origen y destino pueden ser distintos.

Esto permite copiar regiones de framebuffers, texturas u otros buffers sin exigir que estén almacenados de forma compacta.

### 5. COPY + CONVERT

Kernel que lee datos en un formato y los escribe en otro.

Ejemplos:

- RGB8888 -> RGB565;
- RGB565 -> RGB8888;
- planar -> interleaved;
- interleaved -> planar;
- representación lineal -> alguna disposición tiled;
- conversión de formato durante un upload al framebuffer.

La ventaja importante es evitar:

```text
read -> transform -> write
read -> copy -> write
```

y sustituirlo por una sola pasada:

```text
LOAD
transformación en registros
STORE
```

reduciendo tráfico externo de memoria.

## Posibles extensiones posteriores

No necesariamente deben implementarse inicialmente, pero estudiar cómo encajarían:

```c
gpu_blit_colorkey(...);
gpu_blit_masked(...);
gpu_blend(...);
gpu_fill_pattern(...);
gpu_gather(...);
gpu_scatter(...);
```

Por ejemplo, un blit con color key podría hacer conceptualmente:

```c
pixel = load(src);

if (pixel != transparent_color)
    store(dst, pixel);
```

La filosofía es que operaciones que tradicionalmente requerirían añadir funciones a un blitter hardware puedan implementarse simplemente como nuevos kernels GPU.

Una buena regla para decidir si una operación pertenece aquí es:

> Una operación es buena candidata si consiste principalmente en recorrer una cantidad grande de memoria de forma relativamente regular, haciendo poca computación por elemento.

## API de CPU en C

Quiero que la API tenga tanto operaciones asíncronas como bloqueantes.

El mecanismo fundamental debería ser el asíncrono.

Por ejemplo:

```c
typedef uint16_t gpu_job_t;

gpu_job_t gpu_memcpy_async(
    void *dst,
    const void *src,
    size_t size
);

bool gpu_done(gpu_job_t job);

void gpu_wait(gpu_job_t job);
```

La versión bloqueante puede construirse encima:

```c
void gpu_memcpy(void *dst, const void *src, size_t size)
{
    gpu_job_t job = gpu_memcpy_async(dst, src, size);
    gpu_wait(job);
}
```

Aplicar el mismo patrón a los otros servicios:

```c
gpu_job_t gpu_memset_async(...);
void      gpu_memset(...);

gpu_job_t gpu_blit_async(...);
void      gpu_blit(...);

gpu_job_t gpu_fill_rect_async(...);
void      gpu_fill_rect(...);
```

## Job descriptor

La CPU debería enviar a la GPU un descriptor de trabajo.

Estudiar una estructura aproximadamente así:

```c
struct gpu_job_desc {
    uint16_t job_id;
    uint16_t operation;

    uintptr_t src;
    uintptr_t dst;

    uint32_t size;

    uint32_t src_pitch;
    uint32_t dst_pitch;

    uint32_t width;
    uint32_t height;

    uint32_t value;

    /* otros parámetros específicos */
};
```

No es necesario que esta sea exactamente la representación final. Quiero analizar qué campos deberían ser comunes, cuáles específicos por operación y si conviene utilizar descriptores diferentes por kernel.

## Separación entre job y warps

Este punto es importante.

La CPU nunca debería esperar o gestionar warps individuales.

Para la CPU existe:

```text
JOB #37
```

Dentro de la GPU ese job puede convertirse en:

```text
JOB #37
   |
   +-- logical warp 0
   +-- logical warp 1
   +-- logical warp 2
   +-- logical warp 3
   ...
```

La GPU mantiene internamente el número de warps pendientes.

Conceptualmente:

```c
job->warps_pending = N;
```

Cada warp termina y decrementa ese estado.

Cuando todos han terminado:

```text
warps_pending == 0
```

se genera una única completion:

```text
JOB_DONE(job_id)
```

No quiero una IRQ por warp.

Quiero una completion por operación lógica solicitada desde la CPU.

## Completion queue e IRQ

Estudiar un mecanismo donde la GPU tenga una pequeña FIFO de completions.

Por ejemplo:

```c
struct gpu_completion {
    uint16_t job_id;
    uint16_t status;
};
```

Cuando termina un job:

```text
GPU
 |
 +-> completion FIFO
 |
 +-> IRQ CPU
```

La IRQ informa a la CPU de que existen completions pendientes.

El handler consume una o varias entradas de la FIFO.

Esto permite además agrupar varias terminaciones bajo una misma IRQ si varios jobs terminan antes de que la CPU atienda la interrupción.

Analizar:

- profundidad razonable de la FIFO;
- generación y reconocimiento de IRQ;
- manejo de overflow;
- reutilización segura de `job_id`;
- representación de errores.

## Uso bare metal

La API no debe depender obligatoriamente de tener sistema operativo.

En bare metal:

```c
gpu_job_t job = gpu_memcpy_async(...);

while (!gpu_done(job)) {
    ;
}
```

También podría existir una variante que utilice `WFI` si la CPU dispone de ella:

```c
while (!gpu_done(job))
    cpu_wait_for_interrupt();
```

En ese caso no existe otra tarea que ejecutar; simplemente se evita hacer polling activo si el hardware lo permite.

## Integración con un sistema operativo

Si existe un pequeño SO con scheduler, `gpu_wait()` puede bloquear solamente la tarea actual.

Por ejemplo:

```c
void gpu_wait(gpu_job_t job)
{
    block_current_task(EVENT_GPU_JOB, job);
    schedule();
}
```

La tarea pasa conceptualmente:

```text
RUNNING
   |
   | gpu_wait(job)
   v
WAIT_GPU
```

Mientras la GPU trabaja, la CPU puede ejecutar otras tareas.

Cuando llega:

```text
JOB_DONE(job)
```

el handler despierta las tareas correspondientes:

```text
WAIT_GPU -> READY
```

Cuando el scheduler vuelva a seleccionar esa tarea, su ejecución continúa justo después de `gpu_wait()`.

Por tanto, desde el punto de vista del programa C:

```c
foo();

gpu_memcpy(dst, src, size);

bar();
```

parece una operación completamente síncrona.

Pero internamente podría ocurrir:

```text
Task A: foo()
Task A: submit GPU job
Task A: WAIT_GPU

CPU -> ejecuta Task B

GPU -> ejecuta memcpy

GPU -> IRQ completion

Task A -> READY

scheduler -> Task A

Task A: continúa
Task A: bar()
```

Esto proporciona un comportamiento parecido conceptualmente a un `await`, pero utilizando C convencional, interrupciones y scheduling de tareas.

## Scheduler genérico

No quiero que el scheduler conozca detalles de `memcpy` ni idealmente detalles internos de la GPU.

Sería preferible tener un mecanismo general del estilo:

```c
block_current_task(EVENT_GPU_JOB, job_id);
```

y:

```c
wake_tasks(EVENT_GPU_JOB, job_id);
```

El mismo mecanismo podría servir posteriormente para:

```text
WAIT_GPU
WAIT_SD
WAIT_UART
WAIT_TIMER
WAIT_VSYNC
```

Analizar cómo diseñar esta abstracción sin hacer innecesariamente complejo el mini SO.

## Selección CPU vs GPU

No asumir que siempre será mejor usar la GPU.

Para operaciones pequeñas, el overhead de:

```text
crear job
enviar descriptor
arrancar GPU
despachar warp
ejecutar
completion
IRQ/wait
```

puede superar el coste de ejecutar directamente un bucle en CPU.

Podría existir una política interna:

```c
void memcpy_fast(void *dst, const void *src, size_t size)
{
    if (size < GPU_COPY_THRESHOLD)
        cpu_memcpy(dst, src, size);
    else
        gpu_memcpy(dst, src, size);
}
```

`GPU_COPY_THRESHOLD` debería obtenerse mediante mediciones reales sobre FPGA, no decidirse únicamente de forma teórica.

Proponer un benchmark con tamaños como:

```text
32 B
64 B
128 B
256 B
1 KB
4 KB
16 KB
64 KB
256 KB
1 MB
```

comparando:

```text
CPU
GPU 1 warp
GPU 2 warps
GPU 4 warps
GPU 8 warps
GPU 16 warps
```

Quiero encontrar:

- a partir de qué tamaño merece la pena utilizar la GPU;
- cuántos warps hacen falta para ocultar la latencia;
- cuándo se satura el memory fabric/SDRAM;
- si más warps dejan de aumentar rendimiento;
- diferencias entre `memcpy` y `memset`;
- MB/s efectivos;
- ocupación de la CPU;
- latencia de submit/completion.

## Objetivo arquitectónico

La CPU debe percibir algo parecido a un DMA/blitter:

```text
CPU
 |
 | submit job
 v
GPU DMA service
 |
 v
memory
```

Pero internamente no existe necesariamente un DMA dedicado.

Existe:

```text
CPU
 |
 | descriptor
 v
GPU dispatcher
 |
 +-- warp
 +-- warp
 +-- warp
 |
 v
LSU / coalescer
 |
 v
memory fabric
 |
 v
SDRAM
```

Es decir:

> El DMA/blitter es realmente una colección de pequeños kernels GPU de sistema.

Quiero desarrollar esta idea manteniendo una separación clara entre:

1. **API pública en C**
2. **runtime/driver de CPU**
3. **integración opcional con el scheduler del SO**
4. **protocolo CPU-GPU de jobs y completions**
5. **dispatcher GPU**
6. **kernels de sistema**
7. **warps físicos y lógicos**
8. **LSU/coalescer/memory fabric**

Analiza la arquitectura paso a paso.

En particular, propón:

- API C concreta;
- estructura de los jobs;
- cola de comandos CPU -> GPU;
- cola de completions GPU -> CPU;
- estados de un job;
- cómo asignar y reutilizar `job_id`;
- cómo asociar un job con N warps;
- cómo detectar el final de todos sus warps;
- qué debe hacer la IRQ;
- cómo implementar `gpu_done()`;
- cómo implementar `gpu_wait()` en bare metal;
- cómo implementar `gpu_wait()` con scheduler;
- qué kernels iniciales merece la pena tener;
- qué parámetros necesita cada kernel;
- cuáles deberían estar precargados permanentemente;
- cómo elegir el número de warps;
- cómo medir el punto óptimo;
- qué partes conviene mantener en software y cuáles requieren soporte hardware mínimo.

Prioriza una arquitectura pequeña, comprensible y viable para FPGA frente a soluciones sofisticadas propias de GPUs modernas.