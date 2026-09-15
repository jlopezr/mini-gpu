# Scanout: lo que cuesta, y una propuesta para poder apagarlo

Dos cosas distintas en un documento porque están ligadas: la medida dice que el
scanout es caro, y de ahí sale que poder apagarlo desde software no es una
comodidad de depuración sino una herramienta de medida.

La parte de medida es de `22.fpga-gpu-bl8`. La propuesta de MMIO es
**transversal** a los cores con vídeo (16, 18, 19, 21), porque el registro vive
en `video_registers.v`, que comparten.

## Lo que cuesta, medido

Todo a 25 MHz, que es el reloj real de `top_bl8`.

| | |
| --- | --- |
| Pico del canal, un solo cliente leyendo líneas seguidas | **23,5 MB/s** (17 ciclos por línea de 16 B) |
| Vídeo 320×240 RGB565 a 60 Hz (el framebuffer de 21) | **9,2 MB/s**, o sea el 39% del pico |
| Lo que la GPU alcanza sola en un bucle memory-bound | 11,1 MB/s (36 ciclos/tx) |

Ese tercer número es el interesante: **la GPU no está limitada por ancho de
banda, está limitada por latencia**. Solo usa la mitad del canal porque
`memory_fabric_4` admite una transacción global en vuelo, así que cada petición
paga la latencia entera de la SDRAM sin solaparse con nada.

Bancos: `sdram_bandwidth_tb.v` (pico) y `gpu_bench_tb.v` (la GPU sola).

### Y lo que cuesta de verdad, con el tráfico encima

`video_traffic_gen.v` imita el patrón de un scanout —ráfagas de 40
transacciones por línea fuente, con `urgent` alto— sin dibujar nada. Enchufado
al puerto 2 del fabric, corriendo `examples/bench.asm`:

| | Ciclos | |
| --- | --- | --- |
| GPU sola | 2 313 343 | |
| GPU + tráfico de scanout | 3 178 453 | **+37,4%** |

El vídeo movió 80 040 transacciones, o sea 10,1 MB/s — algo por encima del
objetivo de 9,2, porque el modelo de período es aproximado.

**La conclusión es más tranquilizadora de lo que yo esperaba.** Temía que, al
estar la GPU limitada por latencia, el daño fuera muy superior al 39% nominal
de ancho de banda. No lo es: cuesta un 37% de tiempo, aproximadamente
proporcional. `urgent` no destroza al resto.

Y en contexto: 22 con vídeo encendido sigue siendo **1,86× más rápido** que la
base BL1 sin vídeo ninguno (2,56 ÷ 1,374). O sea que **el scanout cabe** — pero
se paga, y se paga justo en las cargas con tráfico de datos, que son las que el
camino BL8 vino a mejorar.

## Por qué esto justifica un bit de MMIO

Si el scanout cuesta un 37%, poder apagarlo desde software deja de ser cosmético:

- **Medir en placa.** Correr el mismo programa con y sin scanout, en el mismo
  bitstream, es la única forma de comprobar en hardware el número de arriba.
  Hoy haría falta sintetizar dos bitstreams distintos, y entonces ya no estás
  comparando lo mismo.
- **Cargas que no dibujan.** Un cómputo que no mira la pantalla no tiene por
  qué regalar el 37%.
- **Puesta en marcha.** Separar "el HDMI no funciona" de "el framebuffer tiene
  basura" es media depuración, y hoy no se pueden separar.

## Propuesta: `VIDEO_CTRL` en `0x80000018`

En `video_registers.v` los registros 0..5 están ocupados (`0x00`..`0x14`); el
6 está libre.

```text
0x80000018  VIDEO_CTRL  RW   bits 1:0  modo de salida
                                  0  BLANK    negro, sin leer SDRAM
                                  1  PATTERN  patrón de prueba, sin leer SDRAM
                                  2  SCANOUT  framebuffer desde SDRAM
                                  3  reservado
                             31:2      reservado, leer como 0
```

**Registro nuevo y no bits en `STATUS`.** `STATUS` tiene semántica de
escribir-1-para-borrar en el bit 0; meter ahí un bit de control persistente es
pedir que alguien lo borre sin querer al limpiar el underflow.

