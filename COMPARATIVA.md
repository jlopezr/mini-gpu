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
  [`x.cpu-tests`](x.cpu-tests), y son las mismas que un caso pide con
  `requires`.

**Cuidado con el Fmax.** Mide caminos dentro del chip y no dice nada de lo que
entra por un pin. La 19 tuvo un fallo real de captura de DQ y el barrido de
semillas daba +14,5 % de holgura con el diseño roto.

## CPU

|                             | [2.sim](2.cpu-sim-func) | [6.ebr](6.fpga-cpu) | [10.sdram](10.fpga-cpu-ram) | [16.hdmi](16.fpga-cpu-hdmi) | [18.bl8](18.fpga-cpu-hdmi-bl8) | [19.ls](19.fpga-cpu-hdmi-ls) | [21.alu](21.fpga-cpu-hdmi-alu) |
|-----------------------------|-------------------------|---------------------|-----------------------------|-----------------------------|--------------------------------|------------------------------|--------------------------------|
| **Fmax / objetivo**         | —                       | 127,3 / 120         | 126,2 / 120                 | 113,0 / 100                 | 94,5 / 80                      | 89,2 / 80                    | 91,8 / 80                      |
| **Memoria**                 | 32 MiB unificada        | 2 × 16 KiB EBR      | 32 MiB SDRAM                | 32 MiB SDRAM                | 32 MiB SDRAM                   | 32 MiB SDRAM                 | 32 MiB SDRAM                   |
| **LUT / FF**                | —                       | 5 664 / 2 466       | 4 962 / 2 249               | 6 782 / 3 164               | 9 128 / 4 617                  | 9 888 / 4 735                | 10 221 / 4 799                 |
| **Monitor / baudios**       | —                       | **1.16** / 3 M      | **1.17** / 3 M              | **1.18** / 1 M              | **1.19** / 1 M                 | **1.20** / 1 M               | 1.15 / 1 M                     |
| **`R0` cableado a cero**    | sí                      | sí                  | sí                          | sí                          | sí                             | sí                           | sí                             |
| ALU, saltos, `LOAD`/`STORE` | sí                      | sí                  | sí                          | sí                          | sí                             | sí                           | sí                             |
| `MUL`, `MULFX`, `DIV`       | sí                      | sí                  | **no**                      | sí                          | sí                             | sí                           | sí                             |
| `video`                     | sí                      | no                  | no                          | sí                          | sí                             | sí                           | sí                             |
| `frame_capture`             | sí                      | no                  | no                          | no                          | sí                             | sí                           | sí                             |
| `subword_memory`            | sí                      | no                  | no                          | no                          | no                             | sí                           | sí                             |
| `calls`                     | sí                      | no                  | no                          | no                          | no                             | sí                           | sí                             |
| `serial`                    | sí                      | no                  | no                          | no                          | no                             | sí                           | sí                             |
| `shift_immediate`           | sí                      | no                  | no                          | no                          | no                             | no                           | sí                             |
| `alu_extended`              | sí                      | no                  | no                          | no                          | no                             | no                           | sí                             |
| Contadores de ciclos        | no                      | no                  | no                          | no                          | sí                             | sí                           | sí                             |
| Ráfagas BL8                 | —                       | —                   | no                          | no                          | sí                             | sí                           | sí                             |

`2.sim` no tiene Fmax ni LUTs porque no es hardware, y tampoco tiene contadores
de ciclos: no modela el tiempo. Lo que sí da es el número de instrucciones, que
es arquitectónico y por eso sirve de contraste contra el contador de la placa.

**El simulador va por delante del RTL, y eso es lo normal:** es donde se prueba
primero una instrucción nueva. Hoy tiene las siete capacidades; la 21 es el
único bitstream que también.

### `R0` a cero no es una capacidad, y por eso está en negrita

Es la **única fila de esta tabla que vale «sí» en todas las columnas**, y no por
casualidad: es una regla de la MiniISA, no algo que un bitstream pueda tener o
no. Ver [`1.isa/isa.md`](1.isa/isa.md) §1.

Lo fue durante un tiempo —la capacidad se llamaba `zero_register` y solo la
tenía la 21— y fue la **única capacidad no aditiva** que ha tenido este
repositorio. Las demás se detectan solas: un bitstream que no las tenga para con
`ERROR_INVALID_OPCODE` y se nota. Con `R0` general no hay parada; hay otro
resultado, en silencio. Una capacidad sirve para omitir un caso con criterio, no
para tapar una divergencia muda entre dos backends que el diferencial compararía.

Por eso se aplicó a las **nueve implementaciones a la vez** —seis de CPU, tres
de GPU, más el simulador de cada una— y por eso las nueve subieron la versión de
su monitor: 1.16–1.20 en CPU y 2.3–2.4 en GPU, sin tocar ni un byte del
protocolo. El número de versión es la única defensa contra grabar el bitstream
equivocado y no enterarse.

### `10.sdram` no implementa `MUL`, `MULFX` ni `DIV`

Esa fila decía «sí» para las siete columnas y **era falsa**. La 10 declara los
tres opcodes y valida su encoding, pero no tiene rama en el `case` del estado
EXECUTE, así que caen al `default` y dan `ERROR_INVALID_OPCODE`. Es el único
core al que le pasa; la 6, que es anterior, sí las implementa.

