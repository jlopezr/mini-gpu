# Diseño: la GPU como motor DMA/blitter

> Borrador v1, 2026-10-06. Parte de [`integracion cpu-gpu.md`](../examples/integracion%20cpu-gpu.md) y recoge las decisiones y necesidades de [`necesidades-detectadas.md`](../examples/necesidades-detectadas.md). Supone conocidos la ISA y [`mmio.md`](../../1.isa/mmio.md); las referencias `§n` son de este último salvo que se diga otra cosa.

## 1. Objetivo y alcance

Un programa de CPU pide operaciones de memoria de alto nivel (copiar, rellenar, blit, convertir formato) y las ejecuta la GPU existente con unos pocos **kernels de sistema**. No hay DMA ni blitter dedicado: el DMA es una colección de kernels.

Cuatro principios guían todo lo que sigue:

1. **Hardware mínimo.** Se usa lo que ya hay (`WARP_START`, `WARP_LIVE`, `WARP_DONE`) más dos registros por warp y cuatro instrucciones nuevas, una de ellas opcional (§9).
2. **Software primero.** La cola de trabajos, el despachador, las completions y los errores los gestiona el runtime de la CPU. La GPU no tiene command processor (§14.1).
3. **La API no revela warps, lanes ni scheduling.** El número de warps de un job es un detalle interno.
4. **La GPU no siempre gana.** La ruta CPU forma parte del diseño, y el umbral se mide.

**Dentro de la v1:** `memcpy`, `memset`, `fill_rect`, `blit`, conversión de formato; API síncrona y asíncrona; sondeo (*polling*); un job a la vez, en orden; errores recuperables por software.

**Fuera de la v1** (§10): interrupciones, jobs concurrentes, integración con un SO, warps residentes, errores por warp, atómicas.

## 2. Arquitectura

```text
aplicación
   │  gpu_memcpy(), gpu_blit(), …                      API pública (§3)
runtime de CPU (librería C)                            cola, despachador, recogida, errores,
   │                                                   política CPU/GPU
   ├── RAM: bloque de argumentos del job               protocolo (§4)
   └── MMIO: GPU WARPS, GPU CORE (WARP_START/DONE)
GPU: warps ejecutando kernels de sistema               kernels (§7), residentes en la imagen
   │  LOAD / STORE
LSU / coalescer ── fabric ── SDRAM
```

| Capa | Vive en | Responsabilidad |
|---|---|---|
| API pública | librería C | operaciones, tipos, estado de un job |
| Runtime | librería C en la CPU | validar, trocear, cola, despachar, recoger `WARP_DONE`, gestionar errores, decidir CPU o GPU |
| Protocolo CPU↔GPU | RAM y MMIO | bloque de argumentos, descriptores de warp, `WARP_START`/`WARP_DONE` |
| Kernels de sistema | ensamblador de GPU | el trabajo en sí |
| Warps | GPU | físicos (slots 0 a `NUM_WARPS-1`) y lógicos (`LOGICAL_WARP_ID`) |
| LSU, coalescer, fabric | hardware | accesos a memoria; el diseño no los toca |

**El despachador no es hardware: es el runtime.** Es el segundo modelo de uso de §14.1: una cola en RAM y reposición de warps según se liberan ranuras.

**Qué necesita hardware y qué no:**

| Software, ya posible | Hardware que falta (§9) |
|---|---|
| API, runtime, cola de jobs, completions, mapa job→warps, errores, umbral CPU/GPU | `LOGICAL_WARP_ID[n]` y `WARP_ARG[n]` por warp |
| Lanzar y recoger con `WARP_START`/`WARP_DONE` | `GETLANE`, `GETLWARP`, `GETARG` (y `GETWARP`) |
| | Accesos de 8 y 16 bits en el RTL de la GPU (solo para quitar los bordes, §7) |

## 3. API pública en C

