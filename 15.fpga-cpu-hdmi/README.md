# MiniCPU con SDRAM y salida HDMI

Fusión de la CPU con SDRAM de `10.fpga-cpu-ram` y la cadena DVI de `13.hdmi`,
sobre ULX3S-85F. El plan por fases está en [`docs/planning.md`](docs/planning.md)
y la arquitectura de destino en
[`docs/gpu_educativa_arquitectura.md`](docs/gpu_educativa_arquitectura.md).

Estado: **hito D completado**. Hay doble framebuffer con intercambio
sincronizado, gobernado desde una ventana de registros en `0x80000000` que
manejan tanto la CPU como el monitor. Con esto termina la fase 2 del plan.

**El dominio de CPU corre a 100 MHz desde el hito C**, y con él el monitor a
2 Mbaud. No fue una decisión de gusto: a 120 MHz no cumplía ninguna semilla.
Está razonado abajo.

## Escalera de hitos

| Hito | Contenido | Estado |
|---|---|---|
| A | Fusión: CPU de 10 intacta + 640×480p60 con patrón generado por lógica | **hecho** |
| B | Doble line buffer, cruce de dominios y escalado 2×, con productor falso | **hecho** |
| C | Scanout real: la CPU escribe el framebuffer en SDRAM y se ve | **hecho** |
| D | Registros en `0x80000000` y doble framebuffer con swap sincronizado | **hecho** |

La separación ha pagado: los tres fallos que aparecieron en C —aritmética de
línea, arbitraje y temporización— se pudieron mirar de uno en uno porque el
pinout, los PLL, la codificación TMDS y el cruce de dominios ya estaban
descartados. Y el patrón del hito A sigue en FIRE1 como referencia viva.

## Qué hay en el hito A

Dos subsistemas independientes en la misma FPGA, sin más recurso compartido que
el cristal de 25 MHz:

```text
clk_25mhz ─┬─ pll_cpu ──── 100 MHz ── CPU + monitor UART + SDRAM
           │
           └─ clock2_gen ─┬─ 125,0 MHz ── serializador TMDS
                          └─  25,0 MHz ── simple_480p → video_pattern → DVI → gpdi
```

La mitad de CPU es byte a byte la de 10: mismo mapa de memoria unificado de
32 MiB, mismos comandos de monitor, mismos cinco bancos de prueba. Lo único que
cambia es la **versión del monitor**, hoy **1.8**, para que
`run_gpu_tests.py --backend cpu-fpga --version hdmi` distinga este bitstream del
1.5 de 10 y del 1.6 de 6. (Fue 1.7 durante los hitos A y B; el cambio de reloj
y baudio del hito C la subió a 1.8.)

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
   dominio de sistema, 100 MHz          dominio de pixel, 25 MHz
   ───────────────────────────          ────────────────────────

   video_line_source_pattern
        │  (en el hito C pasa a ser el lector de SDRAM)
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
después, así que llevan estables más de un ciclo de 100 MHz cuando el pulso
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

El banco usa una pantalla de 32×16 con imagen fuente de 16×8 en lugar de
640×480: la lógica ejercitada es la misma y un frame baja de 420 000 ciclos de
píxel a 960.

### El primer frame tras reset es basura

Al arrancar, el barrido ya está en marcha y no ha habido blanking vertical en el
que prellenar los bancos. La máquina se resincroniza en el siguiente
`frame_start` y a partir de ahí la imagen es correcta. No se marca underflow por
esto: solo se vigila el estado activo.

## Qué hay en el hito C

El productor falso se sustituye por [`video_line_source_sdram.v`](video_line_source_sdram.v),
que lee la línea pedida del framebuffer. El contrato con el scanout no cambia:
es una línea de `top.v`.

### El framebuffer

| | |
|---|---|
| Dirección | `0x01000000`, la región que el mapa de memoria reserva a gráficos |
| Formato | RGB565, 320×240, lineal y sin relleno |
| Tamaño | 153 600 bytes, hasta `0x01025800` |
| Ancho de banda | 9,2 MB/s |

