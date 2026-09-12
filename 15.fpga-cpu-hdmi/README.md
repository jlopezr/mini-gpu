# MiniCPU con SDRAM y salida HDMI

Fusión de la CPU con SDRAM de `10.fpga-cpu-ram` y la cadena DVI de `13.hdmi`,
sobre ULX3S-85F. El plan por fases está en [`docs/planning.md`](docs/planning.md)
y la arquitectura de destino en
[`docs/gpu_educativa_arquitectura.md`](docs/gpu_educativa_arquitectura.md).

Estado: **hito D completado**. Hay doble framebuffer con intercambio
sincronizado, gobernado desde una ventana de registros en `0x80000000` que
manejan tanto la CPU como el monitor. Con esto termina la fase 2 del plan.

**El dominio de CPU corre a 100 MHz desde el hito C**, y con él el monitor a
1 Mbaud. No fue una decisión de gusto: a 120 MHz no cumplía ninguna semilla.
Está razonado abajo.

**Verificado en placa**: versión 1.10, `underflow` a cero, 63 frames/s medidos
por el contador de `STATUS`, los dos framebuffers cargados y verificados, y el
swap intercambiando `FB_FRONT` con `FB_BACK`. De la suite de CPU pasan **12 de
12** casos desde que `MUL`, `MULFX` y `DIV` llegaron de `6.fpga-cpu`.

## Escalera de hitos

| Hito | Contenido                                                               | Estado    |
|------|-------------------------------------------------------------------------|-----------|
| A    | Fusión: CPU de 10 intacta + 640×480p60 con patrón generado por lógica   | **hecho** |
| B    | Doble line buffer, cruce de dominios y escalado 2×, con productor falso | **hecho** |
| C    | Scanout real: la CPU escribe el framebuffer en SDRAM y se ve            | **hecho** |
| D    | Registros en `0x80000000` y doble framebuffer con swap sincronizado     | **hecho** |

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
cambia es la **versión del monitor**, hoy **1.10**, para que
`run_gpu_tests.py --backend cpu-fpga --version hdmi` distinga este bitstream del
1.5 de 10 y del 1.6 de 6. (Fue 1.7 durante los hitos A y B; el cambio de reloj
y baudio del hito C la subió a 1.8, y dos correcciones posteriores a 1.9 y
1.10; el propio `monitor.v` lleva la lista.)

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

|                |                                                                   |
|----------------|-------------------------------------------------------------------|
| Dirección      | `0x01000000`, la región que el mapa de memoria reserva a gráficos |
| Formato        | RGB565, 320×240, lineal y sin relleno                             |
| Tamaño         | 153 600 bytes, hasta `0x01025800`                                 |
| Ancho de banda | 9,2 MB/s                                                          |

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
1 Mbaud eso son cuatro bytes de UART perdidos.

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

| Dirección    | Registro   |    | Contenido                                         |
|--------------|------------|----|---------------------------------------------------|
| `0x80000000` | `FB_FRONT` | RW | dirección de byte del buffer que se muestra       |
| `0x80000004` | `FB_BACK`  | RW | dirección de byte del buffer que se dibuja        |
| `0x80000008` | `SWAP`     | RW | escribir: pide intercambio. leer bit 0: pendiente |
| `0x8000000c` | `STATUS`   | R  | bit 0 underflow, bit 1 pendiente, 31:16 frames    |

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

Todos dibujan lo mismo —una banda verde de 16 píxeles que baja sobre fondo
azul— y se diferencian solo en dos ejes: **dónde** escriben (buffer trasero o
buffer visible) y **cuánto** repintan (las 240 líneas o solo las 32 que
cambian). Esa rejilla de dos por dos es la demostración del hito D: el eje
vertical enseña para qué sirve el doble buffer, el horizontal lo que cuesta.

| Programa                                   | Escribe en | Repinta    | Dibujo  | En pantalla                     |
|--------------------------------------------|------------|------------|---------|---------------------------------|
| [`swap_demo.asm`](examples/swap_demo.asm)           | `FB_BACK`  | 240 líneas | 96,6 ms | 9,8 fps, limpio                 |
| [`swap_demo_fast.asm`](examples/swap_demo_fast.asm) | `FB_BACK`  | 32 líneas  | 13,2 ms | 59,3 fps, limpio                |
| [`tear_demo.asm`](examples/tear_demo.asm)           | `FB_FRONT` | 240 líneas | 96,6 ms | 10,3 fps, frente de repintado   |
| [`tear_demo_fast.asm`](examples/tear_demo_fast.asm) | `FB_FRONT` | 32 líneas  | 13,2 ms | 75,7 fps, costura cada 63 ms    |