```c
typedef unsigned short gpu_job_t;        /* 0 = inválido */
#define GPU_JOB_INVALID 0

enum {
    GPU_OK = 0,
    GPU_ERR_ARGS,       /* rechazado al validar; no llegó a la GPU */
    GPU_ERR_FAULT,      /* fallo de la GPU durante el job */
    GPU_ERR_TIMEOUT,    /* el job no terminó en GPU_TIMEOUT_POLLS sondeos */
    GPU_STALE           /* el id es de un job muy antiguo: ya no hay estado */
};

int gpu_init(void);                      /* 1 si hay GPU utilizable, 0 si no */

/* Asíncronas: encolan y devuelven enseguida. 0 si los argumentos no valen. */
gpu_job_t gpu_memcpy_async   (void *dst, const void *src, unsigned size);
gpu_job_t gpu_memset_async   (void *dst, unsigned char value, unsigned size);
gpu_job_t gpu_fill_rect_async(void *dst, unsigned dst_pitch, unsigned x, unsigned y,
                              unsigned w, unsigned h, unsigned value, unsigned bpp);
gpu_job_t gpu_blit_async     (void *dst, unsigned dst_pitch, const void *src,
                              unsigned src_pitch, unsigned w, unsigned h, unsigned bpp);
gpu_job_t gpu_convert_async  (void *dst, unsigned dst_fmt, const void *src,
                              unsigned src_fmt, unsigned npixels);

/* Estado de un job. */
int  gpu_done(gpu_job_t job);            /* 1 si terminó, bien o mal; no bloquea */
int  gpu_status(gpu_job_t job);          /* GPU_OK o un error; válido tras gpu_done */
void gpu_poll(void);                     /* hace avanzar el runtime (ver abajo) */
void gpu_wait(gpu_job_t job);            /* bloquea hasta gpu_done */

/* Bloqueantes: aplican el umbral CPU/GPU (§8). Devuelven el estado. */
int gpu_memcpy(void *dst, const void *src, unsigned size);
int gpu_memset(void *dst, unsigned char value, unsigned size);
int gpu_fill_rect(/* como la asíncrona */);
int gpu_blit(/* como la asíncrona */);
```

`gpu_fill_rect` escribe en `dst + (y + fila) * dst_pitch + x * bpp`. `bpp` es 2 o 4. Los formatos de `gpu_convert` se toman de [`formatos-graficos.md`](../../15.isa-v2/formatos-graficos.md) (carpeta 15), que este diseño no define.

Semántica que conviene dejar fijada:

- **Los buffers son de la GPU desde el envío hasta `gpu_done`.** La aplicación no los lee ni los escribe entre medias.
- **El orden se conserva.** Los jobs se ejecutan en el orden de envío (§5). Una operación pequeña que el umbral manda a la CPU **espera antes a que la cola se vacíe**, para que nunca adelante a un job anterior que toque los mismos buffers.
- **El avance es cooperativo.** Sin interrupciones, el runtime solo progresa cuando alguien lo llama: `gpu_poll`, `gpu_done`, `gpu_wait` o un nuevo envío. Un programa que envíe un job y se ponga a calcular **no lanzará el siguiente de la cola** hasta que vuelva a la librería. Un bucle largo debe llamar a `gpu_poll()` de vez en cuando. Es una consecuencia directa de no tener IRQ (N1).
- **Sin GPU, la API funciona.** `gpu_init` comprueba `MAGIC`, `MMIO_VERSION` y el bit 10 de `DEVICES` (§5.6). Si no hay GPU, todas las operaciones usan la ruta CPU: el mismo binario corre en una placa sin GPU.
- **Los ids llevan generación.** `gpu_job_t` son 16 bits: los 4 bajos son el slot de la tabla de jobs (16 slots) y los 12 altos un contador de generación. La generación empieza en 1, para que ningún id válido valga 0. Un id que ya no corresponde a su slot es obsoleto: `gpu_done` lo da por terminado y `gpu_status` devuelve `GPU_STALE`. Así un `job_id` se puede reutilizar sin confundir un job nuevo con uno viejo.

## 4. Protocolo CPU↔GPU

### 4.1 Bloque de argumentos

Es lo que lee el kernel. Hay **uno por job**, en RAM, compartido por todos sus warps:

```c
struct gpu_args {
    unsigned nwarps;     /* warps del job: el paso del reparto (§4.3) */
    unsigned nlanes;     /* lanes por warp, de GPU_CAPS */
    unsigned p[6];       /* parámetros del kernel (§7) */
};                       /* 32 bytes, alineado a 4 */
```

El kernel no conoce el hardware: `nwarps` y `nlanes` vienen del bloque. El runtime puede darle a un job 1, 2, 4 u 8 warps sin cambiar el kernel.

### 4.2 Qué escribe la CPU por warp

Para cada warp `w` del job (`0 ≤ w < nwarps`), en el descriptor del warp físico `p` (en la v1, `p = w`):

| Registro (GPU WARPS) | Valor | Para qué |
|---|---|---|
| `PC` | entrada del kernel | |
| `ACTIVE` | todas las lanes (`(1 << nlanes) - 1`) | no puede ser 0: `WARP_START` lo rechaza |
| `WORKGROUP_ID` | `job_id` | convención: un `BAR` solo sincroniza los warps de su job |
| `LOGICAL_WARP_ID` (**nuevo**) | `w` | qué warp lógico es; visible por MMIO para depurar y trazar |
| `WARP_ARG` (**nuevo**) | dirección del `gpu_args` | la entrada del kernel |

`LOGICAL_WARP_ID` y `WARP_ARG` son dos valores distintos con dos propósitos distintos. Mantenerlos separados permite leer el id lógico en el monitor y en la traza sin interpretar un bloque de RAM.

### 4.3 Qué lee el kernel

| Instrucción (`GETID`, opcode `0x30`) | `type` | Devuelve |
|---|---:|---|
| `GETTID` | 0 | thread residente `warp * lanes + lane` (existe) |
| `GETLANE` | 1 | lane dentro del warp |
| `GETWARP` | 2 | slot de warp físico (opcional; el diseño no depende de él) |
| `GETLWARP` | 3 | `LOGICAL_WARP_ID` |
| `GETARG` | 4 | `WARP_ARG` |

`type ≥ 5` es reservado y da `ERROR_INVALID_ENCODING`. `type = 0` es el encoding actual de `GETTID`, así que los binarios existentes no cambian. No hay instrucción para leer `WORKGROUP_ID`: solo lo usa `BAR`.

### 4.4 Reparto del trabajo

Para operaciones lineales sobre `W` palabras, cada lane recorre

```text
i = lwarp * nlanes + lane            (primera palabra)
repetir mientras i < W:  procesar(i);  i += nwarps * nlanes
```

Con `lwarp = GETLWARP`, `lane = GETLANE` y `nwarps`, `nlanes` del bloque. Lanes consecutivas tocan palabras consecutivas, que es lo que el coalescer necesita. El reparto es **estático y sin coordinación**: ningún warp espera a otro, así que no hacen falta atómicas. Es suficiente porque el trabajo de estos kernels es uniforme.

Las operaciones 2D (`fill_rect`, `blit`) reparten **filas** entre warps y **palabras de la fila** entre lanes, para evitar divisiones (§7).

## 5. Ciclo de vida de un job

```text
FREE ── envío ──► QUEUED ── despacho ──► RUNNING ── recogida ──► DONE(estado) ── slot reutilizado ──► FREE
```

La cola es un anillo FIFO de slots en RAM. En la v1 hay **un solo job en ejecución**: el siguiente no empieza hasta que el anterior termina. Esto evita carreras de datos entre jobs y simplifica el asignador. Con un solo job en vuelo, los warps físicos coinciden con los lógicos (`p = w`).

### 5.1 Despacho

El runtime despacha cuando no hay job en ejecución y `GPU_STATUS` muestra `IDLE` sin `ERROR`:

1. Elegir `nwarps` (§8).
2. Hacer la cabeza y la cola desalineadas con la CPU (§7) y escribir el bloque `gpu_args` en RAM.
3. Para `w` en `0..nwarps-1`: escribir `PC`, `ACTIVE`, `WORKGROUP_ID`, `LOGICAL_WARP_ID` y `WARP_ARG` en el descriptor del warp `w`.
4. Escribir `WARP_START = (1 << nwarps) - 1` y anotar `pending = (1 << nwarps) - 1`.