**Dos bits y no uno.** Porque `BLANK` y `PATTERN` no son lo mismo: los dos
liberan el canal, pero `PATTERN` mantiene señal HDMI viva. Con un solo bit
habría que elegir, y las dos hacen falta por motivos distintos —`PATTERN` para
puesta en marcha, `BLANK` para medir sin que el generador de patrón meta ruido
en el consumo de LUTs del line buffer.

### Lo que hace falta implementar: casi nada

La pieza clave es que **las dos fuentes de línea ya existen y comparten
contrato**. En 21:

```text
video_line_source_pattern.v : fill_start, fill_line -> fill_we, fill_addr, fill_data, fill_done
video_line_source_sdram.v   : lo mismo, mas fb_base y el puerto de memoria
```

El propio comentario de `video_scanout.v` lo dice: *"en el hito C ese productor
se sustituye por un lector de SDRAM con el mismo contrato"*. O sea que la
implementación es **un mux entre dos productores que ya están escritos y
probados**, más:

- `BLANK`: no arrancar ningún relleno y servir ceros al line buffer.
- En `BLANK`/`PATTERN`, forzar `video_req` a 0 para que el cliente de SDRAM no
  pida nada — que es el punto entero del ejercicio.

### Valor de reset: `PATTERN`, en todos los cores, sin parámetro

Primero lo planteé como parámetro con `SCANOUT` por defecto, para no tocar los
cores que ya funcionan. Estaba mal: eso es escaquearse de la decisión, y la
decisión tiene una respuesta bastante clara.

**`SCANOUT` tras el reset no es un estado definido.** La SDRAM recién
encendida contiene basura, así que ese "valor por defecto" consiste en mostrar
contenido indefinido. No es que sea arriesgado: es que no está definido.
`PATTERN` sí lo está.

Y el criterio que lo decide: **elegir el valor por defecto cuyo modo de fallo
se explica solo.**

| Por defecto | Si algo va mal, ves... | Qué aprendes |
| --- | --- | --- |
| `SCANOUT` | basura en pantalla | nada: ¿HDMI? ¿PLL? ¿cable? ¿`fb_base`? ¿el programa? |
| `PATTERN` | el patrón | que HDMI, PLL, cable y monitor funcionan; el problema está aguas abajo |
| `PATTERN` | nada en absoluto | que el problema está aguas arriba, antes del framebuffer |

Con `SCANOUT` por defecto los dos fallos posibles se ven igual. Con `PATTERN`
se distinguen sin instrumentar nada, y esa es la mitad de cualquier puesta en
marcha.

**El coste de migrar es menor de lo que parecía.** Las demos de 21 ya cargan la
base del MMIO de vídeo en un registro (`MOVHI R20, 0x8000` en
`swap_demo_fast.asm`), así que habilitar el scanout es **un `STORE` más** en la
inicialización de cada una. Y es un `STORE` que mejora el programa: "quiero
mostrar el framebuffer" pasa a ser una intención declarada en vez de un
accidente del valor de reset.

Sin parámetro: un solo comportamiento en todos los cores. Si algún día un core
necesita de verdad scanout inmediato, se añade el parámetro entonces, con un
caso real delante.

**Cómo hacerlo sin romper nada por el camino:** `VIDEO_CTRL`, el mux, las demos
y los seis bancos de vídeo (`video_frame_tb`, `video_fullframe_tb`,
`video_scanout_tb`, `video_sdram_tb`, `video_burst_tb`, `video_registers_tb`)
van en el **mismo commit**. Si se separan, queda un estado intermedio en el que
las demos no pintan y parece que el cambio las rompió.

### Qué NO propongo

- **Apagar el PLL de píxel o el TMDS en `BLANK`.** Tentador para ahorrar, pero
  apagar y reencender un reloj de píxel hace que los monitores pierdan el
  enganche y tarden segundos en recuperarlo. `BLANK` debe seguir emitiendo
  sincronismos válidos con píxeles negros.
- **Que `SWAP` implique encender el scanout.** Que un registro de dibujo
  cambie el modo de salida por su cuenta es justo el tipo de acoplamiento que
  luego nadie entiende.

## La dirección no puede ser la misma en 22

En 21 los registros de vídeo viven en `0x80000000`. **En 22 esa dirección ya
está ocupada**: es la región de configuración de warps.

