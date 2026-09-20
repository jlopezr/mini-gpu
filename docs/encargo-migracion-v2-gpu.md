# Encargo: terminar MMIO v2 en la familia GPU — la 17, la 14, la 12 y la 22

Quedan cuatro carpetas y son las cuatro de GPU. Con ellas se cierra la travesía
entera y `1.isa/mmio_map_v1.vh` **se borra**, que es lo único que hoy le falta
para desaparecer: su criterio de borrado dice «cuando lo suelta la última
carpeta», y esa última está en esta lista.

**Antes de nada, lee cinco documentos**, en este orden:

1. [`../16.fpga-cpu-hdmi/docs/migracion-v2.md`](../16.fpga-cpu-hdmi/docs/migracion-v2.md)
   — **el más importante para ti**, y no por el mapa. Es la única carpeta a la
   que v2 le costó frecuencia, y la causa es exactamente la forma que tienen
   las cuatro tuyas: **decodificar sin `mmio_mux` por medio**. Lee entero el
   apartado «Dónde está el camino crítico, medido y no supuesto».
2. [`../6.fpga-cpu/docs/migracion-v2.md`](../6.fpga-cpu/docs/migracion-v2.md)
   — la carpeta sin ningún bloque de dispositivo, la fase 0 de las tres últimas
   y los tres analizadores rotos. Su apartado del lado host te vale tal cual:
   tus cuatro carpetas tienen el mismo `MAX_ADDRESS` que la 6.
3. [`validacion-mmio-v2-placa.md`](validacion-mmio-v2-placa.md) — lo que sólo
   se ve cuando el bitstream existe. Cuatro bugs, tres en el arnés compartido y
   uno en RTL, y ninguno tenía que ver con el mapa.
4. [`../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md`](../21.fpga-cpu-hdmi-alu/docs/migracion-v2.md)
   — el camino completo. Léelo una vez entero; luego consúltalo.
5. [`../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md`](../19.fpga-cpu-hdmi-ls/docs/migracion-v2.md)
   — **su apartado «Para la 17, y es otra forma» está medido y en parte es
   falso.** Lo corrige este encargo más abajo. Léelo sabiendo eso.

Y [`../AGENTS.md`](../AGENTS.md) antes de invocar `yosys`, `nextpnr` o `apio` a
mano: **casi seguro que ya existe un lanzador en `tools/`**.

## Regla primera: este prompt es una hipótesis

Todo lo que sigue se midió el **2026-09-20** sobre el árbol, en el commit
`8c2b261`. Verifica cada dato antes de actuar sobre él, y si algo no cuadra,
**dímelo antes de seguir**.

No es fórmula de cortesía, y los tres encargos anteriores lo demuestran con
números: del encargo de la 18, **cinco de nueve** afirmaciones no se
sostuvieron; el de validación de placa afirmaba dos cosas falsas; y el de la 6,
la 10 y la 16 salió limpio en sus datos pero se equivocaba en la conclusión más
importante que sacaba de ellos —decía que conservar cinco registros de vídeo
era «más barato» y era la opción cara—.

Este encargo tiene además un defecto propio y declarado: **corrige una
estimación de la bitácora de la 19 que llevaba meses escrita y que nadie había
vuelto a medir.** Asume que a este documento le pasa lo mismo en algún sitio.

## Lo que hay, medido

### Las cuatro, de un vistazo

| | 12 `gpu` | 14 `gpuram` | 17 `gpuv2` | 22 `gpubl8` |
|---|---|---|---|---|
| Monitor | 3.12 | 3.14 | 3.17 | 3.22 |
| Capacidades | `warp_config`, `simt_debug` | igual | igual | **+ `video`, `perf_counters`** |
| `.v` / bancos | 19 / 8 | 19 / 8 | 19 / 8 | **57 / 26** (+4 `.sv`) |
| `examples/*.asm` | 2 | 2 | 2 | **18** |
| Memoria | 128 KiB EBR | 32 MiB SDRAM | 32 MiB SDRAM | 32 MiB SDRAM |
| Objetivo | 25 MHz | 25 MHz | 25 MHz | 25 MHz (+ pix) |
| Fmax hoy | 33,63 (**+34 %**) | 31,97 (**+28 %**) | 48,15 (**+93 %**) | 36,78 (**+47 %**) |
| Semilla fijada | **ninguna** | **ninguna** | **ninguna** | **ninguna** |
| `sysid.v` | los cuatro idénticos, y en v1 | | | |