Esto es el orden de §18: la CPU escribe datos y descriptores, esas escrituras son visibles, y solo entonces lanza.

**Se usa `WARP_START` y nunca `RUN`.** `RUN` arranca *todos* los descriptores con `ACTIVE ≠ 0`, y quedarían descriptores de jobs anteriores. Además, escribir el descriptor de un warp vivo es error, así que el runtime solo toca warps con su bit de `WARP_LIVE` a cero.

### 5.2 Recogida

```c
void gpu_poll(void)
{
    if (!running) { start_next(); return; }

    status = GPU_STATUS;
    done   = WARP_DONE;
    if (done) {
        WARP_DONE = done;             /* W1C de exactamente lo leído */
        running->pending &= ~done;
    }
    if (status & ERROR)
        fail(running, GPU_ERR_FAULT); /* §6 */
    else if (running->pending == 0)
        complete(running, GPU_OK);    /* y despacha el siguiente */
    else if (++running->polls > GPU_TIMEOUT_POLLS)
        fail(running, GPU_ERR_TIMEOUT);
}
```

**Carrera con `WARP_DONE`, y por qué el orden importa.** `WARP_START` limpia automáticamente el bit del warp (§14.1). Si el runtime reutilizara una ranura antes de leer su bit, **perdería la completion del job anterior**. El orden obligatorio es: leer `WARP_DONE`; completar los jobs de esos bits; limpiarlos con W1C escribiendo **exactamente el valor leído** (nunca `0xFFFFFFFF`, que borraría un bit activado entre la lectura y la escritura); y solo entonces asignar esas ranuras. En la v1 se cumple por construcción, porque no se despacha hasta que `pending` llega a 0, pero el orden se mantiene para que la extensión concurrente (§10) no lo rompa.

### 5.3 Esperar

En bare metal, `gpu_wait` es un bucle de `gpu_poll` hasta que `gpu_done` sea verdadero. Una variante con `WFI` necesita una interrupción (N1). `gpu_wait` mira también el error: si no lo hiciera, una GPU con un fallo dejaría a la CPU esperando para siempre, porque los warps que no acaban nunca ponen su bit en `WARP_DONE`.

## 6. Errores

Un fallo de un warp **para toda la GPU** (hoy, también en el RTL). Queda `GPU_STATUS.ERROR` y el primero en `FIRST_ERROR` / `FIRST_ERROR_PC`; solo `GPU_CONTROL.RESET` la recupera.

| Origen | Cómo se trata |
|---|---|
| Argumentos inválidos (rango, alineamiento, desbordes) | **Se evita:** el runtime valida antes de enviar. El rango completo se comprueba contra `SYSTEM.MEM_SIZE`, incluido `dst + size` y los productos `pitch * h`. Devuelve `GPU_JOB_INVALID` o `GPU_ERR_ARGS`. |
| Fallo de la GPU durante un job | `fail()`: lee `FIRST_ERROR`, `FIRST_ERROR_PC` y `GPU_STATUS`; lee `WARP_DONE` **antes** del `RESET`; hace `GPU_CONTROL.RESET`; completa el job con `GPU_ERR_FAULT` y guarda el código y el PC para diagnóstico. Los demás jobs de la cola siguen su curso. |
| Kernel que no termina | Un límite de sondeos por job. Al saltar: `GPU_CONTROL.HALT`, después `RESET`, y el job queda `GPU_ERR_TIMEOUT`. |

`RESET` conserva los descriptores y también conservará `LOGICAL_WARP_ID` y `WARP_ARG` (N5). Lo que no se debe suponer es qué pasa con `WARP_DONE` al hacer `RESET`, y por eso se lee antes.

**En la v1, el job que falla es siempre el único en vuelo**, así que la atribución es trivial. `FIRST_ERROR` indica además qué warp y qué lane fueron, para depurar. La política de reintento de otros jobs (reenviar los inocentes, que es seguro porque los kernels son idempotentes mientras `src` y `dst` no se solapan) solo se plantea cuando haya jobs concurrentes (§10). Un job culpable no se reintenta.

