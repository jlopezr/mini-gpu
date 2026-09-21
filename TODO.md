# TODO

Por orden de prioridad **argumentada**, no heredada. Cada punto dice qué falta,
por qué importa y qué lo bloquea; si no se pueden escribir esas tres cosas, o no
está verificado o no es un punto.

Repasado el 21/09/2026 contra el árbol. Al final hay un apartado con lo cerrado,
para no volver a abrirlo por error.

---

## 1. Cerrar la ronda de placa

**La ronda está hecha y salió limpia** (20/09/2026). Las nueve carpetas que la
suite conoce, con el mapa v2 y el `monitor.v` final:

| | 6 | 10 | 12 | 14 | 16 | 18 | 19 | 21 | 22 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Casos | 13 | 17 | 30 | 31 | 26 | 26 | 38 | 53 | 33 |
| Fallos | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |

Las nueve pasan los cuatro `shared-mmio-*` —que un bloque **ausente** conteste
error y no cero (§4.3), SYSTEM reservado, SYSTEM de sólo lectura—. La 16 y la
22 pasan además `shared-video-fb-desalineada` y `shared-double-buffer`; la 16
pasa los seis casos de vídeo, o sea que el `frame_capture` que ganó al migrar
está confirmado en silicio.

**Qué falta.** Dos cosas:

1. **La 17 no se puede probar con la suite.** Es la única carpeta de GPU **sin
   `version.json`**, así que `run_tests.py --backend gpu-fpga` no la conoce
   —sólo `bram` (12), `sdram` (14) y `lsu2` (22)—. Se validó a mano: `SYSTEM`
   con los siete valores correctos, los cinco bloques ausentes rechazados por
   la placa y un descriptor de warp escrito y releído en `0x82010030`. Falta
   decidir si merece alias propio o si es redundante con `sdram`.
2. **Resintetizar las diez y repetir la ronda.** Al generar la identidad desde
   el RTL (`tools/generate-sysid`), `DEVICES` cambió en **seis** carpetas: la 6
   y la 10 ganan su bit de CPU, y la 18, la 19, la 21 y la 22 el de FABRIC, que
   ninguna declaraba pese a instanciar `memory_fabric_4`. Las diez elaboran y
   pasan sus bancos, pero sus bitstreams ya no corresponden. Son unas dos horas
   de síntesis más la ronda, que ya está guionizada.

**Por qué importa.** Es el único paso que mide lo que ninguna otra cosa mide:

| Qué | Por qué no lo ve la simulación |
|---|---|
| Que el bloque SYSTEM conteste con los valores de **esa** carpeta | Ningún banco instancia `top` |
| Que un bloque **ausente** conteste error y no cero | Las cuatro GPU tienen bloques ausentes; sólo la 22 tiene vídeo |
| Que el error de un dispositivo **llegue al cliente** | Vive un ciclo y el cliente lo muestrea al siguiente |
| La captura de DQ de la SDRAM | Entra por un pin |
| Los `.asm` de `examples/` | Ningún `test.json` los ejecuta |

Y hay un hueco concreto que sólo la placa cierra: `mmio_error_ack_tb.v` existe
en 18, 19 y 21 y **no en las cuatro de GPU**, así que en la familia GPU nadie
comprueba en simulación que el error de un dispositivo llegue al cliente.

**Qué lo bloquea.** Nada. Son unos diez minutos de placa por carpeta.

Trampas al ejecutarlo, todas ya pagadas:

- **`build-sweep` NO sintetiza.** Re-ruta el `hardware.json` del build archivado
  más reciente. Si esa carpeta ha tocado RTL desde entonces, el barrido mide un
  diseño que ya no existe y devuelve ocho números perfectamente plausibles y
  falsos, sin nada en la salida que lo delate. Hay que correr `tools/build`
  **antes** de barrer, o comprobar la fecha del build de partida.
- El `Elapsed` de `tools/build-status` es **`mm:ss`**, no `hh:mm`.
- Un `build.log` de nextpnr trae la temporización **dos veces**: una estimación
  pre-rutado (10-20 MHz más pesimista, y suele ser un FAIL aparatoso) y la buena.
  **La buena es la última.**
- Hay que subir con `board-upload --rebuild`. Sin esa opción, `apio upload` se
  ahorra el trabajo cuando la versión coincide — y la versión **no distingue dos
  builds de la misma carpeta**. Es el modo de fallo que ya apareció una vez,
  cuando el `default` de la 22 apuntaba a otro diseño.
