# MiniCPU con SDRAM, salida HDMI y memoria en ráfagas

> **Backport de `R0` cableado a cero.** Esta carpeta recibio el cambio despues
> de cerrarse: `R0` vale siempre cero y descarta las escrituras, que es una
> regla de la MiniISA y no una extension opcional. Ver
> [`1.isa/isa.md`](../1.isa/isa.md) seccion 1.
>
> **Este monitor responde ahora 1.19.** Subio por el backport, sin cambiar
> ni un byte del protocolo: es lo unico que el PC puede preguntar para saber que
> bitstream tiene delante, y un programa que use `R0` como registro general no
> para con error en el bitstream viejo, da otro resultado en silencio.
>
> El texto que sigue es anterior al backport. Los numeros de version que
> menciona mas abajo son historicos; los de hoy estan en
> [`resumen-prototipos.md`](../docs/resumen-prototipos.md).


Copia de [`../16.fpga-cpu-hdmi`](../16.fpga-cpu-hdmi) cuyo camino de memoria se
va sustituyendo por uno de ráfagas BL8, para que la CPU no pase la vida
esperando a la SDRAM. Es el punto 0 del [`../TODO.md`](../TODO.md).

**Estado: en curso.** Lo que hay hecho y medido:

| Paso | Contenido | Estado |
|---|---|---|
| 0 | Medir en qué se van los ciclos, antes de escribir RTL | **hecho** |
| 1 | Búfer de instrucciones, cuatro líneas de 16 bytes | **hecho** |
| 2 | Banco de pruebas del controlador BL8 | **hecho, dos fallos encontrados** |
| 3 | Lector de vídeo sobre ráfagas | **hecho** |
| — | Integración del camino entero en `top.v` | **hecho, 2,94× medido** |
| — | Banco de pruebas del árbitro | **hecho, dos suposiciones corregidas** |
| 4 | Combinación de escrituras | **hecho, 4,15× medido** |

Nada de esto está verificado **en placa**: la ULX3S no estaba conectada a esta
máquina. Todo lo de abajo es simulación, síntesis y barrido de semillas.

El paso 0 reordenó el plan y está contado entero en
[`docs/medida-inicial.md`](docs/medida-inicial.md). El resumen: de los ~26 ciclos
por acceso de 16 bits, **8 son comandos de SDRAM y 6,5 son suelo de handshake y
de CPU**; y **el scanout se lleva otro 35 %** del tiempo de la CPU. Por eso el
búfer de instrucciones se hizo primero: es lo más grande, y no necesita BL8 para
nada —sobre el bus de 16 bits ya daba 2,65×—.

El paso 2 encontró **dos fallos** en el controlador BL8 que llegó de
`pruebas/sdram`, uno de ellos grave: la ráfaga de lectura salía corrida un beat
en la placa. Está contado en
[`docs/controlador-bl8.md`](docs/controlador-bl8.md).

El paso 3 sustituye el lector de líneas por
[`video_line_source_burst.v`](video_line_source_burst.v), con el mismo contrato
`fill_*` hacia el scanout. Una línea pasa de **320 accesos sueltos a 40 ráfagas**,
y de ~3 520 ciclos de bus a **852**, de los 6 400 de presupuesto por par de
líneas de pantalla.

Y con eso **el camino de memoria entero está integrado en `top.v`**: controlador
de 128 bits, árbitro de cuatro puertos y un adaptador por cliente. El bucle
interior de `swap_demo_fast` pasa de los **146 ciclos por palabra de la 16 a
49,7: 2,94×**, medido por
[`cpu_burst_system_tb.v`](cpu_burst_system_tb.v) sobre el sistema completo.
Cómo está montado y qué costó cerrar temporización está en
[`docs/camino-de-memoria.md`](docs/camino-de-memoria.md).

Mejora sobre el techo que daba el búfer con el bus de 16 bits (53,2 ciclos por
palabra) porque ahora **una línea de 16 bytes es exactamente una ráfaga BL8**: un
fallo se resuelve con una petición en lugar de cuatro transacciones, y una
escritura de 32 bits es una ráfaga enmascarada en lugar de dos accesos.

