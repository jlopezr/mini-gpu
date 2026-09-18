# Comparativa de simuladores y RTL

Qué sabe hacer cada implementación, cuánta memoria ve y a qué frecuencia cierra.

Las carpetas numeradas son hitos de aprendizaje y se conservan tal cual, así que
lo normal es que **ninguna las tenga todas**: la más reciente no reemplaza a las
anteriores, y una capacidad que aparece en la 19 no está en la 18 aunque la 18
sea «la misma CPU». Esta tabla existe para no tener que abrir cinco `README.md`
para averiguarlo.

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

<!-- BEGIN GENERATED: cpu-matrix -->
| | [2.sim](../2.cpu-sim-func) | [6.ebr](../6.fpga-cpu) | [10.sdram](../10.fpga-cpu-ram) | [16.hdmi](../16.fpga-cpu-hdmi) | [18.bl8](../18.fpga-cpu-hdmi-bl8) | [19.subword](../19.fpga-cpu-hdmi-ls) | [21.alu](../21.fpga-cpu-hdmi-alu) |
|---|---|---|---|---|---|---|---|
| **Reloj** | — | 100 MHz | 100 MHz | 100 MHz | 80 MHz | 80 MHz | 80 MHz |
| **Fmax / objetivo** | — | 104.4 / 100 | 115.6 / 100 | 105.0 / 100 | 84.0 / 80 | 83.9 / 80 | 89.7 / 80 |
| **Memoria** | — | 32 KiB | 32 MiB | 32 MiB | 32 MiB | 32 MiB | 32 MiB |
| **LUT / FF** | — | 5 978 / 2 622 | 5 342 / 2 477 | 7 496 / 3 566 | 9 830 / 4 918 | 10 535 / 5 001 | 10 867 / 5 066 |
| **Monitor** | — | 3.6 | 3.10 | 3.16 | 3.18 | 4.19 | 4.21 |
| **Baudios** | — | 1 M | 1 M | 1 M | 1 M | 1 M | 1 M |
| `mul_div` | sí | sí | no | sí | sí | sí | sí |
| `subword_memory` | sí | no | no | no | no | sí | sí |
| `calls` | sí | no | no | no | no | sí | sí |
| `shift_immediate` | sí | no | no | no | no | no | sí |
| `alu_extended` | sí | no | no | no | no | no | sí |
| `compare` | sí | no | no | no | no | no | sí |
| `frame_capture` | sí | no | no | no | sí | sí | sí |
| `serial` | sí | no | no | no | no | sí | sí |
<!-- END GENERATED: cpu-matrix -->

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
bajó de 120 a 100 y la 18 de 100 a 80. Pero aquí bajar el reloj arrastra el
puerto serie: **120 MHz / 40 = 3 Mbaud exacto**, y a 100 MHz el divisor saldría
33,33. Cambiaría el baudio, el monitor y su versión. Es mucho más que copiar un
fichero, así que se deja como está.

Lo que sí se hizo: **quitar de su `cpu.v` los tres `localparam`**. Estaban
declarados y validados en el `case` de encoding pero sin rama en el EXECUTE, así
que el resultado era correcto —`ERROR_INVALID_OPCODE`— y el código mentía:
aparentaba soportarlas. Ahora el fichero dice la verdad. `x.tests` lo declara
como la capacidad **`mul_div`**, y `cases/alu/multiply` se omite ahí con un
`SKIP` en vez de fallar.

`mul_div` es la única capacidad del runner que significa «a este le **falta**
algo de la base» en lugar de «este tiene algo **de más**». El día que la 10
implemente las tres, la capacidad desaparece entera.

**La versión del monitor sube sin que cambie el protocolo, y es lo normal aquí.**
La 19 saltó a 1.13 sin añadir ni un comando a los de la 18, la 21 a 1.15, y el
backport de `R0` movió las cinco anteriores a 1.16–1.20. `GET_VERSION` es lo
único que el PC puede preguntar antes de cargar un programa, así que es el único
sitio donde puede vivir «este bitstream no es el que crees».

**Y el número no significa antigüedad.** La 21 responde 1.15 y la 6 responde
1.16, que es más alto y mucho más viejo. Nunca lo significó: la 10 ya respondía
1.5 siendo posterior a la 6 con su 1.6. Es un identificador, no una fecha.

Lo que sí hace falta es que sean **distintos entre sí**, porque si dos
bitstreams respondieran lo mismo, `--version ebr` con el de `sdram` cargado
pasaría en silencio y el diagnóstico se perdería. La excepción consciente son
14 y 17, que comparten número porque son funcionalmente idénticas y solo se
diferencian en el camino crítico.

### Por qué la frecuencia baja según avanza la lista

No es que la CPU empeore. El camino crítico se mudó:

- La **6** y la **10** cierran a 120 MHz con una CPU sola colgada de memoria.
  La 10 lo hace además sin multiplicador ni divisor, que no implementa; comparar
  su Fmax con el de la 6 no es comparar lo mismo.
