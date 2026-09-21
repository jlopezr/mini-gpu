# Los prototipos: qué hace cada uno, y qué direcciones usa

Visión general de las implementaciones: qué sabe hacer cada una, cuánta memoria
ve, a qué frecuencia cierra y **qué mapa de direcciones implementa hoy**.

Las carpetas numeradas son hitos de aprendizaje y se conservan tal cual, así que
lo normal es que **ninguna las tenga todas**: la más reciente no reemplaza a las
anteriores, y una capacidad que aparece en la 19 no está en la 18 aunque la 18
sea «la misma CPU». Este documento existe para no tener que abrir cinco
`README.md` para averiguarlo.

**Este documento describe lo que hay.** El contrato al que se quiere converger
—MMIO v2, con otro mapa de direcciones— está en
[`../1.isa/mmio.md`](../1.isa/mmio.md), y el trabajo para llegar hasta él, en
[`../TODO.md`](../TODO.md). La sección de [conformidad](#conformidad-con-mmio-v2)
dice qué le falta a cada prototipo.

## De dónde salen estos números

- **Fmax** es el `hardware.pnr` que hay ahora mismo en el `_build/` de cada
  carpeta, o sea la última síntesis que se hizo allí. Es la frecuencia del
  dominio con menos holgura, que en las versiones con SDRAM es siempre
  `sdram_clk`. Un rebuild con otra semilla da otro número: la dispersión entre
  semillas ronda el 10 % y en la 17 llega al 17 %. Peor aún, **la semilla buena
  es propiedad de un netlist, no de un diseño**: subir una constante de ocho
  bits en la 19 movió su mejor semilla de la 8 a la 3 y le quitó 2 MHz. Un
  barrido caduca con cualquier cambio de RTL.
- **Objetivo** es la restricción del `.lpf`, que es lo que decide si el diseño
  cierra o no. Lo que importa es la pareja, no el Fmax suelto.
- **Memoria** es `ARCHITECTURAL_REGIONS` del `monitor.py` de cada carpeta: lo
  que un programa puede direccionar, no lo que ocupa el bitstream.
- Las capacidades de CPU son las que declaran los backends de
  [`x.tests`](../x.tests), y son las mismas que un caso pide con
  `requires`.

**Cuidado con el Fmax.** Mide caminos dentro del chip y no dice nada de lo que
entra por un pin. La 19 tuvo un fallo real de captura de DQ y el barrido de
semillas daba +14,5 % de holgura con el diseño roto.

## CPU

<!-- gendoc:begin cpu-matrix
generator: cpu-matrix
-->

| | [2.sim](../2.cpu-sim-func) | [6.ebr](../6.fpga-cpu) | [10.sdram](../10.fpga-cpu-ram) | [16.hdmi](../16.fpga-cpu-hdmi) | [18.bl8](../18.fpga-cpu-hdmi-bl8) | [19.subword](../19.fpga-cpu-hdmi-ls) | [21.alu](../21.fpga-cpu-hdmi-alu) |
|---|---|---|---|---|---|---|---|
| **Reloj** | — | 100 MHz | 100 MHz | 100 MHz | 80 MHz | 80 MHz | 80 MHz |
| **Fmax / objetivo** | — | 117.6 / 100 | 115.2 / 100 | 103.2 / 100 | 87.7 / 80 | 88.9 / 80 | 87.3 / 80 |
| **Memoria** | — | 32 KiB | 32 MiB | 32 MiB | 32 MiB | 32 MiB | 32 MiB |
| **LUT / FF** | — | 6 042 / 2 624 | 5 352 / 2 477 | 8 171 / 3 798 | 10 319 / 5 088 | 11 129 / 5 171 | 11 382 / 5 236 |
| **Monitor** | — | 3.6 | 3.10 | 3.16 | 3.18 | 4.19 | 4.21 |
| **Baudios** | — | 1 M | 1 M | 1 M | 1 M | 1 M | 1 M |
| `subword_memory` | sí | no | no | no | no | sí | sí |
| `calls` | sí | no | no | no | no | sí | sí |
| `shift_immediate` | sí | no | no | no | no | no | sí |
| `alu_extended` | sí | no | no | no | no | no | sí |
| `compare` | sí | no | no | no | no | no | sí |
| `frame_capture` | sí | no | no | sí | sí | sí | sí |
| `serial` | sí | no | no | no | no | sí | sí |

<!-- gendoc:end cpu-matrix -->

`2.sim` no tiene Fmax ni LUTs porque no es hardware, y tampoco tiene contadores
de ciclos: no modela el tiempo. Lo que sí da es el número de instrucciones, que
es arquitectónico y por eso sirve de contraste contra el contador de la placa.

**El simulador va por delante del RTL, y eso es lo normal:** es donde se prueba
primero una instrucción nueva. Hoy tiene las siete capacidades; la 21 es el
único bitstream que también.

### `10.sdram` no implementa `MUL`, `MULFX` ni `DIV`

Esa fila decía «sí» para las siete columnas y **era falsa**. Se descubrió al
correr el diferencial contra esa placa por primera vez, porque el backport
obligó a probar las seis.

No es una versión reducida a propósito: es un **hueco**. Son instrucciones base
de la ISA, la 6 —anterior— las tiene y la 16 —posterior— también. Y
`6.fpga-cpu/cpu.v` resultó ser un **superconjunto estricto** del de la 10: la
diferencia son los seis estados `MUL_*`/`DIV_STEP` y un bit más de `state`.
Copiar el fichero es el port entero, y sus cinco suites pasan a la primera.

**Lo que no pasa es la temporización.** Medido:

| | LUT | Semillas que cumplen 120 MHz |
|---|---:|---|
| 10 tal como está | 4 991 | **8 de 8**, 121,7 – 129,6 |
| 10 con `MUL`/`MULFX`/`DIV` | 5 896 + 4 DSP | **1 de 8**, la mejor al +2,4 % |

Un uno de ocho al +2,4 % es una lotería, y es el mismo criterio con el que la 16
bajó de 120 a 100 y la 18 de 100 a 80. Aquello se midió cuando la 10 corría a
120 MHz; hoy corre a 100 —ver [`unificacion-mmio.md`](unificacion-mmio.md)— así
que el barrido habría que repetirlo antes de dar la conclusión por buena. Lo que
no cambia es que portar las tres instrucciones es copiar un fichero y
revalidar una carpeta entera.

Lo que sí se hizo: **quitar de su `cpu.v` los tres `localparam`**. Estaban
declarados y validados en el `case` de encoding pero sin rama en el EXECUTE, así
que el resultado era correcto —`ERROR_INVALID_OPCODE`— y el código mentía:
aparentaba soportarlas. Ahora el fichero dice la verdad. `x.tests` lo declara
como la capacidad **`mul_div`**, y `cases/alu/multiply` se omite ahí con un
`SKIP` en vez de fallar.

`mul_div` es la única capacidad del runner que significa «a este le **falta**
algo de la base» en lugar de «este tiene algo **de más**». El día que la 10
implemente las tres, la capacidad desaparece entera.

### La versión del monitor: qué significan hoy esos números

`GET_VERSION` es lo único que el PC puede preguntar antes de cargar un programa,
así que es el único sitio donde puede vivir «este bitstream no es el que crees».

Desde que los diez `monitor.v` son **un único fichero parametrizado**, el número
tiene por fin una estructura, y sale de los parámetros con que cada `top.v`
instancia el monitor:

```text
mayor   = juego de comandos     3  base + READ_WORD/WRITE_WORD
                                4  lo anterior + SEND_BYTES/RECV_BYTES
menor   = número de carpeta     3.6, 3.10, 3.12, 3.14, 3.16, 3.17,
                                3.18, 3.22, 4.19, 4.21
```

Eso arregla de golpe los dos problemas que tenía el esquema anterior, en el que
había diez números arbitrarios para cuatro juegos de comandos:

- **El mayor sí dice qué entiende la placa.** Antes no: 6, 10 y 16 compartían
  juego de comandos y llevaban tres números distintos, y 19 y 21 compartían otro
  llevando el más alto y el más bajo de la lista.
- **El menor no se puede duplicar**, porque lo impone el nombre del directorio.
  Antes había que vigilarlo a mano, y 14 y 17 llegaron a compartir número — con
  lo que comprobar el bitstream contra la placa equivocada pasaba en silencio.

El número **sigue sin significar antigüedad**, y nunca lo significó: la 6
responde 3.6 y la 21 responde 4.21 siendo la 21 mucho más nueva, pero también la
10 respondía por debajo de la 6 en el esquema viejo. Es un identificador, no una
fecha.

Y sigue haciendo falta aunque exista `SYS_ID`, por un caso concreto: el backport
de `R0` no cambió ni un comando, ni un dispositivo, ni una capacidad — y un
bitstream viejo no da error, **da otro resultado**. Un bitmap de dispositivos no
detecta eso. Es exactamente para lo que sirve una versión.

### Por qué la frecuencia baja según avanza la lista

No es que la CPU empeore. El camino crítico se mudó:

- La **6** y la **10** cerraban a 120 MHz con una CPU sola colgada de memoria.
  Hoy corren a 100: `WRITE_WORD` les costó entre 15 y 19 MHz y ninguna de las
  ocho semillas cerraba a 120. El razonamiento completo, con el barrido y el
  arreglo del camino crítico, está en
  [`unificacion-mmio.md`](unificacion-mmio.md).
- La **16** baja a 100 porque entra el vídeo, que compite por la SDRAM.
- La **18** baja a 80 al pasar el camino de memoria a 128 bits para ráfagas
  BL8. A 100 no cumplía ninguna semilla (83,9 a 91,8 MHz). A cambio, el bucle
  interior de `swap_demo_fast` pasa de 146 a 64 ciclos por palabra: el diseño
  es más lento por ciclo y mucho más rápido por trabajo hecho.
- La **19** pierde unos 5 MHz respecto a la 18 por crecer ~760 LUTs, no por las
  instrucciones nuevas en sí: el camino crítico sigue estando en el handshake de
  memoria —adaptador, árbitro y controlador—, el mismo sitio que en la 18.
- La **21 rompe la tendencia**: sube creciendo ~330 LUTs sobre la 19, y con el
  multiplicador construyendo ahora siempre los 64 bits. Como en los casos
  anteriores, el camino crítico no se movió de `sdram_clk`; lo que cambió fue la
  colocación. Sirve de contraejemplo a la lectura fácil de esta lista: la
  frecuencia de un netlist no es una función monótona del tamaño del diseño.

**Los números se rehicieron con el backport de `R0`**, y hay una lección en eso
que merece quedarse. El cambio es **una línea** en `register_file.v`, la misma en
los seis cores, y aun así:

- **la 10 dejó de cumplir**, en 117,3 MHz sobre un objetivo de 120, con la
  semilla por defecto y **menos** lógica que antes (4 962 LUTs frente a 4 976).
  Ahora lleva semilla fija por primera vez;
- la 19 cayó de 87,2 a 83,7 con la semilla que tenía puesta;
- y rebarridas las seis, **cinco acabaron con más margen que antes**.

Ninguna de esas tres cosas dice nada sobre si el diseño mejoró o empeoró. Dicen
que el netlist cambió lo justo para que el emplazador tomara otras decisiones,
que es lo que avisa el segundo punto de «De dónde salen estos números» y aquí se
cobró de verdad.

## GPU

<!-- gendoc:begin gpu-matrix
generator: gpu-matrix
-->

| | [25.sim](../25.gpu-sim-cycle-uarch) | [11.sim](../11.gpu-sim-func) | [12.bram](../12.fpga-gpu) | [14.sdram](../14.fpga-gpu-ram) | [17.fpga-gpu-ram-v2](../17.fpga-gpu-ram-v2) | [22.lsu2](../22.fpga-gpu-bl8) |
|---|---|---|---|---|---|---|
| **Reloj** | — | — | 25 MHz | 25 MHz | 25 MHz | 25 MHz |
| **Fmax / objetivo** | — | — | 35.1 / 25 | 34.3 / 25 | 44.8 / 25 | 35.2 / 25 |
| **Memoria** | — | — | 128 KiB | 32 MiB | 32 MiB | 32 MiB |
| **LUT / FF** | — | — | 38 078 / 9 357 | 31 038 / 9 236 | 31 392 / 10 310 | 35 937 / 12 520 |
| **Monitor** | — | — | 3.12 | 3.14 | 3.17 | 3.22 |
| **Baudios** | — | — | 250 k | 250 k | 250 k | 250 k |
| `warp_config` | no | no | sí | sí | sí | sí |
| `simt_debug` | no | no | sí | sí | sí | sí |
| `atomic_warp_faults` | sí | sí | no | no | no | no |

<!-- gendoc:end gpu-matrix -->

La **17** es la 14 con el mismo comportamiento y el camino crítico reescrito:
sigue ganándole unos 12 MHz con menos LUTs. Está restringida a 25 porque ese era
el objetivo; el margen es la ganancia.

**Las cuatro GPU no llevan semilla fija, a diferencia de las de CPU.** Ninguna
de 12, 14, 17 y 22 tiene `nextpnr-extra-options` con semilla en su `apio.ini`.
Rebarridas tras el backport, las ocho semillas cumplían en 12, 14 y 17, con
márgenes del +18,8 % de la peor de la 14 al +111 % de la mejor de la 17. Aquí la
semilla no decide si el diseño funciona —ni la peor se acerca al objetivo— así
que fijarla solo serviría para que estos números fueran reproducibles, a cambio
de tener que rebarrer con cada cambio de RTL. En las carpetas de CPU sí se fija,
porque allí el margen se mide en unidades y no en decenas: la 10 llegó a **no
cumplir** con la semilla por defecto después de una sola línea de cambio.

Ninguna implementación de GPU tiene todavía los accesos sub-palabra ni las
llamadas. El backport de las dos extensiones a la MiniGPU está pendiente, y
`JALR`/`JR` en SIMT tienen además un problema propio: un salto indirecto puede
producir tantos destinos distintos como lanes activas, y la maquinaria de `SSY`
está construida para divergencias de dos caminos. Habrá que exigir destino
uniforme entre las lanes activas, y que quede escrito en la ISA antes de que
aparezca código que suponga lo contrario.

## Tabla plana de todos los prototipos

<!-- gendoc:begin prototype-summary
generator: prototype-summary
-->

| Prototype | Version | Monitor | Clock | Capabilities |
|---|---|---|---|---|
| [`6.fpga-cpu`](../6.fpga-cpu) | ebr | 3.6 | 100.0 MHz | mul_div, read_word, write_word |
| [`10.fpga-cpu-ram`](../10.fpga-cpu-ram) | sdram | 3.10 | 100.0 MHz | read_word, write_word |
| [`12.fpga-gpu`](../12.fpga-gpu) | bram | 3.12 | 25.0 MHz | mul_div, read_word, write_word, warp_config, simt_debug |
| [`14.fpga-gpu-ram`](../14.fpga-gpu-ram) | sdram | 3.14 | 25.0 MHz | mul_div, read_word, write_word, warp_config, simt_debug |
| [`16.fpga-cpu-hdmi`](../16.fpga-cpu-hdmi) | hdmi | 3.16 | 100.0 MHz | mul_div, video, frame_capture, read_word, write_word, perf_counters |
| [`17.fpga-gpu-ram-v2`](../17.fpga-gpu-ram-v2) | 17.fpga-gpu-ram-v2 | 3.17 | 25.0 MHz | mul_div, read_word, write_word, warp_config, simt_debug |
| [`18.fpga-cpu-hdmi-bl8`](../18.fpga-cpu-hdmi-bl8) | bl8 | 3.18 | 80.0 MHz | mul_div, video, frame_capture, read_word, write_word, perf_counters |
| [`19.fpga-cpu-hdmi-ls`](../19.fpga-cpu-hdmi-ls) | subword | 4.19 | 80.0 MHz | mul_div, subword_memory, calls, video, frame_capture, serial, read_word, write_word, perf_counters |
| [`21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu) | alu | 4.21 | 80.0 MHz | mul_div, subword_memory, calls, shift_immediate, alu_extended, compare, video, frame_capture, serial, read_word, write_word, perf_counters |
| [`22.fpga-gpu-bl8`](../22.fpga-gpu-bl8) | lsu2 | 3.22 | 25.0 MHz | mul_div, video, read_word, write_word, warp_config, simt_debug, perf_counters |

<!-- gendoc:end prototype-summary -->

La 17 no aparece con alias corto porque no está registrada en los backends de
`x.tests`; cae al nombre de la carpeta. Es deliberado: tampoco es un target de
`test-board`, porque no tiene `version.json`.

---

# El mapa de direcciones implementado

Lo que sigue describe el mapa **de la página única de 4 KiB**, que es el que
implementan hoy siete de los diez prototipos con bitstream. No es el contrato
objetivo: ese es [MMIO v2](../1.isa/mmio.md), y las carpetas que lo cumplen son
la [18](../18.fpga-cpu-hdmi-bl8), la [19](../19.fpga-cpu-hdmi-ls) y la
[21](../21.fpga-cpu-hdmi-alu), cuyo mapa es el de `mmio.md` y no el de aquí.

## Memoria de programa y datos

### CPU con EBR: carpeta 6

| Rango | Tamaño | Uso convencional |
|---|---:|---|
| `0x00000000–0x00003FFF` | 16 KiB | Programa (banco EBR 0) |
| `0x00004000–0x00007FFF` | 16 KiB | Datos (banco EBR 1) |

**El espacio es contiguo**: 32 KiB seguidos, y el bit 14 de la dirección elige
banco. Los puertos de instrucciones y datos alcanzan ambos, así que la separación
de usos es solo una convención — un programa puede pasar de 16 KiB sin cruzar
ningún hueco. Fuera de `0x00008000` el bus da error.

Los bancos estuvieron en `0x00000000` y `0x00100000`, con 1 MiB de hueco entre
ellos. Juntarlos abarató el decodificador —un comparador por puerto en vez de
dos, y hay tres puertos— y dejó a la 6 con el mismo aspecto que el resto de
prototipos, que son todos un bloque de RAM seguido.

Desde que los bancos son contiguos, un bloque **sí** puede cruzar `0x4000`: se
transfiere byte a byte y cada uno se encamina por su cuenta. El cliente declara
el intervalo en [monitor.py](../6.fpga-cpu/monitor.py); el validador de bloques y
la respuesta del bus comprueban aspectos distintos, así que no basta con validar
un tamaño total.

### CPU y GPU con SDRAM

| Rango | Tamaño | Significado |
|---|---:|---|
| `0x00000000–0x01FFFFFF` | 32 MiB | Memoria unificada de programa y datos |
| `0x02000000` | — | Primer byte fuera de SDRAM |

No hay traducción implícita por banco. La última palabra alineada comienza en
`0x01FFFFFC`. Las tecnologías de transferencia BL1/BL8, arbitraje y buffers
cambian según la implementación, no las direcciones.

En las variantes CPU con vídeo, las bases iniciales de framebuffer son
`0x01000000` y `0x01025800`: dos imágenes RGB565 de 320 × 240, de 153 600 bytes
cada una. Son regiones de RAM ordinaria elegidas por configuración, no MMIO ni
reservas impuestas a todos los programas. El flujo inicial de Mandelbrot usa
otra convención, una palabra por pixel a partir de `0x00100000`.

### GPU con EBR: carpeta 12

`0x00000000–0x0001FFFF`, 128 KiB continuos y compartidos para código y datos de
los warps. El límite exclusivo es `0x00020000`.

### Simuladores

El runner configura 32 MiB para MiniCPU. Su clase de CPU admite dispositivos
opcionales `VideoDevice` y `SerialDevice`, en las direcciones de las variantes
FPGA. Sin el dispositivo configurado, el acceso a esa dirección falla; no se
simula automáticamente toda la ventana de 4 KiB con el comportamiento del RTL.
Los accesos CPU sub-palabra a MMIO son rechazados por el simulador.

MiniGPU mantiene PC, máscaras y configuración de warps como estado del modelo,
accesible por la API de lanzamiento y observación. No ofrece a los kernels la
ventana de configuración MMIO del monitor FPGA. En 23 eso es una decisión, no una
carencia: `plasma.asm` lee `FB_BACK` y escribe `SWAP`, así que para comparar RTL
y modelo existe `plasma_nommio.asm`, la misma carga sin accesos a MMIO.

Los tres motores comparten [`../tools/sim_devices.py`](../tools/sim_devices.py).
Sus bases de vídeo se alinean a 4 bytes y cualquier escritura a `SWAP` solicita
intercambio; para portabilidad al RTL de GPU hay que usar alineación de 16 bytes
y escribir 1.

> MMIO v2 elimina `plasma_nommio.asm`: su §17 exige que el simulador implemente
> el mismo contrato que el RTL, precisamente para que no haga falta un programa
> distinto.

## Qué dispositivo tiene cada prototipo

| Prototipo | Vídeo | Captura | Serie | Warps | SIMT debug | Perf | Quién accede |
|---|---|---|---|---|---|---|---|
| 2.cpu-sim-func | opcional | — | opcional | — | — | — | el programa, si el caso lo configura |
| 6.fpga-cpu | — | — | — | — | — | — | — |
| 10.fpga-cpu-ram | — | — | — | — | — | — | — |
| 11.gpu-sim-func | — | — | — | API Python | API Python | — | host, sin ventana MMIO |
| 12.fpga-gpu | — | — | — | ✓ | ✓ | — | solo host, GPU parada |
| 14.fpga-gpu-ram | — | — | — | ✓ | ✓ | — | solo host, GPU parada |
| 16.fpga-cpu-hdmi | ✓ | — | — | — | — | ✓ | CPU + monitor |
| 17.fpga-gpu-ram-v2 | — | — | — | ✓ | ✓ | — | solo host, GPU parada |
| 18.fpga-cpu-hdmi-bl8 | ✓ | ✓ | — | — | — | ✓ | CPU + monitor |
| 19.fpga-cpu-hdmi-ls | ✓ | ✓ | ✓ | — | — | ✓ | CPU + monitor |
| 21.fpga-cpu-hdmi-alu | ✓ | ✓ | ✓ | — | — | ✓ | CPU + monitor |
| 22.fpga-gpu-bl8 | ✓ | ✓ | — | ✓ | ✓ | ✓ | mixto |
| 23.gpu-sim-uarch | — | — | — | — | — | modelado | — |
| 24.gpu-sim-pipeline | — | — | — | — | — | — | — |

Todo el MMIO del repositorio cabe en una única página de 4 KiB, y ningún
prototipo usa más del 5,1 % de ella. La escasez nunca fue de espacio.

## Ventanas publicadas por el cliente

| Carpeta | Ventana | Decodificación |
|---|---|---|
| 16, 18, 19, 21 | `0x80000000–0x80000FFF` | `address[31:12]`, 16 slots de 256 B por `address[11:8]` |
| 22 | `0x80000000–0x80000FFF` | `address[31:12]`, regiones por `address[11:6]` y palabras sueltas |
| 12, 14, 17 | `0x80000000–0x80001FFF` | `address[31:13]`, **dos páginas**: `address[12]` separa lo compartido del control exclusivo de la GPU |

El reparto por slots de 256 B, tal como está implementado:

| Slot | Dirección | CPU 16/18/19/21 | GPU 12/14/17/22 |
|---|---|---|---|
| 0 | `0x80000000` | Vídeo | Vídeo (solo 22) |
| 1 | `0x80000100` | reservado | Depuración SIMT |
| 2 | `0x80000200` | Puerto serie (19, 21) | libre |
| 3 | `0x80000300` | Contadores | Contadores (solo 22) |
| 15 | `0x80000F00` | `SYS_ID` | `SYS_ID` |
| — | `0x80001000` | — | Configuración de warps |

Una dirección sin registro **es un error de acceso** en ambas familias, en
lectura y en escritura, y esa política está verificada en placa. En CPU el
decodificador propaga el error al núcleo o al monitor; en GPU se propaga como
`bad`. Los slots reservados no sirven para descubrir hardware: para eso está
`SYS_ID`.

## Los registros, tal como están hoy

### Vídeo — `0x80000000`

Mismos offsets en todos los prototipos que tienen vídeo.

| Offset | Registro | Presente en |
|---|---|---|
| `+0x00` | `FB_FRONT` | todos |
| `+0x04` | `FB_BACK` | todos |
| `+0x08` | `SWAP` | todos |
| `+0x0C` | `STATUS` | todos |
| `+0x10` | `SWAP_COUNT` | desde 18 |
| `+0x14` | `HALT_AT` | implementado solo en CPU; en 22 lee cero |
| `+0x18` | `VIDEO_CTRL` | 16, 18, 19, 21 y 22 |

`STATUS` lleva el underflow pegajoso en el bit 0, el swap pendiente en el bit 1
y **el contador de frames en los bits 31:16** — de ahí que sea de 16 bits y no
de 32.

Divergencias que siguen vivas, y que MMIO v2 resuelve:

- **`HALT_AT` solo funciona en CPU.** En 22 la dirección responde —lee cero,
  escribir no hace nada— para que el bloque se pueda leer entero de una vez,
  pero el mecanismo no está: la GPU no se detiene sola, se para con las órdenes
  del monitor. En consecuencia `SWAP_COUNT` cuenta en 22 desde el reset y nada
  más, mientras que en 18, 19 y 21 cuenta desde el reset **o desde el último
  armado de `HALT_AT`**.
- **La alineación de las bases no está unificada.** CPU alinea a 4 bytes
  (`{merged_front[31:2], 2'b00}`), la 22 alinea a 16
  (`{fb_front[31:4], 4'b0000}`), y escribir una base mal alineada **no da
  error**: se truncan los bits bajos en silencio. Hoy hay que alinear a 16 para
  que un binario de vídeo valga en las dos familias.
- **El estado tras reset difiere.** La 21 arranca con bases cableadas; la 22 con
  `fb_front = fb_back = 0` y en modo PATTERN.

### Puerto serie — `0x80000200`, solo en 19 y 21

Dispositivo de colas sobre el UART del monitor, con `DATA` en `+0x00`, `STATUS`
en `+0x04` y `PEEK` en `+0x08`. Las dos carpetas son idénticas. Los offsets y la
semántica coinciden ya con MMIO v2.

### Configuración de warps — `0x80001000`, en 12, 14, 17 y 22

Ocho descriptores de 16 bytes: PC, `active`/`live`, `workgroup_id` y estado SIMT
de solo lectura. Escribir la cuarta palabra es error de bus.

**La ventana está llena al 100 %** —8 × 16 B sin un hueco—, que es justo lo que
la hace incómoda de ampliar, y la razón de que MMIO v2 le dé un bloque de
64 KiB.

**La GPU no llega a esta ventana**: `gpu_lsu2` solo deja pasar la primera página.

Los comandos run/halt/step/reset **no están aquí**: llegan por señales desde el
monitor, no por registros.

### Depuración SIMT — `0x80000100`, en 12, 14, 17 y 22

`CONTEXT`, slots de LSU, instrucciones retiradas globales y por warp, y el
primer error con su PC. Mismo decodificador en las cuatro, sin divergencias.
`error_code` `0x06` es `ERROR_SIMT`, el de un salto divergente sin `SSY` delante.

### Contadores de rendimiento — `0x80000300`

En 22, siete contadores de 32 bits legibles por host y GPU; escribir es fault.
En 16, 18, 19 y 21 los dos primeros —ciclos e instrucciones retiradas— también
están en MMIO desde la fase 3.5.

| Offset | Contador |
|---|---|
| `+0x00` | `CYCLES` |
| `+0x04` | `RETIRED` |
| `+0x08` | `IMEM_HITS` |
| `+0x0C` | `IMEM_MISSES` |
| `+0x10` | `LSU_TX` |
| `+0x14` | `VIDEO_TX` |
| `+0x18` | `STALL_MEM` |

Todos avanzan **solo con el núcleo corriendo**, y eso no es un detalle de
implementación sino el punto: con `CYCLES` libre, `profile.py` daba un CPI de 43
en vez de 15,6 — medía el reloj de pared.

Divergencia viva: la CPU **satura** a `0xFFFFFFFF` y la GPU **da la vuelta**. A
80 MHz son 54 segundos hasta saturar. MMIO v2 unifica en wrap y añade bandera de
desbordamiento.

### Identificación — `0x80000F00`

Cuatro palabras de solo lectura, en los diez prototipos con bitstream:

| Offset | Registro | Contenido |
|---|---|---|
| `+0x00` | `SYS_ID` | Magic `0x4D47` en 31:16 y **número de carpeta** en 7:0 |
| `+0x04` | `CONTRACT` | Versión del contrato de direcciones |
| `+0x08` | `DEV_BITMAP` | Cero, con el significado «sin declarar» |
| `+0x0C` | `ISA_PROFILE` | Perfil de ISA |

Escribirlas da error, y el resto del slot también: no devuelve cero ni repite
las cuatro palabras por alias.

## Conformidad con MMIO v2

Qué le falta a cada prototipo para cumplir [`../1.isa/mmio.md`](../1.isa/mmio.md).
**A los que faltan les falta lo mismo de fondo**: el mapa entero, porque v2
abandona la página de 4 KiB y los slots de 256 B. **La familia CPU entera ya lo
hizo** —6, 10, 16, 18, 19 y 21— y sólo quedan las cuatro de GPU. El camino está
contado paso a paso en seis bitácoras: la de la
[21](../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md), que es la completa; la de
la [19](../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md), que cuenta sólo lo que
cambió al repetirla y trae la estimación corregida; la de la
[18](../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md), que mide hasta dónde llega
el atajo de copiar de una carpeta gemela y es la primera sin puerto serie; la
de la [6](../6.fpga-cpu/docs/migracion-v2.md), que es la primera **sin ningún
bloque de dispositivo** y por tanto la forma que van a necesitar las de GPU; la
de la [10](../10.fpga-cpu-ram/docs/migracion-v2.md), que mide lo que cuesta una
gemela; y la de la [16](../16.fpga-cpu-hdmi/docs/migracion-v2.md), que lleva la
decisión del bitmap de vídeo.

| Prototipo | Qué cumple ya | Qué le falta |
|---|---|---|
| **6, 10** | **Conformes.** Bloque `SYSTEM` de siete palabras en `0x80000000`, con `DEVICES` (`0x009` la 6, EBR; `0x005` la 10, SDRAM), `MEM_BASE`/`MEM_SIZE` y `MONITOR_VERSION`. Su `sysid.v` es byte a byte el de las otras cuatro. **Siguen sin ventana de periféricos, por diseño**: no tienen decodificador y un programa no puede leer el bloque, que cuelga sólo del camino del monitor | Nada del mapa. La palabra 7 del bloque (`+0x1C`) da error como pide §5, y hace falta una comparación de más para ello porque siete palabras no son potencia de dos. Ver la bitácora de la [6](../6.fpga-cpu/docs/migracion-v2.md) |
| **16** | **Conforme.** Bloques de 64 KiB, `SYSTEM` de siete palabras, **los diez registros de vídeo** —gana `FRAME_COUNT` de 32 bits, `SWAP_COUNT`, `HALT_AT`, `HALT_TARGET` y `VIDEO_TX`, o sea `frame_capture`—, contadores con `PERF_CTRL`/`PERF_OVF0`, errores en vez de ceros y ningún `.asm` con la dirección cableada. Sin puerto serie: `DEVICES = 0x225` y **tres** ventanas de monitor. Cinco de sus ficheros MMIO son byte a byte los de 18/19/21 | Lo mismo que el resto de la familia: escrituras sub-palabra a MMIO (§4.1/§16.2). Su bloque único `sdram_system_adapter.v` hace de mux y de adaptador a la vez, así que **su banco sí migra**, al revés que en 18/19/21. Ver [la bitácora](../16.fpga-cpu-hdmi/docs/migracion-v2.md) |
| **21** | **Conforme.** Mapa de bloques de 64 KiB, `SYSTEM` con las siete palabras, vídeo con `FRAME_COUNT`/`HALT_TARGET`/`VIDEO_TX` y alineación por error, contadores con `PERF_CTRL`/`PERF_OVF0`, errores en vez de ceros, y ningún `.asm` con la dirección cableada | Escrituras sub-palabra a MMIO (§4.1/§16.2): documentado y fijado en `video_registers_tb.v`; hay que mover el host a `WRITE_WORD` a la vez. Ver [la bitácora](../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md) |
| **19** | **Conforme.** Lo mismo que la 21: bloques de 64 KiB, `SYSTEM` de siete palabras, vídeo con `FRAME_COUNT`/`HALT_TARGET`/`VIDEO_TX` y alineación por error, contadores con `PERF_CTRL`/`PERF_OVF0`, y ningún `.asm` con la dirección cableada. Sus seis ficheros MMIO compartidos son byte a byte los de la 21 | Lo mismo que la 21: escrituras sub-palabra a MMIO (§4.1/§16.2). Sintetizada, barrida y con semilla nueva fijada, y **validada en placa** el 20/09/2026. Ver [la bitácora](../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md) |
| **18** | **Conforme.** Lo mismo que la 19 y la 21: bloques de 64 KiB, `SYSTEM` de siete palabras, vídeo con `FRAME_COUNT`/`HALT_TARGET`/`VIDEO_TX` y alineación por error, contadores con `PERF_CTRL`/`PERF_OVF0`, errores en vez de ceros, y ningún `.asm` con la dirección cableada. Sus seis ficheros MMIO compartidos son byte a byte los de la 19 y la 21. Sin puerto serie, así que su `DEVICES` es `0x225` y tiene **tres** ventanas de monitor en vez de cuatro | Lo mismo que las otras dos: escrituras sub-palabra a MMIO (§4.1/§16.2). Sintetizada, barrida y con semilla nueva fijada, y **validada en placa** el 20/09/2026. Ver [la bitácora](../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md) |
| 12, 14, 17 | Warps y depuración SIMT; dos páginas | Direcciones v2; `GPU_CONTROL` y máscaras de warp; 32 warps |
| 22 | Vídeo, contadores, warps, depuración; MMIO abierto a la GPU | Direcciones v2; `GPU_CONTROL`; `HALT_AT` real; separar `VIDEO_TX` |
| 2, 11, 25 | Periféricos funcionales compartidos | `SYS_ID`; `HALT_AT` y serie en el RTL de GPU; retirar `plasma_nommio.asm` |

Transversal a todos, y lo que más trabajo lleva:

- **Acceso MMIO desde SIMT con varias lanes**: hoy se sirven por turnos, la de
  menor índice primero; v2 §4.2 exige error.
- **Alineación de framebuffer**: se trunca en silencio en todas menos la 18, la
  19, la 21 y los tres simuladores funcionales, donde ya es error; v2 §9.2 exige
  error.
- **Contadores**: unificar wrap, añadir `PERF_OVF` y `PERF_CTRL`, y mover
  `VIDEO_TX` a VIDEO.
- **`DEVICES`**: hoy `DEV_BITMAP` lee cero. v2 lo deriva del RTL.

## Validación y fuentes

Hay que comprobar las direcciones en todos los niveles, y cada uno responde a una
pregunta distinta:

- El **caso de prueba** describe accesos y capabilities requeridas.
- El **backend** identifica versión, capacidades y rangos de RAM.
- El **cliente del monitor** valida rangos y modalidades de transferencia.
- Los **adaptadores y decodificadores RTL** determinan el dispositivo real y sus
  errores.

`ARCHITECTURAL_REGIONS` describe los intervalos de RAM usados para validar
programas. En GPU, `MONITOR_REGIONS` añade las ventanas solo host. En las CPU con
vídeo y serie está **vacío y los dispositivos existen igualmente**: no se puede
inferir la ausencia de MMIO de que `MONITOR_REGIONS` esté vacío. Los intervalos
Python son normalmente semiabiertos.

Referencias principales:

- CPU: [mmio_decoder.v](../21.fpga-cpu-hdmi-alu/mmio_decoder.v),
  [video_registers.v](../21.fpga-cpu-hdmi-alu/video_registers.v),
  [serial_port.v](../21.fpga-cpu-hdmi-alu/serial_port.v),
  [cpu_dmem_adapter.v](../21.fpga-cpu-hdmi-alu/cpu_dmem_adapter.v),
  [top.v](../21.fpga-cpu-hdmi-alu/top.v),
  [monitor.py](../21.fpga-cpu-hdmi-alu/monitor.py).
- GPU: [gpu_system_bl8.v](../22.fpga-gpu-bl8/gpu_system_bl8.v),
  [gpu_video_regs.v](../22.fpga-gpu-bl8/gpu_video_regs.v),
  [gpu_perf_counters.v](../22.fpga-gpu-bl8/gpu_perf_counters.v),
  [monitor.py](../22.fpga-gpu-bl8/monitor.py),
  [gpu_system.v](../17.fpga-gpu-ram-v2/gpu_system.v).
- Por qué la 22 abrió el MMIO a la GPU y cómo:
  [mmio.md](../22.fpga-gpu-bl8/mmio.md).
- Simuladores: [minicpu_sim.py](../2.cpu-sim-func/minicpu_sim.py),
  [minigpu_sim.py](../11.gpu-sim-func/minigpu_sim.py).

## Bring-up

Las carpetas anteriores a la CPU, para tener el cuadro entero:

| Carpeta | Qué es | Fmax / objetivo | LUT / FF |
|---|---|---|---|
| [3.fpga](../3.fpga) | Un LED: que la cadena de síntesis y carga funciona | 295,4 / 25 | 31 / 24 |
| [4.fpga-uart](../4.fpga-uart) | UART a 3 Mbaud | 166,9 / 120 | 190 / 102 |
| [5.fpga-monitor](../5.fpga-monitor) | Monitor UART sobre 16 KiB de EBR | 139,8 / 120 | 331 / 148 |
| [7.ulx3s_w9825g6kh_test](../7.ulx3s_w9825g6kh_test) | Prueba autónoma de la SDRAM | 136,1 / 25 | 315 / 191 |
| [8.fpga-ram](../8.fpga-ram) | SDRAM a través del monitor | 119,0 / 25 | 651 / 336 |
| [9.fpga-ram-param](../9.fpga-ram-param) | Controlador SDRAM parametrizado | 120,6 / 120 | 813 / 406 |

[13.hdmi](../13.hdmi) no aparece porque es la cadena DVI/TMDS suelta, sin monitor
ni memoria que comparar; de ahí sale el vídeo de la 16 en adelante.