**Limitación que hay que tener presente:** un puntero equivocado pero **dentro de la RAM no produce ningún fallo**; corrompe en silencio. La GPU no tiene protección de memoria, y la validación en la CPU es la única defensa.

La **ordenación está garantizada** por §18: un evento de finalización no se hace visible antes de que las escrituras del warp hayan alcanzado el punto de coherencia. Si algún día la CPU tuviera caché de datos, `gpu_wait` tendría que invalidarla.

## 7. Kernels de sistema

Los kernels son ensamblador de GPU escrito con la ISA de `11` (con accesos de 8 y 16 bits, N6), residentes en la misma imagen que el runtime (se incluyen con `.include`). Las etiquetas de entrada las resuelve el ensamblador; el runtime las usa para rellenar `PC`. No hay carga aparte ni direcciones escritas a mano.

Todos los kernels de la v1 trabajan **por palabras**. La CPU resuelve en el envío la cabeza y la cola que no son múltiplo de 4 bytes (o los píxeles de borde de un rectángulo de 16 bits). Cuando el RTL de la GPU tenga accesos pequeños (N6), esos bordes desaparecen y la CPU deja de intervenir.

| Kernel | `p[0]` … `p[5]` | Trabajo por lane |
|---|---|---|
| `MEMSET` | `dst`, `value` (byte replicado en la palabra), `nwords` | una palabra por iteración |
| `MEMCPY` | `dst`, `src`, `nwords` | una palabra por iteración |
| `FILL_RECT` | `dst` (primera fila, alineado), `pitch`, `row_words`, `rows`, `value` | filas `lwarp`, `lwarp+nwarps`, …; en cada fila, palabras `lane`, `lane+nlanes`, … |
| `BLIT` | `dst`, `dst_pitch`, `src`, `src_pitch`, `row_words`, `rows` | como `FILL_RECT`, leyendo `src` |
| `CONVERT` | `dst`, `src`, `npairs`, formato | 8888→565: lee dos píxeles y escribe una palabra. 565→8888: lee una palabra y escribe dos |

`memcpy` por palabras exige que `src` y `dst` sean congruentes módulo 4. Si no lo son, la operación va por la CPU en la v1.

Estructura de `MEMSET` (el resto es variante de este esquema):

```c
i = lwarp * nlanes + lane;              /* GETLWARP, GETLANE, args */
paso = nwarps * nlanes;
SSY fin;                                /* los lanes salen en iteraciones distintas */
while (i < nwords) { dst[i] = value; i += paso; }
fin:
EXIT;
```

La condición del bucle **diverge** en la última pasada, y un salto divergente sin `SSY` delante detiene la GPU con `ERROR_SIMT`. Los kernels 2D tienen dos bucles anidados con la misma precaución.

`CONVERT` gasta unas diez instrucciones por píxel con la ISA base, así que está en el límite de la regla "mucha memoria, poco cálculo". La capability `pack565` de `propuesta-v0.4b.md` lo abarataría. No es necesaria para empezar.

**Criterio para admitir un kernel nuevo** (colorkey, blend, patrón, gather, scatter): recorrer una cantidad grande de memoria de forma regular, con poca computación por elemento.

## 8. Selección CPU frente a GPU, y benchmark

### 8.1 Política

La versión bloqueante aplica un umbral por operación:

```c
int gpu_memcpy(void *dst, const void *src, unsigned size)
{
    if (!gpu_present || size < GPU_THRESHOLD_MEMCPY || ((unsigned)src ^ (unsigned)dst) & 3)
        return cpu_memcpy_ordered(dst, src, size);   /* espera a que la cola esté vacía */
    return gpu_wait_status(gpu_memcpy_async(dst, src, size));
}
```

Las asíncronas **siempre** van a la GPU: pedir `_async` es pedir la GPU de forma explícita.

El número de warps de un job es

```text
nwarps = min(NUM_WARPS, GPU_MAX_WARPS_PER_JOB, ceil(size / GPU_MIN_BYTES_PER_WARP))
```

Los tres umbrales (`GPU_THRESHOLD_*`, `GPU_MAX_WARPS_PER_JOB`, `GPU_MIN_BYTES_PER_WARP`) son constantes configurables, **sin valor inicial decidido**: los fija el benchmark, no la teoría.

