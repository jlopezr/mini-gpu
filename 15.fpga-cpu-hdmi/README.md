# MiniCPU con SDRAM y salida HDMI

Fusión de la CPU con SDRAM de `10.fpga-cpu-ram` y la cadena DVI de `13.hdmi`,
sobre ULX3S-85F. El plan por fases está en [`docs/planning.md`](docs/planning.md)
y la arquitectura de destino en
[`docs/gpu_educativa_arquitectura.md`](docs/gpu_educativa_arquitectura.md).

Estado: **hito B completado**. Hay imagen por HDMI generada a través del doble
line buffer, con el escalado 2× ya funcionando, pero **la CPU y el vídeo todavía
no se comunican**: las líneas las calcula lógica, no se lee ni un byte de SDRAM.

## Escalera de hitos

| Hito | Contenido | Estado |
|---|---|---|
| A | Fusión: CPU de 10 intacta + 640×480p60 con patrón generado por lógica | **hecho** |
| B | Doble line buffer, cruce de dominios y escalado 2×, con productor falso | **hecho** |
| C | Scanout real: la CPU escribe el framebuffer en SDRAM y se ve | pendiente |
| D | Registro `FB_BASE` y doble framebuffer con swap en VBlank | pendiente |

La separación importa: si en el hito C la pantalla sale negra, A y B ya han
descartado el pinout, los PLL, la codificación TMDS y el cruce de dominios.

## Qué hay en el hito A

Dos subsistemas independientes en la misma FPGA, sin más recurso compartido que
el cristal de 25 MHz:

```text
clk_25mhz ─┬─ pll_120 ──── 120 MHz ── CPU + monitor UART + SDRAM
           │
           └─ clock2_gen ─┬─ 125,0 MHz ── serializador TMDS
                          └─  25,0 MHz ── simple_480p → video_pattern → DVI → gpdi
```

La mitad de CPU es byte a byte la de 10: mismo mapa de memoria unificado de
32 MiB, mismos comandos de monitor, mismos cinco bancos de prueba. Lo único que
cambia es la **versión del monitor, ahora 1.7**, para que
`run_gpu_tests.py --backend cpu-fpga --version hdmi` distinga este bitstream del
1.5 de 10 y del 1.6 de 6.

### Modo de vídeo

640×480p60 con polaridad negativa en ambos sincronismos
([`simple_480p.sv`](simple_480p.sv)). El PLL entrega 125,0 y 25,0 MHz desde un
VCO de 625 MHz; los 25,0 MHz son un 0,7 % más lentos que los 25,175 nominales,
aproximación equivalente a la que hacía 13 con 74 frente a 74,25 MHz para 720p.

Bajar de 720p a 480p no es un capricho: el reloj serie TMDS pasa de 370 a
125 MHz, y con él desaparece el margen ajustado que obligaba a 13 a fijar la
semilla de nextpnr por el vídeo. Aquí sobra: 395 MHz alcanzados sobre 125
exigidos.

### Lo que se ve

Ocho barras verticales de 80 px, una banda blanca que baja cuatro líneas por
frame y una rejilla de puntos cada 64 px. La banda distingue una imagen viva de
una congelada; la rejilla revela recortes o sobreescaneo del monitor.

Sigue disponible: **con FIRE1 pulsado la salida vuelve a este patrón**, saltándose
el line buffer por completo. Es el instrumento que separa «falla la cadena HDMI»
de «falla el camino de datos».

## Qué hay en el hito B

El doble line buffer y el cruce de dominios, con el escalado 2× ya montado. El
productor de líneas sigue siendo falso: calcula el contenido en lugar de leerlo
de SDRAM.

```text
   dominio de sistema, 120 MHz          dominio de pixel, 25 MHz
   ───────────────────────────          ────────────────────────

   video_line_source_pattern
        │  (hito C: lector SDRAM)
        ▼
   escritura ─────► line_buffer ──────► lectura, cada pixel y
                     2 bancos            cada linea por duplicado
                                              │
                     handshake                ▼
        fill_start ◄──────────────── peticion de linea
        fill_done  ────────────────► banco listo
```

