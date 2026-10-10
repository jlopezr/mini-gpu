# 32.cpu-gpu-func-sim

Simulador funcional de **MiniCPU + MiniGPU sobre una RAM compartida**, con el
mapa y los permisos de MMIO v2 ([`../1.isa/mmio.md`](../1.isa/mmio.md)).

No reimplementa ningún núcleo: importa la `CPU` de
[`../2.cpu-sim-func`](../2.cpu-sim-func/minicpu_sim.py) y el `System` de
[`../11.gpu-sim-func`](../11.gpu-sim-func/minigpu_sim.py), y les pone en medio lo
que les falta para convivir. Un arreglo en cualquiera de los dos simuladores
llega aquí sin tocar nada.

```bash
cpugpusim examples/asm/launch.asm
python -m unittest test_cpu_gpu_sim        # desde esta carpeta
```

[`examples/asm/launch.asm`](examples/asm/launch.asm) es un solo fichero con el código de
la CPU y el kernel de la GPU. Se carga entero en la dirección 0, y la CPU
lanza los warps con la etiqueta `kernel` en el descriptor: no hay ninguna
dirección escrita a mano. Los resultados también van en una etiqueta (`out`).

[`examples/asm/dma/`](examples/asm/dma/dma.asm) es el arnés del diseño de
[`docs/diseno-gpu-dma.md`](docs/diseno-gpu-dma.md): la GPU como `memset` y
`memcpy`, lanzada por polling desde un runtime de CPU (`x.tests/inc/gpu_runtime.inc`) con los
kernels en `gpu_kernels.inc`, todo en una sola imagen. Incluye un job que falla,
uno que no termina y la recuperación de la GPU.

[`examples/asm/render/`](examples/asm/render/render.asm) es un programa gráfico: un
plasma que pinta la GPU y cuyo bucle de frames lleva la CPU.

```bash
cpugpusim examples/asm/render/render.asm --window
mini-dbg --gpu examples/asm/render/render.asm --window     # depurado
```

`--window` abre la ventana y ya implica el vídeo. Sin ventana, `--video` da los
registros de vídeo (en `mini-dbg`, `fb` abre una ventana con el framebuffer).

La CPU configura el vídeo, y en cada frame escribe los argumentos, lanza 8 warps
con el runtime de `examples/asm/dma`, espera, pide el `SWAP` y espera a que se
aplique. Cada uno de los 64 hilos pinta una fila de un mosaico de 80 × 60 celdas
de 4 × 4 píxeles, con tres ondas triangulares (una por canal RGB565) calculadas
sin ramas; solo diverge al principio, en los 4 hilos que sobran. Un frame son
unas 27 000 instrucciones de warp. `test_cpu_gpu_sim.py` lo compara píxel a píxel
con un modelo en Python. Con `mini-dbg`, `break gpu_k_render` para en cada warp
(ocho veces por frame): `until present` o `watch` sobre el framebuffer trasero
dan una vista más tranquila.

[`examples/asm/render/render_cpu.asm`](examples/asm/render/render_cpu.asm) pinta **la misma
imagen byte a byte** solo con la CPU (el test lo exige), para tener con qué
comparar lo que aporta la GPU: 42 instrucciones por celda, unas 203 000 por
frame, frente a las 27 000 de warp de la versión con GPU.

[`examples/asm/render/render_v2.asm`](examples/asm/render/render_v2.asm) es la misma
imagen con **las escrituras coalescidas**: en vez de un hilo por fila de celdas
(8 lanes escribiendo en 8 filas distintas), un warp pinta una fila entera y sus 8
lanes escriben 8 palabras consecutivas, 32 bytes seguidos. Solo cambia el reparto;
la aritmética es idéntica y los tests exigen la misma imagen.

Medido con el simulador de ciclos (`gpusim-cycle`, carpeta 25) sobre el kernel de
cada versión, un frame:

| | instr. de warp | transacciones LSU | ciclos | a 25 MHz | X ocupada |
|---|---:|---:|---:|---:|---:|
| `render.asm` (v1) | 27 072 | 38 400 | 654 550 | 26,2 ms | 16 % |
| `render_v2.asm` | 46 564 | 9 600 | 209 999 | 8,4 ms | 95 % |

La v1 es de la memoria (cada transacción son ~17 ciclos y no se juntan nunca); la
v2 hace casi el doble de instrucciones pero cuatro veces menos transacciones, y
pasa a ser del cálculo: el 85 % del tiempo de X son los desplazamientos, que son
iterativos (un bit por ciclo, `SAR` por 31 cuesta 31). Son cifras del **modelo**:
en la placa el mismo código tarda más (en `demo-bench` la placa midió 1,55× los
ciclos del modelo), así que 8,4 ms es una cota inferior, no una predicción.

### Medido en la placa (36, hito 1)

En la placa, `run-board` ensambla con `-D BOARD`: `gpu_runtime.inc` lanza con `RUN` porque la 36 aún no tiene
`WARP_START`, y los programas cuentan sus propios ciclos con el `CYCLES` de la CPU (80 MHz). Es el mismo `.asm`
que en el simulador: los de `render` llevan la medición entre `.ifdef BOARD` y `.endif`. Se leen con `monitor.py halt` y `read-register`: `R22` ciclos de
pintado, `R29` ciclos del frame entero, `R19` frames válidos (los que cruzan una
parada del monitor se descartan: sin eso salen cifras que dependen de cuánto se
tarda en leer). Vídeo a 59,5 Hz.

