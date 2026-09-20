# TODO

Por orden de prioridad **argumentada**, no heredada. Cada punto dice qué falta,
por qué importa y qué lo bloquea; si no se pueden escribir esas tres cosas, o no
está verificado o no es un punto.

Repasado el 19/09/2026 contra el árbol. Al final hay un apartado con lo cerrado,
para no volver a abrirlo por error.

---

## 1. Cinco bitstreams no corresponden a su RTL

**Qué falta.** Resintetizar **12, 14, 16, 17 y 18**, rebarriendo semilla donde
la haya fijada, y después una ronda de placa de esas cinco más la **6** y la
**10**, que nunca se han probado con el `monitor.v` final.

**Por qué importa.** `monitor.v` es del 18/09 00:07 y es idéntico en las diez
carpetas. Comparando con el `_build/default/hardware.pnr` de cada una:

| Resintetizadas después | Con bitstream anterior          |
|------------------------|---------------------------------|
| 6, 10, 22              | **12, 14, 16, 17, 18, 19, 21**  |

La 19 y la 21 estaban en la columna izquierda y han cambiado de lado: la
migración a MMIO v2 les tocó el RTL y su bitstream es anterior al RTL igual que
en las otras cinco. Es el mismo riesgo, sólo que éste lo hemos creado nosotros y
está anotado. La **18** está ahora en la misma situación, por lo mismo.

De las tres, la única que se ha vuelto a sintetizar es la **21**, y el resultado
es que **no cumple**: 79,90 MHz contra 80,00 con la semilla 13. O sea que el
barrido de las tres no es una formalidad.

En esas cinco, el bitstream que `test-board` programa **no es el RTL que hay en
la carpeta**. Cualquier medida o validación que se haga contra ellas es de
procedencia desconocida, y eso contamina en silencio todo lo demás — es
exactamente el modo de fallo que ya apareció una vez, cuando el `default` de la
22 apuntaba a otro diseño y la placa acababa con un bitstream que no era el que
se creía haber subido.

**Qué lo bloquea.** Nada. Son unos diez minutos de placa y un rato de síntesis.
`yosys` y `nextpnr` son monohilo: se lanza en paralelo con `Start-Job`, una
carpeta por trabajo.

**Dos trampas al ejecutarlo:**

- Hay que subir con `board-upload --rebuild`. Sin esa opción, `apio upload` se
  ahorra el trabajo cuando la versión coincide — y la versión **no distingue dos
  builds de la misma carpeta**, que es exactamente el caso aquí: el número no
  cambia, el netlist sí. Sin `--rebuild` se validaría otra vez el bitstream
  viejo, creyendo lo contrario.
- Que la síntesis en segundo plano devuelva éxito **no significa que haya
  cumplido timing**. Hay que mirar el resultado de cada una con `build-status`
  antes de pasar a placa.

**Va primero porque es barato y porque todo lo que se valide en placa después
depende de ello.** Y cuanto más se acumule sin verificar, menos dirá un fallo
sobre cuál de los cambios lo causó.

---

## 2. Migrar a MMIO v2

**Qué falta.** Aplicar [`1.isa/mmio.md`](1.isa/mmio.md) al RTL, a los monitores,
a los simuladores y a los tests. Es el contrato decidido el 19/09/2026.