**El reloj baja de 100 a 80 MHz**, y no es opcional: con la restricción en 100,
el camino de 128 bits **no cumple ninguna semilla** (83,9 a 91,8 MHz). A 80
cumplen las ocho —hoy, con los contadores de rendimiento dentro, siete de ocho
entre 80,9 y 94,0 MHz—, así que la semilla vuelve a no decidir si el diseño
funciona, que es el mismo criterio con el que la 16 bajó de 120 a 100. **El
baudio no cambia**: el divisor 80 sigue dando 1 Mbaud exacto, y por eso se
eligió 80 MHz y no otra frecuencia. La versión del monitor sube a **1.12**.

Eso se come parte de la mejora: **4,15× en ciclos son 3,32× en tiempo real**.

El lector de vídeo no da por hecha la alineación. `video_registers` solo obliga a
alinear `FB_FRONT` y `FB_BACK` a cuatro bytes, así que una base como `0x01000004`
es legal y dejaría todas las líneas a caballo entre ráfagas. Arranca en la ráfaga
alineada que contiene la primera palabra y descarta lo que sobra por delante;
cuesta una ráfaga más por línea, y el banco lo comprueba con los dos casos.

## Un framebuffer de verdad, sin placa

[`video_fullframe_tb.v`](video_fullframe_tb.v) es la prueba más cercana a la
placa que se puede hacer sin ella: **320×240 de verdad**, dibujado por la CPU
real ejecutando un programa real desde la SDRAM, sobre el camino de memoria
completo. Tarda **35 segundos** y simula 2,5 millones de ciclos de CPU.

Ejercita lo que un simulador funcional no puede: el búfer de instrucciones, la
combinación de escrituras con su vaciado forzado al escribir `SWAP`, el
controlador BL8, el árbitro con dos clientes compitiendo, y `HALT_AT` dentro del
sistema completo en vez de aislado.

```powershell
..\.venv\Scripts\apio.exe test video_fullframe_tb.v
..\.venv\Scripts\python.exe ..\tools\frame-to-image.py frame_full.bin mirar.jpg
..\.venv\Scripts\python.exe ..\tools\frame-to-image.py frame_full.hex mirar.png --escala 2
```

Vuelca el framebuffer en dos formatos a la vez: `.bin` en RGB565 crudo, que es
**exactamente lo que devuelve `monitor.py read-block` desde la placa** —así el
mismo fichero esperado sirve para los dos sitios—, y `.hex` de medias palabras
una por línea, para mirar un píxel concreto con un editor de texto.

Dos cosas difieren de la placa y conviene saberlas:

- **Los framebuffers están en `0x00010000` y `0x00035800`**, no en `0x01000000`.
  El modelo de SDRAM saca la fila de los bits `[23:11]` de la dirección de
  palabra, y `0x01000000` pediría la fila 4096. Con las bases bajas los dos
  buffers caben en 128 filas. No toca ningún camino lógico.
- **No se comprueba la salida del scanout píxel a píxel.** Renderizar 640×480
  son 420 000 ciclos de píxel y aquí ya cuesta. El scanout corre igualmente
  —hace falta para que ocurran los intercambios y para vigilar el underflow— y
  la comparación píxel a píxel la hace [`video_frame_tb.v`](video_frame_tb.v) a
  resolución reducida, donde es barata.

El programa es [`examples/fullframe.asm`](examples/fullframe.asm), que pinta una
«L» azul y un cuadrado blanco. La «L» no es simétrica a propósito: un marco
completo se ve igual si alguien intercambia los ejes; una línea arriba y una
columna a la izquierda, no.

## La combinación de escrituras

El paso 4 guarda **una línea de 16 bytes** en `cpu_dmem_adapter`: mientras la CPU
siga escribiendo dentro de esa línea, las escrituras se funden y se contestan en
un ciclo, sin tocar la memoria. Cuatro `STORE` con `+4` caben en una línea, que
es exactamente el bucle interior.