```text
22:  mmio        = address[31:12] == 0x80000
     cfg_region  = address[11:7]  == 0        -> 0x80000000-0x8000007F  warps
     0x80000100-0x80000114                    -> depuración y contadores
```

Así que en 22 el bloque de vídeo tiene que ir a otra base — `0x80000200`
encaja limpio, porque `address[11:2]` = 0x080..0x085 cae hoy en el `default`
del decodificador y da fault.

Conviene decirlo sin adornos: **lo que es portable entre cores es la semántica
del registro, no su dirección.** Un programa que quiera valer para los dos
tiene que tomar la base del bloque de vídeo como un dato, no como una
constante compilada.

## Implementado: pasos 1 y 2

Hecho en 22. `VIDEO_CTRL` en `0x80000200`, mux entre `video_line_source_burst`
(SDRAM) y `video_line_source_pattern`, salida HDMI con el stack de 21 y 13.

**El riesgo del reloj TMDS que anticipé no se materializó.** Los tres relojes
cierran con margen:

| Reloj               | Consigue   | Necesita |
|---------------------|------------|----------|
| `clk_pix`           | 67,05 MHz  | 25       |
| `clk_pix_5x` (TMDS) | 252,21 MHz | 125      |
| sistema / SDRAM     | 38,52 MHz  | 25       |

Área: 33 124 LUT contra 31 012 sin vídeo, o sea **+2 112 LUT** por todo el
subsistema. La FPGA queda al 39,6% de LUT, 14% de biestables y **8,2% de block
RAM**.

### El coste real, con el cliente de verdad

Repetida la medida con `video_line_source_burst` en vez del generador
sintético:

|                        | Ciclos    |          |
|------------------------|-----------|----------|
| `bench.asm` en PATTERN | 2 313 338 |          |
| `bench.asm` en SCANOUT | 2 991 301 | **+29%** |

El sintético daba +37%: era pesimista porque su patrón de ráfaga es algo más
agresivo que el real. **+29% es el número bueno.**

### Dos fallos que encontraron los bancos

1. **`gpu_reset` reseteaba los registros de vídeo.** El monitor hace
   `gpu_reset` antes de cargar cada programa, así que la configuración de
   pantalla se habría perdido en cada carga. Ahora `gpu_video_regs` cuelga de
   `reset`, no de `core_reset`: el vídeo es un periférico, no parte del núcleo.
2. **`FB_BASE` estaba escalado mal.** `video_line_source_burst` quiere una
   dirección de *palabra de 16 bits* (hace `fb_base + fill_line*320`), y yo la
   dividía entre 4 en vez de entre 2. El primer banco no lo vio porque solo
   comprobaba que *hubiera* peticiones de vídeo, no *a dónde* iban. Ahora
   comprueba que la línea N se pida en `FB_BASE + N*640`.

El segundo es la lección que se repite en este documento: **una prueba que
verifica que algo ocurre no verifica que ocurra bien.**

## El primer programa que dibuja: `examples/plasma.asm`

Los 64 hilos (`GETTID` da el id global `{warp,lane}`) se reparten las 38 400
palabras del framebuffer con paso 64, elegido para que los 8 hilos de un warp
escriban palabras **consecutivas** y la LSU v2 las coalesca en 2 transacciones.

### Lo que la GPU no puede hacer

**Ningún hilo puede encender el scanout.** Dos barreras independientes:

- la LSU marca fault toda dirección ≥ `0x02000000`, así que un `STORE` a
  `0x80000200` nunca llega al MMIO;
- y aunque llegara, `video_write` exige `halted`.

El MMIO es territorio exclusivo del host. Si algún día se quiere una GPU que
cambie de buffer por su cuenta, hace falta abrirle un camino a la ventana MMIO
desde la LSU — hoy no existe.

### Cuánto tarda, y por qué

| | Ciclos/frame | Fallos de fetch | |
| --- | --- | --- | --- |
| Efecto v1, bufer de 4 líneas (64 B) | 4 480 403 | 188 778 (29%) | 5,6 fps |
| Efecto v1, bufer de 16 líneas (256 B) | 3 320 606 | 14 (0%) | 7,5 fps |
| Efecto v2 (`MUL` en vez de `SHL`), 16 líneas | **2 964 113** | 14 (0%) | **8,4 fps** |