Un píxel RGB565 son 16 bits y el bus físico de la SDRAM también, así que **cada
píxel es exactamente un acceso**: no hay que componer palabras ni preocuparse
del endianness dentro del píxel. Una palabra de CPU, en cambio, necesita dos
accesos. Es la razón de fondo por la que RGB565 es el formato cómodo para
empezar, incluso antes que INDEX8.

### Arbitraje: la prioridad tuvo que acotarse

El vídeo es el tercer cliente de `sdram_system_adapter.v` y va primero: si el
line buffer se seca la imagen se rompe, mientras que una CPU parada solo va más
lenta.

Pero **prioridad absoluta resultó ser monopolio**. El lector vuelve a subir
`video_req` un ciclo después de cada concesión, así que cuando el árbitro
regresa a reposo el vídeo ya está pidiendo otra vez y nadie más entra nunca. La
CPU y el monitor se congelaban los ~27 µs que dura una línea. Con el monitor a
2 Mbaud eso son ocho bytes de UART perdidos.

La solución es un tope: tras `VIDEO_RUN` concesiones seguidas, el vídeo cede un
turno si hay alguien esperando. El dimensionado, por par de líneas de pantalla
(el tiempo disponible para traer una línea fuente):

```text
presupuesto     2 × 800 píxeles / 25 MHz = 64 µs = 6400 ciclos a 100 MHz
coste           SRC_W × V + (SRC_W / VIDEO_RUN) × C

con V = 10 ciclos por acceso de vídeo y C = 20 por transacción de CPU:

VIDEO_RUN = 1   →  9600 ciclos   no cabe
VIDEO_RUN = 4   →  4800 ciclos   cabe, 25 % de margen
```

`VIDEO_RUN = 4` da a la CPU un hueco cada medio microsegundo aproximadamente.
El banco de pruebas comprueba **las dos mitades del trato**: que la CPU avanza
durante un fill, y que las cesiones no alargan el fill más de un 60 %.

### Cómo probarlo en la placa

```powershell
..\.venv\Scripts\python.exe make_framebuffer.py diagonal fb.bin
..\.venv\Scripts\python.exe monitor.py write-block 0x01000000 fb.bin --port COM3
```

`make_framebuffer.py` genera patrones pensados para diagnosticar, no para
lucir: `diagonal` delata errores de pitch o de línea, `bars` delata bytes
intercambiados dentro del píxel, `checker` delata desplazamientos de medio
píxel y problemas de escalado.

Si algo sale mal, **FIRE1** vuelve al patrón del hito A sin tocar memoria: si
con el botón se ve bien, el problema está del line buffer hacia dentro.
`led[0]` sigue marcando underflow.

## Qué hay en el hito D

Una ventana de registros y el doble framebuffer que gobiernan.

| Dirección | Registro | | Contenido |
|---|---|---|---|
| `0x80000000` | `FB_FRONT` | RW | dirección de byte del buffer que se muestra |
| `0x80000004` | `FB_BACK` | RW | dirección de byte del buffer que se dibuja |
| `0x80000008` | `SWAP` | RW | escribir: pide intercambio. leer bit 0: pendiente |
| `0x8000000c` | `STATUS` | R | bit 0 underflow, bit 1 pendiente, 31:16 frames |

Las direcciones se alinean a cuatro bytes: los dos bits bajos se ignoran al
escribir y se leen como cero.

### El instante del intercambio

Intercambiar los buffers a mitad de frame parte la imagen. Hay que hacerlo
cuando no queda nada del frame anterior por leer y no se ha leído nada del
siguiente, y **ese instante existe y es exacto: la primera petición de línea
del frame**. El scanout la marca con `fill_first`.

No hace falta cruzar una señal de VBlank desde el dominio de píxel, ni razonar
sobre cuál de dos cruces llega antes: el swap viaja dentro de la propia
petición, que ya cruza. Un cruce menos y una carrera menos.

