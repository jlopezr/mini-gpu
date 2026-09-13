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
| **Fmax / objetivo**         | —                       | 124,4 / 120         | 130,7 / 120                 | 112,9 / 100                 | 94,8 / 80                      | 87,9 / 80                    | **91,8** / 80                  |
| **Memoria**                 | 32 MiB unificada        | 2 × 16 KiB EBR      | 32 MiB SDRAM                | 32 MiB SDRAM                | 32 MiB SDRAM                   | 32 MiB SDRAM                 | 32 MiB SDRAM                   |
| **LUT / FF**                | —                       | 5 650 / 2 466       | 4 976 / 2 249               | 6 785 / 3 164               | 9 101 / 4 617                  | 9 887 / 4 735                | 10 221 / 4 799                 |
| **Monitor / baudios**       | —                       | 1.6 / 3 M           | 1.5 / 3 M                   | 1.10 / 1 M                  | 1.12 / 1 M                     | 1.14 / 1 M                   | **1.15** / 1 M                 |
| ALU, saltos, `LOAD`/`STORE` | sí                      | sí                  | sí                          | sí                          | sí                             | sí                           | sí                             |
| `MUL`, `MULFX`, `DIV`       | sí                      | sí                  | sí                          | sí                          | sí                             | sí                           | sí                             |
| `video`                     | sí                      | no                  | no                          | sí                          | sí                             | sí                           | sí                             |
| `frame_capture`             | sí                      | no                  | no                          | no                          | sí                             | sí                           | sí                             |
| `subword_memory`            | sí                      | no                  | no                          | no                          | no                             | sí                           | sí                             |
| `calls`                     | sí                      | no                  | no                          | no                          | no                             | sí                           | sí                             |
| `serial`                    | sí                      | no                  | no                          | no                          | no                             | sí                           | sí                             |
| `shift_immediate`           | sí                      | no                  | no                          | no                          | no                             | no                           | **sí**                         |
| `alu_extended`              | sí                      | no                  | no                          | no                          | no                             | no                           | **sí**                         |
| `zero_register`             | sí                      | no                  | no                          | no                          | no                             | no                           | **sí**                         |
| Contadores de ciclos        | no                      | no                  | no                          | no                          | sí                             | sí                           | sí                             |
| Ráfagas BL8                 | —                       | —                   | no                          | no                          | sí                             | sí                           | sí                             |

`2.sim` no tiene Fmax ni LUTs porque no es hardware, y tampoco tiene contadores
de ciclos: no modela el tiempo. Lo que sí da es el número de instrucciones, que
es arquitectónico y por eso sirve de contraste contra el contador de la placa.

**El simulador va por delante del RTL, y eso es lo normal:** es donde se prueba
primero una instrucción nueva. Hoy tiene las ocho capacidades; la 21 es el único
bitstream que también.

**La 21 está sintetizada pero no probada en placa.** Simulador, testbenches y
`x.cpu-tests` con el backend de simulador están en verde, y el bitstream existe:
**las ocho semillas cumplen**, entre 84,04 y 91,80 MHz, y se fija la 6 con
+14,8 %. Es el mejor margen que ha tenido esta familia. Lo que falta es la
placa: la ULX3S no estaba disponible, así que nada de esto se ha visto correr en
hardware.

Y **el margen sube pese a los ~330 LUTs de más** respecto a la 19. No es que el
diseño sea más rápido: el camino crítico sigue siendo `sdram_clk` —adaptador,
árbitro y controlador—, el mismo sitio desde la 18, y ninguno de los cuatro
cambios lo toca. Lo que ha pasado es que este netlist se coloca mejor, que es
exactamente la lección del aviso de arriba leída en la dirección agradable.