Dos cosas de esa tabla que cambian el plan:

- **Ninguna tiene semilla fijada.** Sus `apio.ini` sólo llevan
  `--detailed-timing-report`. O sea que aquí no hay una semilla que invalidar,
  pero tampoco hay línea base de barrido contra la que comparar: si quieres la
  comparación honesta que este repo exige —mismo juego de semillas, mismo
  día— **hay que barrer v1 antes de tocar nada**, como se hizo con la 6.
- **Van sobradísimas de holgura.** Entre +28 % y +93 % sobre 25 MHz, contra el
  +5 % del que partía la 16. Eso es lo que hace que el riesgo estructural del
  apartado siguiente probablemente **no** te muerda. Probablemente.

### La corrección grande: el atajo de copiar SÍ les sirve

La bitácora de la 19 dice, sobre la 17:

> «**No hereda nada del trabajo de la 19**: su decodificación es *inline* en
> `gpu_system.v`, no un `mmio_decoder.v`. Hay que reescribirla como bloques de
> 64 KiB. Es diseño, no renombrado — aunque `gpu_system.v` es único de cada
> carpeta, así que no bifurca nada compartido.»

La primera mitad es cierta. **La segunda es falsa, y es la que decide el
coste.** Medido con `git hash-object`:

```text
wire mmio=address[31:13]==19'h40000;     <- literal, en las CUATRO
```

Y los `gpu_system.v` entre sí:

| Par | Diferencia real |
|---|---|
| 14 vs 17 | **una línea**: `FOLDER(8'd14)` contra `FOLDER(8'd17)` |
| 17 vs 22 | esa misma, más un puerto (`.retired_lanes()`) |
| 12 vs 14 | la interfaz de memoria (la 12 no tiene SDRAM). **Nada de MMIO** |

O sea que `gpu_system.v` **es de hecho un fichero compartido parametrizado por
el número de carpeta**, aunque nadie lo haya declarado así. Rediseñar su bloque
de decodificación es **un diseño, aplicado cuatro veces**, exactamente como
`mmio_decoder.v` lo fue para la familia CPU. No son cuatro diseños.

Y hay seis ficheros byte a byte idénticos en las cuatro: `gpu_register_file.v`,
`mmio_monitor_tb.v`, `monitor.v`, `sysid.v`, `uart.v` y `util.v`.

> Antes de estimar «esta familia no hereda nada», haz el diff. La frase de la 19
> se escribió mirando *que* la decodificación es inline, sin mirar *si* los
> cuatro ficheros inline son el mismo. Cuesta un `git hash-object`. `[TODAS]`

### El mapa de v2 ya tiene los nombres de GPU, y el de transición no tiene ninguno

`1.isa/mmio_map.vh` define **los cuatro bloques y sus veinte offsets**, ya
congelados:

```text
0x8200_0000  MMIO_GPU_BASE         ID, VERSION, ISA, FEATURES, CAPS, STATUS,
                                   CONTROL, WARP_START/LIVE/DONE
0x8201_0000  MMIO_GPU_WARPS_BASE   stride 0x10: PC, ACTIVE, GROUP, SIMT
0x8202_0000  MMIO_GPU_SIMT_BASE    CONTEXT, LSU_SLOTS, FIRST_ERROR,
                                   FIRST_ERROR_PC, WARP_RETIRED
0x8203_0000  MMIO_GPU_PERF_BASE
```