### Por qué doble banco y no una FIFO asíncrona

Por el escalado vertical. Con una FIFO de flujo, mostrar cada línea fuente dos
veces obliga al productor a **leerla dos veces de SDRAM**: 18,4 MB/s en lugar de
9,2. Con dos bancos el lector relee el banco que ya tiene y la SDRAM se queda en
9,2 MB/s. Dado lo justo que va la temporización (más abajo), ese margen no está
para regalarlo.

De paso el cruce de dominios sale más simple: un handshake petición/respuesta de
dos fases con **una sola petición viva**, en vez de punteros Gray y contadores
libres. Manda el lector: decide qué línea toca y en qué banco, así que el
productor no lleva contador propio y no puede desincronizarse del barrido.

Los buses `fill_line` y `fill_bank` no se sincronizan: cambian en el mismo flanco
de píxel que el toggle y no vuelven a cambiar hasta dos líneas de pantalla
después, así que llevan estables más de un ciclo de 120 MHz cuando el pulso
sincronizado llega al otro lado. Es el patrón habitual de dato acompañando a un
toggle.

### Underflow

Si al cambiar de banco el productor no ha terminado, se activa `underflow`, que
es pegajoso hasta el reset y sale por **`led[0]`** (que deja de mostrar
`last_command[0]`). En pantalla un underflow solo se ve como una imagen rota, que
puede confundirse con muchas otras cosas.

`video_scanout_tb.v` instancia **dos** sistemas: uno con productor rápido, que
debe dar imagen correcta y nunca marcar underflow, y otro con productor
deliberadamente lento, que **debe** marcarlo. Un detector que no se dispara nunca
no sirve de nada en el hito C.

El banco usa una pantalla de 32×16 con fuente de 16×8 en lugar de 640×480: la
lógica ejercitada es la misma y un frame baja de 420 000 ciclos de píxel a 960.

### El primer frame tras reset es basura

Al arrancar, el barrido ya está en marcha y no ha habido blanking vertical en el
que prellenar los bancos. La máquina se resincroniza en el siguiente
`frame_start` y a partir de ahí la imagen es correcta. No se marca underflow por
esto: solo se vigila el estado activo.

## Temporización: el dominio de CPU ya no cumple

| Dominio | Restricción | 10.fpga-cpu-ram | 15 tras hito A | 15 tras hito B |
|---|---:|---:|---:|---:|
| CPU + SDRAM | 120 MHz | 130,67 MHz | 123,32 MHz | **119,85 MHz** |
| Pixel | 25 MHz | — | 160,28 MHz | 102,91 MHz |
| TMDS 5× | 125 MHz | — | 395,10 MHz | 355,24 MHz |

Barrido de ocho semillas tras el hito B:

```text
106,73  107,85  107,98  109,72  112,71  113,08  113,78  119,85 MHz
```

**Ninguna llega a 120.** La mejor se queda a 0,15 MHz, y eso es suerte, no
diseño. Ya no es dispersión de semillas: la mediana ha caído de ~123 a ~111.

Lo importante es que **no hay ningún camino crítico nuevo**. El camino es
enteramente interno a la CPU:

```text
instruction → decodificación de shift_kind → step_active → branch_taken → pc
8,34 ns totales: 1,9 de lógica y 4,9 de routing
```

Ni un bloque de vídeo aparece en él. Lo que ha empeorado es el *routing*, porque
el emplazador tiene menos libertad. Con el dado un 6,6 % ocupado, la palabra
«congestión» sobra: es que el netlist tiene ahora dos dominios con restricción y
el reparto cambia.

Quedan tres salidas, por orden de lo que costaría:

1. **Seguir a 120 MHz con semilla fijada.** Es lo que hay ahora (`--seed 6`).
   Funciona, pero cada cambio de RTL vuelve a ser una lotería.