Hay un detalle que parece un descuido y no lo es: **`fb_base` es combinacional**
respecto a esa decisión. El lector de líneas registra su dirección base en el
mismo flanco en que se actualizan `fb_front` y `fb_back`; si `fb_base` fuera un
registro, la línea 0 saldría del buffer viejo y las 239 restantes del nuevo —un
desgarro de una línea, justo el fallo que este mecanismo existe para evitar—.
`video_registers_tb.v` lo comprueba muestreando `fb_base` en el mismo momento
en que lo ve el lector.

Una petición de swap que cae en el mismo ciclo que otro en curso queda
pendiente para el frame siguiente en lugar de perderse: un programa que dibuja
a toda velocidad puede pedirlo justo en ese flanco, y perderlo lo dejaría
esperando un intercambio que no llega. También tiene prueba.

### Acceso desde la CPU y desde el monitor

La CPU usa palabras completas; el monitor, bytes. Los registros **responden
también con la CPU en marcha**, al contrario que la SDRAM: no hay coherencia
que romper, y el contador de frames solo sirve si se puede leer mientras un
programa dibuja. La regla de «el monitor posee la memoria solo con la CPU
parada» sigue aplicándose sin cambios a la SDRAM.

Eso permite probar el swap **sin escribir ni una línea de programa**:

```powershell
..\.venv\Scripts\python.exe make_framebuffer.py bars fb0.bin
..\.venv\Scripts\python.exe make_framebuffer.py checker fb1.bin
..\.venv\Scripts\python.exe monitor.py write-block 0x01000000 fb0.bin --port COM3
..\.venv\Scripts\python.exe monitor.py write-block 0x01025800 fb1.bin --port COM3
..\.venv\Scripts\python.exe monitor.py write-byte 0x80000008 1 --port COM3
```

La pantalla debe saltar de las barras al tablero. Repetir el último comando
alterna entre los dos.

### Los programas

- [`swap_smoke.asm`](swap_smoke.asm) no dibuja: lee los dos registros, pide un
  intercambio, espera a que ocurra y comprueba que se intercambiaron. Es el que
  ejecuta `cpu_video_tb.v`, así que su comportamiento **está verificado en
  simulación RTL con instrucciones reales**.
- [`swap_demo.asm`](swap_demo.asm) es la demostración: una banda horizontal que
  baja, redibujando el buffer trasero entero cada frame. Ensambla, pero **no
  está verificado**: 38 400 escrituras por frame no terminan en simulación en
  un tiempo razonable. La prueba que importa es comparativa —quitar la espera
  de `wait_swap` o dibujar sobre `FB_FRONT` debe hacer aparecer tearing— y esa
  solo se puede hacer en la placa.

```powershell
..\.venv\Scripts\python.exe ..\1.isa\miniisa_asm.py swap_demo.asm -o swap_demo.bin
..\.venv\Scripts\python.exe monitor.py write-block 0 swap_demo.bin --port COM3
..\.venv\Scripts\python.exe monitor.py run --port COM3
```

## Temporización: de 120 a 100 MHz

Cada hito ha ido comiendo margen en el dominio de CPU, siempre por el mismo
mecanismo y nunca por un camino crítico nuevo:

| | 10.fpga-cpu-ram | hito A | hito B | hito C |
|---|---:|---:|---:|---:|
| Mejor semilla | 130,67 | 123,32 | 119,85 | 111,35 |
| ¿Cumple 120 MHz? | sí | sí, 1 de 8 | **ninguna** | **ninguna** |

Con ocho semillas tras el hito C, el máximo fue 111,35 MHz y la mediana 109,5.
Los 120 MHz dejaron de ser alcanzables, así que se baja la restricción a
**100 MHz**, y entonces cumplen **las ocho semillas**, entre 103,89 y 115,55.
La lotería de semillas desaparece: ya no decide si el diseño funciona.

Lo que cuesta:

- La CPU va un **17 % más lenta**.
- El monitor baja de 3 a **2 Mbaud**. No es solo `100/50`: el generador de
  baudios del FTDI produce 3 MHz partido por 1, 1,125, 1,25… así que 2,5 Mbaud
  (que sería `100/40`) **no es alcanzable desde el PC**, mientras que 2 Mbaud es
  3 MHz / 1,5 y sí lo es. Cargar el framebuffer entero tarda 0,77 s.
- La versión del monitor pasa a **1.8**, porque un bitstream con otro baudio es
  otro bitstream a todos los efectos.

La alternativa era atacar el camino crítico de la CPU (`instruction` →
decodificación → `branch_taken` → `pc`, 8,34 ns con 4,9 de routing), que es el
punto 1 del `TODO.md` del repositorio. Eso sigue disponible y devolvería el
margen; bajar el reloj solo compra tiempo para llegar al hito D.

### Por qué se degradó, y por qué no es lo que parece

**No hay ningún camino crítico nuevo.** El camino es, en los tres hitos, el
mismo y enteramente interno a la CPU:

```text
instruction → decodificación de shift_kind → step_active → branch_taken → pc
8,34 ns totales: 1,9 de lógica y 4,9 de routing
```

Ni un bloque de vídeo aparece en él. Lo que empeora es el *routing*. Con el dado
al 6,6 % de ocupación la palabra «congestión» sobra: lo que pasa es que el
netlist tiene ahora dos dominios con restricción y el emplazador reparte
distinto.

### Se intentó recuperar los 120 MHz, y no salió

Las cuatro paradas por error hacían `pc <= pc - 4` dentro del `case` gigante
sobre el opcode, lo que metía el decodificador entero en el cono de datos del
PC: ocho niveles de LUT desde `instruction` hasta `pc`. Ahora marcan
`pc_restore` y la resta se hace al entrar en `STATE_HALTED`, que es adonde van
las cuatro sin excepción. El PC sigue apuntando a la instrucción culpable y las
tres pruebas de error de `cpu_tb.v` que lo comprueban siguen pasando.

**El camino desapareció, pero los 120 MHz no volvieron.** Con la misma
restricción de 120, antes y después:

```text
antes    min 102,03   mediana 109,46   max 111,35
después  min 103,57   mediana 110,13   max 116,97
```

La mediana se mueve menos que el ruido entre semillas. Lo que sí cambió es
dónde está el problema: el camino crítico ya no está en la CPU sino en el
monitor (`block_end_address` → `response_byte_0`), y **de sus 9,13 ns hay
6,92 de routing y solo 1,69 de lógica en siete niveles**.

Eso es un techo de otra naturaleza. Una ruta dominada por routing con tan poca
lógica no se arregla acortando lógica: las celdas están físicamente lejos.
Seguir puliendo RTL solo asciende el siguiente camino de la lista. El cambio se
conserva porque es simple, está cubierto por pruebas y sube el peor caso a
100 MHz de 103,89 a 106,53 MHz —margen real para el hito D—, pero **no es el
camino de vuelta a los 120**. Eso pediría floorplanning, o menos lógica
compitiendo en el mismo dominio.

### Resultado a 100 MHz

| Dominio | Restricción | Alcanzado |
|---|---:|---:|
| CPU + SDRAM | 100 MHz | 114,57 MHz |
| Pixel | 25 MHz | ~103 MHz |
| TMDS 5× | 125 MHz | ~400 MHz |

Ocho semillas, todas cumpliendo: 106,53 / 108,33 / 108,41 / 110,62 / 111,89 /
112,73 / 113,19 / 114,57 MHz. `apio.ini` fija la mejor por margen, no por
necesidad.

Recursos: 5477 LUT y 2523 FF (6,6 % del ECP5-85F), **1 EBR** para los dos bancos
de línea, 2 PLL y 1 DSP. El DSP sale del producto `línea × 320` del lector: se
podría forzar a sumas de desplazamientos, pero eso ataría el módulo a un ancho
concreto y hay 156 DSP sin usar.

## Uso y comprobaciones

Desde esta carpeta:

```powershell
..\.venv\Scripts\apio.exe test cpu_video_tb.v
..\.venv\Scripts\apio.exe test video_registers_tb.v
..\.venv\Scripts\apio.exe test video_sdram_tb.v
..\.venv\Scripts\apio.exe test video_scanout_tb.v
..\.venv\Scripts\apio.exe test cpu_sdram_system_tb.v
..\.venv\Scripts\apio.exe test cpu_tb.v
..\.venv\Scripts\apio.exe test monitor_tb.v
..\.venv\Scripts\apio.exe test sdram_controller_tb.v
..\.venv\Scripts\apio.exe test sdram_system_adapter_tb.v
..\.venv\Scripts\apio.exe build
```

Los cinco bancos de CPU son los de 10 y pasan sin cambios; el único ajuste es la
versión esperada en `monitor_tb.v`. Los dos de vídeo se reparten el trabajo a
propósito:

- `video_scanout_tb.v` (hito B) simula el cruce de dominios **sin memoria**.
- `video_sdram_tb.v` (hito C) simula la aritmética del framebuffer y el
  arbitraje **sin dominio de píxel**, contra el adaptador real y un modelo
  funcional de memoria con tres ciclos de latencia.

Ninguno simula la cadena TMDS ni los PLL: eso se verifica enchufando un monitor.
Tampoco sustituyen al banco del controlador de SDRAM, que es el que cubre la
temporización JEDEC.

La suite completa de CPU contra esta placa:

```powershell
..\.venv\Scripts\python.exe ..\x.cpu-tests\run_gpu_tests.py --backend cpu-fpga --version hdmi --port COM3
```

Es la comprobación que de verdad importa: que meter el vídeo no ha roto la CPU.

## Notas de integración

- `pll_cpu.v`, `clock2_gen.v` y `dvi_generator.sv` envuelven sus primitivas
  (`EHXPLLL`, `ODDRX1F`) en `` `ifdef SYNTHESIZE ``. Apio define ese símbolo al
  sintetizar y al lintar, pero no al simular, e iverilog compila **todas** las
  fuentes del proyecto para cada testbench: sin la guarda, los bancos de la CPU
  no elaborarían. Fuera de síntesis los relojes pasan a ser el de entrada y la
  serialización DDR se reduce a `D0`, así que una simulación de `top` no
  reproduce el subsistema de vídeo.
- `ulx3s.lpf` es el de 10 más los cuatro pares GPDI de `13.hdmi/ulx3s_v20.lpf`.
  Solo se restringe el pin positivo: con `IO_TYPE=LVCMOS33D` el complementario
  queda implícito y el top no declara `gpdi_dn`.
- El reset del dominio de píxel no cruza desde los 100 MHz: se sincroniza
  `btn_pwr_n` dentro del dominio de píxel y se combina con `clk_pix_locked`.
- `video_pattern.sv` expone el mismo interfaz (`sx`, `sy`, `de` → `r`, `g`, `b`)
  que el scanout, y en `top` se elige entre los dos con FIRE1. El patrón es
  combinacional desde `sx` mientras que el scanout llega un ciclo más tarde, así
  que en `top` se retrasa un ciclo para que ambos compartan sincronismos.
- Los dos bancos de línea caben en **un solo EBR**: 320 píxeles RGB565 son
  5120 bits por banco, y un DP16KD tiene 18 kbit.
- `video_line_source_pattern.v` ya no se instancia, pero se conserva: su banco
  sigue siendo el que valida el cruce de dominios sin meter memoria de por medio.
  Sustituirlo por el lector de SDRAM fue una línea de `top.v`, gracias al
  contrato común (`fill_start` / `fill_line` → `fill_we`, `fill_addr`,
  `fill_data` → `fill_done`).
- El vídeo no se atiende antes de `init_done`. Durante los 200 µs de arranque de
  la SDRAM la petición queda pendiente y el scanout se queda en el prellenado,
  sin marcar underflow, que es justo lo que hace falta.