En total **−34%** desde el punto de partida, sin tocar el hardware más que el
tamaño del bufer: el resto salió de dejar de pelearse con la ISA.

El bucle ocupa ~160 bytes y no cabía en 64. Con 16 líneas el fetch desaparece
como problema, por 2 048 biestables en vez de 512 — el 2,4% del presupuesto de
FF. Por eso `IMEM_LINES` pasa a 16 por defecto.

Y con el fetch resuelto, el reparto del frame queda así:

```text
escribir el framebuffer entero:  9 600 transacciones = 163 200 ciclos = 3,6%
ejecutar instrucciones:                                           el resto
```

**El límite es el ritmo del SM, no la memoria.** 162 324 instrucciones de warp
por frame entre 3 320 606 ciclos son **20,5 ciclos por instrucción**, con el
fetch acertando el 100%. Parte es estructural (la lane recorre
`FETCH_REQUEST → FETCH_WAIT → DECODE → EXECUTE → RETIRE`, más el ida y vuelta
de `gpu_imem_buffer` incluso en acierto); el resto está sin desglosar.

### Una trampa de la ISA que costó la mitad del efecto

**Los desplazamientos son de un bit por ciclo** (`STATE_SHIFT_STEP`:
`shift_result <= shift_result << 1` con un contador). La primera versión del
efecto empaquetaba RGB565 con `SHL` por 11, 5 y 16, o sea **48 ciclos por
palabra solo desplazando**. La versión actual usa `MUL` por una constante (4
estados fijos) para los desplazamientos grandes.

Conviene tenerlo presente al escribir cualquier programa para esta ISA: un
`SHL` por 16 cuesta cuatro veces más que un `MUL`.

### Y el efecto en sí

La primera versión usaba `(x+t)&31` y `(y+t)&63` directos. En pantalla salían
cuatro bandas horizontales con corte seco (240/64 = 3,75 vueltas) y rayas cada
32 píxeles: funcionaba perfectamente, pero parecía ruido. **Un diente de
sierra en un canal de color es una costura muy visible.** La versión actual usa
degradados que no dan la vuelta (`x2>>4`, `y>>2`) con la textura XOR de
amplitud baja encima.

## Orden sugerido

Primero **22**, no 21: aquí no hay ninguna demo con vídeo que migrar, así que
el coste de equivocarse es cero. El backport a 21 se hace después, y solo si el
experimento sale bien.

Pero "probarlo en 22" significa portar el stack de vídeo entero, que es
bastante más grande que el cambio de `VIDEO_CTRL` en sí. Conviene partirlo:

1. **Vídeo solo con `PATTERN`.** HDMI + reloj de píxel + `video_scanout` +
   `line_buffer` + `video_line_source_pattern` + `VIDEO_CTRL` con `BLANK` y
   `PATTERN`. **Sin cliente en p2 y sin leer SDRAM**, así que no cuesta ni un
   byte de ancho de banda y no puede afectar a lo ya medido. Valida el segundo
   dominio de reloj, el TMDS en esta placa, y de paso `PATTERN` por defecto —
   que es justo lo que se quería probar.
2. **Añadir `video_line_source_sdram` en p2** y el modo `SCANOUT`. A partir de
   aquí se puede medir en placa lo que este documento midió en simulación:
   correr `examples/bench.asm` con `VIDEO_CTRL=SCANOUT` y con `=BLANK`, y
   comparar con el +37,4%.
3. **Backport a 21**, con el `STORE` de habilitación en las demos.

### El riesgo del paso 1 no es el que parece

No es el ancho de banda (no consume ninguno) ni el Fmax de la GPU: el reloj
serie TMDS vive en **su propio dominio** y no toca el camino crítico de
`gpu_lsu2`. El riesgo es que ese dominio cierra justo — `13.hdmi` tiene un
`check_timing.ps1` dedicado y fija la semilla de nextpnr precisamente porque el
reloj serie no cierra con cualquiera. Añadirlo a un diseño que ya ocupa 31 000
LUT puede hacer que la semilla que hoy vale deje de valer, y eso se arregla
barriendo semillas, no tocando RTL.
