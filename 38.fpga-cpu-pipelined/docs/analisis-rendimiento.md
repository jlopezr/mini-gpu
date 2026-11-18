# Análisis de rendimiento de la 38 (noviembre de 2026)

Medidas y decisiones sobre la CPU segmentada y su memoria, con racer, tanks y
skimmer (mini-gl, build `3d-fixed-fp32-ext`) como carga. Recoge qué se probó,
qué se midió y qué queda pendiente, para no repetir el trabajo.

## Cómo se ha medido

- **Placa, contadores de rendimiento** (ranuras de `0x81010000`, mmio.md §12):
  CPI y su reparto (`STALL_MEM`, `STALL_EX_MEM`, `STALL_RAW`,
  `STALL_BRANCH`, `STALL_MULDIV`...), fallos de I-cache y D-cache. CPU a 50 MHz.
- **Simulador funcional con la traza** (`32.cpu-gpu-func-sim` sobre
  `2.cpu-sim-func`, con pypy): modelos de caché, de prefetch, de dependencias
  y de reordenación. Se comparan los frames 10 → 14 (o 10 → 30) para quitar el
  arranque. Los modelos se han contrastado con la placa y cuadran (ver cada
  sección).
- **racer necesita el piloto automático** (guion de entrada que pulsa `P`):
  sin él está en el menú y los contadores no representan el juego.

### Cuidado: en racer hay que medir los mismos frames

El contador de swaps no se pone a cero al cargar un programa (sí al subir el
bitstream): las ventanas se cuentan desde los swaps que haya tras la carga.

Medir durante un tiempo fijo (p. ej. 20 s a partir de un momento) compara
**tramos distintos del circuito**: con una CPU más rápida el juego va por
delante y la geometría por frame cambia. Con el multiplicador segmentado, la
medida por tiempo dio los mismos fps (11,09 frente a 11,08) con un 5 % más de
instrucciones por frame, lo que parecía no ganar nada. Medido entre los mismos
swaps (≈225 → 525), con 2,41 M instrucciones por frame en los dos:

| Bitstream | fps | CPI |
|---|---:|---:|
| I-cache de 32 KB | 11,58 | 1,790 |
| + MUL segmentada | **12,12** / 12,10 | 1,711 |

Es decir, **+4,5 %**. Para comparar hardware en racer: esperar a que el
contador de swaps (`0x80200018`) llegue a N y medir hasta M.

## Cachés

### Tamaños actuales

- I-cache: **32 KB** (2048 líneas de 16 B, mapeo directo, EBR). Commit
  `c6cff11`.
- D-cache: **16 KB** (1024 líneas, mapeo directo, write-through sin reservar
  línea al escribir).

### I-cache de 16 a 32 KB (hecho)

Fallos por cada mil instrucciones: racer 2,35 → 0,78, tanks 7,67 → 1,85,
skimmer 6,67 → 1,51. tanks 40,8 → 42,9 fps, skimmer 20,0 → 21,5.

### D-cache: tamaño frente a vías (simulado, sin hacer)

Fallos de LOAD por cada mil instrucciones. El modelo cuadra con la placa
(racer 6,11 frente a 5,64, tanks 2,73 frente a 2,27, skimmer 8,74 frente a 7,53).

| | 16 KB (ahora) | 32 KB | 64 KB | 2 vías 16 KB | 4 vías 32 KB |
|---|---:|---:|---:|---:|---:|
| racer | 6,11 | 5,06 | 4,49 | 5,14 | 4,55 |
| tanks | 2,73 | 1,46 | 0,55 | 2,37 | 0,93 |
| skimmer | 8,74 | **3,36** | 1,83 | 3,99 | 2,03 |
| tie_fighter | 3,98 | 2,35 | 1,29 | 2,83 | 1,99 |

- En skimmer y tanks casi todos los fallos son de **datos del programa**
  (variables, pila, tablas): conflictos que una caché más grande quita.
- En racer, más de la mitad (3,4 de 6,1) son del **Z-buffer** (150 KB,
  recorrido una vez por frame): ningún tamaño razonable los guarda. Los
  quitaría el pintor (`hint(ENABLE_DEPTH_SORT)`) o un prefetch.