### 8.2 Benchmark

Tamaños: 32 B, 64 B, 128 B, 256 B, 1 KB, 4 KB, 16 KB, 64 KB, 256 KB y 1 MB. Operaciones: `memcpy`, `memset`, y después `fill_rect` y `blit`. Configuraciones: **CPU, GPU con 1, 2, 4 y 8 warps.** La GPU actual tiene 8 warps físicos (`GPU_CAPS`), así que "16 warps" no es una configuración real.

Se quiere averiguar:

- a partir de qué tamaño merece la pena la GPU;
- cuántos warps hacen falta para ocultar la latencia;
- cuándo se satura el fabric o la SDRAM, y si más warps dejan de mejorar;
- diferencias entre `memcpy` y `memset`;
- MB/s efectivos, ocupación de la CPU y latencia de envío y de completion.

**Con qué se mide.** Los contadores de CPU PERFORMANCE (§13.2, con `PERF_CTRL` para congelar) dan ciclos. El reloj de pared necesita el TIMER, que está sin definir. Hasta donde he visto, **no hay en el repo un prototipo RTL con CPU y GPU a la vez**, así que hoy el benchmark real no se puede ejecutar. El simulador de la carpeta 32 es funcional: cuenta instrucciones de CPU y de warp, no ciclos, y no modela la contienda de memoria. Sirve para comprobar que los kernels y el protocolo son correctos y para obtener una medida de coste en instrucciones, nada más.

## 9. Cambios necesarios

| # | Cambio | Estado |
|---|---|---|
| N1 | Interrupciones: IRQ con `WARP_DONE != 0` y espera tipo `WFI`. Requiere definir el INTC. | pospuesto |
| N3 | `LOGICAL_WARP_ID[n]` en `+0x200` y `WARP_ARG[n]` en `+0x280` de GPU WARPS (§14.2, regla §1.4). Lectura y escritura; error si el warp está vivo. | contrato y simulador de `32` hechos; RTL pendiente |
| N4 | `GETID` con `type` 1 a 4: `GETLANE`, `GETWARP`, `GETLWARP`, `GETARG`. Renombra `GETWID`/`warp_user_id` de las propuestas v0.2 a v0.4b. | ensamblador, `isa.md` y simuladores de `11` y `25` hechos; faltan `NEW-ASSM` y el RTL |
| N5 | `RESET` conserva `LOGICAL_WARP_ID` y `WARP_ARG`; solo el reset físico los pone a cero. | contrato y simulador de `32` hechos; RTL pendiente |
| N6 | Accesos de 8 y 16 bits en la GPU. Simulador de `11` hecho; **RTL de la 29 pendiente**, con su LSU y coalescer. | simulador hecho |
| N7 | Errores por warp, en lugar de un fallo que para toda la GPU. Delicado, no caro en área; efecto en Fmax sin medir. | pospuesto |
| N8 | `ATOMADD`, `ATOMCAS` y `FENCE`. La v1 no los necesita. | pospuesto |

**Trabajo en simulador y ensamblador, hecho:**

1. `1.isa/mini_asm.py`: mnemónicos `GETLANE`, `GETWARP`, `GETLWARP` y `GETARG` (`GETID_TYPES`).
2. `11.gpu-sim-func`: decodificación de `GETID` con `type` 0 a 4, estado `logical_warp_id` y `arg` por warp, campos en `--config`, nombres en `gpu_trace.py`. También los accesos de 8 y 16 bits (N6).
3. `32.cpu-gpu-func-sim`: los dos arrays en `GpuWarpsDevice`, copiados al warp al lanzar, con `RESET` que los conserva.
4. `1.isa/mmio_map.vh` y los ficheros generados (`tools/mmio_map.py`, `x.tests/inc/mmio.inc`), `mmio.md` §14.2 y `isa.md`.
5. `25.gpu-sim-cycle-uarch`: `GETID` con `type` 0 a 4, con el mismo diferencial contra `11`.
6. `x.tests`: la capability `gpu_ids` (`tools/capabilities.json`, sin `file`: solo los simuladores), `logical_warp_id` y `arg` en `warps.json` (el runner exige declararla) y el caso `cases-gpu/extensions/gpu-ids/getid-family`.
7. `examples/dma/`: el arnés mínimo en ensamblador (ver abajo).