| | pintado | frame entero | fps |
|---|---:|---:|---:|
| `render_cpu.asm` | 54,2 ms | 67,2 ms (4 periodos) | 14,8 |
| `render.asm` (v1) | 27,2 ms | 33,6 ms (2 periodos) | 29,8 |
| `render_v2.asm` | 19,6 ms | 33,6 ms (2 periodos) | 29,8 |

El frame entero es siempre un número entero de periodos de vídeo (16,8 ms) porque
el swap espera al siguiente frame. La v2 pinta en 19,6 ms: 3 ms por encima de un
periodo, y por eso va a 30 fps y no a 60. Frente al modelo, la v1 sale como se
esperaba (27,2 ms medidos contra 26,2) y la v2 no (19,6 contra 8,4): el modelo
subestima el código limitado por cálculo.

## Demos "carrera" (`examples/asm/race`)

Tres demos que hacen **el mismo trabajo con tres métodos** y los turnan cada 60
fotogramas: la CPU sola, la GPU "ingenua" (un hilo por fila: las 8 lanes de un warp
tocan 8 filas distintas) y la GPU "bien puesta" (un warp por fila, con las lanes en
columnas seguidas: 8 palabras contiguas por instrucción). El estado se pasa de un
método al otro sin tocarlo, así que la animación sigue donde estaba y solo cambia lo
deprisa que va.

Las 32 primeras líneas de la pantalla son una **gráfica de tiempos**: una columna por
fotograma, tan alta como lo que tardó el trabajo (en la placa, con `CYCLES` de la
CPU) y de color verde (CPU), naranja (GPU ingenua) o cian (GPU bien puesta). En el
simulador sale plana: los simuladores cuentan instrucciones, no ciclos.

| Demo | Qué hace | Memoria por celda |
|---|---|---|
| `life` | juego de la vida, 160 x 104 celdas | 9 lecturas, 3 escrituras |
| `blur` | difusión de calor: 3 puntos que se mueven y un desenfoque 3 x 3 | 9 lecturas, 3 escrituras, algo más de cálculo |
| `rotate` | una textura que gira y se acerca (un gather por celda) | 1 lectura, 2 escrituras |
| `cube` | un cubo sólido con una textura por cara, girando sobre dos ejes (ortográfico) | 1 lectura, 2 escrituras, mucho cálculo y divergencia |

Cada uno es un solo `.asm` (`life.asm`) para el simulador y para la placa: `run-board` lo ensambla con
`-D BOARD` (runtime con `RUN` y `CYCLES`). El anfitrión es `race_host.inc`
y el trabajo de cada demo, `life.inc`, `blur.inc` o `rotate.inc`. Los tests
comprueban los tres métodos contra una referencia en Python con la imagen entera, y
el cambio de método en cada fotograma hace que un solo método que calcule algo
distinto rompa la comparación.

Medido en la placa (80 MHz), tiempo por fotograma:

| Demo | CPU | GPU ingenua | GPU bien puesta | bien puesta frente a ingenua |
|---|---:|---:|---:|---:|
| `life` | 172,7 ms | 138,7 ms | 45,1 ms | 3,1 x |
| `blur` | 190,9 ms | 138,7 ms | 45,4 ms | 3,1 x |
| `rotate` | 42,0 ms | 29,5 ms | 12,2 ms | 2,4 x |
| `cube` | 89,6 ms | 27,4 ms | 15,6 ms | 1,8 x |

- **La GPU ingenua apenas gana a la CPU** (1,3 x a 1,4 x): sus lecturas y escrituras
  no se pueden juntar, y la GPU, que va a 25 MHz, se pasa el tiempo en la memoria.
- **Colocar las lanes bien es lo que mueve la aguja**: 3,1 x en los dos demos de
  rejilla, donde las 9 lecturas y las 3 escrituras se coalescen, y 2,4 x en la
  rotación, donde solo se junta la escritura y la lectura es un gather.
- **`cube` es el que más gana la GPU a la CPU** (3,3 x la ingenua, 5,7 x la bien puesta)
  porque tiene mucho cálculo por celda y lo reparte entre las lanes, pero la
  diferencia entre las dos GPU es la menor (1,8 x): el cálculo pesa más y la lectura
  de textura es un gather. Las lanes de un warp pueden tomar caminos distintos en
  cada celda (tres caras y el fondo), y ahí la ingenua pierde más.
- **`life` y `blur` dan lo mismo en la GPU** (138,7 y 45,1 / 45,4 ms): la memoria
  manda y el cálculo de más del desenfoque queda tapado. En la CPU, que sí paga el
  cálculo, `blur` tarda un 10 % más.

## Kernels de sistema y su benchmark (`examples/asm/dma`)

`gpu_kernels.inc` tiene los kernels de `docs/diseno-gpu-dma.md` §7: `memset`, `memcpy`,
`fill_rect` y `blit` (falta `convert`). `rect.asm` ejercita `fill_rect` y `blit` con
geometrías incómodas y `bench_dma.asm` los cuatro, con todas las configuraciones,
comprobando el resultado. En la placa, `bench_dma.asm` (con `run-board`) y `bench_dma_report.py`
miden cada operación con cada tamaño (32 B a 1 MiB) en la CPU y en la GPU con 1, 2, 4
y 8 warps. Las tablas y lo que se deduce de ellas están en [docs/bench-dma.md](docs/bench-dma.md):
la GPU solo gana en `memcpy` y `blit` (1,2 a 1,3 x, desde unos 4 KiB) y pierde siempre en
`memset` y `fill_rect`. Cada transacción de 16 B cuesta unos 38 ciclos de GPU (30 en
`memcpy`), el doble de lo que suponía el simulador de ciclos, y no es por el sondeo de la
CPU: `poll_exp.asm` en la placa lo descarta midiendo con los contadores de la propia GPU.

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