| | ciclos por palabra | ráfagas |
|---|---:|---:|
| La 16 | 145,9 | (1 610 accesos de 16 bits) |
| Camino de ráfagas | 49,7 | 163 |
| **Con combinación** | **35,2** | **42** |

**4,15×** sobre la 16, o **3,32× netos** contando el reloj más lento.

Lo delicado no es la combinación sino los tres vaciados forzados —MMIO, parada de
la CPU, y lectura que caiga en la línea guardada—, y cada uno tiene control
negativo comprobado: se quitó del RTL y se verificó que el banco falla. Ahí
apareció un fallo real, que `wb_dirty` bajaba al *empezar* el volcado y no al
terminarlo, con lo que la carrera con el monitor seguía abierta. Está contado en
[`docs/combinacion-escrituras.md`](docs/combinacion-escrituras.md).

## El árbitro, y dos cosas que su banco corrigió

[`memory_fabric_tb.v`](memory_fabric_tb.v) es el banco propio de
`memory_fabric_4`, que llegó de `pruebas/sdram` sin ninguno. Encontró dos
suposiciones falsas, una mía y otra del diseño:

**El caso de round-robin que escribí primero no probaba nada.** Con cuatro
clientes que piden una vez y callan, el orden sale 0,1,2,3 *aunque el puntero no
avance jamás*: cada uno baja su `valid` al ser servido y el `else if` en cascada
hace el resto. Lo comprobé sustituyendo el avance del puntero por
`rr_ptr <= MASTER_0`, y **el banco seguía en verde**. De ahí sale el caso que sí
lo distingue: los cuatro pidiendo sin parar. Con el árbitro bueno, 12/12/12/12;
con el puntero clavado, 21/21/3/3 y falla.

**`urgent` mantenido no es monopolio**, que es lo que yo había supuesto por
analogía con la prioridad absoluta que se le dio al vídeo en la 16 —y que allí
resultó ser monopolio de verdad—. El árbitro solo mira `p2_urgent` cuando
`p2_req_valid` está alto, así que en cuanto el lector de vídeo deja un hueco
entre peticiones, el round-robin reparte. Lo que sí se cumple es el invariante
«mientras el puerto 2 pide con `urgent`, no se concede a nadie más», y el banco
lo vigila en todos los ciclos, no solo donde se espera que se cumpla.

De paso se quitaron cuatro `$error` del árbitro que saltaban con direcciones no
alineadas a 16 bytes. No es un fallo: el árbitro **ya responde `rsp_error`** a
ese caso, que es comportamiento definido. Un assert que se dispara por una
entrada que el módulo maneja bien solo convierte una prueba legítima en ruido.

## Una trampa de `memory_fabric_4`, para la lista

**`req_ready` no llega hasta que el cliente ha levantado `req_valid`**: la
concesión mira el `valid` del propio puerto. Un cliente escrito de la forma que
parece razonable —esperar a `ready` y entonces levantar `valid`— **se cuelga para
siempre**. Hay que levantar `valid` primero y esperar `ready` después.

Es la primera piedra con la que tropieza cualquiera que escriba un cliente para
este árbitro, y costó una simulación colgada. Va en la misma familia que el pulso
de un ciclo del monitor: el árbitro tampoco engancha pulsos, y por eso el
`monitor_mem_adapter_128` es quien lo mantiene.

La concesión pasó a ir **registrada** al cerrar temporización, así que ya no hay
lazo combinacional entre `valid` y `ready` —eso costaba 11 ns de camino—, pero el
orden sigue siendo el mismo: primero `valid`.

Todo lo de abajo, desde «Escalera de hitos», es la documentación heredada de la
16 y sigue describiendo lo que hay, salvo donde esta sección diga otra cosa.

## El búfer de instrucciones

[`instruction_buffer.v`](instruction_buffer.v) se intercala entre el puerto
`imem` de la CPU y el puerto 1 del árbitro. Del lado de la CPU el contrato es el
de `imem` tal cual; del lado de la memoria es un puerto de 128 bits.

Son **cuatro líneas de 16 bytes**, mapeo directo, 512 biestables de datos. El
tamaño no es arbitrario: 16 bytes son exactamente las cuatro instrucciones del
bucle interior de [`swap_demo_fast`](examples/swap_demo_fast.asm), así que desde
la segunda iteración el bucle entero vive dentro y el `BLT` salta dentro del
propio búfer.