- Que la síntesis en segundo plano devuelva éxito **no significa que haya
  cumplido timing**. Hay que mirar cada una con `build-status` antes de pasar a
  placa.
- **La placa desaparece sola tras programar.** COM3 se va y vuelve por su
  cuenta; no hay que replugar el USB, hay que esperar.
- Si hay placa enchufada, **pregúntale lo que ya pueda contestar antes de
  gastar una síntesis**: qué bitstream lleva, si su bloque SYSTEM responde.

**Lo que la ronda encontró y la simulación no**, que es la razón de que este
punto vaya primero:

- **`x.tests/backends/gpu_fpga.py` seguía entero en v1** —los cinco registros
  de vídeo y cuatro direcciones de depuración cableadas—. El backend de placa
  que estaba migrado era `fpga.py`, que es **otro fichero**. 18 de 33 casos de
  la 22 fallaban por esto. Ya migrado, con las tres bases leídas del
  `monitor.py` del prototipo.
- **Un contador cambió de dominio de reset al cambiar de bloque.** El global de
  retiros lo servía el SM (`core_reset`) y pasó a servirlo `gpu_perf_counters`
  (`reset`), que acumula entre casos: `instructions_executed` daba 20.864.707
  donde el caso esperaba 22. No estaba mal el contador, **era otro contador**.
- **La 22 truncaba la base de framebuffer desalineada** en vez de dar error
  (§9.2). Arreglado y verificado.

Ninguna de las tres la podía ver un banco, y las dos primeras no las ve
**ningún** camino automático: nadie ejecuta el backend de placa.

---

## 2. Lo que MMIO v2 deja a deber