**`zero_register` es la primera capacidad incompatible de la tabla.** Las otras
siete son aditivas: un bitstream que no las tenga para con opcode inválido y se
nota. Con `R0` a cero no hay parada; hay otro resultado, en silencio. Por eso el
salto de monitor a 1.15 importa más que los anteriores, y por eso la 19 sigue
siendo válida tal cual en vez de quedar obsoleta: allí `R0` es un registro
general y los programas de esa carpeta cuentan con ello.

**La 19 saltó a 1.13 sin añadir ni un comando al protocolo de la 18**, y la 21
hace lo mismo al saltar a 1.15 desde el 1.14 de la 19 (1.14 sí añadió los dos
comandos del puerto serie). Las instrucciones nuevas viven enteras dentro de la
CPU. Suben la versión igual porque `GET_VERSION` es lo único que el PC puede
preguntar antes de cargar un programa, y un programa que use `JAL` o `LOADB` no
corre en un bitstream 1.12:
para con opcode inválido a la primera. Con las dos respondiendo 1.12,
`x.cpu-tests` daría por bueno el bitstream equivocado. Es el mismo criterio por
el que 14 responde 2.2 compartiendo todos los comandos con 12.

### Por qué la frecuencia baja según avanza la lista

No es que la CPU empeore. El camino crítico se mudó:

- La **6** y la **10** cierran a 120 MHz con una CPU sola colgada de memoria.
- La **16** baja a 100 porque entra el vídeo, que compite por la SDRAM.
- La **18** baja a 80 al pasar el camino de memoria a 128 bits para ráfagas
  BL8. A 100 no cumplía ninguna semilla (83,9 a 91,8 MHz). A cambio, el bucle
  interior de `swap_demo_fast` pasa de 146 a 64 ciclos por palabra: el diseño
  es más lento por ciclo y mucho más rápido por trabajo hecho.
- La **19** pierde unos 5 MHz respecto a la 18 por crecer ~280 LUTs, no por las
  instrucciones nuevas en sí: el camino crítico sigue estando en el handshake de
  memoria —adaptador, árbitro y controlador—, el mismo sitio que en la 18. La
  semilla 6, que era la fijada antes de añadir `JAL`/`JALR`/`JR`, da el mismo
  margen con ellas que sin ellas.
- La **21 rompe la tendencia**: sube a 91,8 MHz creciendo ~330 LUTs sobre la
  19, y con el multiplicador construyendo ahora siempre los 64 bits. Como en
  los casos anteriores, el camino crítico no se movió de `sdram_clk`; lo que
  cambió fue la colocación. Sirve de contraejemplo a la lectura fácil de esta
  lista: la frecuencia de un netlist no es una función monótona del tamaño del
  diseño.

## GPU

| | [11.sim](11.gpu-sim-func) | [12.bram](12.fpga-gpu) | [14.sdram](14.fpga-gpu-ram) | [17.sdram-v2](17.fpga-gpu-ram-v2) |
|---|---|---|---|---|
| **Fmax / objetivo** | — | 36,4 / 25 | 33,6 / 25 | 50,6 / 25 |
| **Memoria** | unificada, hasta 32 MiB | 128 KiB BRAM | 32 MiB SDRAM | 32 MiB SDRAM |
| **LUT / FF** | — | 35 791 / 9 137 | 30 744 / 9 016 | 29 171 / 10 090 |
| **Monitor / baudios** | — | 2.1 / 250 k | 2.2 / 250 k | 2.2 / 250 k |
| Warps × lanes | 8 × 8 configurable | 8 × 8 | 8 × 8 | 8 × 8 |
| SIMT (`SSY`, `BAR`, `EXIT`) | sí | sí | sí | sí |
| `atomic_warp_faults` | sí | no | no | no |
| `video` | no | no | no | no |
| `subword_memory` | no | no | no | no |
| `calls` | no | no | no | no |

La **17** es la 14 con el mismo comportamiento y el camino crítico reescrito:
50,6 MHz frente a 33,6, y menos LUTs. Sigue restringida a 25 porque ese era el
objetivo; el margen es la ganancia.

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