Las dos últimas columnas dicen cosas distintas y conviene no confundirlas. «Dibujo»
es lo que tarda la CPU en pintar un frame; «en pantalla» es a qué ritmo se ve
cambiar la imagen. En los `swap_` no coinciden porque la espera al intercambio
redondea cada frame a un número entero de frames de vídeo.

Y aparte, [`swap_smoke.asm`](examples/swap_smoke.asm), que no dibuja: lee los dos
registros, pide un intercambio, espera a que ocurra y comprueba que se
intercambiaron. Es el que ejecuta `cpu_video_tb.v`, así que es el único cuyo
comportamiento **está verificado en simulación RTL con instrucciones reales**.

Lanzarlos, con el script que hace los cuatro pasos —ensamblar, parar la CPU,
cargar y arrancar— y comprueba el estado al terminar:

```powershell
.\run-demo.ps1 swap_demo_fast
.\run-demo.ps1 tear_demo_fast
.\run-demo.ps1 swap_demo -NoRun     # cargar sin arrancar
.\run-demo.ps1 tear_demo -Port COM4
```

El orden no es cosmético: **hay que resetear la CPU antes de escribir**, porque
el monitor rechaza cualquier acceso a memoria mientras la CPU corre. Olvidarlo
da un error de acceso que parece un fallo de la placa y no lo es.

Y aparte de los cinco programas hay uno que no es un programa:
[`examples/demo-no-cpu.ps1`](examples/demo-no-cpu.ps1) pinta una imagen **sin
ejecutar ni una instrucción**, escribiendo el framebuffer desde el PC y pidiendo
el intercambio. Es el mejor aislante de fallos que hay aquí: si la imagen
aparece, el scanout, la SDRAM, los registros de vídeo y la cadena DVI funcionan,
y cualquier problema que veas con una demo está en el programa o en la CPU.

```powershell
.\examples\demo-no-cpu.ps1 -Pattern frame
```

#### Qué se ve, y por qué

**Los dos `swap_`** bajan la banda sin partir la imagen nunca, uno a tirones y
otro fluido. Los `tear_` son el control negativo: la única diferencia con su
pareja son dos líneas —`LOAD` desde `+0` en vez de `+4`, y fuera la petición de
intercambio con su espera—, a propósito, para que lo que se vea distinto solo
pueda venir del doble buffer.

Lo que no esperaba, y salió al medirlo: **los dos `tear_` rompen la imagen de
forma muy distinta**. `tear_demo` tarda 96,6 ms en repintar, casi seis frames de
vídeo, así que no se ve una costura sino un frente de repintado bajando
despacio. `tear_demo_fast` tarda 13,2 ms contra los 16,7 ms que dura un frame:
la CPU y el barrido van casi a la misma velocidad pero no exactamente, así que
el punto donde se cruzan se desplaza poco a poco y sale **una costura
horizontal recorriendo la pantalla cada 63 ms**. Esa es la que se reconoce de
un juego sin vsync, y el ritmo no está ajustado a mano: sale de lo que tarda
esta CPU en escribir 5 120 palabras compitiendo con el vídeo por la SDRAM.

#### El umbral de los 16,7 ms

Pintar 32 líneas en vez de 240 es **7,5 veces menos trabajo**, y el tiempo de
dibujo baja 7,3× —de 96,6 a 13,2 ms—, así que ahí no hay sorpresa. Lo que sí
cambia de naturaleza es lo que se ve, porque entre esos dos números está el
umbral que importa: **los 16,7 ms de un frame de vídeo**.

Con la espera al intercambio, un frame dibujado dura un número entero de frames
de vídeo, nunca algo intermedio. Por eso `swap_demo` sale a 9,8 fps —uno de cada
seis— y `swap_demo_fast` se engancha a 59,3, o sea a los 60 del monitor. Cruzar
el umbral no acelera un 7,3 %: cambia quién manda.