`1.isa/mmio_map_v1.vh` tiene **cero** nombres de GPU. Confirmado, no queda
ninguno por casualidad. O sea que la fase 1 de la 19 —resucitar el punto
intermedio— aquí se repite en su parte aditiva: **hay que extender el mapa de
transición con los nombres de GPU sacados del RTL de hoy**, no de un documento.
Es aditivo y no toca lo que ya hay.

Sin eso no existe el punto intermedio donde «todo pasa y nada se ha movido», y
te quedas con las dos fases de la 21 a la vez, que es justo lo que la 19
documentó como el error caro.

### El lado host: son como la 6, no como la 16

Las cuatro tienen `MAX_ADDRESS = 0xFFFF_FFFF` y **ninguna tiene
`parse_address`**. Eso significa, directamente:

- **NO les añadas `MMIO_BASE`/`MMIO_LIMIT`.** Sería declarar un filtro que no
  existe, que es como sobrevivió el `SERIAL_BASE` de la 19 hasta que costó una
  sesión de placa. `test_monitor_protocol.test_la_ventana_del_cli_cubre_los_bloques_que_decodifica`
  ya comprueba la misma invariante contra `MAX_ADDRESS` para las carpetas sin
  ese par — se hizo para la 6 y te vale tal cual.
- **Pero sí mira la 10 antes de darlo por hecho.** Allí `MAX_ADDRESS` eran los
  32 MiB de SDRAM y el CLI **no podía leer su propio bloque de
  identificación**, ni en v1. Las cuatro tuyas tienen los 32 bits enteros, así
  que no deberían tener ese problema. *Deberían.*

`MONITOR_REGIONS` hoy, medido:

| | Regiones |
|---|---|
| 12 | *(ninguna listada)* |
| 14, 17 | `(0x8000_0100, 0x8000_0118)` |
| 22 | esa, más `(0x8000_0300, 0x8000_0320)` |

### Nadie ejecuta los `examples` de ninguna de las cuatro

**Cero** `test.json` apuntan a `12/`, `14/`, `17/` o `22/`. Igual que pasaba con
la 6, la 10 y la 16, y por la misma razón: los casos de GPU usan
`x.tests/cases`, no los `examples` de las carpetas.

O sea que la única red que vas a tener sobre esos 24 `.asm` es la guarda de
direcciones cableadas, `CARPETAS` en `x.tests/test_mmio_map.py`. **Añade las
cuatro `examples/` antes de tocar un `.asm`**: falla al instante, nombra los
ficheros, y a partir de ahí la guarda es tu lista de trabajo.

**Y hay una trampa concreta al añadirlas**, que la 19 anticipó y ahora está
medida: bajo esas cuatro carpetas hay **64 ficheros `.asm` dentro de `_build/`**
frente a 152 versionados. Si añades las carpetas sin excluir `_build`, la guarda
te va a nombrar decenas de ficheros generados y vas a perder media hora
distinguiendo cuáles son tuyos.

## Trampas, en orden de lo que más duele

**1. El coste de v2 en esta familia es ESTRUCTURAL, y tus cuatro carpetas
tienen la forma cara.** Es la lección de la 16 y la única que puede costarte un
rediseño.

La 16 fue la única de la familia CPU a la que v2 le costó frecuencia: **cero de
dieciséis semillas**. Y no era el área. Extraído el camino crítico del
`build.log`:

```text
adapter.mmio_address[28]  ->  decodificador  ->  dispositivo
   ->  logica de proximo estado del PROPIO adaptador
```

Un lazo combinacional de un ciclo, que empieza en un bit que **sólo existe
porque v2 ensancha la dirección de 12 a 32**. La 18, la 19 y la 21 no lo sufren
porque `mmio_mux` se sienta en medio y lo parte. La 16 no tiene mux.

**Tus cuatro carpetas tampoco lo tienen**: decodifican inline en
`gpu_system.v`. Así que espera el mismo lazo. Lo que te salva —si te salva— es
que corren a 25 MHz con entre +28 % y +93 % de holgura, mientras la 16 iba a
+5 %.

