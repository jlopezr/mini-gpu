# TODO

Por orden de prioridad **argumentada**, no heredada. Cada punto dice qué falta,
por qué importa y qué lo bloquea; si no se pueden escribir esas tres cosas, o no
está verificado o no es un punto.

Repasado el 01/10/2026 contra el árbol. Al final hay un apartado con lo cerrado,
para no volver a abrirlo por error.

---

## 1. Cerrar la ronda de placa

**La ronda se repitió el 01/10/2026 y salió limpia**: la suite completa en las
once carpetas que la conocen —6, 10, 12, 14, 16, 18, 19, 21, 22, 29 y 30— con 0
fallos, y con los bitstreams resintetizados desde el RTL actual (la identidad
`DEVICES` ya sale de `tools/generate-sysid`). Se lanza con `test-all`.

**Qué falta.** Una cosa: **`mmio_error_ack_tb.v` existe en 18, 19 y 21 y no en
las GPU**, así que en la familia GPU nadie comprueba en simulación que el error
de un dispositivo llegue al cliente. La placa lo cierra (los cuatro
`shared-mmio-*` pasan), pero un banco lo cerraría sin placa.

**Por qué importa.** La placa mide lo que ninguna otra cosa mide:

| Qué | Por qué no lo ve la simulación |
|---|---|
| Que el bloque SYSTEM conteste con los valores de **esa** carpeta | Ningún banco instancia `top` |
| Que un bloque **ausente** conteste error y no cero | Las GPU tienen bloques ausentes; sólo la 22 y la 29 tienen vídeo |
| Que el error de un dispositivo **llegue al cliente** | Vive un ciclo y el cliente lo muestrea al siguiente |
| La captura de DQ de la SDRAM | Entra por un pin |

**Qué lo bloquea.** Nada.

Trampas al ejecutarlo, todas ya pagadas:

- **`build-sweep` NO sintetiza.** Re-ruta el `hardware.json` del build archivado
  más reciente. Si esa carpeta ha tocado RTL desde entonces, el barrido mide un
  diseño que ya no existe y devuelve ocho números perfectamente plausibles y
  falsos, sin nada en la salida que lo delate. Hay que correr `tools/build`
  **antes** de barrer, o comprobar la fecha del build de partida.
- **La semilla de nextpnr es de un netlist concreto.** Tras cambiar RTL hay que
  re-barrerla: la 16 pasó de cerrar timing a 99,0/100 MHz con la semilla antigua
  al cambiar `HALT_AT`.
- **Tocar un `.v`, aunque sea un comentario, deja el bitstream STALE** (también
  `.vh`, `.lpf` y `apio.ini`). Y varios ficheros se copian idénticos entre
  carpetas, con un test que lo exige.
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