- La **16** baja a 100 porque entra el vídeo, que compite por la SDRAM.
- La **18** baja a 80 al pasar el camino de memoria a 128 bits para ráfagas
  BL8. A 100 no cumplía ninguna semilla (83,9 a 91,8 MHz). A cambio, el bucle
  interior de `swap_demo_fast` pasa de 146 a 64 ciclos por palabra: el diseño
  es más lento por ciclo y mucho más rápido por trabajo hecho.
- La **19** pierde unos 5 MHz respecto a la 18 por crecer ~760 LUTs, no por las
  instrucciones nuevas en sí: el camino crítico sigue estando en el handshake de
  memoria —adaptador, árbitro y controlador—, el mismo sitio que en la 18.
- La **21 rompe la tendencia**: sube a 91,8 MHz creciendo ~330 LUTs sobre la
  19, y con el multiplicador construyendo ahora siempre los 64 bits. Como en
  los casos anteriores, el camino crítico no se movió de `sdram_clk`; lo que
  cambió fue la colocación. Sirve de contraejemplo a la lectura fácil de esta
  lista: la frecuencia de un netlist no es una función monótona del tamaño del
  diseño.

**Todos estos números se rehicieron con el backport de `R0`**, y hay una lección
en eso que merece quedarse. El cambio es **una línea** en `register_file.v`, la
misma en los seis cores, y aun así:

- **la 10 dejó de cumplir**, en 117,3 MHz sobre un objetivo de 120, con la
  semilla por defecto y **menos** lógica que antes (4 962 LUTs frente a 4 976).
  Ahora lleva semilla fija por primera vez;
- la 19 cayó de 87,2 a 83,7 con la semilla que tenía puesta;
- y rebarridas las seis, **cinco acabaron con más margen que antes**.

Ninguna de esas tres cosas dice nada sobre si el diseño mejoró o empeoró. Dicen
que el netlist cambió lo justo para que el placer tomara otras decisiones, que
es lo que avisa el segundo punto de «De dónde salen estos números» y aquí se
cobró de verdad.

## GPU

<!-- BEGIN GENERATED: gpu-matrix -->
| | [25.sim](../25.gpu-sim-cycle-uarch) | [11.sim](../11.gpu-sim-func) | [12.bram](../12.fpga-gpu) | [14.sdram](../14.fpga-gpu-ram) | [17.fpga-gpu-ram-v2](../17.fpga-gpu-ram-v2) | [22.lsu2](../22.fpga-gpu-bl8) |
|---|---|---|---|---|---|---|
| **Reloj** | — | — | 25 MHz | 25 MHz | 25 MHz | 25 MHz |
| **Fmax / objetivo** | — | — | 33.6 / 25 | 32.0 / 25 | 48.1 / 25 | 36.8 / 25 |
| **Memoria** | — | — | 128 KiB | 32 MiB | 32 MiB | 32 MiB |
| **LUT / FF** | — | — | 37 336 / 9 365 | 32 535 / 9 244 | 31 519 / 10 318 | 35 393 / 12 560 |
| **Monitor** | — | — | 3.12 | 3.14 | 3.17 | 3.22 |
| **Baudios** | — | — | 250 k | 250 k | 250 k | 250 k |
| `warp_config` | no | no | sí | sí | sí | sí |
| `simt_debug` | no | no | sí | sí | sí | sí |
| `atomic_warp_faults` | sí | sí | no | no | no | no |
<!-- END GENERATED: gpu-matrix -->
La **17** es la 14 con el mismo comportamiento y el camino crítico reescrito:
sigue ganándole unos 12 MHz con menos LUTs. Está restringida a 25 porque ese era
el objetivo; el margen es la ganancia.

**Las tres GPU no llevan semilla fija, a diferencia de las de CPU.** Rebarridas
tras el backport, **las ocho semillas cumplen en las tres**, con márgenes del
+18,8 % de la peor de la 14 al +111 % de la mejor de la 17. Aquí la semilla no
decide si el diseño funciona —ni la peor se acerca al objetivo— así que fijarla
solo serviría para que estos números fueran reproducibles, a cambio de tener que
rebarrer con cada cambio de RTL. En las carpetas de CPU sí se fija, porque allí
el margen se mide en unidades y no en decenas: la 10 llegó a **no cumplir** con
la semilla por defecto después de una sola línea de cambio.


Ninguna implementación de GPU tiene todavía los accesos sub-palabra ni las
llamadas. El backport de las dos extensiones a la MiniGPU está pendiente, y
`JALR`/`JR` en SIMT tienen además un problema propio: un salto indirecto puede
producir tantos destinos distintos como lanes activas, y la maquinaria de `SSY`
está construida para divergencias de dos caminos. Habrá que exigir destino
uniforme entre las lanes activas, y que quede escrito en la ISA antes de que
aparezca código que suponga lo contrario.

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