2. **Bajar la CPU a 100 MHz.** `CLK_FREQ_HZ` y el controlador SDRAM ya están
   parametrizados, así que el cambio real es el divisor de UART: con `DIVISOR=40`
   la velocidad pasaría de 3 a 2,5 Mbaud, y habría que ajustar `BAUDRATE` en
   `monitor.py`. Como esta carpeta tiene su propio `monitor.py`, el cambio queda
   contenido. Cuesta un 17 % de velocidad de CPU.
3. **Atacar el camino de la CPU**, que es el punto 1 del `TODO.md` del
   repositorio. Es trabajo de verdad y no pertenece a esta fase.

La decisión conviene tomarla en el hito C, no antes: el lector de SDRAM añadirá
más lógica a ese mismo dominio y entonces habrá el dato que falta.

## Uso y comprobaciones

Desde esta carpeta:

```powershell
..\.venv\Scripts\apio.exe test video_scanout_tb.v
..\.venv\Scripts\apio.exe test cpu_sdram_system_tb.v
..\.venv\Scripts\apio.exe test cpu_tb.v
..\.venv\Scripts\apio.exe test monitor_tb.v
..\.venv\Scripts\apio.exe test sdram_controller_tb.v
..\.venv\Scripts\apio.exe test sdram_system_adapter_tb.v
..\.venv\Scripts\apio.exe build
```

Los cinco bancos de CPU son los de 10 y pasan sin cambios; el único ajuste es la
versión esperada en `monitor_tb.v`. `video_scanout_tb.v` es el del hito B y sí
simula el cruce de dominios; lo que ningún banco simula es la cadena TMDS ni los
PLL, que se verifican enchufando un monitor.

La suite completa de CPU contra esta placa:

```powershell
..\.venv\Scripts\python.exe ..\x.cpu-tests\run_gpu_tests.py --backend cpu-fpga --version hdmi --port COM3
```

Es la comprobación que de verdad importa del hito A: que meter el vídeo no ha
roto la CPU.

## Notas de integración

- `pll_120.v`, `clock2_gen.v` y `dvi_generator.sv` envuelven sus primitivas
  (`EHXPLLL`, `ODDRX1F`) en `` `ifdef SYNTHESIZE ``. Apio define ese símbolo al
  sintetizar y al lintar, pero no al simular, e iverilog compila **todas** las
  fuentes del proyecto para cada testbench: sin la guarda, los bancos de la CPU
  no elaborarían. Fuera de síntesis los relojes pasan a ser el de entrada y la
  serialización DDR se reduce a `D0`, así que una simulación de `top` no
  reproduce el subsistema de vídeo.
- `ulx3s.lpf` es el de 10 más los cuatro pares GPDI de `13.hdmi/ulx3s_v20.lpf`.
  Solo se restringe el pin positivo: con `IO_TYPE=LVCMOS33D` el complementario
  queda implícito y el top no declara `gpdi_dn`.
- El reset del dominio de píxel no cruza desde los 120 MHz: se sincroniza
  `btn_pwr_n` dentro del dominio de píxel y se combina con `clk_pix_locked`.
- `video_pattern.sv` expone el mismo interfaz (`sx`, `sy`, `de` → `r`, `g`, `b`)
  que el scanout, y en `top` se elige entre los dos con FIRE1. El patrón es
  combinacional desde `sx` mientras que el scanout llega un ciclo más tarde, así
  que en `top` se retrasa un ciclo para que ambos compartan sincronismos.
- Los dos bancos de línea caben en **un solo EBR**: 320 píxeles RGB565 son
  5120 bits por banco, y un DP16KD tiene 18 kbit.
- El hito C solo tiene que sustituir `video_line_source_pattern` por un lector de
  SDRAM con el mismo contrato (`fill_start` / `fill_line` → `fill_we`,
  `fill_addr`, `fill_data` → `fill_done`). Es una línea de `top`.
