# 32.cpu-gpu-func-sim

Simulador funcional de **MiniCPU + MiniGPU sobre una RAM compartida**, con el
mapa y los permisos de MMIO v2 ([`../1.isa/mmio.md`](../1.isa/mmio.md)).

No reimplementa ningún núcleo: importa la `CPU` de
[`../2.cpu-sim-func`](../2.cpu-sim-func/minicpu_sim.py) y el `System` de
[`../11.gpu-sim-func`](../11.gpu-sim-func/minigpu_sim.py), y les pone en medio lo
que les falta para convivir. Un arreglo en cualquiera de los dos simuladores
llega aquí sin tocar nada.

```bash
cpugpusim examples/launch.asm
python -m unittest test_cpu_gpu_sim        # desde esta carpeta
```

[`examples/launch.asm`](examples/launch.asm) es un solo fichero con el código de
la CPU y el kernel de la GPU. Se carga entero en la dirección 0, y la CPU
lanza los warps con la etiqueta `kernel` en el descriptor: no hay ninguna
dirección escrita a mano. Los resultados también van en una etiqueta (`out`).

[`examples/dma/`](examples/dma/dma.asm) es el arnés del diseño de
[`docs/diseno-gpu-dma.md`](docs/diseno-gpu-dma.md): la GPU como `memset` y
`memcpy`, lanzada por polling desde un runtime de CPU (`gpu_runtime.inc`) con los
kernels en `gpu_kernels.inc`, todo en una sola imagen. Incluye un job que falla,
uno que no termina y la recuperación de la GPU.

[`examples/render/`](examples/render/render.asm) es un programa gráfico: un
plasma que pinta la GPU y cuyo bucle de frames lleva la CPU.

```bash
cpugpusim examples/render/render.asm --video --window
mini-dbg --gpu examples/render/render.asm --video --window     # depurado
```

La CPU configura el vídeo, y en cada frame escribe los argumentos, lanza 8 warps
con el runtime de `examples/dma`, espera, pide el `SWAP` y espera a que se
aplique. Cada uno de los 64 hilos pinta una fila de un mosaico de 80 × 60 celdas
de 4 × 4 píxeles, con tres ondas triangulares (una por canal RGB565) calculadas
sin ramas; solo diverge al principio, en los 4 hilos que sobran. Un frame son
unas 27 000 instrucciones de warp. `test_cpu_gpu_sim.py` lo compara píxel a píxel
con un modelo en Python. Con `mini-dbg`, `break gpu_k_render` para en cada warp
(ocho veces por frame): `until present` o `watch` sobre el framebuffer trasero
dan una vista más tranquila.

## Qué se comparte

| | |
|---|---|
| **RAM** | El mismo `bytearray` en la CPU y en todas las lanes de la GPU. Lo que escribe uno lo lee el otro sin copias ni caché. |
| **SYSTEM, SERIAL, VIDEO, INPUT** | Los dispositivos de `tools/sim_devices.py`, accesibles desde las dos (§15). `SYSTEM_ID` es 32 y `DEVICES` declara también el bit de GPU. |
| **Reloj de dispositivos** | Una vez por instrucción retirada, de CPU o de warp. `HALT_TARGET` decide a quién para `HALT_AT`: bit 0 la CPU, bit 1 la GPU. |

## Dónde se sincronizan

Solo en el MMIO de la GPU (§14), que es lo que hace el hardware. No hay otro
canal.

```text
CPU escribe código y datos en RAM
CPU escribe descriptores en GPU WARPS (0x82010000)
CPU escribe GPU_CONTROL.RUN  o  WARP_START          ← lanza
GPU ejecuta (los warps escriben en la RAM)
CPU lee GPU_STATUS / WARP_LIVE / WARP_DONE          ← sondea
CPU escribe unos en WARP_DONE (W1C) y lee resultados
```

