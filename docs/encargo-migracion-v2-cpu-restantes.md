# Encargo: terminar MMIO v2 en la familia CPU — la 6, la 10 y la 16

Tres carpetas de CPU siguen en v1: la **6**, la **10** y la **16**. Con ellas se
cierra la familia entera y el mapa de transición `1.isa/mmio_map_v1.vh` pierde a
la mitad de sus clientes.

**Antes de nada, lee cuatro documentos**, en este orden:

1. [`validacion-mmio-v2-placa.md`](validacion-mmio-v2-placa.md) — la ronda de
   placa de las tres ya migradas. **Es el más importante para ti** y no es una
   bitácora de migración: es lo que sólo se ve cuando el bitstream existe.
   Encontró cuatro bugs, tres en el arnés compartido y uno en RTL, y ninguno
   tenía que ver con el mapa.
2. [`../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md`](../18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md)
   — la más corta, y la que mide hasta dónde llega el atajo de copiar de una
   gemela. Es también la primera carpeta sin puerto serie, que es tu caso ×3.
3. [`../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md`](../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md)
   — lo que cambió al repetir la migración, y la estimación corregida.
4. [`../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md`](../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md)
   — el camino completo. Léelo una vez entero; luego consúltalo.

Y [`AGENTS.md`](../AGENTS.md) antes de invocar `yosys`, `nextpnr` o `apio` a
mano: **casi seguro que ya existe un lanzador en `tools/`**.

## Regla primera: este prompt es una hipótesis

Todo lo que sigue se midió el **2026-09-20** sobre el árbol. Verifica cada dato
antes de actuar sobre él, y si algo no cuadra, **dímelo antes de seguir**.

No es una fórmula de cortesía. De las nueve afirmaciones concretas del encargo
anterior a la 18, **cinco no se sostuvieron**. Y el encargo de validación de
placa, escrito con esa lección delante, aun así afirmaba que «los bitstreams
programados son de v1» —la placa llevaba uno de v2— y que «la receta de placa
está corregida en los README de las tres» —la de la 21 sigue entera en v1—.

Un dato que viaja de documento en documento sin volver a medirse envejece igual
que el código, y es más difícil de auditar porque suena a conclusión.

## Lo que hay, medido

### Las tres no son la misma carpeta

| | 6 `ebr` | 10 `sdram` | 16 `hdmi` |
|---|---|---|---|
| Monitor | 3.6 | 3.10 | 3.16 |
| Capacidades | `mul_div` | — | `mul_div`, `video`, `perf_counters` |
| `.v` sin bancos / bancos | 11 / 7 | 11 / 7 | 20 / 12 |
| `examples/*.asm` | **0** | **0** | **6** (5 tocan MMIO) |
| `mmio_decoder.v` | no | no | **sí** |
| `video_registers.v` | no | no | **sí** |
| `cpu_perf_counters.v` | no | no | **sí** |
| `mmio_mux.v` | **no** | **no** | **no** |
| `cpu_dmem_adapter.v` | no | no | **no** — usa `sdram_system_adapter.v` |
| `sysid.v` | sí | sí | sí |
| Semilla fijada | 4 | 2 | 1 |

**La 6 y la 10 no tienen MMIO en absoluto.** Su `sysid` cuelga del camino del
monitor, seleccionado por una comparación cableada:

```verilog
wire sysid_selected = mem_address[31:4] == 28'h800_00f0;   // 6.fpga-cpu:83
wire sysid_selected = adapter_monitor_address[31:4] == 28'h800_00f0;  // 10:140
```

Y sus dos `top.v` lo dicen con todas las letras: «Esta carpeta NO tiene MMIO, y
no lo gana aquí». Migrarlas **no es darles MMIO**: es mover el bloque de
identificación de `0x80000F00` (4 palabras) a `0x80000000` (7 palabras).