El arreglo de la 16, por si lo necesitas, es una página de RTL: registrar la
respuesta MMIO dentro del adaptador y consumirla al ciclo siguiente, a costa de
un ciclo por acceso. **No alargues el `select`**: dispararía dos veces los
registros con efecto secundario, que es el bug que `mmio_mux.v` documenta.

> Y el corolario de método, que es lo que de verdad hay que copiar de la 16:
> **extrae el camino crítico del `build.log` antes de tocar nada.** El
> `apio.ini` de la 16 tenía escrito dónde mirar si hacía falta holgura, y
> apuntaba al sitio equivocado: era una hipótesis correcta para otro netlist.
> Cuesta un `Select-String`.

**2. Una dirección MMIO aparece en cinco formas y ninguna búsqueda las
encuentra todas.** Literal (`32'h8000_0000`), dentro de una instrucción
ensamblada a mano (`32'h5E80_8000` es `MOVHI R20, 0x8000`), partida en bytes de
protocolo (`send_byte(8'h80); send_byte(8'h00);`), como offset de 16 bits sobre
una base implícita, y en constantes de Python.

Y en esta familia hay una sexta forma que ya mordió una vez: los `0x80000000`
de `gpu_control_tb.v` (`32'hf8000000`, `32'hc8000000`) son **codificaciones de
instrucción**, no direcciones. Migrarlas rompe el banco.

El consejo concreto de la 21, que en la 16 se cobró otra vez: **nombra los
offsets como `localparam` al principio del banco antes de migrar ninguno**, y
sólo entonces cámbialos.

**3. `retired_count` está intercalado, y eso mueve offsets sin dar error.** Hoy
vive en `0x108`, entre los slots de LSU y el primer error. En v2 se va a
`MMIO_GPU_PERF_BASE`, así que **los offsets de SIMT posteriores se desplazan**.
Mover una base da error de decodificación, que es ruidoso; mover un offset hace
que conteste **otro registro**. Migra las bases primero y los offsets después,
que es la separación que la 21 hizo a propósito en sus fases 5a y 5b.

**4. `tools/build-sweep` NO sintetiza.** Re-ruta el `hardware.json` del build
archivado más reciente. Si la carpeta ha tocado RTL desde entonces, el barrido
mide un diseño que ya no existe y devuelve ocho números plausibles y **falsos**,
sin nada en la salida que lo delate. Ejecuta `tools/build` **antes** de barrer.

Y dos detalles de lectura que cuestan tiempo:

- El `Elapsed` de `tools/build-status` es **`mm:ss`**, no `hh:mm`.
- Un `build.log` de nextpnr trae la temporización **dos veces**: una estimación
  pre-rutado, 10-20 MHz más pesimista, y la buena. **La buena es la última.**
  En la 16 la estimación daba 80,53 y el número real era 98,07.

**5. Cuando toques una pieza compartida, mira si tiene gemela.** Y cuando
arregles un analizador, **busca sus copias antes de darlo por arreglado**. En la
sesión de la familia CPU aparecieron **tres** copias del mismo parser roto
—buscaba `monitor #(` sobre texto crudo y casaba con un comentario— y la que
importaba era la que **no** reventaba: `tools/rtl_facts.py` publicó «monitor
1.0» para la 6 en una tabla generada, y un `1.0` es una versión perfectamente
plausible.

**6. El backend de placa es único y compartido.** `x.tests/backends/fpga.py`
está en v2 y lo usan las diez carpetas, así que **las cuatro tuyas tienen sus
tests de placa rotos hasta que migren**. Se cura sola según migres. Lo que no se
cura sola es su gemelo: el simulador recibió en su día dos correcciones que el
backend de placa no, y nadie lo notó porque **ningún camino automático ejecuta
el backend de placa**.

**7. La placa desaparece sola tras programar.** COM3 se va y vuelve por su
cuenta. **No pidas replugar el USB**: espera.