- **Duplicar el tamaño gana a añadir vías**, y en FPGA es lo barato: sobra EBR
  (37 de 208 bloques) y no toca el camino crítico. Las vías ponen un
  multiplexor detrás de los comparadores, justo en el acierto, que se decide en
  EX. Por eso los soft-cores de los fabricantes (Nios II, MicroBlaze) usan
  mapeo directo, y cuando quieren más, una *victim cache*, no vías.
- **Siguiente paso propuesto:** D-cache de 32 KB
  (`dcache #(.LINES(2048), .INDEX_BITS(11))` en `top.v`, ~9 bloques EBR).

## Multiplicador segmentado (hecho)

Antes, MUL/MULHI/MULFX paraban EX 3 ciclos. Ahora los cuatro productos de
16×16 se registran al salir de EX (en los DSP) y la suma y la corrección de
signo se hacen en MEM, que escribe el resultado en WB. La instrucción justo
detrás que lo usa espera 1 ciclo (MUL-use, en `raw_hazard`), la de dos
después ninguno. Detalle en `cpu.v`, sección 04b.

- En la traza: racer hace 81,7 k MUL por frame, y la instrucción siguiente usa
  el resultado en el 46 % de los casos (tanks 41 %, skimmer 37 %).
- En la placa, racer: `STALL_MULDIV` 0,243 → 0,131 ciclos por instrucción,
  `STALL_RAW` 0,052 → 0,074, CPI 1,786 → 1,700. tanks 42,9 → 44,1 fps,
  skimmer 21,5 → 22,3.
- Fmax: CPU 53,62 → 54,07 MHz. 10 DSP y 37 bloques EBR, como antes.
- Bitstream: `reports/20261114-132348-123764-mulpipe`.

Lo que queda en `STALL_MULDIV` son divisiones y operaciones FP (el contador
cuenta las dos).

### Divisores más rápidos (simulado, sin hacer)

Por frame. Los bits de cociente son los que calcula de verdad el divisor
actual, que se salta los ceros iniciales:

| | DIV | Bits de cociente (media / mediana) | Ciclos |
|---|---:|---:|---:|
| racer | 18,0 k | 6,5 / 6 | 188 k (4,6 %) |
| tanks | 5,4 k | 4,3 / 4 | 45 k (3,7 %) |
| skimmer | 10,2 k | 4,1 / 4 | 83 k (3,5 %) |

Una división típica cuesta 4 ciclos fijos (preparar, contar ceros, saltarlos,
entregar) más ~4–6 pasos de 1 bit. Ahorro de ciclos totales (racer / tanks /
skimmer):

- Recortar los ciclos fijos de 4 a 2: ~0,9 % en los tres.
- Radix-4 (2 bits por ciclo): 1,3 % / 0,9 % / 0,8 %.
- Las dos juntas: ~2,2 % / ~1,6 % / ~1,5 %. Es la opción recomendada.
- Radix-16 o SRT: 2,0 % / 1,3 % / 1,1 %. Casi lo mismo que radix-4, con más
  complejidad: los cocientes son cortos.
- Newton-Raphson o Goldschmidt (~10 ciclos fijos): no gana o pierde.
- Software: `udiv_shift` hace 2–3 DIVU por llamada (2.536 llamadas por frame
  en racer).

## Unidad FP con varias operaciones en vuelo (descartado de momento)

Por frame (las comparaciones FEQ/FLT/FLE ya van en la ALU en un ciclo):

| | FMUL | FADD/FSUB | FTOI/ITOF | FDIV |
|---|---:|---:|---:|---:|
| racer | 11,0 k | 4,9 k | 5,6 k | 0,1 k |
| tanks | 9,2 k | 6,6 k | 2,5 k | ~0 |
| skimmer | 17,1 k | 12,0 k | 5,5 k | 0,1 k |

El resultado de una FMUL se usa en la instrucción siguiente el 68–78 % de
las veces (`a*b + c`), así que segmentar la unidad ganaría poco (~1 % racer,
~3 % tanks y skimmer). Además, su resultado llega después de WB, lo que
obligaría a añadir un marcador de registros pendientes, una segunda escritura
en el banco y el vaciado ante HALT/STEP. Solo compensaría junto con un pase
que reordene instrucciones (abajo), o con una instrucción FMA.

## Esperas por dependencia (RAW)

### AGI