**La 16 sí es una migración de verdad**, pero con otra forma que la 18: no tiene
`mmio_mux.v` ni `cpu_dmem_adapter.v`, su dirección MMIO son **12 bits**
(`wire [11:0] mmio_address`, `top.v:203`) y monta `sdram_system_adapter.v`, que
es su bloque único.

### Los siete `sysid.v` de v1 son byte a byte el mismo fichero

Medido con `Get-FileHash`: **6, 10, 16, 12, 14, 17 y 22** comparten
`E79538C7B9F0462818BD07FD2DBFB3B1`. Los de 18, 19 y 21 son otro, el de v2.

Eso importa por `test_monitor_port.test_sysid_es_copia_identica`, que agrupa por
la versión del contrato que declara el magic de dentro. Migrar la 6 la saca del
grupo de v1 y la mete en el de v2, y el test lo acepta **por diseño**. Cuando
migre la última, el grupo de v1 se vacía y vuelve a ser la comprobación de
siempre sin tocar nada.

### El decodificador de la 16 no tiene los parámetros de v2

```verilog
mmio_decoder #(.FOLDER(8'd16), .HAS_SERIAL(0), .VIDEO_REGISTERS(64'h4f),
               .ISA_PROFILE(32'h0000_0003)) mmio_decoder_i(
```

Faltan `DEVICES`, `MEM_BASE`, `MEM_SIZE` y `MONITOR_VERSION`, que son de v2 y
hay que añadirlos. Los tres valores fáciles salen del RTL; **`MONITOR_VERSION`
no se deduce de nada**: es `(mayor << 8) | menor` con los números del
`monitor #(...)` de al lado, o sea `32'h0000_0310` para la 16. Copiar el de otra
carpeta es un número perfectamente válido que hace que el bloque SYSTEM declare
un juego de comandos que esta carpeta no implementa, y **ningún test lo dice**.

### La decisión de diseño de la 16, y es la única que hay

Su `video_registers.v` implementa **cinco** registros:

```verilog
REG_FB_FRONT = 0   REG_FB_BACK = 1   REG_SWAP = 2   REG_STATUS = 3   REG_CTRL = 6
```

De ahí el `VIDEO_REGISTERS(64'h4f)`, que es **correcto hoy** —no es el resto de
nada— y que el test `test_el_top_no_estrecha_el_bitmap_de_video` ya respeta,
porque deriva el bitmap esperado de los `localparam REG_*` de la propia carpeta y
no del contrato.

En v2 el orden cambia: `CTRL` pasa a índice 0 y los demás se desplazan. Si la 16
conserva exactamente los mismos cinco registros, su bitmap pasa a ser
**contiguo** —`CTRL`=0, `FB_FRONT`=1, `FB_BACK`=2, `SWAP`=3, `STATUS`=4, o sea
`0x1f`—. **Compruébalo, no te fíes de esta línea**, y decide explícitamente si la
16 gana los cinco registros nuevos de v2 (`FRAME_COUNT`, `SWAP_COUNT`, `HALT_AT`,
`HALT_TARGET`, `VIDEO_TX`) o se queda con los cinco que tiene. Lo segundo es
conforme —§20 pide «el periférico que tengas, en v2»— y es más barato; lo primero
le daría `frame_capture`, que hoy no tiene, y con ello los casos de vídeo del
runner.

**Esa decisión es tuya y quiero que la escribas**, con el porqué.

### Nadie ejecuta los `examples` de estas tres

`grep` sobre los `test.json`: **cero** casos apuntan a `6/`, `10/` o `16/`. Y la
guarda de direcciones cableadas, `CARPETAS` en `test_mmio_map.py:318`, cubre los
`examples` de **18, 19 y 21** y no los de la 16.

O sea que los cinco `.asm` de la 16 que hacen `MOVHI R20, 0x8000` no los mira
nada hoy. **Añade `16.fpga-cpu-hdmi/examples` a `CARPETAS` antes de tocar un
`.asm`**: falla al instante, nombra los ficheros, y a partir de ahí la guarda es
tu lista de trabajo — cuando deja de fallar, la fase está hecha.