Y a partir de ahí manda la pantalla. `tear_demo_fast` hace exactamente el mismo
dibujo sin esperar a nadie y sale a **75,7 fps**: la CPU tiene 3,5 ms libres de
cada 16,7 que el doble buffer sincronizado no puede aprovechar. Eso no es
tiempo perdido —no hay dónde enseñar esos frames de más en un monitor de
60 Hz—, pero sí es el margen que un triple buffer convertiría en menos latencia.

#### La contabilidad que exige el doble buffer

Lo más instructivo de la versión rápida no es la velocidad, sino un detalle que
no existe con un solo buffer: **el buffer trasero no contiene lo que se dibujó
el frame pasado, sino lo del anterior a ese**, porque los dos se alternan. Para
borrar la banda vieja hay que recordar dónde quedó **en cada buffer por
separado** —`R10` y `R11`, que rotan en cada intercambio—. Con un solo registro,
como basta en `tear_demo_fast`, queda un rastro de bandas verdes que no se
borra nunca.

Es decir: la ausencia de costura se paga llevando esa contabilidad. El hito D
no la regala.

Ninguno de los cuatro está verificado en RTL —ni 38 400 ni 5 120 escrituras por
frame terminan en simulación en un tiempo razonable—. Lo que sí se comprobó
antes de subirlos es la lógica de borrado, modelando el algoritmo en Python y
pasando 600 frames contra el contenido esperado del buffer; y se comprobó que
**la versión ingenua de un solo registro falla en el frame 2**, para que la
prueba no fuera una que aprueba cualquier cosa.

#### Cómo se miden, y cómo se midieron mal

Las cifras de arriba salen de [`measure-demo.ps1`](measure-demo.ps1), que lee
`R21` —la posición de la banda— antes y después de dejar correr la CPU un
segundo. La banda avanza de dos en dos, así que el ritmo es directo.

Hay dos trampas, y la primera se cayó en ella:

- **El cronómetro tiene que pararse en el `halt`**, no después de leer el
  registro. Leerlo cuesta unos 250 ms por el puerto serie, y contarlos como
  tiempo de ejecución rebajaba la medida un 20 %: los 59,3 fps reales se leían
  como 50, y de ahí salió una explicación entera sobre una «mezcla de frames de
  16,7 y 33,3 ms» que describía un fenómeno que no estaba ocurriendo. El error
  era coherente consigo mismo, que es lo que lo hacía creíble.
- **La ventana tiene que ser corta.** A 60 fps la banda da la vuelta en 1,9 s, y
  con ventanas más largas el número queda ambiguo.

Lo que delató el fallo fue una comprobación cruzada: los 13,2 ms de las 32
líneas y los 96,6 ms de las 240 dan 258 y 252 ciclos por palabra
respectivamente. Dos medidas independientes que coinciden al 2 % son mucho más
difíciles de falsear que una sola.

## Temporización: de 120 a 100 MHz

Cada hito ha ido comiendo margen en el dominio de CPU, siempre por el mismo
mecanismo y nunca por un camino crítico nuevo:

|                  | 10.fpga-cpu-ram |     hito A |      hito B |      hito C |
|------------------|----------------:|-----------:|------------:|------------:|
| Mejor semilla    |          130,67 |     123,32 |      119,85 |      111,35 |
| ¿Cumple 120 MHz? |              sí | sí, 1 de 8 | **ninguna** | **ninguna** |

Con ocho semillas tras el hito C, el máximo fue 111,35 MHz y la mediana 109,5.
Los 120 MHz dejaron de ser alcanzables, así que se baja la restricción a
**100 MHz**, y entonces cumplen **las ocho semillas**, entre 103,89 y 115,55.
La lotería de semillas desaparece: ya no decide si el diseño funciona.

Lo que cuesta:

- La CPU va un **17 % más lenta**.
- El monitor baja de 3 a **1 Mbaud**. Cargar el framebuffer entero tarda 1,5 s.
- La versión del monitor sube, porque un bitstream con otro baudio es otro
  bitstream a todos los efectos.

### El baudio: dos condiciones, no una

Elegir el divisor de UART parece aritmética simple y no lo es. Tiene que
cumplir **las dos** a la vez:

1. **Múltiplo de cuatro.** `uart.v` alimenta la recepción con `DIVISOR/4`
   porque sobremuestrea cuatro veces, y la división es entera. El aviso está en
   el propio código —`must be divisible by 4 for rx clock`— y aun así se coló
   un divisor de 50: la recepción quedó a 12 en vez de 12,5, un **4,2 % rápida**,
   casi medio bit de deriva en una trama de diez. En la placa eso se veía como
   un enlace que funcionaba **la mitad de las veces**.
2. **Un baudio que el FTDI sepa generar exacto**, o sea 3 MHz partido por 1,
   1,5, o múltiplos de 0,125 a partir de 2.

Entre 40 y 200, el único divisor que cumple ambas es **100 → 1 Mbaud**:

| Divisor |      Baudio | ¿Múltiplo de 4? | ¿FTDI exacto? |
|--------:|------------:|:---------------:|:-------------:|
|      40 |   2,5 Mbaud |       sí        |  no (3/1,2)   |
|      48 | 2,083 Mbaud |       sí        |  no (3/1,44)  |
|      50 |     2 Mbaud |     **no**      |  sí (3/1,5)   |
|      64 | 1,563 Mbaud |       sí        |  no (3/1,92)  |
| **100** | **1 Mbaud** |     **sí**      | **sí (3/3)**  |

Como el requisito era solo un comentario, ahora `uart.v` lo comprueba al
elaborar: si `DIVISOR` no es múltiplo de cuatro instancia un módulo inexistente
llamado `DIVISOR_must_be_divisible_by_4` y la síntesis para en seco. Ningún
banco de pruebas instancia esta UART, así que no había otra forma de cazarlo.

### El pulso del monitor, y por qué el vídeo lo hacía desaparecer

Más grave que el baudio, y encontrado el mismo día. **El monitor pide memoria
con un pulso de un ciclo**, no con un nivel mantenido hasta `ready` como hacen
la CPU y el vídeo. Mientras el árbitro lo atendía en la primera rama de
`STATE_IDLE` eso daba igual. Desde el hito C el vídeo tiene prioridad, así que
un pulso que caía en un ciclo ocupado **se perdía**, y el monitor se quedaba
esperando para siempre un `ready` que no llegaba: la placa dejaba de responder
hasta el siguiente reset.

El síntoma era desconcertante y vale la pena recordarlo: `ping` y `get-version`
funcionaban 20 de 20 veces, pero **cualquier lectura de memoria colgaba la placa
de forma permanente**. La explicación es que `ping` no toca el adaptador.

El arreglo es engancharlo en el árbitro. `video_sdram_tb.v` lo cubre ahora
emitiendo el pulso en mitad de un fill de vídeo, sin mirar si el árbitro está
libre, que es justo lo que hace el monitor real; sin el enganche, esa prueba
falla.

La alternativa era atacar el camino crítico de la CPU (`instruction` →
decodificación → `branch_taken` → `pc`, 8,34 ns con 4,9 de routing). Eso sigue
disponible y devolvería el margen; bajar el reloj solo compra tiempo para
llegar al hito D. No está en el `TODO.md` del repositorio.

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
Pasan **12 de 12** casos.

### `MUL`, `MULFX` y `DIV`

Hasta hace poco pasaban 11 de 12: fallaba `multiply`, porque esta CPU declaraba
`MUL` y lo validaba, pero no tenía rama de ejecución. Caía en el `default` y
respondía `ERROR_INVALID_OPCODE`. El simulador sí lo implementaba, así que el
mismo caso pasaba con `--backend cpu-simulator` y fallaba en la FPGA.

Las tres instrucciones vienen de [`../6.fpga-cpu`](../6.fpga-cpu), que las tenía
desde antes: `MUL` conserva los 32 bits bajos, `MULFX` es signed Q16.16 con
cuatro productos parciales de 16×16 sobre DSP, y `DIV` es un divisor iterativo
de 32 pasos con truncamiento hacia cero. Ocupan 4 `MULT18X18D` de 156; el vídeo
ya usaba uno.