La dirección de LOAD/STORE se calcula en **ID** (base + desplazamiento), una
etapa antes que la ALU, para que la petición a la D-cache salga enseguida. Si
la base la escribe la instrucción anterior, el LOAD espera: es el *Address
Generation Interlock* (AGI).

Calcular la dirección en EX, como en el diseño clásico, quitaría las esperas
AGI, pero haría que un LOAD seguido de su consumidor esperase 1 ciclo, y eso
ocurre mucho más: 328 k veces por frame en racer frente a 128 k ciclos de
AGI. El diseño actual es el correcto.

Qué produce la base en las esperas AGI:

| | Ciclos AGI por frame | ADD (índice) | MOVHI+ORI (global) | ADDI | LOAD (puntero) |
|---|---:|---:|---:|---:|---:|
| racer | 128 k | 32 % | 19 % | 29 % | 20 % |
| tanks | 76 k | 42 % | 34 % | 17 % | 8 % |
| skimmer | 146 k | 38 % | 36 % | 18 % | 8 % |

### Adelantamiento de MEM a ID para la dirección (hecho y medido)

`id_address_base` toma la base de `mem_result` cuando la escribe la
instrucción que está en MEM (salvo una MUL, cuyo producto aún se suma ahí).
La espera AGI baja de 2 ciclos a 1 cuando la base viene de la instrucción
anterior, y de 1 a 0 cuando viene de la de dos antes. Solo lo usa el sumador
de direcciones; el resto de operandos de ID no cambia.

- Estimado: racer ~71 k ciclos por frame (~1,7 %), tanks ~43 k (~3,5 %),
  skimmer ~80 k (~3,3 %).
- Pruebas: `cpu_perf_tb` (`addrdep`: esperas RAW de 128 a 64; programa `agi`
  con cada productor, 3 esperas exactas) y el resto de bancos pasan.
- Síntesis con la semilla 9 del `apio.ini`: CPU 54,02 MHz, pero la SDRAM en
  99,78 MHz. Barrido de semillas **con las opciones del `apio.ini`**
  (`--nextpnr-options tmg-ripup placer-heap-timingweight=180`; sin ellas
  ninguna cumple y no es comparable): cumplen 5 de 6, CPU 50,7–53,9 MHz.
- En la placa, mismos frames: racer 12,10 → 12,29 fps (+1,5 %), tanks
  45,71 → 47,00 (+2,8 %), skimmer 21,64 → 22,15 (+2,4 %).

### Otras formas de quitar esperas AGI

- **Globales en los primeros 32 KB** (`LOAD x, R0, dir`): cada acceso a una
  global son hoy `MOVHI ; ORI ; LOAD` y 2 ciclos de espera. Hay 12,3 k
  accesos así por frame en racer, 4,4 k en tanks y 26,3 k en skimmer. Con el
  adelantamiento ya hecho, ahorraría unos 3 ciclos por acceso (~1–3 %). No
  cambia la ISA; cambia la colocación (el código empieza ahora en 0 y los
  datos en 0x8000). Alternativa: un registro fijo de globales, como el `gp`
  de MIPS.
- **Plegar `ADDI` en el desplazamiento del LOAD/STORE**: racer 27 k, tanks
  10 k, skimmer 20 k ciclos por frame. Poco.
- **LOAD con índice escalado** (`LOADX rd, ra, rb << s`): para `tabla[i]`
  (`SHL ; ADD ; LOAD`), el tipo más frecuente. Ahorra 1–2 instrucciones y la
  espera (~1,4 % racer, ~3 % tanks y skimmer antes del adelantamiento). Solo
  para LOAD: un STORE así leería 3 registros. Cambia la ISA, el ensamblador,
  los simuladores y lcc o mini_opt.

### Reordenar instrucciones (pase de compilador, sin hacer)

Modelo: los bloques básicos de la traza, reordenados con *list scheduling*
respetando las dependencias de registros y el orden de memoria, con las
reglas de espera de la 38 (AGI 2/1, MUL-use 1). El modelo cuadra con la
placa (RAW en ciclos por instrucción: racer 0,068 frente a 0,074, tanks
0,119 frente a 0,119, skimmer 0,123 frente a 0,120).

Esperas RAW por frame:

| | Ahora | Reordenando | + renombrar registros | + accesos a pila libres |
|---|---:|---:|---:|---:|
| racer | 169 k | 94 k | 77 k | 63 k |
| tanks | 85 k | 37 k | 30 k | 27 k |
| skimmer | 162 k | 76 k | 60 k | 53 k |

Es −1,8 a −2,5 % de ciclos en racer y −3,6 a −4,8 % en tanks y skimmer
(medido antes del adelantamiento de MEM a ID; con él, algo menos). El límite
son los bloques básicos, de solo 3,9–4,9 instrucciones de media. El sitio
natural es un pase nuevo en `tools/mini_opt`, que ya tiene bloques, vida de
registros y `defs_uses`.

### Adelantamientos que quedan (no compensan)

- **Resultado de una MUL a la instrucción siguiente**: la suma de 64 bits, la
  corrección y la ALU en un solo ciclo no cierran a 50 MHz. ~0,9 % en racer.
- **Base de la dirección desde EX**: pondría la ALU delante del sumador de
  direcciones. Lo hace mejor el compilador plegando los ADDI.
- **Saltos decididos en ID**: alarga el camino de búsqueda; mejor predecir
  mejor (abajo).

## Memoria de datos

### Microbenchmark en la placa (4096 vueltas, zona libre de la SDRAM)

| Caso | Ciclos por vuelta | Espera de memoria por vuelta |
|---|---:|---:|
| STORE seguidos con paso de 4 B (se combinan) | 5,0 | 0 |
| STORE cada uno a otra línea | 8,2 | 3,9 |
| LOAD que falla en la D-cache | 28,4 | **24,4** |
| STORE a otra línea y luego LOAD que falla | 39,0 | **33,0** |

- Los STORE casi no esperan: el adaptador contesta al ciclo siguiente y
  vuelca la línea sin esperar respuesta. Solo paran si se llena la cola.
- **Un fallo de D-cache cuesta ~24 ciclos de CPU** (~490 ns). La SDRAM en sí
  tarda unos 15 ciclos de memoria; el resto, unos 30, se va en colas, cruces
  de reloj y arbitraje.
- **Un STORE justo antes añade ~9 ciclos**: el camino hasta la SDRAM va en
  orden y la lectura espera a que se ejecute la escritura de la línea
  anterior.
- En los juegos, cada fallo sale de media por ~31–43 ciclos (contando lo
  anterior y el vídeo leyendo de la SDRAM). En racer, la espera de memoria de
  datos es ~15 % de los ciclos, casi toda de fallos de LOAD.

### Descartado: que la D-cache no espere a las escrituras pendientes

La D-cache no pide un fallo hasta `pending == 0`, pero como el adaptador
contesta los STORE al ciclo siguiente, esa espera es de 1 ciclo como mucho.
No ganaría nada.

### Prefetch de la línea siguiente (simulado, sin hacer)

Tiene que ir en `cpu_dmem_adapter.v`, no en la D-cache: el adaptador solo
admite una lectura en vuelo y, mientras espera, no acepta ni los STORE. La
idea: al servir un fallo de la línea N, pedir también la N+1 y guardarla en
un registro de una línea, sin dejar de aceptar STORE. Si luego falla N+1, se
contesta desde ahí. Hay que invalidarla ante un STORE a esa línea y al parar
la CPU (el monitor puede escribir memoria).

Fallos de la D-cache de 16 KB que cubriría:

| | Fallos por cada mil instrucciones | Siempre N+1: cubre / inútiles por cada mil instrucciones | Solo si el fallo sigue al anterior: cubre / inútiles |
|---|---:|---|---|
| racer | 6,11 | 51 % (Z-buffer 67 %) / 3,01 | 35 % (Z-buffer 46 %) / 0,99 |
| tanks | 2,72 | 34 % / 1,78 | 25 % / 0,30 |
| skimmer | 8,85 | 22 % / 6,91 | 6 % / 1,47 |
| tie_fighter | 3,82 | 13 % / 3,31 | 5 % / 0,38 |

Estimado (≈30 ciclos ahorrados por fallo cubierto, ≈10 perdidos por prefetch
inútil): racer ~3 %, tanks ~1 %, skimmer 0 con detección de flujo (y pierde si
se pide siempre N+1). Sirve sobre todo para el Z-buffer de racer, y el pintor
lo haría innecesario.