**La migración de las diez carpetas está hecha** (20/09/2026). Las seis de CPU
—6, 10, 16, 18, 19, 21— y las cuatro de GPU —12, 14, 17, 22— conforman con
[`1.isa/mmio.md`](1.isa/mmio.md) en bases, bloque SYSTEM, ventanas del monitor y
programas. Los diez `sysid.v` son byte a byte idénticos, `1.isa/mmio_map_v1.vh`
se ha borrado con todo su andamio, y los 152 `.asm` versionados pasan la guarda
de direcciones cableadas. Las bitácoras por carpeta están enlazadas desde
[`docs/resumen-prototipos.md`](docs/resumen-prototipos.md#conformidad-con-mmio-v2).

**v2 no cuesta frecuencia.** En CPU el techo baja 3-6 MHz por los ~650 LUT del
mapa; en GPU **ni eso**: 12 +3,3 %, 14 +10,0 %, 17 −4,1 %, 22 +5,3 %, con el
camino crítico en el mismo sitio antes y después en las cuatro. El signo lo pone
el emplazamiento, no el mapa.

Lo que queda son **seis deudas de contrato**, ninguna de ellas «migrar una
carpeta». Van de más a menos transversal.

### 2.1. Escrituras sub-palabra a MMIO (§4.1 y §16.2)

Lo único que la 21 dejó a deber a propósito, y sigue abierto en las seis de CPU.
El host y varios bancos escriben byte a byte y tienen que pasar a `WRITE_WORD`
**a la vez**: es un cambio del protocolo del host, transversal, no de una
carpeta. Es la deuda más cara de las seis y la que más gente toca.

### 2.2. GPU CORE no existe (§14.1)

`GPU_ID`, `VERSION`, `CAPS`, `STATUS`, `GPU_CONTROL` y `WARP_START/LIVE/DONE`
**no están en ningún `.v` del repo**. Las cuatro carpetas de GPU decodifican el
bloque `0x8200_0000` y contestan error, que es lo correcto para un bloque
ausente (§4.3), pero el mapa promete registros que nadie implementa.

Se dejó fuera de la migración con precedente: **CPU CORE (§13.1) tampoco
existe**, y lo dice la cabecera de `sysid.v`. Implementarlo es hardware nuevo,
no mover un mapa.

**Por qué importa.** Es lo que decide si la MiniGPU puede ser un acelerador de
la MiniCPU o se queda como sistema hermano. Hoy `run/halt/step/reset` llegan por
señales del monitor, así que **solo el host puede lanzar la GPU, y solo con la
GPU parada**. Y la ventana de warps está llena al 100 %, sin sitio para más de
ocho. Es el trozo con más RTL nuevo de toda la lista.

### 2.3. Acceso MMIO desde SIMT: hoy se serializa, v2 exige error (§4.2)

> «Si dos o más lanes acceden a MMIO en la misma instrucción, el acceso genera
> **error** […]. Serializarlas en silencio sería peor que el error: el mismo
> kernel haría cosas distintas según cuántas lanes estuvieran activas.»

`gpu_lsu2.v` hace exactamente lo que el contrato prohíbe, y su banco lo
documenta como comportamiento esperado: *«dos lanes NO se coalescen: cada lane
sale por su cuenta, la de menor índice primero»*. Arreglarlo es una condición en
`gpu_lsu2.v` **y** cambiar ese caso del banco, que hoy afirma lo contrario.

### 2.4. El bloque PERF de la GPU no cumple §12

`cpu_perf_counters.v` tiene `PERF_CTRL`, `PERF_OVF0` y `PERF_OVF1`;
`gpu_perf_counters.v` **no tiene ninguno**. O sea que en GPU no hay congelar
para leer (§12.5) ni banderas de desbordamiento (§12.4). Falta también unificar
el wrap: la CPU satura y la GPU da la vuelta.

Lo que sí se hizo al migrar la 22: `VIDEO_TX` se movió de PERF a VIDEO, que es
lo que pide §9.7, y con él su regla de *gating*. Eso bajó `STALL_MEM` a la
ranura 5 y `LANE_OPS` a la 6.

### 2.5. Vídeo de la GPU: dos divergencias medidas

`gpu_video_regs.v` adoptó la numeración de v2 y sacó `FRAME_COUNT` de `STATUS`,
pero quedan dos:

- ~~**§9.2 exige error en base desalineada**~~ — **hecho** el 20/09/2026, y
  verificado en placa: `shared-video-fb-desalineada` pasa en la 22. La GPU
  truncaba en silencio; ahora `gpu_video_regs.v` rechaza la palabra entera y
  no guarda nada. Sólo se juzga con los cuatro strobes, que es como escribe
  `WRITE_WORD`: byte a byte el registro pasa por estados intermedios
  desalineados que son legítimos.
- **§9.5 pide `FRAME_COUNT` de 32 bits** y el de la GPU es un registro de 16
  extendido con ceros. Sigue abierto. En placa se ve avanzar correctamente,
  así que el síntoma sólo aparecería al dar la vuelta a los 65 536 frames —
  unos 18 minutos a 60 Hz.

### 2.6. Dos cosas del contrato, no del RTL

Aparecieron al migrar la 12 y la 22, y son decisiones de `mmio.md`, no trabajo
de carpeta:

- **`MMIO_MEM_SIZE_EBR` describe la 6, no «los prototipos sin SDRAM».** Hay dos
  —la 6 con 32 KiB y la 12 con **128 KiB**— y §3.1 documenta sólo el primero,
  generalizando desde un único caso. El RTL de la 12 declara la verdad en su
  `MEM_SIZE` y hay un caso que lo comprueba, pero **la constante y §3.1 siguen
  diciendo 32 KiB**. O §3.1 admite dos tamaños, o la constante se renombra a
  algo que diga de quién es.
- **`LANE_OPS` no lo nombra el mapa.** Vive en la ranura 6 de GPU PERF, detrás
  de las seis de §14.4, que §12.6 permite. O se declara como extensión o se
  nombra.

**Qué lo bloquea.** El punto 1 para todo lo que quiera medirse en placa. La 2.1
no lo bloquea nada salvo que es transversal; la 2.2 es la única que es diseño de
verdad.

## 3. Snapshots de ejecución (simulador)

**Qué falta.** Guardar y restaurar memoria, PC, registros, máscaras y estado del
scheduler. Extensión del fichero de lanzamiento, con un propósito distinto.

**Por qué importa.** `mandelbrot` son ~100 s y el 99,8 % del tiempo de la suite
GPU. Hoy, depurar un fallo tardío es relanzar con `--trace-detail`, esperar
100 s, formular una hipótesis y volver a esperar 100 s. Veinte iteraciones de
«¿y si es esto?» son 35 minutos de espera pura. Con snapshot se para una vez
cerca del fallo y **cada iteración posterior arranca ahí**. No encuentra fallos
que antes no se encontraran; convierte una tarde en diez minutos.

**Qué lo bloquea.** Nada, ya. Estuvo el último mientras `SSY` estaba en diseño
activo, porque un snapshot tiene que serializar `region_stack` y `path_stack`.
Eso se acabó:
[`11.gpu-sim-func/docs/ssy-reusable-regions-design.md`](11.gpu-sim-func/docs/ssy-reusable-regions-design.md)
abre con «semántica vigente de MiniISA v0.1» y la da por implementada en el
funcional de 11, en `gpu_sm.v` de 12, 14, 17 y 22, y en `simt.py` de 25. El
formato ya se puede congelar.

**Es lo de más valor por esfuerzo de la lista, y no depende de nadie**: sólo
toca simulador, así que no comparte un fichero ni con la ronda de placa del
punto 1 ni con las deudas del 2. Se puede hacer en paralelo con cualquiera de
los dos.

---

## 4. Segmentar el cauce del SM

**Qué falta.** Implementar el diseño ya escrito en
[`22.fpga-gpu-bl8/sm-pipeline.md`](22.fpga-gpu-bl8/sm-pipeline.md), que el README
de la 22 llama v2.1 (`pending_spec`, preparación en la sombra).

**Por qué importa.** El camino crítico **se mudó**: ya no vive en la LSU, vive en
el SM ([`lsu-v2.md`](22.fpga-gpu-bl8/lsu-v2.md)). Seguir puliendo la LSU es donde
están los rendimientos decrecientes; el SM es donde queda ganancia. Este punto
sustituye al antiguo «optimizar LSU», que está hecho: `gpu_lsu2.v`,
`gpu_aux_adapter_128.v` y `gpu_imem_buffer.v` sobre `memory_fabric_4` y
`sdram_controller_128` dieron −42 % de ciclos, −17 % de Fmax, **x1,44 neto**.

**Qué lo bloquea.** Nada, y hay con qué predecir la ganancia antes de escribir
RTL: el simulador de ciclos de
[`25.gpu-sim-cycle-uarch`](25.gpu-sim-cycle-uarch) existe, con su `DESIGN.md` y
su `VALIDATION.md`.

---

## 5. SDRAM: aprovechar la fila abierta

**Qué falta.** Hoy cada transacción activa una fila, la usa y la cierra: el
controlador de [`7.ulx3s_w9825g6kh_test`](7.ulx3s_w9825g6kh_test) ya hacía
auto-precharge en cada acceso, y `sdram_controller_128.v` sigue siendo una
activación por ráfaga BL8. Accesos consecutivos a la misma fila pagan
`tRP + tRCD` que no harían falta.

**Por qué importa.** Es la última ganancia grande de memoria que queda sin tocar,
y la memoria es donde vive el camino crítico de toda la familia CPU.

**Qué lo bloquea.** Dos preguntas de diseño sin responder, que es donde está el
trabajo de verdad:

- **Interfaz controlador↔fabric:** el controlador tendría que exponer qué fila
  tiene abierta y aceptar una petición nueva sin cerrarla. Deja de ser una
  interfaz sin estado.
- **Interfaz fabric↔masters:** el árbitro tendría que poder conceder por
  **afinidad de fila** y no solo por prioridad, o toda la ganancia se pierde en
  cuanto dos masters alternan. Y eso choca con la equidad: un master que siempre
  acierta de fila podría dejar sin turno a otro.

Ahí está el riesgo: `memory_fabric_4.v` es hoy un árbitro genérico que no sabe
qué hay detrás de cada puerto, y esto lo acopla a la SDRAM.

---

## 6. Unificar la documentación por prototipo

**Qué falta.** Decidir **qué documentos tiene un prototipo por definición** y
dónde viven, y luego aplicarlo. Hoy no sigue ninguna regla. Verificado el
19/09/2026:

| Documento | Dónde está | Dónde falta |
|---|---|---|
| `cycles.md` | 6, 10, 16, 18, 19, 21 | **toda la GPU**: 12, 14, 17, 22 |
| `timing.md` | 6, 10, 16, 18, 19, 21 | GPU; 14 y 17 usan `sintesis.md` para algo parecido |
| `validation.md` | 12, 14, 17 | CPU entera, y la 22 |
| `memory-interface.md` | 12, 14, 17 | la 22 |

La **ubicación** tampoco: la 22 tiene **ocho** `.md` en la raíz y uno en `docs/`;
la 17 tiene dos en la raíz y cuatro en `docs/`; 18, 19 y 21 tienen uno en la
raíz y entre siete y doce en `docs/`. Y las tres arrastran `plan-18-bl8.md` y
`medida-inicial.md` copiados tal cual: eran el plan de la 18 y ya no son plan de
nada.

**La estructura propuesta**, que es la decisión de fondo y ya está tomada en
cuanto al criterio:

- **`README.md`** explica **qué hace el prototipo y cómo**, en estado final. Es
  lo primero que alguien lee y tiene que quedar entendible: no necesita las
  decisiones que se tomaron por el camino. A nadie le interesa ya que en algún
  momento `R0` no estuviera cableado a cero.
- **`docs/log.md`** recoge la historia y la evolución cuando son relevantes: la
  vida y la obra. Ahí van los porqués que hoy ensucian los README.
- **`docs/timing.md`** cuenta los cambios de camino crítico y cómo afectaron al
  Fmax, cuando ha habido trabajo de ese tipo.
- Y hay que **identificar qué fichero se repite o se puede repetir en todos**,
  que es lo que convierte esto en una regla en vez de una limpieza puntual.

**Por qué importa.** No es renombrar ficheros: es decidir si `optimizacion.md` se
generaliza o es específico de la 17, y qué se hace con un documento de plan una
vez ejecutado el plan. Ese último caso acaba de resolverse una vez —
[`docs/unificacion-mmio.md`](docs/unificacion-mmio.md) pasó a ser un log
explícito, con una cabecera que dice que no es una referencia— y esa receta es
exactamente la separación README/`log.md` de arriba, aplicada a `docs/`.

**Qué lo bloquea.** Nada, salvo que es trabajo tedioso sin resultado medible.

Va junto con buscar inexactitudes entre doc y código, que es el mismo barrido.
`tools/check-links.py` valida enlaces; el contenido no lo valida nadie.

---

## 7. `apio lint` no pasa en ningún prototipo

**Qué falta.** Los diez salen con exit 1. Medido el 20/09/2026 con `tools/lint`,
ahora con las cuatro de GPU incluidas —faltaban en la tabla anterior—:

| Prototipo | 6 | 10 | 12 | 14 | 16 | 17 | 18 | 19 | 21 | 22 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Total | 18 | 41 | 17 | 17 | **66** | 17 | 39 | 32 | 34 | 31 |
| `PINMISSING` | 18 | 20 | 17 | 17 | 35 | 17 | 39 | 32 | 34 | 31 |
| `WIDTHEXPAND` | — | 21 | — | — | 29 | — | — | — | — | — |
| otros | — | — | — | — | 2 | — | — | — | — | — |

Dos cosas que la tabla vieja no dejaba ver:

- **Las cuatro de GPU son las más limpias**, con 17 avisos y de un solo tipo.
  Migrarlas a v2 no cambió ese número: 12, 14 y 17 tenían 17 antes y después, y
  la 22 tenía 31 antes y después. El criterio de «no empeorar» es el reparto
  **por tipo**, no el total.
- **`WIDTHEXPAND` sólo existe en la 10 y en la 16.** Es el aviso de anchura que
  la ronda de la familia CPU ya detectó, y sigue concentrado en esas dos.

**Por qué importa.** Casi todo es ruido —`PINMISSING` en los `*_tb.v`:
testbenches que instancian módulos a los que se añadieron puertos después, como
`cpu_burst_system_tb.v:131` sin `perf_read_data` o `video_registers_tb.v:44` sin
`video_mode`—. Pero mientras el lint salga en rojo por ruido, **no sirve para
detectar lo que sí importa**, y ya hay un caso real escondido dentro.

**El único que no es ruido es el `CASEINCOMPLETE` de la 16**, en
`sdram_system_adapter.v:285`: `state` es de 4 bits con 12 estados y el `case` no
tiene `default`, así que 12–15 no los cubre nadie. No es un fallo vivo —esos
valores son inalcanzables por construcción— pero si se alcanzaran la FSM se
congelaría sin recuperación, y es el único camino a la SDRAM de esa carpeta.

**Qué lo bloquea.** El arreglo de la 16 **está decidido y escrito como comentario
en el propio fichero**, y espera al próximo cambio de RTL de esa carpeta: lleva
semilla fija, y dos palabras de arreglo obligan a rebarrer las ocho semillas de
un diseño que cierra.

Antes esto decía «el punto 2 va a tocar esa carpeta de todas formas», y **ya no
es cierto**: la migración a v2 de la 16 está hecha y **ninguna de las seis
deudas que quedan del punto 2 pasa por esa carpeta** —son de GPU, del protocolo
del host o del propio contrato—. Así que el arreglo necesita ahora una excusa
propia para pagar el rebarrido, o se aplica aprovechando la ronda de placa del
punto 1, que sí va a tocar esa carpeta.

---

## 8. Acelerar la carga por UART: latency timer y `MAX_BLOCK_SIZE`

**Qué falta.** Dos cosas, ninguna de RTL:

- Bajar el **latency timer del FTDI** de 16 ms a 1 ms en el driver de Windows.
- Subir **`MAX_BLOCK_SIZE`** por encima de 256. El campo de longitud del
  protocolo ya es de 16 bits: el límite está en el cliente y en el búfer de
  `monitor.v`.

**Por qué importa.** Medido en placa, **una ida y vuelta cuesta 16 ms fijos** por
el latency timer — un `ping` de dos bytes tarda lo mismo que un bloque de 256. O
sea que hoy el tiempo de carga de un programa no lo manda el baudio, lo manda el
número de viajes. Bajar el timer es un ~10x directo sobre todo lo que hable con
la placa, y subir el tamaño de bloque reduce los viajes.

Esto es también lo que **no** arregló `WRITE_WORD`: aquel comando bajó de cuatro
viajes a uno para escribir un registro suelto, pero `WRITE_BLOCK` ya mandaba sus
256 bytes en un solo viaje, así que no tocó el cuello de botella real.

**Qué lo bloquea.** El latency timer es una opción del driver, fuera del repo, y
hay que ver cómo dejarlo documentado —o detectado— para que no sea magia local de
una máquina. `MAX_BLOCK_SIZE` sí es trabajo del repo y necesita revisar el búfer
de `monitor.v`, que toca las diez carpetas y por tanto arrastra resíntesis.

**Prioridad media a propósito:** no desbloquea nada, pero cada ronda de placa de
las de los puntos 1 y 2 la paga entera.

---

## 9. Herramienta para testear y dibujar componentes RTL por separado

**Qué falta.** Dos cosas que parten de lo mismo, saber qué instancia a qué:

- **Testear un componente aislado** (p. ej. la LSU) con su `*_tb.v`, sin
  arrastrar el proyecto entero.
- **Dibujar el grafo de bloques**: cómo se conecta la LSU con el resto y el
  resto entre sí.

**Por qué importa.** Hoy no hay forma barata de entender un prototipo nuevo sin
leerse el `top.v` entero. Y hay media hecha:
[`tools/interface-diagram.ps1`](tools/interface-diagram.ps1) saca el SVG de la
**interfaz** de un módulo con `yosys` blackbox + `show`; lo que no hace es el
grafo de conexiones **entre** módulos.

**Qué lo bloquea.** Nada. `tools/rtl_facts.py` ya empieza a leer lo que hace
falta. Además `interface-diagram.ps1` es la única herramienta del repo sin
lanzador y fuera del sistema de `tools/` ([`AGENTS.md`](AGENTS.md)), así que
integrarla cierra también esa anomalía.

---

## 10. Ejecución paso a paso o N pasos

**Qué falta.** Avanzar una instrucción de warp, inspeccionar registros y memoria,
y detenerse en un PC o un warp concreto. Debe ser una herramienta **aparte**, no
una opción de `run_tests.py`: el runner responde pasa/falla y un depurador
interactivo es otro oficio.

**Parcial.** `monitor.py step` ya existe —un paso de CPU en placa real— pero es
el primitivo de bajo nivel, no la herramienta descrita aquí: no inspecciona
registros ni memoria automáticamente, ni para en un PC o warp concreto.
`TextTrace` ya hace el resto del trabajo sucio.

**Por qué importa poco.** No encuentra fallos, ayuda a entenderlos una vez
encontrados, y con las expectativas actuales `--trace-detail` ya cubre casi todos
los casos. Si sale el punto 3, cubre buena parte de esto de rebote.

---

## 11. Volcado de estado SIMT en placa

**Qué falta.** Volcar `region_stack`/`path_stack` por MMIO.

**Por qué importa.** Permite comparar simulador y FPGA **en un punto intermedio**
en lugar de solo al final, que es lo que convierte «la placa da otra cosa» en
«divergen en el frame 47». Con bisección sobre `run_until.swap`, cuatro paradas
localizan el frame.

**Qué lo bloquea.** Nada para el volcado, que es leer y es barato. Está separado
del punto 3 a propósito, porque **restaurar** es otra cosa: es escribir estado
arquitectónico desde fuera, y obliga a abrir ventanas y comandos nuevos en
`monitor.v` para algo que solo sirve para depurar. Volcar vale la pena por sí
solo; restaurar, probablemente no.

---

## Cerrado — no reabrir sin motivo nuevo

- **`DEV_BITMAP` como punto propio.** Era la fase 4b de la unificación y estuvo
  abierto sin consumidor. Ya no es un punto suelto: es `SYSTEM.DEVICES` en
  [`1.isa/mmio.md`](1.isa/mmio.md) §5.4, dentro del punto 2. Y la contradicción
  que lo bloqueaba —la fase 4a escribió `SYS_ID` e `ISA_PROFILE` a mano,
  argumentando que un fichero generado se desincroniza en silencio, mientras 4b
  pedía generar— **quedó resuelta**: v2 lo deriva del RTL por el camino que ya
  existe (`tools/capabilities.json` + `tools/rtl_facts.py`), y exige el test que
  comprueba que lo generado está al día, que es lo que le faltaba al argumento
  de 4a.
- **El resto de la unificación MMIO.** Fases 0, 1, 2, 3, 3.4, 3.5, 4a y el
  renumerado de la 5, cerradas. Lo que hicieron vive en el RTL; el porqué, en
  [`docs/unificacion-mmio.md`](docs/unificacion-mmio.md), que es un log.
- **`DEVICES` escrito a mano, y sus dos convenios.** Cerrado el 21/09/2026.
  `tools/generate-sysid` deriva del RTL la identidad de cada prototipo
  —`FOLDER`, `ISA_PROFILE`, `DEVICES`, `MEM_BASE`/`MEM_SIZE`,
  `MONITOR_VERSION`— y la escribe en `<carpeta>/sysid_params.vh`, que es lo que
  §5.4 pedía. `sysid.v` sigue siendo la lógica compartida e idéntica en las
  diez; los valores van aparte, y como el `include` se resuelve por carpeta,
  **el `gpu_system.v` de la 14 y el de la 17 son ahora byte a byte idénticos**.
  Al estrenarlo aparecieron **seis bits mal** en diez carpetas: la 6 y la 10 no
  declaraban su bit de CPU y la 18, la 19, la 21 y la 22 no declaraban FABRIC
  pese a instanciar `memory_fabric_4`. Ninguno rompía nada — un bit de más o de
  menos en un bitmap descriptivo no da error, sólo miente.
  - Se decidió que los bits 9 y 10 significan **«tiene ese núcleo»**, no «el
    bloque CORE contesta»: §5.4 dice «dispositivos presentes» y reserva un bit
    para EBR, que no es ningún bloque. La 6 y la 10 llevaban escrita la lectura
    contraria y se corrigió.
  - `mul_div` estaba declarada `"architecture": "cpu"` en `capabilities.json`
    aunque `gpu_lane.v` tiene `OPCODE_MUL:` y `OPCODE_DIV:`. Corregido allí,
    que es el sitio que el repo tiene para decir qué buscar en el RTL. No mueve
    la selección de casos: los 47 de `x.tests/cases` declaran
    `architecture: cpu` y ese filtro va antes que las capacidades.
  - Lo vigila `x.tests/test_sysid_params.py` (sincronía, conformidad contra
    números a mano, y que nadie vuelva a poner un literal en el RTL), más
    `test_monitor_port.SysIdTest`, que deriva el perfil de los rasgos del RTL
    por un camino distinto al del generador. Fue ese contraste el que cazó lo
    de `mul_div`.
- **Migrar las diez carpetas a MMIO v2.** Cerrado el 20/09/2026 con la 22. Lo
  que queda de v2 son deudas de contrato, no migraciones, y está en el punto 2.
  Con ello se cierran también:
  - **El mapa de transición `1.isa/mmio_map_v1.vh`**, borrado por fin cumpliendo
    su propio criterio —«sobra cuando lo suelta la ÚLTIMA carpeta»—, junto con
    `x.tests/inc/mmio_v1.inc`, `tools/mmio_map_v1.py`, su entrada en `MAPAS` y la
    clase `MapaV1Test`. Se había borrado antes de tiempo una vez, al cerrar la
    21, y hubo que rehacerlo entero para la 19.
  - **La deuda del backend de placa compartido.** `x.tests/backends/fpga.py`
    lleva en v2 desde el 20/09 y las diez carpetas ya están en v2, así que no
    queda ninguna con los tests de placa rotos por el mapa.
  - **Los diez `sysid.v` idénticos**, con el grupo de v1 vacío:
    `test_sysid_es_copia_identica` vuelve a ser la comprobación de siempre.
  - **La guarda de direcciones cableadas** cubre ya los 152 `.asm` versionados,
    con las **ocho** rutas de la familia GPU —`examples/` **y** `fixtures/` de
    cada una—. Añadir sólo `examples/`, que es lo que decía el encargo, habría
    dejado 128 de 152 sin vigilar.
- **`docs/TODO JUAN.md`.** Absorbido y borrado. De lo que tenía, lo vivo pasó a
  los puntos 1 (la trampa de `--rebuild`), 6 (la separación README / `log.md` /
  `timing.md`) y 8 (latency timer y `MAX_BLOCK_SIZE`). El resto estaba hecho:
  - **Comandos del monitor en la 19.** `read-word` y `memory-test` sí estaban; lo
    que fallaba era que solo `read-byte`/`write-byte` podían apuntar al MMIO.
    Arreglado en 16, 18, 19 y 21 (`parse_address`).
  - **Propagar `WRITE_WORD` desde la 19.** Hecho: está en los diez `monitor.v`,
    que además son byte a byte idénticos. Las dos cosas que el documento pedía
    decidir antes están decididas y aplicadas — las versiones se renumeraron a 3
    y 4 según el juego de comandos, y la excepción de la 19 en
    `test_monitor_port.py` y su `monitor_write_word.diff` ya no existen: en su
    lugar hay un `test_write_word_esta_en_las_diez` que fija la convergencia.
  - **La secuencia de PowerShell para probar, sintetizar y pasar por placa.** Era
    un guion de una ronda concreta, no una tarea. Lo que había que conservar de
    ella son las dos trampas, que están en el punto 1.
- **`docs/mapa-de-memoria.md`.** Borrado. Proponía un contrato objetivo
  —página de 4 KiB, slots de 256 B— que MMIO v2 sustituye, y describía un estado
  actual que ahora vive en
  [`docs/resumen-prototipos.md`](docs/resumen-prototipos.md). Su §6.5, sobre
  unificar los monitores, tenía la premisa muerta: hablaba de «diez `monitor.v`
  con cuatro juegos de comandos» y de «diez números de versión, 1.15 a 2.4»
  cuando los diez ficheros son ya byte a byte idénticos y las versiones son
  3.x/4.x.
- **Optimizar la LSU.** Hecha en la 22 (`gpu_lsu2.v`), x1,44 neto. Lo que queda
  es el punto 4, que es otra cosa.
- **Revisar los inmediatos de la ISA.** `ADDI/ANDI/ORI/XORI` son opcodes base
  `0x11–0x14` desde v0.1. El único inmediato que faltaba era el de comparación, y
  `SLTI/SLTIU` están propuestos en
  [`propuesta-v0.4.md`](1.isa/propuesta-v0.4.md) con su coste en opcodes.
- **Divergencias entre versiones / `MULX`.** `MULX` no existía en ninguna parte
  del repo salvo en este fichero. Lo que hay es `MULFX` y `MULHI`, en las dos
  familias. La duda real que había detrás —por qué no hay `DIVFX`— está
  contestada en [`propuesta-v0.4.md`](1.isa/propuesta-v0.4.md): es el ancho
  del dividendo (48 bits, no 32), `ADD`/`SUB` funcionan tal cual, y las
  conversiones son un `SHLI`/`SARI`.
- **Revisar `MONITOR_REGIONS`.** La ventana quedó abierta a la página entera
  (`0x80000000–0x80001000`) en 16, 18, 19 y 21, no a los 24 bytes que este
  fichero llegó a decir: `perf` lee `0x80000300` y con la ventana estrecha se
  rechazaba en el cliente.
- **Tests de capacidad en `x.tests`.** El mecanismo está sano (34 `test.json` con
  `requires`). El smoke test es `cases/basics/smoke`, y `swap_demo`/
  `swap_demo_fast` son `cases/video/swap-demo` y `cases/video/swap-demo-fast`,
  apuntando al `.asm` de la 21 sin copiarlo. `tear_demo` **no se puede convertir
  en caso** y no es una tarea pendiente: no pide `SWAP` nunca —es justo lo que
  demuestra—, así que `run_until.swap` no se dispara, y lo que enseña es una
  carrera que el simulador no modela. Razonado en
  [`x.tests/cases/video/README.md`](x.tests/cases/video/README.md).
- **«¿VVP qué ejecuta?»** Sí, el RTL: `vvp` corre el binario que compila
  `iverilog` a partir del RTL y su testbench.