Cuatro líneas y no una, ni dos, por el mismo motivo que el plan señalaba: si el
bucle cae a caballo entre dos líneas se fallaría en cada iteración. Con el índice
en los dos bits que siguen a la línea, dos líneas contiguas nunca chocan y un
bucle de hasta 64 bytes entra entero, esté alineado o no.
[`instruction_buffer_tb.v`](instruction_buffer_tb.v) lo comprueba con un control
negativo explícito: instancia **también** un búfer de dos líneas y un bucle de
48 bytes en el que ese tiene que degradarse. Y se degrada: 3 fallos contra 11.
Sin ese caso, elegir cuatro líneas sería una decisión sin respaldo.

### Coherencia, que aquí es barata

El monitor reescribe la memoria de programa mientras la CPU está parada, así que
el búfer **se vacía entero mientras `cpu_halted` está alto**: la primera búsqueda
después de arrancar falla siempre, por construcción. Eso cubre el único caso de
incoherencia que existe, porque esta CPU no escribe su propio código: `dmem` no
pasa por el búfer. Un reset de CPU también la deja parada, así que la misma señal
cubre los dos casos.

Lo que **no** se guarda: las direcciones fuera de la SDRAM y las búsquedas
anteriores a `init_done`, que el adaptador responde con `0xf8000000` —un opcode
inválido a propósito—. Guardar esa respuesta la haría permanente.

### Lo que cobra

Sobre el bucle interior real, 160 iteraciones:

| | ciclos por palabra | medido por |
|---|---:|---|
| La 16, sin vídeo | 145,9 | [`perf_probe_tb.v`](perf_probe_tb.v) |
| Con búfer, sobre el bus de 16 bits | 55,1 | (versión intermedia, 2,65×) |
| Con búfer, sobre ráfagas | **49,7** | [`cpu_burst_system_tb.v`](cpu_burst_system_tb.v), **2,94×** |

Del bucle entero quedan **163 ráfagas**: 160 escrituras y tres rellenos de línea,
porque el programa ocupa tres líneas de 16 bytes y ninguna se relee. En la 16 eso
mismo eran 1 610 accesos de 16 bits.

Un fallo trae la línea entera en **una sola ráfaga**, que es la razón de que una
línea sean 16 bytes y no otra cosa: 16 bytes son exactamente una BL8. Así que el
código en línea recta no pierde nada —traer cuatro instrucciones cuesta una
petición en lugar de cuatro— y gana todo lo que se relea.

### Lo que costó en la FPGA

El camino entero, no solo el búfer: 5 477 → **8 624 LUT** y 2 523 → **4 713 FF**,
que sigue siendo el 10 % del ECP5-85F. La mitad larga de ese crecimiento es el
bus de 128 bits, que ensancha el árbitro, el controlador y los tres adaptadores.

Lo que costó cerrar temporización —de 84 a 100 MHz, con una parada en 78 por
arreglar el camino crítico equivocado— está en
[`docs/camino-de-memoria.md`](docs/camino-de-memoria.md).

---

# Documentación heredada de la 16