## Lo que ya está hecho y no se repite

Esto era la mitad del trabajo de la 21 y está pagado:

- **`.equ` en el ensamblador**, `1.isa/mmio_map.vh` como fuente única y
  `tools/generate-mmio --check`.
- **`1.isa/mmio_map_v1.vh`**, el mapa de transición con los nombres de v2. Deja
  simbolizar los `.asm` **sin mover ninguna dirección**, y que migrarlos sea
  después cambiar la línea del `.include`. Su criterio de borrado está corregido:
  sobra cuando lo suelta la **última** carpeta, no la primera.
- **`test_top_wiring.py`**, anchuras de puerto en los diez `top.v` y en sus
  bancos.
- **`test_fullframe_fixture.py`**, que descubre solo las carpetas con el trío.
- **Los periféricos funcionales** y los tres backends de simulador.
- **`test_monitor_protocol.test_la_ventana_del_cli_cubre_los_bloques_que_decodifica`**,
  nuevo, que caza el resto de v1 del apartado siguiente.

## Trampas, en orden de lo que más duele

Las tres primeras son de la ronda de placa y **no están en ninguna de las tres
bitácoras de migración**, porque se descubrieron después.

**1. Migrar una dirección no es migrar su semántica.** `x.tests/backends/fpga.py`
es único y compartido por las diez carpetas, y tras la migración tenía las
direcciones de v2 con la semántica de v1 en tres sitios a la vez: armaba
`HALT_AT` con un número de intercambios (en v2 cuenta **frames**), no escribía
nunca `HALT_TARGET` (que arranca a cero, o sea que la alarma no para a nadie) y
leía los frames de `STATUS[31:16]` (en v2 tienen registro propio). Nueve casos de
vídeo daban **timeout de 20-30 s**, que no se parece a la causa.

Ya está arreglado. Lo que te toca a ti es el corolario: **cuando toques una pieza
compartida, mira si tiene gemela.** El simulador había recibido las dos
correcciones en su día, con comentarios explicando la trampa; su gemelo de placa
no recibió ninguna, porque ningún camino automático lo ejecuta sin una placa
enchufada.

**2. El lado host tiene DOS sitios con la ventana MMIO, y los tests sólo miraban
uno.** `MONITOR_REGIONS` estaba migrado en la 18 y la 19; `MMIO_BASE` /
`MMIO_LIMIT` —que usa `parse_address`, o sea la línea de órdenes— seguían con la
página de 4 KiB de v1, y la 19 además declaraba `SERIAL_BASE = 0x8000_0200`.
Desde el CLI de esas dos eran inalcanzables VIDEO, SERIAL y CPU PERF.

Lo perverso es cómo se camuflaba: el síntoma era `exit=1` con un `Error:`, que es
**exactamente lo que se espera** al comprobar que un bloque ausente da error. Al
medir el caso negativo de la 18, el resto de v1 se leía como la confirmación que
se venía a buscar.

Ahora hay un test que lo exige. **Tu trabajo es que las tres carpetas lo pasen**,
y en la 6 y la 10 hay que mirarlo con cuidado porque su `monitor.py` **no tiene**
`MMIO_BASE`/`MMIO_LIMIT` —no tienen MMIO— sino un `SYSID_BASE` y una
`MONITOR_REGIONS` de una sola ventana `(SYSID_BASE, 0x8000_0f10)`.

**3. `tools/build-sweep` NO sintetiza.** Re-ruta el `hardware.json` del build
archivado más reciente. Si la carpeta ha tocado RTL desde entonces, el barrido
mide un diseño que ya no existe y devuelve ocho números plausibles y **falsos**,
sin nada en la salida que lo delate. Ejecuta `tools/build` **antes** de barrer.

Y dos detalles de lectura que cuestan tiempo:

- El `Elapsed` de `tools/build-status` es **`mm:ss`**, no `hh:mm`.
- Un `build.log` de nextpnr trae la temporización **dos veces**: una estimación
  pre-rutado, 10-20 MHz más pesimista y que suele ser un FAIL aparatoso, y la
  buena. **La buena es la última.**

**4. La semilla es propiedad de un netlist, no de un diseño.** Cualquier cambio
de RTL invalida el barrido anterior, y «cualquiera» incluye cambios que no tocan
ningún camino crítico: en esta última ronda, **una línea** de `video_registers.v`
llevó a la 21 de 3-de-8 a 7-de-8. Rebarre siempre, y compara contra el barrido
anterior **del mismo juego de semillas** — comparar «la semilla que estaba
fijada» contra «un barrido nuevo» compara un máximo contra una muestra y siempre
sale mal.

**5. El bloque SYSTEM es casi gratis y los contadores no.** El reparto del área
de v2, medido por módulo sobre la 18:

| Módulo | ΔLUT4 |
|---|---:|
| `cpu_perf_counters` | **+180** (44 % del total) |
| `monitor_mem_adapter_128` | +91 |
| `video_registers` | +90 |
| `monitor` | +42 |
| `mmio_decoder` | +40 |
| `mmio_mux` | +20 |
| `sysid` | **+6** |
| `cpu_dmem_adapter` | **−66** |

Las siete palabras de SYSTEM son **constantes**, y una constante no cuesta
lógica. Para ti: **la 6 y la 10 deberían costar casi nada** —sólo tocan `sysid`—
y la 16 se lleva lo suyo por `cpu_perf_counters` y `video_registers`.

**6. `HALT_TARGET` arranca a cero, así que no para a nadie.** Si decides darle
`frame_capture` a la 16, esto te va a morder. En v1 bastaba escribir `HALT_AT`.

**7. La placa desaparece sola tras programar.** COM3 se va y vuelve por su
cuenta. **No pidas replugar el USB**: espera.

## Orden recomendado: 6 → 10 → 16

Y el porqué, que no es el tamaño:

- **La 6 primero** porque es la migración más pequeña que existe en este repo
  —un `sysid.v` copiado, una comparación cableada, una ventana de monitor y un
  `monitor.py`— y porque es la primera carpeta **sin ningún bloque de
  dispositivo**. Esa forma es la que van a necesitar las de GPU, así que lo que
  aprendas ahí se amortiza cuatro veces.
- **La 10 después**, que es su gemela y debería salir casi gratis. Si no sale
  casi gratis, eso es el hallazgo y hay que escribirlo.
- **La 16 al final**, porque es la única con una decisión de diseño dentro (el
  bitmap de vídeo) y conviene tomarla con las otras dos ya hechas.

Si al medir ves que el orden es otro, dilo y cámbialo — pero dilo.

## Qué se paga en placa, y cuándo

**La placa va antes de lo que crees.** El encargo anterior la puso en el paso 6
de 7 y fue un error: es el único paso que mide algo que ninguna otra cosa mide, y
ponerlo al final garantiza que sus fallos se descubran tarde. La regresión del
arnés compartido se habría visto una hora antes.

Si hay una placa enchufada, **pregúntale lo que ya pueda contestar antes de
gastar una síntesis**: qué bitstream lleva, si su bloque SYSTEM responde, si el
mapa que ves es el que crees.

Lo que sólo se ve en placa, con lo que costó cada línea:

| Qué | Por qué no lo ve la simulación |
|---|---|
| Que el bloque SYSTEM responda con los valores de **esa** carpeta | Ningún banco instancia `top` |
| Que un bloque **ausente** conteste error y no cero | La 6 y la 10 no tienen ningún dispositivo: son el caso negativo puro |
| Que el error de un dispositivo **llegue al cliente** | Vive un ciclo y el cliente lo muestrea en el siguiente; lo caza `mmio_error_ack_tb.v`, que ya existe en 18/19/21 |
| La captura de DQ de la SDRAM (la 10 y la 16) | Entra por un pin; el barrido no la ve |
| Los `.asm` de `examples/` de la 16 | **Ningún `test.json` los ejecuta** |