Se descubrió al correr el diferencial contra esa placa por primera vez —el
backport obligó a probar las seis— y **no se ha arreglado**: implementarlas es
añadir funcionalidad a un hito cerrado, que es otra decisión. El caso
`cases/alu/multiply` falla ahí, y es un fallo honesto que apunta a algo real.

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

| | [11.sim](11.gpu-sim-func) | [12.bram](12.fpga-gpu) | [14.sdram](14.fpga-gpu-ram) | [17.sdram-v2](17.fpga-gpu-ram-v2) |
|---|---|---|---|---|
| **Fmax / objetivo** | — | 36,4 / 25 | 33,6 / 25 | 50,6 / 25 |
| **Memoria** | unificada, hasta 32 MiB | 128 KiB BRAM | 32 MiB SDRAM | 32 MiB SDRAM |
| **LUT / FF** | — | 35 791 / 9 137 | 30 744 / 9 016 | 29 171 / 10 090 |
| **Monitor / baudios** | — | **2.3** / 250 k | **2.4** / 250 k | **2.4** / 250 k |
| **`R0` cableado a cero** | sí | sí | sí | sí |
| Warps × lanes | 8 × 8 configurable | 8 × 8 | 8 × 8 | 8 × 8 |
| SIMT (`SSY`, `BAR`, `EXIT`) | sí | sí | sí | sí |
| `atomic_warp_faults` | sí | no | no | no |
| `video` | no | no | no | no |
| `subword_memory` | no | no | no | no |
| `calls` | no | no | no | no |

La **17** es la 14 con el mismo comportamiento y el camino crítico reescrito:
sigue ganándole unos 12 MHz con menos LUTs. Está restringida a 25 porque ese era
el objetivo; el margen es la ganancia.

**El guardián de `R0` va en otro sitio en la GPU**, y por una razón que conviene
no perder. En la MiniCPU vive dentro de `register_file.v`, porque allí el banco
son flops con reset y basta con no escribir la entrada 0: queda a cero por
construcción y yosys hasta elimina los flops. En la GPU el banco es **BRAM y no
tiene reset**; lo pone a cero un barrido de 256 ciclos que el propio SM hace en
su estado `INIT`, por ese mismo puerto de escritura.

Si el guardián estuviera dentro del banco bloquearía también ese barrido, `R0`
no se inicializaría nunca, y en la placa saldría cero —el EBR arranca a cero—
mientras que en simulación se quedaría a `X` para siempre. Así que va en
`gpu_sm.v`, dejando el barrido fuera: lo escribe una vez y ninguna instrucción
vuelve a tocarlo. Misma invariante, distinto sitio, y ningún coste en el camino
de lectura, que en la GPU ya está registrado.

Ahí el argumento de área que en la CPU descartamos por irrelevante tampoco
aplica al revés: son 8 lanes × 8 warps × 32 registros, o sea 2 048 palabras, pero
al ser BRAM no se ahorra nada por no escribir una de ellas.

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
| [3.fpga](3.fpga) | Un LED: que la cadena de síntesis y carga funciona | 295,4 / 25 | 31 / 24 |
| [4.fpga-uart](4.fpga-uart) | UART a 3 Mbaud | 166,9 / 120 | 190 / 102 |
| [5.fpga-monitor](5.fpga-monitor) | Monitor UART sobre 16 KiB de EBR | 139,8 / 120 | 331 / 148 |
| [7.ulx3s_w9825g6kh_test](7.ulx3s_w9825g6kh_test) | Prueba autónoma de la SDRAM | 136,1 / 25 | 315 / 191 |
| [8.fpga-ram](8.fpga-ram) | SDRAM a través del monitor | 119,0 / 25 | 651 / 336 |
| [9.fpga-ram-param](9.fpga-ram-param) | Controlador SDRAM parametrizado | 120,6 / 120 | 813 / 406 |

[13.hdmi](13.hdmi) no aparece porque es la cadena DVI/TMDS suelta, sin monitor
ni memoria que comparar; de ahí sale el vídeo de la 16 en adelante.

## Cómo mantener esta tabla

Los números salen de los `_build/`, así que se quedan viejos en cuanto alguien
sintetiza. Para regenerar los de una carpeta:

```powershell
.\.venv\Scripts\apio.exe build -p .\19.fpga-cpu-hdmi-ls
.\tools\seed-sweep.ps1 -ProjectDir 19.fpga-cpu-hdmi-ls -Seeds @(1,2,3,4,5,6,7,8)
```

Y las capacidades de CPU, sin abrir nada:

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'x.cpu-tests'); from backends import fpga, simulator; print('sim', sorted(simulator.capabilities())); [print(v, sorted(fpga.capabilities(v))) for v in fpga.VERSIONS]"
```

```text
sim     ['alu_extended', 'calls', 'frame_capture', 'serial', 'shift_immediate', 'subword_memory', 'video', 'zero_register']
ebr     []
sdram   []
hdmi    ['video']
bl8     ['frame_capture', 'video']
subword ['calls', 'frame_capture', 'serial', 'subword_memory', 'video']
alu     ['alu_extended', 'calls', 'frame_capture', 'serial', 'shift_immediate', 'subword_memory', 'video', 'zero_register']
```