Arrastra varias cosas que salieron al implementar `GETID` en la 29: que un warp
lea SYSTEM, separar el reset del núcleo del de configuración y escribir
descriptores con la GPU en marcha. Están en el punto [16.2](#162-un-warp-no-puede-leer-system-en-el-rtl-de-la-29-n10).

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

### 2.5. Vídeo de la GPU: `FRAME_COUNT` de 16 bits

`gpu_video_regs.v` adoptó la numeración de v2 y sacó `FRAME_COUNT` de `STATUS`,
pero §9.5 lo pide de **32 bits** y el de la GPU es un registro de 16 extendido
con ceros. En placa se ve avanzar correctamente, así que el síntoma sólo
aparecería al dar la vuelta a los 65 536 frames — unos 18 minutos a 60 Hz.

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

## 4. Segmentar la unidad X del SM

**Hecho:** el cauce de 6 etapas (S → F → I → D → X → W) está en
[`29.fpga-gpu-sm-pipeline`](29.fpga-gpu-sm-pipeline) y pasa la suite en placa.
Medido en la ronda del 01/10/2026, el CPI de warp baja de 16,3 en la 22 a 8,4.

**Qué falta.** `gpu_lane.v`, la unidad X, se reutiliza tal cual con su FSM
interna de 15 estados: 4 ciclos la ALU, 8 la MUL y hasta 37 la DIV. Colapsarla y
segmentar X en sub-etapas (X1/X2/X3…) es la siguiente iteración, según el README
de la 29.

**Por qué importa.** Con el cauce hecho, X es lo que queda por segmentar y lo
que fija lo que cuesta cada instrucción.

**Qué lo bloquea.** Nada conocido.

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
vez ejecutado el plan. La receta es exactamente la separación README/`log.md`
de arriba, aplicada a `docs/`: la documentación vigente conserva el resultado
y el documento de trabajo deja de ser una referencia permanente.

**Qué lo bloquea.** Nada, salvo que es trabajo tedioso sin resultado medible.

Va junto con buscar inexactitudes entre doc y código, que es el mismo barrido.
`tools/check-links.py` valida enlaces; el contenido no lo valida nadie.

---

## 7. `apio lint` no pasa en ningún prototipo

**Qué falta.** Los doce salen con exit 1. Medido el 01/10/2026 con `tools/lint`:

| Prototipo | 6 | 10 | 12 | 14 | 16 | 17 | 18 | 19 | 21 | 22 | 29 | 30 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Total | 19 | 42 | 18 | 18 | **67** | 18 | 40 | 33 | 35 | 32 | 27 | 43 |
| `PINMISSING` | 18 | 20 | 17 | 17 | 35 | 17 | 39 | 32 | 34 | 31 | 25 | 42 |
| `WIDTHEXPAND` | — | 21 | — | — | 29 | — | — | — | — | — | — | 1 |
| `WIDTHTRUNC` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | — |
| otros | — | — | — | — | 2 | — | — | — | — | — | 1 | — |

Tres cosas que conviene saber:

- **`WIDTHTRUNC` es nuevo en todas menos la 30**, y es el mismo aviso en `sysid.v:44`:
  `FOLDER` es de 8 bits y `sysid_params.vh` le da una constante de 32. Aparece
  desde que la identidad se genera del RTL. Se arregla en el generador
  (`tools/generate-sysid`) escribiendo la constante con su ancho.
- **`WIDTHEXPAND` sólo existe en la 10, la 16 y, con un aviso, la 30**
  (`mmio_decoder.v:234`). Es el aviso de anchura que la ronda de la familia CPU
  ya detectó.
- **El criterio de «no empeorar» es el reparto por tipo**, no el total.

**Por qué importa.** Casi todo es ruido —`PINMISSING` en los `*_tb.v`:
testbenches que instancian módulos a los que se añadieron puertos después, como
`cpu_burst_system_tb.v:131` sin `perf_read_data` o `video_registers_tb.v:44` sin
`video_mode`—. Pero mientras el lint salga en rojo por ruido, **no sirve para
detectar lo que sí importa**, y ya hay un caso real escondido dentro.

**Los que no son ruido son los `CASEINCOMPLETE`**: el de la 16, en
`sdram_system_adapter.v:285`: `state` es de 4 bits con 12 estados y el `case` no
tiene `default`, así que 12–15 no los cubre nadie. No es un fallo vivo —esos
valores son inalcanzables por construcción— pero si se alcanzaran la FSM se
congelaría sin recuperación, y es el único camino a la SDRAM de esa carpeta. La 29 trae otro en
`gpu_sm.v:455` que conviene mirar con el mismo criterio.

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
[`tools/module-diagram.ps1`](tools/module-diagram.ps1) saca el SVG de la
**interfaz** de un módulo con `yosys` + `netlistsvg`, y con `-Inside` el top con
sus submódulos a un nivel; lo que no hace es el grafo de conexiones **entre**
módulos de todo el prototipo, ni resolver solo qué `.v` hay que pasarle.

**Qué lo bloquea.** Nada. `tools/rtl_facts.py` ya empieza a leer lo que hace
falta. Además `module-diagram.ps1` es la única herramienta del repo sin
lanzador y fuera del sistema de `tools/` ([`AGENTS.md`](AGENTS.md)), así que
integrarla cierra también esa anomalía.

---

## 10. Ejecución paso a paso o N pasos

**Qué falta.** Avanzar una instrucción de warp, inspeccionar registros y memoria,
y detenerse en un PC o un warp concreto. Debe ser una herramienta **aparte**, no
una opción de `run_tests.py`: el runner responde pasa/falla y un depurador
interactivo es otro oficio.

**Hecho para la CPU.** `mini-dbg` ([`tools/README.md`](tools/README.md)) es esa
herramienta aparte: TUI de cuatro paneles, paso a paso, breakpoints por
etiqueta, lectura y escritura de registros y memoria, y ventana de framebuffer
(`front` estable y `back` a medio dibujar). Y **se conecta** a los dos
sitios con el mismo comando —`mini-dbg programa.asm` al simulador funcional,
`mini-dbg --board -p 21` a la placa por el monitor—, que era la mitad del punto:
`monitor.py step` sigue siendo el primitivo, pero ya no hay que usarlo a pelo.

**Qué falta.** El warp. Hoy el depurador habla de un PC y 32 registros, no de
warps y carriles, así que en la MiniGPU no sirve. Es un `DebugTarget` más
(`tools/debug_target.py`) más vista de carriles: la interfaz y los comandos no
se tocan. En placa, además, no se pueden escribir registros ni mover el PC; eso
es el punto 11 y `mini-dbg` lo rechaza con su motivo en vez de fingirlo.

**Por qué sigue importando poco.** No encuentra fallos, ayuda a entenderlos una
vez encontrados, y con las expectativas actuales `--trace-detail` ya cubre casi
todos los casos.

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

## 12. Board-upload no controla que protipo esta cargado

```text
(tools) (.venv) PS C:\Users\j_lop\Documents\repos\mini-gpu\x.tests\cases-cpu\video\pacman> board-load -p 21 --program .\pacman.asm
Puerto detectado: COM3 (USB Serial Port (COM3))
Using prototype: 21.fpga-cpu-hdmi-alu
38425 palabras -> C:\Users\j_lop\Documents\repos\mini-gpu\x.tests\cases-cpu\video\pacman\pacman.bin
== cargando pacman.bin (153700 bytes) en 0x00000000
error: `monitor.py reset` falló:
Error: Invalid RESET_CPU response: f8
Available ports: COM3 (FTDI), COM1, COM6, COM8
```

Y estaba la 22.

## 13. Nuevo assembler/dissambler

## 14. Revisar como se llaman a las tools

## 15. `tools/lint` ensucia el estado de build de cada prototipo

> **Resuelto el 8/10/2026.** `prototype_build_summary` (`build-list --prototypes`)
> ignora los registros de etiqueta `test` al elegir el último build, salvo los que
> siguen en marcha. Test en `x.tests/test_build_runner.py`. El texto de abajo se
> conserva como historia; el aviso de ancho que provocó el último `FAILED` de la 34
> (`mmio_decoder.v:257`, `palabra >= PERF_SLOTS`) sigue sin limpiar.

**Qué falta.** `tools/lint -p N` se registra como un build de etiqueta `test` y
termina `FAILED` siempre que el lint saca avisos, o sea, hoy en los doce
prototipos. Ese registro pasa a ser el «último build» en `build-list
--prototypes`, que enseña `FAILED` en todos aunque el bitstream sea `CURRENT` y la
síntesis estuviera bien. Pasó el 01/10/2026 al medir el punto 7: doce prototipos
en rojo hasta borrar a mano quince carpetas de `reports/`.

**Por qué importa.** Quien lo ejecuta para mirar avisos no espera tocar el estado
de las síntesis, y quien mira `build-list` después no tiene forma de distinguir un
fallo de timing de un lint con avisos.

**Qué lo bloquea.** Nada. Lo razonable es que el lint no escriba en el historial
de builds, o que `build-list` ignore los registros de etiqueta `test` al elegir el
último build.

## 16. Lo que queda tras `GETID` y los accesos de 8 y 16 bits en la 29

**Hecho el 06/10/2026.** El RTL de la 29 ejecuta `GETID` (`type` 0 a 4) con los
arrays `LOGICAL_WARP_ID` y `WARP_ARG`, y `LOADB`…`STOREH`. Probado en placa: 72
casos de GPU, 0 fallos; síntesis con la semilla 2, 38,4 / 25 MHz. Lo que sigue
son los cabos que salieron al hacerlo, de más a menos importante. Las notas de
diseño están en
[`32.cpu-gpu-func-sim/docs/necesidades-detectadas.md`](32.cpu-gpu-func-sim/docs/necesidades-detectadas.md).

### 16.1. `fault.address` obligatorio deja fuera de la placa los casos de fallo de memoria

**Qué falta.** El esquema de `x.tests` exige `fault.address` y el monitor no la
expone, así que `gpu_fpga.incompatibility` omite todo caso que la declare. Dos de
los casos nuevos (`subword/misaligned-halfword` y `subword/mmio-byte`) se omiten
por eso, aunque el RTL los hace bien: se comprobaron a mano contra la placa con la
dirección a `null` y coinciden en todo menos en ella (N11).

**Por qué importa.** Es el único sitio donde los fallos de memoria de la LSU
quedarían cubiertos en hardware; hoy solo los cubre su banco directo y una
comprobación manual.

**Qué lo bloquea.** Nada. Hacer `address` opcional y que la comparación use solo
los campos declarados, **con una marca explícita** para quien la omite
(`"address": "unexposed"`) y no un simple «no ponerla», para que no sea un hueco
por descuido. No toca RTL ni síntesis. Exponer la dirección en el RTL
(`FIRST_ERROR_ADDR`) cambiaría `mmio.md` y costaría área en la LSU: no merece la
pena solo por esto.

### 16.2. Un warp no puede leer SYSTEM en el RTL de la 29 (N10)

**Qué falta.** `gpu_system_bl8.v` solo deja a la GPU llegar a VIDEO y PERF; un
`LOAD` de `0x80000000` desde un warp para con `ERROR_MEMORY_ACCESS`. `mmio.md`
§15 dice que un warp lee SYSTEM y los simuladores lo permiten.

**Por qué importa.** Un kernel que quisiera leer `MEM_SIZE` o `DEVICES` no puede.
Y el caso `subword/mmio-byte` no discrimina en la placa: falla antes, en el
`LOAD` de palabra, no en el `LOADB` que quiere probar.

**Qué lo bloquea.** Es una condición en el decodificador, pero cuesta otra
síntesis (unos 25 minutos en la 29). **No sintetizar solo por esto**: tocar el
mismo decodificador es parte del trabajo de GPU CORE (2.2), y se hace en el mismo
cambio. Junto con él, en esa misma pasada:

- Separar el reset del núcleo del reset de configuración: hoy el único reset de
  la 29 (`core_reset`, el del monitor) pone a cero los dos arrays, y el contrato
  dice que `GPU_CONTROL.RESET` los conserva (N5).
- Escribir descriptores y arrays con la GPU en marcha, en los warps no vivos.
  Hoy el host solo escribe con el núcleo parado, y eso impide el `WARP_START` de
  un warp mientras otros corren.

### 16.3. `getid-family` solo corre en simulador

**Qué falta.** Usa `warp_size = 4` y el RTL tiene 8 lanes, así que la placa lo
omite. Es correcto por diseño (prueba otra geometría), pero su README no lo dice y
su `test.json` tampoco.

**Qué lo bloquea.** Nada: una línea en el README. `getid-8warps` ya cubre lo mismo
en placa.

### 16.4. Fusionar los stores de lanes que caen en la misma palabra

**Qué falta.** Dos lanes que escriben bytes distintos de la misma palabra no se
fusionan: gana la de menor índice y la otra espera otra vuelta de la LSU. Un
`memset` por bytes cuesta cuatro vueltas por palabra.

**Por qué importa.** Los kernels de memoria del diseño `diseno-gpu-dma.md` van
por palabras en la v1 justo para esquivarlo, pero quien use `STOREB` en un bucle lo
paga. **No está medido**: antes de tocar la LSU, medir con
`cases-gpu/extensions/subword/lane-bytes-halves` cuánto pesa en ciclos (modelo 25
y contadores `CYCLES`/`RETIRED` de la placa).

**Qué lo bloquea.** Medirlo. Fusionar con las máscaras de bytes que la LSU ya
forma es el camino natural, pero añade lógica en el camino crítico de `gpu_lsu2`.

### 16.5. Acelerar la síntesis de la 29: probar `router2 --threads`

**Qué falta.** El build de la 29 tarda unos 23 minutos y es casi todo `nextpnr`,
que con `router1` (el de `apio.ini`) es monohilo. El nextpnr instalado (0.10)
tiene `router2` y `--threads`, y la máquina tiene 24 hilos. No hay comparativas
publicadas de `router1` frente a `router2` en ECP5 que hayamos encontrado.

**Por qué importa.** Cada cambio de RTL de la 29 cuesta ese tiempo, y el trabajo
de 2.2 va a necesitar varias iteraciones.

**Qué lo bloquea.** Medirlo en una copia de la carpeta, no en la real: la misma
síntesis con `--router router2 --threads 8`, comparando tiempo, Fmax y que cierre
timing a 25 MHz. Cambia el resultado (otro enrutado, otra semilla): solo se adopta
si cierra y baja el tiempo de verdad, y obliga a re-barrer semillas. Lo que sí
escala sin riesgo es lanzar varias semillas o carpetas a la vez.

**No actualizar el oss-cad-suite a ciegas.** El instalado (marzo de 2026, Yosys
0.63+173) es anterior a una regresión de ABC que empeoró el timing en ECP5 en las
versiones 20260331 a 20260415 y se arregló en la 20260513
([hilo](https://yosyshq.discourse.group/t/timing-closure-degraded/139)).

### 16.6. Las demás GPU no tienen `GETID` ni accesos pequeños

**Qué falta.** Solo la 29 los implementa. 12, 14, 17 y 22 siguen parando con
`0x05` o `0x01`; sus casos se omiten por capacidad, que es lo correcto, pero un
kernel que los use solo corre en la 29 y en los simuladores. `gpu_lane.v` y
`gpu_lsu2.v` ya no son copia de los de la 22.

**Qué lo bloquea.** Decidir si se retroportan o se dan por congeladas. Si la 22
sigue siendo la línea base de comparación de ciclos (`profiling.md`), conviene que
no se mueva.

### 16.7. `NEW-ASSM` y el ensamblador vigente

**Qué falta.** `1.isa/NEW-ASSM` tiene su propia tabla de instrucciones y no
conoce la familia `GETID` ni que `ANDI`/`ORI`/`XORI` aceptan `.equ`. Es el punto 13
de este archivo, hoy vacío: decidir si `NEW-ASSM` es el ensamblador vigente antes
de portarle nada.

### 16.8. Tres comprobaciones que no se han hecho

- **Las familias `programs` y `demos` de `gpusim` y `gpusim-cycle` no se han
  vuelto a pasar** tras el cambio de `GETID` en 11 y 25. Se pasaron alu, faults,
  memory, scheduling, simt y extensions (mandelbrot tarda unos 100 s por
  simulador). En la placa sí pasan todas, así que el riesgo es del simulador.
- **Falta contrastar la LSU del modelo de ciclos (25) con el RTL en los stores
  pequeños a la misma palabra.** El RTL serializa las lanes que caen en la misma
  palabra (una vuelta por lane). Si el 25 las fusiona o las cuenta distinto, un
  kernel con `STOREB` en bucle saldrá más barato en el modelo que en la placa, y
  calibrar el número de warps con el 25 (como se propuso) daría una cifra
  optimista.
- **No se ha medido el efecto en ciclos de la 29.** El cambio añadió unos 4 400
  LUT (de unos 43 000 a 47 473) y lógica en la ruta de respuesta de la LSU. Fmax
  y timing no se resienten (38,4 / 25 MHz), pero no se han repetido los contadores
  `CYCLES`/`RETIRED` de `gpu_bench` contra la línea base de `profiling.md`.

### 16.9. Lo que depende de GPU CORE (2.2)

El protocolo de `32.cpu-gpu-func-sim/docs/diseno-gpu-dma.md` (runtime de CPU con
`WARP_START`/`WARP_DONE`, ids de job con generación, kernels `memset`/`memcpy`)
está validado en simulador con el arnés de `32.cpu-gpu-func-sim/examples/dma`. En
placa **no hay prototipo con CPU y GPU a la vez** ni GPU CORE, así que es lo último
de la cadena: primero 2.2 y 16.2, después el sistema con RAM compartida, y por
último el runtime en C sobre el mismo protocolo (sin linker: el compilador genera
un `.asm` y el runtime y los kernels se incluyen con `.include`).

### 16.10. El acarreo entre lanes de `lsu_address` en la 29: falta verlo en placa

**Qué se descubrió** (7 de octubre de 2026, al recortar `gpu_sm` para la 36).
`assign lsu_address=d_rf_a+{8{d_immediate}}` era UN sumador de 256 bits: el acarreo
de la lane n entraba en la n+1. Con un desplazamiento negativo (inmediato
`0xFFFFFFxx`) casi toda suma acarrea y cada lane recibía un byte de más. Reproducido
en `iverilog` con `a={0x104,0x100}`, `imm=-4`: la lane 1 daba `0x101`. Entró en la
29; la 12, 14, 17 y 22 sumaban por lane, y la 32 es un simulador sin RTL.

**Qué se hizo.** Arreglo en `29.../gpu_sm.v` y en la 36 (rama `gpu-36-bram`,
commits `1668af4` y `5728e81`), `gpu_barrier_tb` en la 36 (con el `gpu_sm` anterior
acaba en error; con solo el sumador arreglado pasa) y el caso
`x.tests/cases-gpu/memory/negative-offset` (`0dc8307`), que pasa en `gpusim` y
`gpusim-cycle`.

**Qué falta.**
- **Pasar el caso en placa con la 29 antes y después del arreglo.** No se ha visto
  fallar: la razón por la que los simuladores no lo detectan es que suman por lane
  en Python. Hasta que falle sin el arreglo, no está demostrado que el caso lo cubra.
- **Reconstruir el bitstream de la 29** (el RTL cambió) y re-barrer semillas antes
  de fiarse de los números de su README.
- **Revisar si algún caso anterior de la 29 en placa pasaba por casualidad** con un
  offset negativo y base baja (sin acarreo), y si el `mandelbrot`/`demos` los usan.
- Las optimizaciones de área de `gpu_sm` (scheduler por vector de elegibilidad,
  `same_group`, `generation` de 1 bit) están solo en la 36; no se han portado a la
  29 porque cambiarían su timing sin medirlo.

## 17. Más margen en el reloj de CPU de la 35: la validación de bloques del monitor

**Qué se descubrió** (7 de octubre de 2026, semilla 24 del barrido sobre el RTL
nuevo, CPU 77,10 MHz para 80). `timing-wall --path` da un camino de 12,97 ns que
**no es de la CPU sino del monitor**: sale de `monitor_i.block_end_address`
(`monitor.v:344`), pasa por 14 LUT (3,2 ns de lógica, 9,3 de ruteo) y acaba en el
`CE` de un registro. Es `STATE_VALIDATE_BLOCK` (`monitor.v:835-851`): en un solo
ciclo evalúa `block_length` fuera de rango y `block_range_valid` (RAM más cinco
`in_window`, once comparadores de 33 bits) y con ese resultado decide el `if` que
habilita `response_byte_0`, `response_length`, `response_index`,
`response_done_state` y `state`. El comentario de `monitor.v:379` ya sacó el
sumador del camino, pero no la comparación de rangos.

**Arreglo propuesto, sin hacer.** Un estado nuevo (`STATE_CHECK_BLOCK`, del 48 en
adelante, que están libres) entre `STATE_CALCULATE_BLOCK_END` y
`STATE_VALIDATE_BLOCK` que registre el veredicto en `block_ok`; la validación pasa
a mirar solo ese bit. Cuesta un ciclo de 80 MHz por comando de bloque (un byte de
UART a 115200 son unos 87 µs): irrelevante. El protocolo no cambia. Solo en la
copia del 35, no en el `monitor.v` de las demás.

**Por qué no se hizo.** El 35 ya cierra con la semilla 17 (CPU 83,21, memoria
107,35). Los caminos críticos **cambian de semilla a semilla**: en el barrido
antiguo la semilla 24 caía en `instruction_buffer.v:111` (10 LUT hasta un `CE` con
un salto de 2,56 ns que cruza 31 posiciones), así que quitar este muro no
garantiza subir la mediana. Probarlo cuesta un build, un barrido de 24 semillas
(2-3 horas con `tmg-ripup`) y repetir la validación en placa.

**Cómo comprobarlo si se retoma.** Commit aparte en la rama, `build` antes de
barrer (el barrido re-ruta el último build archivado), mismas opciones de nextpnr
(`tmg-ripup placer-heap-timingweight=30`) y comparar contra el barrido
`sweep-20261007-140059-470717` de la 35 (10 de 23 cumplen, CPU 73 a 83 MHz). Si la
mediana de CPU no sube, quitar el commit. Ojo: con el diseño aplanado
`timing-wall` solo atribuye módulo a `input_i` y `console_i`; para el resto, usar
`--path` en varias semillas.

**Actualización (8 de octubre de 2026).** El arreglo ya está hecho en la 36
(`STATE_CHECK_BLOCK` y `block_ok`), no en la 35, y con él deja de ser el muro de
la CPU. Sigue sin aplicarse al `monitor.v` de la 35 ni al de las demás.

## 18. Tiempo máximo en el acceso MMIO a la GPU (36)

**Qué falta.** Un contador en `mmio_mux` que cuente solo mientras espera
`slow_done` del puente de la GPU (`gpu_mmio_bridge`), con unos 1.000 ciclos de
80 MHz (10 bits, unos 12 µs; un acceso normal tarda decenas). Si salta: dar el
acceso por terminado, devolver error al cliente y **ignorar un `slow_done` que
llegue tarde** (hoy el mux acepta `slow_done` solo si hay un acceso lento en
curso, pero tras un tiempo agotado conviene dejar la GPU marcada como caída hasta
el siguiente reset, para que una respuesta tardía no se confunda con la de otro
acceso). Hace falta un caso en `gpu_mmio_bridge_tb.v` con una GPU que no contesta.

**Por qué importa.** Sin él, si la GPU no contesta nunca, `mmio_mux` espera para
siempre: la CPU se queda parada en esa instrucción y el monitor tampoco puede
tocar el MMIO (el bus es único), de modo que solo se sale con el reset de la
placa. Hoy no se ve porque `gpu_system` siempre contesta, con error si la
dirección es mala; podría pasar con un reloj de la GPU parado, un fallo de su
reset o un camino futuro sin respuesta.

**Qué lo bloquea.** No es técnico: cualquier cambio de RTL deja el bitstream de
la 36 en STALE y cuesta un build de unos 40 minutos (rutado de `router1`,
cerró el 8 de octubre con `sdram_clk` +2,0 % y CPU +4,9 %, márgenes finos).
Conviene hacerlo **junto con otro cambio de RTL**, y después de probar la 36 en
placa; si en placa se ve un cuelgue al tocar la GPU, sube de prioridad.

**Va con esto, en el mismo cambio.** Documentar en el comentario de
`gpu_mmio_bridge.v` tres cosas: que el reset de un solo dominio dejaría un `done`
espurio (hoy los dos cuelgan del mismo botón); que nextpnr no analiza los caminos
entre `clk` y `gclk`, así que con otra herramienta habría que marcarlos como
`false path`; y que sin tiempo máximo una GPU caída bloquea el bus.

---

## Cerrado — no reabrir sin motivo nuevo

- **La 17 en la suite de placa.** Decidido el 01/10/2026 dejarla fuera: fue un
  intento que no llegó a cerrarse y no merece alias propio ni `version.json`. Se
  validó a mano: `SYSTEM` con los siete valores correctos, los cinco bloques
  ausentes rechazados por la placa y un descriptor de warp escrito y releído en
  `0x82010030`.
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
  renumerado de la 5, cerradas. El resultado vive en el RTL y en el contrato
  MMIO vigente.
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
    la selección de casos: los 47 de `x.tests/cases-cpu` declaran
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
  `requires`). El smoke test es `cases-cpu/basics/smoke`, y `swap_demo`/
  `swap_demo_fast` son `cases-cpu/video/swap-demo` y `cases-cpu/video/swap-demo-fast`,
  apuntando al `.asm` de la 21 sin copiarlo. `tear_demo` **no se puede convertir
  en caso** y no es una tarea pendiente: no pide `SWAP` nunca —es justo lo que
  demuestra—, así que `run_until.swap` no se dispara, y lo que enseña es una
  carrera que el simulador no modela. Razonado en
  [`x.tests/cases-cpu/video/README.md`](x.tests/cases-cpu/video/README.md).
- **«¿VVP qué ejecuta?»** Sí, el RTL: `vvp` corre el binario que compila
  `iverilog` a partir del RTL y su testbench.