Implementado según el contrato: `RUN` (solo sin warps vivos), `HALT`, `RESUME`
(solo con la GPU detenida), `STEP` (una instrucción de warp, solo detenida),
`RESET` (conserva los descriptores), `WARP_START` (añade trabajo con otros warps
en marcha), `WARP_LIVE`, `WARP_DONE` pegajoso y W1C, `GPU_CAPS` con la geometría
real y `GPU_STATUS` (`RUNNING`, `HALTED`, `IDLE`, `ERROR`, `LIVE_WARPS`).

Los accesos inválidos paran el núcleo que los hace con error `0x02`, no devuelven
cero (§4.3): escribir un registro de solo lectura, bits reservados o dos
comandos a la vez en `GPU_CONTROL`, `WARP_START` de un warp no implementado, ya
vivo o con `ACTIVE = 0`, `RUN` con warps vivos, `RESUME`/`STEP` sin `HALT`,
`PC` desalineado, `ACTIVE` con lanes que no existen, y tocar el descriptor de un
warp en marcha.

### Configuración por warp: id lógico y argumento

Además de los descriptores, GPU WARPS tiene dos arrays de una palabra por warp
(§14.2): `LOGICAL_WARP_ID[n]` en `+0x200 + 4n` y `WARP_ARG[n]` en `+0x280 + 4n`,
de lectura y escritura. La CPU los rellena antes de `WARP_START` y el kernel los
lee con las instrucciones `GETLWARP` y `GETARG` (la familia `GETID` de
[`isa.md`](../1.isa/isa.md), junto con `GETLANE` y `GETWARP`).

- Escribirlos con el warp vivo es error, como el resto del descriptor.
- `GPU_CONTROL.RESET` los **conserva**, igual que los descriptores.
- Se copian al warp al lanzarlo, así que un cambio posterior en el registro no
  afecta a un warp que ya corre.

Así un kernel recibe su parámetro sin ninguna dirección escrita a mano: la CPU
pone en `WARP_ARG` el puntero a un bloque de argumentos, y en `LOGICAL_WARP_ID`
qué warp lógico es cada uno, que no tiene por qué coincidir con su slot físico.
El diseño que usa esto está en [`docs/diseno-gpu-dma.md`](docs/diseno-gpu-dma.md).

Una **GPU con error** queda parada con `GPU_STATUS.ERROR` y `FIRST_ERROR` /
`FIRST_ERROR_PC` en `GPU SIMT DEBUG`; la CPU sigue. Solo `RESET` la recupera, y
mientras haya error `RUN` y `WARP_START` fallan.

## Permisos por master (§15)

| Bloque | CPU | GPU |
|---|---|---|
| SYSTEM | R | R |
| SERIAL, VIDEO, INPUT | RW | RW |
| CPU CORE (`0x81000000`) | R | — |
| GPU CORE, solo `ID`…`STATUS` | RW | R |
| GPU CORE, `CONTROL`, `WARP_*` | RW | — |
| GPU WARPS (descriptores, `LOGICAL_WARP_ID`, `WARP_ARG`) | RW | — |
| GPU SIMT DEBUG | RW (solo `CONTEXT` escribible) | — |

Un warp no puede reprogramarse a sí mismo ni a sus vecinos: es error.

## Planificación

Determinista y de un solo hilo. Cada ronda ejecuta `--cpu-steps` instrucciones
de CPU (1) y luego `--gpu-steps` de warp (1), con el round-robin de `11`. El
resultado de un programa correcto **no depende** de la proporción (hay un test),
pero el reparto es una elección del modelo, no una medida: el simulador cuenta
instrucciones, no ciclos ni esperas, y no reproduce contienda por la memoria.

Termina cuando la CPU ha parado y la GPU no puede avanzar sola (sin warps vivos,
con error o detenida). Una CPU con `HALT` no corta a la GPU: los warps lanzados
terminan. Si la CPU ya paró y quedan warps vivos sin poder avanzar (una barrera
a la que no llegan todos) sale con código 2 y el aviso «sin progreso».