Fusión de la CPU con SDRAM de `10.fpga-cpu-ram` y la cadena DVI de `13.hdmi`,
sobre ULX3S-85F. El plan por fases está en
[`../15.isa-v2/planning.md`](../15.isa-v2/planning.md) y la arquitectura de
destino en
[`../15.isa-v2/gpu_educativa_arquitectura.md`](../15.isa-v2/gpu_educativa_arquitectura.md).

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
`run_tests.py --backend cpu-fpga --version hdmi` distinga este bitstream del
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
..\.venv\Scripts\python.exe ..\..\tools\make-framebuffer diagonal fb.bin
..\.venv\Scripts\python.exe monitor.py write-block 0x01000000 fb.bin --port COM3
```

`tools/make-framebuffer` genera patrones pensados para diagnosticar, no para
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
..\.venv\Scripts\python.exe ..\..\tools\make-framebuffer bars fb0.bin
..\.venv\Scripts\python.exe ..\..\tools\make-framebuffer checker fb1.bin
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
..\tools\run-board.ps1 --prototype 18 --program swap_demo_fast
..\tools\run-board.ps1 --prototype 18 --program tear_demo_fast
..\tools\run-board.ps1 --prototype 18 --program swap_demo --no-run     # cargar sin arrancar
..\tools\run-board.ps1 --prototype 18 --program tear_demo --port COM4
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

Las cifras de arriba salen de [`tools/measure-demo.ps1`](../tools/measure-demo.ps1), que lee
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

## Lo que sólo dijo la placa

Tres cosas pasaron los 18 bancos en verde y fallaron en hardware. Vale la pena
mirarlas juntas, porque las tres fallan por el mismo motivo de fondo: **el
banco y el diseño compartían la suposición equivocada**.

### La captura de DQ no tenía margen

El síntoma inicial fue una vuelta completa de escribir y leer que devolvía la
ráfaga corrida un beat. `READ_DELAY_CYCLES` estaba en 1 por analogía con el
controlador BL1 de la 16, que muestrea en `ST_READ` + dos esperas + captura. La
analogía era mala: **la 16 corre a 100 MHz y ésta a 80**. El viaje de ida y
vuelta —camino de salida, pin, pista, pin de vuelta, camino de entrada— es
físico y no cambia con el reloj, así que a 10 ns se sale del ciclo y a 12,5 ns
cabe dentro.

Con el parámetro a 0 la vuelta salía exacta y la suite pasaba 12 de 12… la
primera vez. Después empezó a fallar de forma intermitente. Una matriz de las
128 casillas (8 beats × 16 DQ), escribiendo un único 1 aislado en cada una,
dio el diagnóstico:

```
semilla 7 ->  (3,4) (3,5) (7,4) (7,5)
semilla 1 ->  (0,6) (3,4) (3,6) (4,6) (6,6) (7,4) (7,6)
```

**Los bits malos cambian al recompilar.** Un fallo que se mueve con la
colocación es margen, no lógica. Y el `Fmax` de nextpnr no lo veía: daba
+14,5 % de holgura, porque el camino que falla entra por un pin y nextpnr no
modela lo que pasa fuera del chip.

Las dos medidas acotan el instante bueno: en T+2 la captura es marginal, en T+3
llega un beat entera tarde. O sea que el límite del beat cae entre los dos
flancos de subida. La solución es muestrear en medio, en el flanco de **bajada**:

```verilog
reg [15:0] dq_negedge;
always @(negedge clk) dq_negedge <= sdram_d;
```

Medio ciclo —6,25 ns a 80 MHz— de margen por los dos lados en vez de cero.
Después: las 128 casillas limpias en cuatro direcciones distintas, y cinco
suites completas seguidas a 15 de 15.

La matriz queda como herramienta, porque es lo único que distingue este fallo:

```powershell
..\.venv\Scripts\python.exe sdram_dq_matrix.py --port COM3
```

**Por qué ningún banco pudo cazarlo.** El modelo de SDRAM tiene el mismo
parámetro `READ_DELAY_CYCLES` que el controlador. Emparejados, leen bien con
cualquier valor: la simulación comprueba que son coherentes entre sí, no que
coincidan con la placa. Es una calibración, y una calibración sólo la fija el
hardware. `sdram_controller_128_tb.v` lo dice ahora en su cabecera, donde antes
afirmaba lo contrario.

### `HALT_AT` sólo servía una vez por encendido

Comparaba con `==` contra un `SWAP_COUNT` que sólo el reset de la placa ponía a
cero. El caso `bounce` pasaba la primera vez y después **no paraba nunca más**:
el contador iba ya por 3 655 y la igualdad no volvía a darse. Ahora armar la
alarma fija el origen de la cuenta, y es de un disparo.

El simulador no podía verlo: construye un `VideoDevice` nuevo en cada
ejecución, así que siempre empieza de cero. Es la diferencia entre un modelo
que arranca limpio y una placa que acumula estado.

### El contador de instrucciones contaba una de menos

Y esto lo cazó la propia tabla de `--measure`, que es para lo que sirve tener
el número de instrucciones de varios backends en la misma fila: salió
`¡discrepan!` en los nueve programas a la vez, siempre por uno. El `HALT` retira
en el mismo ciclo en que `cpu_halted` sube, y el contador estaba condicionado a
`!cpu_halted`. Nueve discrepancias idénticas no son nueve CPU distintas: son una
definición mal puesta.

## Uso y comprobaciones

Desde esta carpeta:

```powershell
..\.venv\Scripts\apio.exe test video_fullframe_tb.v
..\.venv\Scripts\apio.exe test video_frame_tb.v
..\.venv\Scripts\apio.exe test cpu_burst_system_tb.v
..\.venv\Scripts\apio.exe test write_combine_tb.v
..\.venv\Scripts\apio.exe test memory_fabric_tb.v
..\.venv\Scripts\apio.exe test video_burst_tb.v
..\.venv\Scripts\apio.exe test sdram_controller_128_tb.v
..\.venv\Scripts\apio.exe test instruction_buffer_tb.v
..\.venv\Scripts\apio.exe test perf_probe_tb.v
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