## Orden recomendado: 17 → 14 → 12 → 22

Y el porqué, que no es el tamaño:

- **La 17 primero**, y cambio la recomendación de la 19 sólo en el motivo. Ella
  decía «porque es la primera de la familia GPU»; el motivo medido es mejor:
  **es la que más holgura tiene con diferencia, +93 %**. Si el lazo estructural
  del apartado 1 se va a cobrar algo, quieres descubrirlo donde sobra sitio, no
  donde te tumba el diseño.
- **La 14 después**, que es su gemela de una línea. Debería salir casi gratis,
  y **si no sale casi gratis, eso es el hallazgo**: significaría que lo que
  parece un fichero compartido no lo es, y eso cambia la estimación de las dos
  que quedan.
- **La 12 tercera**: es la 6 de esta familia —EBR, sin SDRAM— y su `gpu_system.v`
  difiere por la memoria. Es donde se ve si el diseño nuevo aguanta sin SDRAM
  detrás. Ojo: `test_monitor_protocol.test_el_modelo_de_warps_es_el_de_cada_placa`
  ya le hace un caso especial por sus 128 KiB.
- **La 22 al final**, porque es la grande —57 `.v`, 26 bancos, 18 `.asm`— y la
  única con vídeo y contadores. Es la 16 de esta familia, y ahí es donde van a
  vivir las decisiones tipo «¿qué bitmap declara?». Con las otras tres hechas,
  llegas con el patrón montado.

Si al medir ves que el orden es otro, dilo y cámbialo — pero dilo.

## Qué se paga en placa, y cuándo

**La placa va antes de lo que crees.** Es el único paso que mide algo que
ninguna otra cosa mide, y ponerlo al final garantiza que sus fallos se
descubran tarde. En la ronda de validación, la regresión del arnés compartido se
habría visto una hora antes.

Si hay una placa enchufada, **pregúntale lo que ya pueda contestar antes de
gastar una síntesis**: qué bitstream lleva, si su bloque SYSTEM responde, si el
mapa que ves es el que crees.

Lo que sólo se ve en placa:

| Qué | Por qué no lo ve la simulación |
|---|---|
| Que el bloque SYSTEM responda con los valores de **esa** carpeta | Ningún banco instancia `top` |
| Que un bloque **ausente** conteste error y no cero | Las cuatro tienen bloques ausentes: ninguna tiene serie, y sólo la 22 tiene vídeo |
| Que el error de un dispositivo **llegue al cliente** | Vive un ciclo y el cliente lo muestrea en el siguiente; lo caza `mmio_error_ack_tb.v`, que existe en 18/19/21 y **no en las tuyas** |
| La captura de DQ de la SDRAM (14, 17, 22) | Entra por un pin; el barrido no la ve |
| Los `.asm` de `examples/` | **Ningún `test.json` los ejecuta** |

## Valida lo que midas con un control negativo

Rompe la referencia a propósito y comprueba que falla, **y que falla por el
motivo correcto**. Cuatro avisos de método que ya costaron tiempo:

- **Verifica que la mutación se aplicó.** El repo es CRLF en disco y LF en el
  índice, así que un `.Replace()` con el final de línea equivocado no encuentra
  nada y el control sale «OK» sin haber tocado el código.
- **Borra `__pycache__` entre pasadas.** Una mutación del mismo número de
  caracteres queda enmascarada por el bytecode viejo.
- **Que los dos desenlaces se distingan.** Al sondear si una escritura
  desalineada se rechazaba o se truncaba, dejar antes el registro en el valor
  truncado hace que los dos desenlaces den el mismo número.
- **Cuando la mutación pasa por un generador, comprueba que la regeneración
  tuvo éxito.** Un generador que rechaza la mutación deja los ficheros
  generados intactos y los tests leen datos rancios y pasan.