El detalle que importa para esta carpeta es que **el 6 no cumplía su reloj**: se
quedaba en 116,39 MHz contra 120, porque el arreglo de signo del multiplicador
—una negación condicional de 32 bits— desembocaba en el multiplexor de
`register_write_data`. Se arregló allí partiéndolo en `STATE_MUL_SIGN` y
`STATE_MUL_WRITE`, exactamente como `STATE_ALU_WRITE` hace con la suma de la
ALU, y es **esa** versión la que se trajo aquí. El coste es un ciclo en las tres
instrucciones, que `cpu_tb.v` comprueba. Con ellas la CPU tiene 18 estados y
`state` pasó de `[3:0]` a `[4:0]`.

El efecto en temporización fue nulo dentro del ruido de colocación: siguen
cerrando siete de ocho semillas a 100 MHz, ahora entre 95,37 y 112,88 MHz. La
semilla fijada pasó de la 3 a la 5. En área, 5 888 → 6 785 LUT.

Y el caso `multiply` deja de ser una discrepancia entre backends: aprueba en las
dos FPGA y en el simulador.

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

## Pasos siguientes

La escalera A → D está terminada y verificada en la placa, y las demos cierran
la última pregunta que quedaba abierta: el tearing aparece al quitar el doble
buffer, así que el hito D hace lo que dice. Lo que las demos abren es otra cosa.

### El número incómodo

`swap_demo_fast` escribe 5 120 palabras en 13,2 ms. A 100 MHz eso son **1,32
millones de ciclos, unos 258 por palabra**; `swap_demo`, con 38 400 palabras en
96,6 ms, da 252, así que el número está bien sujeto. El bucle interior son
cuatro instrucciones (`STORE`, dos `ADDI`, `BLT`), o sea **unos 64 ciclos por
instrucción**.

Eso no es el vídeo robando ancho de banda: el vídeo consume 9,2 MB/s de los
~200 MB/s que da la SDRAM, y `VIDEO_RUN = 4` le impide pasar de ahí. Son la CPU
multiciclo y, sobre todo, que **cada instrucción se busca en SDRAM**, con su
activación de fila y su latencia, igual que cada dato. Un bucle de cuatro
instrucciones hace cinco accesos a memoria por píxel doble.

De ahí salen tres caminos, de menos a más ambicioso:

1. **Memoria de instrucciones en EBR.** El bucle interior son 68 bytes. Una
   caché de instrucciones mínima, o simplemente ejecutar desde EBR, quita cuatro
   de cada cinco accesos a SDRAM sin tocar la CPU. Es el cambio con mejor
   relación resultado/esfuerzo, y de largo.
2. **Escrituras en ráfaga.** El adaptador hace un acceso por palabra y paga la
   activación de fila cada vez. Rellenar una línea son 160 palabras
   consecutivas: exactamente el caso para el que existe el modo ráfaga. Son los
   puntos 0 («Usar BL8») y 1 («Optimizar LSU») del `TODO.md` del repositorio, y
   aquí se ve por qué encabezan la lista.
3. **Que no sea la CPU quien rellene.** Un bloque que rellene rectángulos por
   sí solo, mandado desde los registros MMIO, es el siguiente escalón natural
   después del scanout: el vídeo ya lee de la SDRAM sin la CPU, y esto sería
   escribir igual. Es también la frontera donde esto deja de ser una CPU con
   salida de vídeo y empieza a ser una GPU.

### Lo que falta en la CPU

`MUL`, `MULFX` y `DIV` ya están, traídos de `../6.fpga-cpu`. Las demos siguen
calculando `y*640` como `(y<<9) + (y<<7)` porque se escribieron antes; no hay
motivo para no usar `MUL` ahora, más allá de que un desplazamiento cuesta menos
ciclos que las once de una multiplicación.

De la ISA siguen sin implementar `MULHI`, `DIVU`, `REM` y `REMU`. Los tres
primeros salen casi gratis del hardware que ya hay: `MULHI` son los 32 bits
altos del producto que `STATE_MUL_COMBINE` ya calcula entero para `MULFX`, y
`REM` es el resto que el divisor deja en `divide_remainder` y hoy se tira.

Y `MULHI`, `DIVU`, `REM` y `REMU` siguen siendo los únicos cuatro mnemónicos de
la ISA sin ningún test, como dice el punto 4 del `TODO.md` del repositorio.