**Estado: la 21, la 19 y la 18 ya conforman**, y con ellas el ensamblador, el
generador de constantes y los tres simuladores funcionales. **Quedan siete
carpetas.** Hay tres bitácoras: la de la
[21](21.fpga-cpu-hdmi-alu/docs/migracion-v2.md) es el camino completo; la de la
[19](19.fpga-cpu-hdmi-ls/docs/migracion-v2.md) cuenta sólo lo que cambió al
repetirlo y trae la estimación corregida; y la de la
[18](18.fpga-cpu-hdmi-bl8/docs/migracion-v2.md) mide hasta dónde llega el atajo
de copiar de una gemela ya migrada, y es la primera carpeta sin puerto serie.
La tabla de conformidad está en
[`docs/resumen-prototipos.md`](docs/resumen-prototipos.md#conformidad-con-mmio-v2).

**Ninguna de las tres se ha sintetizado desde la migración con éxito**: las tres
tienen la semilla de su `apio.ini` invalidada y el barrido pendiente, y ninguna
se ha probado en placa. La 21 **sí se sintetizó**, el 20/09/2026, y **no cumple
temporización**: 79,90 MHz contra los 80,00 del objetivo con la semilla 13, y
11 590/5 236 LUT/FF frente a los 10 867/5 066 de antes. Está en
`docs/synthesis-report.md`. El barrido de las tres se paga junto.

Lo que ya está hecho y **no hay que repetir por carpeta**:

- **`.equ` en el ensamblador** y `mmio_map.vh` como fuente única generada
  (v2 §20), con `tools/generate-mmio --check` y `x.tests/test_mmio_map.py`.
- **`1.isa/mmio_map_v1.vh`**, el mapa de transición, con los mismos nombres que
  v2 y los valores de hoy. Permite simbolizar los `.asm` de una carpeta **sin
  mover ninguna dirección**, y que migrarla sea después cambiar la línea del
  `.include`. Se borró al cerrar la 21 y hubo que rehacerlo para la 19: el
  criterio correcto es que **sobra cuando lo suelta la última carpeta**, no la
  primera.
- **`x.tests/test_top_wiring.py`**, que compara anchuras de puerto en los diez
  `top.v` **y ahora también en los bancos** (4681 comparaciones). Al extenderlo
  aparecieron cuatro direcciones MMIO sin ensanchar en la 21 y dos en la 18,
  todas ya arregladas; en `DEUDA_EN_BANCOS` sólo quedan las tres de
  `perf_probe_tb.v`, que son ajenas a MMIO y compartidas por 18, 19 y 21. Trae
  además una comprobación de que un `top.v` no estrecha el bitmap de registros
  de vídeo.
- **`x.tests/test_fullframe_fixture.py`**, que descubre solo las carpetas con el
  trío `fullframe_tb.asm` / `examples/fullframe.asm` / `fullframe.hex`.
- **Los periféricos funcionales** (`tools/sim_devices.py`, `sysid_device.py`) y
  los tres backends de simulador, que ya hablan v2.

Los trozos que quedan por carpeta, de más a menos mecánico:

- **Reubicar los bloques** a las bases de 64 KiB de v2 §2. Decodificadores,
  listas blancas, `monitor.py` y constantes de programas.
- **`SYSTEM`** (v2 §5): `MAGIC`, `MMIO_VERSION`, `SYSTEM_ID`, `DEVICES`,
  `MEM_BASE`/`MEM_SIZE`, `MONITOR_VERSION`. Sustituye al `SYS_ID` de cuatro
  palabras.
- **Contadores** (v2 §12): array en el offset 0 con el control detrás, wrap
  uniforme —hoy la CPU satura y la GPU da la vuelta—, `PERF_OVF`, `PERF_CTRL`
  con freeze, y `VIDEO_TX` movido a VIDEO.
- **Vídeo** (v2 §9): `FRAME_COUNT` de 32 bits fuera de `STATUS`, `HALT_TARGET`,
  y error en base desalineada en vez del truncamiento silencioso de hoy.
- **Los bancos de pruebas**, que es donde está el trabajo que nadie cuenta: los
  offsets viven sueltos por todo el fichero y no hay generador que los cubra.
- **`GPU_CONTROL` y las máscaras de warp** (v2 §14.1), con los comandos del
  monitor pasando a ser una fachada que escribe esos registros. Es lo que
  permite que la CPU lance la GPU, y es el trozo con más RTL nuevo.
- **Acceso MMIO desde SIMT**: hoy varias lanes se sirven por turnos; v2 §4.2
  exige error.
- **Escrituras sub-palabra a MMIO** (§4.1 y §16.2). Es lo único que la 21 deja
  a deber, y a propósito: el host y varios bancos escriben byte a byte y
  tienen que pasar a `WRITE_WORD` **a la vez**. Es un cambio del protocolo del
  host, transversal, no de una carpeta.

**Por qué importa.** Es lo que decide si la MiniGPU puede ser un acelerador de la
MiniCPU o se queda como sistema hermano. Hoy `run/halt/step/reset` llegan por
señales del monitor, así que **solo el host puede lanzar la GPU, y solo con la
GPU parada**. Y la ventana de warps está llena al 100 %, sin sitio para más de
ocho.

**Qué lo bloquea.** El punto 1: migrar sobre bitstreams que no corresponden a su
RTL haría indistinguible un fallo de migración de uno de procedencia.

**Está en el 2 y no en el 1 a propósito**, y conviene decir la tensión: no hay
ningún consumidor que lo pida hoy —no existe ningún bitstream con CPU y GPU
juntas— así que su valor es futuro. Lo que lo sube hasta aquí es que el coste
crece solo: cada prototipo nuevo construido sobre el mapa viejo es más
migración después, y mientras tanto el RTL apunta a un mapa y la referencia
describe otro.

Antes de empezar conviene **medir el coste real** en una carpeta —la 16, que es
pequeña y ya lleva semilla fija— en vez de planificar las diez a ciegas.

---

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

**Es lo de más valor por esfuerzo de la lista, y es independiente del punto 2**:
solo toca simulador, no comparte un fichero con la migración. Se puede hacer en
paralelo.

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

**Qué falta.** Los siete salen con exit 1. Medido el 19/09/2026 con `tools/lint`:

| Prototipo | 6 | 10 | 16 | 18 | 19 | 21 | 22 |
|---|--:|--:|--:|--:|--:|--:|--:|
| Diagnósticos | 18 | 41 | 66 | 40 | 36 | 38 | 31 |

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
un diseño que cierra y está verificado en placa. El punto 2 va a tocar esa
carpeta de todas formas — es el momento de aplicarlo.

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