## Dónde se va el tiempo ahora (racer en la placa, con la MUL segmentada)

CPI 1,70 sobre una base ideal de 1,0:

| Motivo | Ciclos por instrucción | Proporción |
|---|---:|---:|
| Memoria de datos (MEM esperando) | ~0,25 | ~15 % |
| Saltos (fallos de predicción y burbujas) | 0,17 | ~10 % |
| DIV y FP (`STALL_MULDIV`) | 0,13 | ~8 % (DIV ~4,6 %) |
| ID vacío | 0,07 | ~4 % |
| RAW | 0,07 | ~4 % (baja con el adelantamiento de MEM a ID) |

### Predicción de saltos (BTB de 256 hecho y medido)

Hoy: BTB de 64 entradas (contador de 2 bits por entrada), estática para lo
que el BTB no predice (hacia atrás tomado, hacia delante no) y pila de
retornos. Modelo de la traza (`brsim`); "burbujas" son los ciclos perdidos
por saltos, en ciclos por instrucción, contando fallos y burbujas de saltos
bien predichos:

| | racer: fallos / burbujas | tanks | skimmer |
|---|---|---|---|
| Actual (BTB 64 + estática) | 10,4 % / 0,242 | 12,2 % / 0,271 | 11,8 % / 0,260 |
| BTB 256 | 7,7 % / 0,196 | 8,7 % / 0,216 | 8,9 % / 0,210 |
| Bimodal 1K | 6,5 % / 0,224 | 7,1 % / 0,243 | 7,0 % / 0,232 |
| gshare 4K, historia de 10 | 5,2 % / 0,210 | 6,2 % / 0,233 | 6,0 % / 0,222 |
| BTB 256 + gshare 4K | 5,2 % / 0,175 | 6,2 % / 0,193 | 6,0 % / 0,186 |

- Pesa más el BTB pequeño (los saltos se pisan entre sí y caen a la estática,
  con su burbuja larga) que la falta de un predictor dinámico. gshare solo
  predice la dirección: sin entrada en el BTB, un salto tomado paga igual la
  burbuja.
- El modelo sobreestima las burbujas (racer 0,242 frente a 0,170 medidos).
  Escalado con la placa: BTB 256, ~−1,9 % de ciclos en racer y skimmer y
  ~−2,5 % en tanks; con gshare 4K además, ~−2,8 % y ~−3,6 %.
- **BTB 256 hecho** (`BTB_BITS = 8`). Con 256 entradas Yosys puso las
  etiquetas en EBR, de lectura síncrona, y la lógica de la búsqueda siguiente
  acabó en su dirección: CPU a 47,74 MHz. Forzado a memoria distribuida
  (`(* ram_style = "distributed" *)`): CPU 52,21 MHz, SDRAM 100,21 MHz.
- En la placa, mismos frames: racer 11,88 → 12,22 fps (+2,9 %), tanks 47,00 →
  48,69 (+3,6 %), skimmer 22,15 → 22,89 (+3,3 %). Más de lo estimado.
- gshare (pendiente): 4K contadores en 1 bloque EBR, más el registro de
  historia, en el camino de IF. El modelo le da ~1 % más sobre el BTB de 256.

## Pendiente, por orden propuesto

1. D-cache de 32 KB.
2. gshare sobre el BTB de 256.
3. Divisor más rápido: recortar los ciclos fijos y radix-4 (~1,5–2,2 %).
4. Software: globales en los primeros 32 KB, plegar ADDI y pase de
   reordenación en mini_opt.
5. Prefetch en el adaptador, si racer sigue usando Z-buffer.
6. LOAD con índice escalado (ISA), si después de todo lo anterior sigue
   valiendo la pena.
7. ISA: aprobar los contratos propuestos de `RCPFX` (con escala `k`, para el
   `1/w` de mini-gl) y `FSQRT`, y la retirada de `RSQRTFX` (`1.isa/isa.md`
   §7.3).

Nota: el repo principal no compila la 38 mientras estén
`dma_engine_v2_checkpoint2.v` y `dma_engine_v2_checkpoint3.v` sin commitear,
porque declaran el mismo módulo que `dma_engine_v2.v` y `apio` coge todos
los `.v` de la carpeta. Las pruebas y síntesis de este análisis se hicieron
en un worktree sin los ficheros `dma_*`.