**El arnés mínimo** (`examples/dma/dma.asm`, con `gpu_runtime.inc` y `gpu_kernels.inc` incluidos en una sola imagen) implementa el protocolo de §4 a §6 con un job en vuelo y por polling: validar, escribir el bloque de argumentos y los cinco campos por warp, `WARP_START`, sondear con W1C de lo leído, y en el error o el timeout leer `FIRST_ERROR` y `WARP_DONE` antes de `RESET`. `gpu_run` es la rutina de CPU; `gpu_k_memset` y `gpu_k_memcpy` los kernels. Cinco jobs lo ejercitan: memset y memcpy con 100 palabras (la última pasada es parcial y las lanes divergen), un fallo de memoria, un kernel que no termina y la recuperación posterior. Lo comprueba `DmaHarnessTest`. Lo que **no** hace todavía: cola de jobs, ids con generación, selección CPU/GPU, cabeza y cola desalineadas, ni los kernels 2D.

**Pendiente, sin bloquear el resto:**

- El ensamblador de `1.isa/NEW-ASSM`, que tiene su propia tabla de instrucciones: hay que decidir si es el vigente.
- El RTL de la GPU: `GETID`, los dos arrays, y los accesos de 8 y 16 bits.
- El runtime en C (cola, ids con generación, política CPU/GPU, kernels 2D), sobre el protocolo que ya valida el arnés. No hay linker: el compilador genera un `.asm` y el runtime y los kernels se incluyen con `.include`, como aquí.
- Re-ejecutar las familias `programs` y `demos` de `gpusim` tras el cambio de `GETID` (no se han repetido).

## 10. Extensiones previstas

- **Jobs concurrentes.** Un asignador de ranuras sobre `~WARP_LIVE` y dependencias explícitas (`gpu_fence()` o un campo "depende de"). Obliga a razonar sobre las carreras de datos entre jobs. Aquí entra la política de reintento de los jobs inocentes tras un fallo.
- **Interrupciones** (N1). Una IRQ hace que el runtime avance sin depender de que la aplicación sondee. La API ya tiene el punto de enganche: `gpu_wait` llama a un `wait_hook` (por defecto un bucle) y `gpu_poll` llama a un `complete_hook(job, estado)` cuando un job acaba. El INTC no se define aquí.
- **Integración con un SO con scheduler.** Con los dos hooks, `gpu_wait` bloquea solo la tarea actual (`block_current_task(EVENT_GPU_JOB, job)`) y el `complete_hook` la despierta (`wake_tasks(EVENT_GPU_JOB, job)`). El scheduler no conoce `memcpy` ni los detalles de la GPU. Sin IRQ, el *tick* o el bucle ocioso del scheduler debe llamar a `gpu_poll()`. El mismo mecanismo serviría para `WAIT_SD`, `WAIT_UART`, `WAIT_TIMER` y `WAIT_VSYNC`.
- **Warps residentes.** Kernels que se quedan en bucle leyendo un buzón en RAM, para que la CPU no toque MMIO por cada job. Exigen poder ordenar escrituras (un `FENCE`, o `BAR` en un workgroup de un solo warp) y gastan ancho de banda sondeando.
- **Reparto dinámico** de trozos con `ATOMADD`, si algún kernel tiene trabajo desigual (N8).
- **Errores por warp** (N7), que cambia también la política de errores de §6.

## Referencias

- [`mmio.md`](../../1.isa/mmio.md): §5.6 (descubrimiento), §13 y §14 (CPU y GPU), §15 (visibilidad por master), §18 (orden entre CPU y GPU).
- [`atomics.md`](../../1.isa/atomics.md), [`propuesta-v0.4b.md`](../../1.isa/propuesta-v0.4b.md): atómicas, `FENCE`, `GETID`.
- [`README.md`](../README.md) de esta carpeta: el simulador CPU+GPU sobre el que se valida el diseño.