Los siete primeros son de esta carpeta. `write_combine_tb.v` cubre los tres
vaciados forzados del bufer de escrituras, cada uno con control negativo. `memory_fabric_tb.v` es el banco propio
del arbitro, contado mas arriba. `cpu_burst_system_tb.v` es el de
sistema del camino nuevo: carga un programa por el monitor con la CPU parada, la
arranca, mide el bucle interior, la para y vuelve a leer lo que escribió —el
camino que rompe una incoherencia de búfer, y el que se queda mudo si se pierde
el pulso del monitor—. `video_burst_tb.v` monta el lector de ráfagas contra el
árbitro, el controlador BL8 y el modelo de SDRAM; `sdram_controller_128_tb.v` verifica el
controlador BL8 contra un modelo de SDRAM, con su propio control negativo; `instruction_buffer_tb.v` verifica el
búfer contra un control negativo, y `perf_probe_tb.v` es el instrumento de
medida del paso 0, que además sirve de banco de no-regresión —comprueba que el
búfer real no se aleja más de un 10 % de su techo—.

Los cinco bancos de CPU son los de 10 y pasan sin cambios; el único ajuste es la
versión esperada en `monitor_tb.v`, y que `cpu_sdram_system_tb.v` ahora instancia
el búfer de instrucciones, porque es el banco que mejor lo ejercita de punta a
punta: carga el programa por el monitor con la CPU parada y luego la arranca, que
es justo el caso que obliga a vaciarlo. Los dos de vídeo se reparten el trabajo a
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
..\.venv\Scripts\python.exe ..\x.tests\run_tests.py --backend cpu-fpga --version bl8 --port COM3
```

Es la comprobación que de verdad importa: que meter el vídeo no ha roto la CPU.
Pasan **12 de 12** casos.

### Medir el CPI

`top.v` cuenta ciclos e instrucciones mientras la CPU corre, y el monitor los
saca con los comandos `0x36` y `0x37`:

```powershell
..\.venv\Scripts\python.exe monitor.py perf --port COM3
```

Para comparar esta versión con las anteriores en los mismos programas, el runner
tiene `--measure`, que saca una tabla en Markdown:

```powershell
..\.venv\Scripts\python.exe ..\x.tests\run_tests.py --backend cpu-fpga `
    --measure medidas.md --port COM3 ..\x.tests\cases
```

El porqué de los dos contadores, y qué miden exactamente, está en
[`docs/cycles.md`](docs/cycles.md).

### `MUL`, `MULFX` y `DIV`

Hasta hace poco pasaban 11 de 12: fallaba `multiply`, porque esta CPU declaraba
`MUL` y lo validaba, pero no tenía rama de ejecución. Caía en el `default` y
respondía `ERROR_INVALID_OPCODE`. El simulador sí lo implementaba, así que el
mismo caso pasaba con `--backend cpusim` y fallaba en la FPGA.

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