## Valida lo que midas con un control negativo

Rompe la referencia a propósito y comprueba que falla, **y que falla por el
motivo correcto**. Tres avisos de método que ya costaron tiempo:

- **Verifica que la mutación se aplicó.** Este repo es CRLF en disco y LF en el
  índice, así que un `.Replace()` con el final de línea equivocado no encuentra
  nada y el control sale «OK» sin haber tocado el código.
- **Borra `__pycache__` entre pasadas.** Una mutación del mismo número de
  caracteres queda enmascarada por el bytecode viejo.
- **Que los dos desenlaces se distingan.** Al sondear si una escritura
  desalineada se rechazaba o se truncaba, dejé antes el registro en el valor
  truncado: los dos desenlaces daban el mismo número y la sonda «demostró» lo
  contrario de lo que pasaba.

Y uno nuevo, de esta última ronda: **un fallo perfectamente reproducible no
descarta una carrera.** Sólo significa que uno de los dos corredores gana casi
siempre.

## Verificación, sin saltarte ninguna

```
./tools/test --prototype 6        # y 10, y 16
./tools/lint --prototype 6        # compara el reparto POR TIPO, no el total
python x.tests/run_tests.py --backend cpusim
python -m unittest discover -s x.tests -p "test_*.py"
python tools/check-links.py && ./tools/generate-docs --check
./tools/generate-mmio --check
```

Y las suites de `1.isa`, `2.cpu-sim-func` y `11.gpu-sim-func`.

**Usa los lanzadores de `tools/`, no el `.py` a mano.** `generate_mmio.py` no
tiene bloque `__main__`: ejecutarlo directamente sale con 0 sin hacer nada, y
como 0 es lo que se espera de un `--check`, el falso verde es indistinguible del
bueno.

Números base a no empeorar, medidos hoy: **279** tests de `x.tests`, **53** casos
de `cpusim` con 0 fallos, **61 / 44 / 62** en `1.isa` / `2` / `11`.

## El entregable es el log

Uno por carpeta, `<carpeta>/docs/migracion-v2.md`, escrito **mientras** trabajas,
no al final. No repitas lo que dicen las tres bitácoras: enlázalas y **escribe
sólo la diferencia**. Lo que quiero:

- **qué salió más barato y qué más caro de lo estimado**, que es lo que corrige
  la estimación de la siguiente;
- **la decisión del bitmap de vídeo de la 16**, con el porqué;
- **qué encontró esta migración en las carpetas ya migradas** — las tres
  bitácoras anteriores encontraron algo cada vez, y la de la 18 encontró un FAIL
  de temporización;
- **qué falló que parecía funcionar**, incluido lo que hayas tenido que desmontar
  para creerte un verde;
- **si el orden 6 → 10 → 16 fue el correcto**, o había uno mejor;
- y **qué cuesta la primera de GPU**, corregido con lo que hayas visto.

## Definición de terminado

Las tres carpetas conforman con [`1.isa/mmio.md`](../1.isa/mmio.md); los tres
`sysid.v` están en el grupo de v2 y son byte a byte idénticos entre ellos y con
los de 18/19/21; `MONITOR_REGIONS` y la ventana del CLI cuadran en las tres y sus
tests pasan; cada una tiene bitstream que corresponde a su RTL y semilla fijada
**con su párrafo** en `apio.ini`; `generate-docs --check` al día y
`docs/synthesis-report.md` sin ningún FAIL; la matriz de DQ limpia en las que
tengan SDRAM; lint no ha empeorado **por tipo**; las suites de simulación siguen
verdes; `TODO.md` refleja el estado nuevo; y el log de cada carpeta sirve para
estimar la siguiente.

Al terminar, dime **qué queda para cerrar `mmio_map_v1.vh`** —o sea qué falta de
las cuatro de GPU— y **si el patrón de la familia CPU le sirve a la 17 o hay que
inventar otro**.