**Límites de ejecución.** `--run-limit N` vale **N para cada núcleo**: N
instrucciones de CPU y N de warp (no N entre las dos), contando los warps
relanzados. `--cpu-run-limit` y `--gpu-run-limit` lo sustituyen para uno solo,
por si quieres, por ejemplo, dejar la CPU libre y acotar la GPU. Se comprueban
antes de cada instrucción y salta el primero que se alcance, con código 2 y el
mensaje de qué núcleo fue. Un núcleo que ya paró no dispara su límite.

## Línea de órdenes

```text
cpu_gpu_sim.py PROGRAMA [--num-warps 8] [--warp-size 8]
    [--cpu-steps 1] [--gpu-steps 1]
    [--run-limit N] [--cpu-run-limit N] [--gpu-run-limit N]
    [--memory-size 0x2000000] [--dump DIR TAM FICHERO]
    [--trace | --trace-file F] [--trace-limit N]
    [+ periféricos de tools/sim_peripherals.py]
```

Una sola imagen, cargada en 0: el código de la CPU primero (termina con `HALT`
antes de llegar al kernel) y el kernel detrás. Para tenerlos en ficheros
distintos, `.include "kernel.asm"` en el de la CPU: las etiquetas son globales,
así que cada uno puede usar las del otro. No hay opción para cargar un kernel
aparte: obligaría a escribir su dirección a mano.

La CPU pone los descriptores y lanza: no hay ningún `--config` que lo haga por
ella, porque eso sería un camino que la placa no tiene.

`--trace` intercala una línea por instrucción, con `CPU` delante de las de CPU y
`GPU` delante de las de warp (el formato de `11`):

```text
CPU     0x00000030  LOAD R15, R10, 36
GPU     000001  W0   0x0000004C  FF  AAAAAAAA GETTID R1   -> 0x00000050 READY
```

`--trace-limit N` (implica `--trace`) imprime como máximo N líneas, de CPU y de
warp juntas, y avisa con `... traza limitada a N líneas; la ejecución continúa`.
Solo limita lo que se imprime: el programa corre hasta el final. Para parar la
ejecución están los límites de arriba.

Código de salida: 0 bien, 1 error de CPU o de GPU, 2 límite alcanzado, sin
progreso o entrada inválida.

## Límites conocidos

- **Provisional:** `CPU_ID` (2) y `GPU_ID` (11) son el número de carpeta del
  modelo que implementa cada núcleo, `*_VERSION` es 1, `*_FEATURES` es 0,
  `CPU_STATUS` usa el bit 0 (parada) y el 1 (error), y `WARP_RETIRED` lee el
  warp de `CONTEXT`. §22 pospone esos bits «junto a MiniISA» y §14.3 no dice de
  qué warp es el contador: cuando se definan, se cambian aquí.
- CPU PERFORMANCE, GPU PERFORMANCE, CPU DEBUG, TIMER, INTC, DMA, FABRIC y SDRAM
  no existen: acceder es error (§17), no cero.
- **§4.2 (una sola lane activa en un acceso MMIO desde SIMT) no se comprueba**:
  es una carencia heredada de `11`, que serializa las lanes en silencio. Los
  kernels de los tests y de la demo usan `ACTIVE = 1` cuando acceden a MMIO.
- **Accesos de 8 y 16 bits en la GPU:** el simulador de `11` los tiene (se
  retroportaron de la CPU y del modelo de ciclos de la 25), así que los kernels de
  este simulador pueden usar `LOADB`/`LOADUB`/`STOREB`/`LOADH`/`LOADUH`/`STOREH`
  sobre RAM. **El RTL de la GPU (29) todavía no los tiene** y declara un perfil de
  ISA sin ese bit: un kernel que los use corre aquí y no en la placa hasta que se
  añadan a la LSU. Contra MMIO son error, como manda §4.1.
- La GPU de `11` no tiene `JAL`/`JR`; el kernel solo puede usar su ISA, y la CPU
  la suya.