Y uno nuevo de la ronda de la familia CPU: **un control negativo anclado en un
caso real caduca cuando el caso real se arregla.** Al ganar la 16 su
`frame_capture`, un test que la usaba de contraste dejó de ser negativo. Si el
caso puede dejar de serlo, ancla la **forma** y no el caso.

## Verificación, sin saltarte ninguna

```
./tools/test --prototype 17        # y 14, y 12, y 22
./tools/lint --prototype 17        # compara el reparto POR TIPO, no el total
python x.tests/run_tests.py --backend gpusim
python x.tests/run_tests.py --backend gpusim-cycle
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

Números base a no empeorar, **medidos el 2026-09-20 en `8c2b261`**: **285**
tests de `x.tests`, **53** casos de `cpusim` con 0 fallos, **61 / 44 / 62** en
`1.isa` / `2` / `11`, y `check-links` con 689 enlaces en 188 `.md`.

Mide tú el lint de las cuatro antes de tocar nada: **no está medido en este
encargo**, y la ronda anterior encontró que la 10 y la 16 partían de avisos de
anchura que las tres primeras carpetas no tenían. El criterio es el reparto por
tipo, no el total.

## El entregable es el log

Uno por carpeta, `<carpeta>/docs/migracion-v2.md`, escrito **mientras**
trabajas, no al final. No repitas lo que dicen las seis bitácoras anteriores:
enlázalas y **escribe sólo la diferencia**. Lo que quiero:

- **qué salió más barato y qué más caro de lo estimado**, que es lo que corrige
  la estimación de la siguiente;
- **si `gpu_system.v` era de verdad un fichero compartido** o si eso es otra
  frase que envejeció, y qué te costó comprobarlo;
- **si el lazo estructural de la 16 aparece aquí**, con el camino crítico
  extraído del `build.log` y no supuesto — y si no aparece, por qué no;
- **qué encontró esta migración en las carpetas ya migradas**: las seis
  anteriores encontraron algo cada vez, sin excepción;
- **qué falló que parecía funcionar**, incluido lo que hayas tenido que
  desmontar para creerte un verde;
- **si el orden 17 → 14 → 12 → 22 fue el correcto**, o había uno mejor.

## Definición de terminado

Las cuatro carpetas conforman con [`../1.isa/mmio.md`](../1.isa/mmio.md); los
diez `sysid.v` del repo son byte a byte idénticos **y el grupo de v1 está
vacío**, o sea que `test_sysid_es_copia_identica` vuelve a ser la comprobación
de siempre sin tocar nada; `MONITOR_REGIONS` y la ventana del CLI cuadran en las
cuatro y sus tests pasan; cada una tiene bitstream que corresponde a su RTL y
semilla fijada **con su párrafo** en `apio.ini` —ninguna la tiene hoy—;
`generate-docs --check` al día y `docs/synthesis-report.md` sin ningún FAIL; la
matriz de DQ limpia en las que tengan SDRAM; lint no ha empeorado **por tipo**;
las suites de simulación siguen verdes; `TODO.md` refleja el estado nuevo; y el
log de cada carpeta sirve para estimar la siguiente.

**Y lo que cierra la travesía entera:** borrar `1.isa/mmio_map_v1.vh`, su
entrada en `MAPAS` de `tools/generate_mmio.py`, los dos ficheros que genera
(`x.tests/inc/mmio_v1.inc` y `tools/mmio_map_v1.py`) y la clase `MapaV1Test` de
`x.tests/test_mmio_map.py`. Su criterio de borrado está escrito en su propia
cabecera y por fin se cumple: **sobra cuando lo suelta la última carpeta, no la
primera.** Ya se borró una vez antes de tiempo y hubo que rehacerlo entero.

Al terminar, dime **qué queda de MMIO v2 en el repo** —la deuda de las
escrituras sub-palabra (§4.1 y §16.2) sigue abierta en las seis de CPU y hay que
pagarla en el host y en los bancos a la vez— y **si el patrón de estas diez
carpetas sirve para lo que venga después o hay que inventar otro**.
