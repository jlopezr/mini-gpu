# CPU pipelined sobre la base del prototipo 35

Prototipo derivado de `35.fpga-cpu-fifo-sdram2`. Mantiene el mismo fabric FIFO,
SDRAM de cuatro bancos, consola de video, puerto serie, INPUT y mapa MMIO; su
objetivo es aislar la pregunta de microarquitectura: si la MiniCPU puede
convertirse en un nucleo segmentado que acepte una instruccion nueva por ciclo
en el caso comun.

La identificacion de placa es monitor `5.38`. La CPU va a 25 MHz (el oscilador
de la placa, sin PLL) y cierra a 65-70 MHz segun la colocacion (builds
`dcache-decide` y `perf-video`); la SDRAM a 100 MHz.

## Estado actual (12 de noviembre)

```text
          ┌─ instruction_buffer (I-cache 8 KB, EBR) ─┐
cpu.v ────┤                                          ├── arbitro ── SDRAM
 IF/ID/EX/WB └─ dcache (8 KB, EBR) ── cpu_dmem_adapter ─┘
```

- **Pipeline IF/ID/EX/WB** con punto de retiro arquitectonico. ID decodifica,
  lee el banco y calcula la direccion de LOAD/STORE; EX tiene la ALU, la
  decision de salto, el acceso a memoria y las MUL/DIV (paso 3). Con
  **adelantamiento** (seccion siguiente) la unica dependencia que para es la
  base de un LOAD/STORE recien calculada. Cada etapa es un `always` con un
  unico dueño por registro (`timing-etapas.md`).
- **Fuentes predecodificadas** (paso 1 del plan de etapas, abajo): al pasar de
  IF a ID se registran que registros lee la instruccion (`id_src_a/b`) y si es
  un LOAD/STORE (`id_memory`), asi que las comparaciones para adelantar salen
  de registros y no de decodificar `id_instruction`.
- **Redireccion del salto registrada** (paso 2): EX decide el salto y la
  busqueda se redirige un ciclo despues (`if_redirect`, `if_redirect_pc`); la
  instruccion que entra en EX detras del salto pasa como burbuja. Un salto
  tomado sin predecir cuesta 6 burbujas (3 con la decision en ID sin
  registrar, 5 con la redireccion registrada, una mas al pasar la decision a
  EX).
- **Prediccion de saltos, fase 1** (`cpu.v`, seccion 02b, parametro
  `BRANCH_PREDICT`): al pasar la cabeza de la cola de IF a ID se predicen
  tomados BRA y JAL, los saltos condicionales hacia atras (*backward-taken,
  forward-not-taken*) y `JR R31`, el retorno de mini-cc, con una pila de 8
  direcciones (*return address stack*) que llenan JAL/JALR con `rd = R31`.
  Lo de detras en la cola se descarta y se busca el destino: ~3 burbujas en
  vez de 6. EX comprueba y solo redirige si fallo (tomado sin predecir,
  predicho y no tomado, o retorno a otra direccion), con el coste de antes.
- **Prediccion de saltos, fase 2: BTB** (*branch target buffer*, seccion
  02c, parametros `BTB`, `BTB_BITS`, `BTB_TAG_BITS`): 64 entradas de mapeo
  directo con etiqueta parcial de 10 bits, destino, contador de 2 bits y bit
  de retorno (que toma la cima de la pila). Se consulta con cada peticion y
  la respuesta se **registra**: si predice tomado, la busqueda va al destino
  al ciclo siguiente y la peticion aceptada entre medias (`pc+4`) se marca
  para descartarla (`if_req_drop`). Un acierto cuesta **1 burbuja**. Como las
  peticiones ya no son seguidas, una FIFO de lo pedido en vuelo
  (`if_req_*`) guarda el PC de cada una. Se escribe un ciclo despues de que
  el salto sale de EX (`if_btb_write_*`) y se vacia al parar la CPU. Lo que
  no predice la BTB lo sigue prediciendo la fase 1. Una entrada ajena solo
  cuesta un fallo: ID comprueba el destino relativo, EX el de los retornos, y
  una instruccion predicha que no es salto vuelve a `pc+4`.
  Sin registrar (0 burbujas) la tabla queda dentro del bucle de
  `imem_address`: la CPU caia a ~45 MHz estimados y nextpnr no acababa de
  rutar en 45 minutos.
- **Busqueda de una instruccion por ciclo.** `imem` separa peticion
  (`valid/ready`) y respuesta (`rvalid`); una cola de cuatro entradas en IF y un
  contador descartan las respuestas del camino viejo tras un salto.
- **Cache de instrucciones** (`instruction_buffer.v`): 8 KB, mapeo directo,
  lineas de 16 bytes (una rafaga BL8), en EBR. Acierto en dos ciclos con la
  respuesta registrada (paso 2b) y una busqueda por ciclo; si una busqueda
  falla, la que ya se acepto detras se repite tras el relleno, asi que `ready`
  sigue saliendo de un registro.
- **Cache de datos** (`dcache.v`): 8 KB, mapeo directo, escritura inmediata a
  memoria y sin reservar linea al escribir, en EBR. Los STORE a SDRAM no
  esperan (posted) y siguen pasando por el bufer de combinacion de
  `cpu_dmem_adapter`; un LOAD que acierta espera a que el adaptador no deba
  respuestas, para no adelantar a la de un STORE. Un acierto ocupa EX **2
  ciclos**: la comparacion de etiqueta se registra (`ST_LOOKUP` -> `ST_DECIDE`)
  y la instruccion siguiente entra en EX en el mismo ciclo en que llega la
  respuesta (`ctl_advance` mira `ex_mem_done`).
- **Volcados sin esperar respuesta** (`cpu_dmem_adapter.v`): el bufer de
  combinacion es de una linea, pero al cambiar de linea la vieja se manda al
  puerto y el STORE se contesta al ciclo siguiente, sin esperar a la SDRAM;
  caben hasta 4 escrituras en vuelo (la cola del puerto). El orden lo garantiza
  el camino (cola del puente, cabeza por puerto en el fabric y emision en orden
  de llegada en el controlador), asi que un LOAD detras de un volcado ve el
  dato. Solo esperan a que se confirmen todas las escrituras el MMIO (que puede
  fallar y debe dar error preciso), la parada de la CPU (el monitor lee por
  otro puerto) y un LOAD a la linea guardada.
- **MUL, MULHI, MULFX, DIV, DIVU, REM y REMU** en EX (`cpu.v`, seccion 04b),
  que se queda la instruccion varios ciclos como un acceso a memoria. Los
  operandos son los de EX ya adelantados (`ex_a`, `ex_b`); al acabar, EX
  escribe el resultado en `ex_result` y la instruccion sale hacia WB como
  cualquier otra, y su consumidor lo toma adelantado. MUL/MULHI/MULFX salen del mismo producto con
  signo (cuatro parciales 16x16 en DSP, inferidos): 3 ciclos mas que una
  instruccion de ALU. La division es iterativa con signo al final: unos 34
  ciclos mas, y un REM/REMU justo detras de su DIV/DIVU con los mismos
  registros reutiliza el resto (2 ciclos mas, `ALU_FAST_PATH`, como en la 35).
  La division por cero es un error preciso. Sus esperas tienen contador propio
  (ranura 14, `STALL_MULDIV`, un motivo mas del reparto) y la ranura 15
  (`MULDIV_RETIRED`) cuenta cuantas se retiran.
- **Adelantamiento (forwarding).** Todos los caminos que salen baratos; en
  `cpu.v` llevan una etiqueta para buscarlos y el mapa completo esta en la
  cabecera del modulo:

  | Etiqueta | Camino (en ingles) | Que resuelve |
  |---|---|---|
  | `FWD-WB-EX` | *WB -> EX forwarding*: mux delante de la ALU (`ex_a`, `ex_b`) | usar el resultado de la instruccion de justo antes: ALU, comparacion del salto, destino de JALR/JR, dato del STORE y operandos de MUL/DIV. Lo selecciona `ex_forward_a/b`, decidido en ID y registrado, asi que el mux sale de un FF |
  | `FWD-WB-ID` | *register-file bypass* (`id_op_a`, `id_op_b`) | el valor que WB escribe este ciclo, que la lectura asincrona del banco aun no ve |
  | `FWD-HOLD` | operandos retenidos en EX | una instruccion que se queda en EX (memoria, MUL/DIV) guarda lo adelantado: WB se retira al ciclo siguiente |

  El consumidor de un LOAD (*load-use*) no necesita camino propio: espera en
  ID mientras dura el acceso y entra en EX cuando el LOAD pasa a WB con el
  dato, asi que no paga nada extra.

  Lo que **no** se adelanta, a proposito:

  | Caso | En ingles | Coste | Por que no |
  |---|---|---|---|
  | LOAD/STORE cuya base escribe la instruccion de justo antes (`ADDI R1,R1,4` + `LOAD [R1]`) | *address-generation interlock* (AGI) | 1 burbuja (`raw_hazard`, la unica parada por dependencia) | la direccion se calcula en ID para que la peticion a la D-cache salga de un registro; adelantar de EX a ID pondria la ALU delante del sumador de la direccion en el mismo ciclo |
  | Decidir el salto en ID con operandos adelantados | *early branch resolution* | 1 burbuja mas por salto tomado | el mismo camino largo; lo recupera la prediccion |
  | Dato del LOAD directo de la respuesta a EX | *memory -> EX forwarding* | — | no ganaria nada: el consumidor ya entra en EX justo cuando el LOAD pasa a WB |

- **Invalidacion por epoca** en las dos caches: cada etiqueta guarda la epoca
  en que se escribio e invalidar todo es sumar uno (en el flanco de `reset` o de
  la CPU parandose). Sin bits de valido, cada cache cuesta unas 330-390 LUT en
  vez de unas 2.000-2.300.
- **Dos resets en la CPU**: `reset` (el del sistema, con el que tambien se
  vacian las caches) y `soft_reset` (el RESET del monitor, solo la CPU). Con
  el segundo las caches siguen y contestan lo que ya habian aceptado; la CPU
  conserva la cuenta de lo que esta en vuelo (`if_inflight`, `ex_mem_drop`) y
  lo descarta. Antes las dos entradas eran una y `board-load` sobre un programa
  en marcha dejaba la CPU, a veces, sin pedir instrucciones (0 retiradas): una
  respuesta tardia de la I-cache daba la vuelta a `if_inflight`. Pasaba desde
  el adelantamiento (y seguramente antes); lo cubre el caso 3 de
  `cpu_memory_system_tb`, que se cuelga con el cableado antiguo.
- **Contadores de rendimiento** (CPU PERFORMANCE, `1.isa/mmio.md` §13.2): las
  ranuras 8-11 y 14 reparten cada ciclo sin emitir en un motivo (`CPI = 1 +
  EX con memoria + MUL/DIV + dependencia + salto + ID vacio + otros`), las
  12-13 cuentan aciertos y fallos de la cache de datos, la 15 las MUL/DIV
  retiradas y las 16-17 (`VIDEO_FRAMES`, `SWAP_WAIT`) cuanto del frame ocupa
  el trabajo de la CPU. `run_tests.py --measure` los saca en tablas.
- **SDRAM**: los registros de los pines van en las celdas de IO tambien con
  Yosys (`syn_useioff` en `sdram_controller_128.v`); la ventana de fase buena
  paso de 8 a unas 20-22 posiciones. La fase sale en el bitstream
  (`SDRAM_PHASE` en `top.v`, una por herramienta) y se mide con
  `tools/phase-sweep`. **Cuidado:** la ventana se sigue moviendo entre builds
  y la 18 de fabrica ha quedado en el borde (17-37 en `dcache-decide`). Con el
  build del adelantamiento, test-scheduler-c fallaba en placa de forma
  intermitente con la 18 (un resultado distinto cada vez; la memoria pasaba
  la prueba de 256 KB) y pasa siempre con la 27 (`monitor.py phase-set 27`).
  Antes de medir, fijar la fase; la solucion de fondo es el reloj de la SDRAM
  por la celda de IO (paso 6).

Bancos: `tools/test -p 38` (entre ellos `cpu_perf_tb`, que mide CPI sin placa
con programas que aislan cada efecto: dependencias encadenadas, salto que
depende de la anterior, LOAD seguido de su uso, base recien calculada...,
`dcache_tb`, `instruction_buffer_reset_tb`, `cpu_dmem_adapter_tb` y
`cpu_muldiv_tb` y `cpu_redirect_tb`, con mutantes comprobados). `cpu_data_path_tb` junta CPU, D-cache y adaptador reales,
y `cpu_memory_system_tb` añade puente, fabric, controlador, modelo de SDRAM y
dos generadores de trafico en los otros puertos. En placa pasan los 72 casos
de `run_tests.py --backend fpga-cpu -p 38`.

**Cuidado con el orden de las `<=` en Yosys (0.63+173).** Dentro de un bloque
anidado, una asignacion condicional seguida de otra sin condicion a la misma
señal sale mal: `if (c) begin if (a) v <= 0; v <= b; end` da `a ? 0 : b` en vez
de `b` (y con un `if/else` completo delante, Yosys ignora la ultima). En el
nivel de arriba del `always`, o con el valor por defecto primero y el
condicional despues (lo habitual), sale bien. La primera version de los
volcados sin esperar pasaba todos los bancos y fallaba 12 casos en placa por
eso: `if (wb_valid) send_flush; wb_valid <= 1`, con `wb_valid <= 0` dentro de
la tarea, dejaba la linea nueva invalida. Se encontro simulando la netlist de
Yosys (`synth -flatten; write_verilog` mas `simlib.v`) con el mismo banco.
Regla: nunca una asignacion sin condicion despues de otra condicional a la
misma señal; las tareas lo esconden facil.

## Rendimiento medido en placa

CPI de algunos casos de `run_tests.py --measure`; cada columna añade un cambio.

| Caso | Busqueda 1/ciclo | STORE sin esperar | I-cache 256 B | + D-cache 8 KB | I-cache 8 KB EBR | Volcados sin esperar | MUL/DIV | Etapas 1-2b | Acierto D-cache 2 ciclos | Adelantamiento | Prediccion | BTB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| video-bounce | 4,43 | 3,85 | 3,85 | 3,85 | 3,85 | 2,61 | 2,61 | 4,07* | 3,97* | 2,61* | 2,18* | 1,97* |
| video-band | — | — | — | — | 3,82 | 2,90 | 2,71 | 3,96* | 3,82* | 2,88* | 2,34* | 1,95* |
| video-swap-demo | — | — | — | — | 3,86 | 2,65 | 2,67 | 4,06* | 3,96* | 2,67* | 2,18* | 1,99* |
| program-bresenham-lines-core | 7,93 | 7,81 | 2,64 | 2,64 | 2,48 | 2,48 | 2,48 | 2,99 | 2,94 | 2,86 | 2,52 | 2,11 |
| program-bresenham-circles-core | 7,79 | 7,49 | 2,65 | 2,65 | 2,57 | 2,57 | 2,57 | 3,04 | 2,94 | 2,57 | 2,25 | 2,03 |
| program-mandelbrot | — | — | — | — | — | — | 2,76 | 2,90 | 2,90 | 2,12 | 1,90 | 1,76 |
| shared-calls-call-return | — | 10,86 | 8,32 | 8,14 | 8,41 | 8,50 | 8,36 | 8,68 | 8,82 | 8,77 | 8,64 | 8,64 |
| program-memory-copy | 6,68 | 6,05 | 6,07 | 5,00 | 5,02 | 4,64 | 4,64 | 5,14 | 5,09 | 4,73 | 4,23 | 3,89 |
| program-array-sum | 6,03 | 5,88 | 5,79 | 4,85 | 4,79 | 4,88 | 4,76 | 5,21 | 4,94 | 4,50 | 4,35 | 4,18 |
| subword-loads | 16,54 | 15,54 | 15,77 | 6,85 | 7,08 | 7,08 | 7,15 | 6,85 | 6,85 | 6,46 | 6,77 | 6,46 |

`Etapas 1-2b`: fuentes predecodificadas, redireccion registrada y respuesta de
la I-cache registrada (12 de noviembre). Suben el CPI de todo lo que salta
(+0,4-0,5 en bresenham: 5 burbujas por salto tomado en vez de 3) a cambio de
reloj: la CPU pasa de cerrar a 55,8 MHz a 63,2, y a 65,4 con la D-cache.

`Adelantamiento` (paso 3, 12 de noviembre): ALU y salto en EX con
adelantamiento WB -> EX. El CPI medio de `--measure` baja un 24 % (3,49 ->
2,65) con el reloj igual (69,4 MHz): test-scheduler-c 3,49 -> 2,59,
mandelbrot -27 %, xorshift -30 %, bresenham-circles -13 %. Lo que salta mucho y apenas encadena resultados
(calls, jump-table) sube un 2-4 %: el salto tomado cuesta una burbuja mas.

`Prediccion` (fase 1 de los saltos, 12 de noviembre): prediccion estatica y
pila de retornos en la cabeza de la cola de IF. CPI medio 2,65 -> 2,30
(-13 %), con el reloj igual (69,8 MHz): test-scheduler-c 2,59 -> 2,21,
fibonacci -17 %, calls-link-and-return -16 %, bresenham -12 %. En video el
salto pasa de ~1,5 a ~0,6 por instruccion; parte de lo ganado se va a EX con
memoria (0,08 -> 0,56 en bounce): el bucle llega antes al STORE que cambia de
linea y espera mas al volcado.

`BTB` (fase 2 de los saltos, 12 de noviembre): tabla de destinos consultada
con cada peticion de busqueda. CPI medio 2,30 -> 1,85 (-20 %), con el reloj
igual (69,1 MHz): test-scheduler-c 2,21 -> 1,65, string-c 2,89 -> 2,17,
bresenham-lines -16 %. En video el salto queda en 0,01 por instruccion (la
burbuja de cada acierto sale como "ID vacio", ~0,2).

\* El CPI de los casos de video **no compara CPUs** desde `Etapas 1-2b`: a
25 MHz el frame de bounce ya no cabe en un vsync (unos 530.000 ciclos de
trabajo para 417.000 por frame), asi que pierde un vblank de cada dos y el
bucle que espera al swap da mas vueltas, que cuentan como instrucciones. Para
el video la medida buena es la de "Ritmo de video" de `--measure` (ranuras 16
y 17): cuanto del frame ocupa el trabajo.

La I-cache en EBR descubre un fallo un ciclo mas tarde que la de biestables
(acepta, lee la EBR y compara al ciclo siguiente), asi que en los casos cortos,
que son casi todo fallos de primer acceso, sube 0,2-0,5 de CPI. Lo que gana es
espacio (8 KB en vez de 256 B por ~740 LUT menos); estos casos no tienen codigo
que lo aproveche.

Lo que dicen los contadores:

- **Video** no hace ni un LOAD a SDRAM: su "EX con memoria" (1,40) eran STORE
  al framebuffer y accesos MMIO, que ninguna cache acelera. Con los volcados
  sin esperar baja a 0,35-0,58 (lo que queda es sobre todo MMIO y el STORE que
  encuentra las 4 escrituras en vuelo).
- **Bresenham** (2,64) pierde sobre todo en saltos (1,03 por instruccion: unos
  3 ciclos por salto tomado) y dependencias (0,34).
- **MUL/DIV** (build `muldiv-contadores`, 72 casos en placa): pesan poco
  salvo en mandelbrot, donde el 21 % de las instrucciones son MUL y su espera
  es 0,68 de un CPI de 2,76. En starfield las DIV esperan 24 ciclos de media,
  pero son el 0,6 % de las instrucciones (0,14 de CPI). Lo que mas rinde es
  acortar la MUL (hoy 3 ciclos), no un scoreboard para la DIV.
- **Los fallos de cache que quedan son de primer acceso.** Los casos son muy
  cortos (10-5.000 instrucciones) y caben enteros en 8 KB: agrandar las caches
  no mejoraria ninguno. La cache de datos acierta un 57-60 % en memory-copy y
  array-sum porque cada linea nueva falla la primera vez.

## Video: cuanto del frame ocupa

Con las ranuras 16 y 17, en "Ritmo de video" de `--measure`. Solo los casos con
muchos intercambios; en los de 1 a 4 domina el dibujo inicial. `Frames por
swap` es Ciclos/swap entre Ciclos/frame.

| Caso | Frame ocupado (`perf-video`) | Frames por swap | Frame ocupado (adelantamiento) | Frames por swap | Frame ocupado (prediccion) |
|---|---:|---:|---:|---:|---:|
| video-band | 110,5 % | 2,0 | 99,2 % | 1,25 | **70,1 %** |
| video-bounce | 102,9 % | 2,0 | **93,9 %** | 1,01 | **66,4 %** |
| video-swap-demo | 102,9 % | 2,0 | **93,0 %** | 1,04 | **65,7 %** |
| video-starfield | 102,7 % | 2,0 | **92,5 %** | 1,02 | **65,4 %** |
| video-cube | 95,4 % | 1,08 | — | — | — |
| video-swap-demo-fast | 21,6 % | 1,08 | 19,5 % | 1,04 | 14,0 % |
| video-starfield-fast | 18,9 % | 1,05 | 17,0 % | 1,05 | 14,9 % |
| pacman | 4,1 % | 1,02 | — | — | — |

Con `perf-video` (antes del paso 3), bounce, starfield y swap-demo **no
cabian por un 3 %** e iban a un intercambio cada dos frames (30 fps en vez de
60). Con el adelantamiento les sobra un 6-7 % y vuelven a ir a un swap por
frame; band queda justo (99 %) y pierde un vblank de cada cuatro. Con la
prediccion todos se quedan en un 65-70 %: un tercio del frame libre. (cube y
pacman no entraron en esa medida.) La columna antigua `Swaps/frame` escondia
todo esto: cuenta frames de pared, con el viaje de parada. A 50 MHz el frame
ocupado se reduciria a la mitad.

## Que mejorar primero (tras la BTB)

Reparto de `--measure` (CPI = 1 + motivos) en los casos que mas duran; entre
parentesis, el salto con la prediccion estatica sola:

| Caso | CPI | EX con memoria | MUL/DIV | Dependencia | Salto | ID vacio |
|---|---:|---:|---:|---:|---:|---:|
| video-bounce | 1,97 | **0,78** | 0 | 0 | 0,01 (0,61) | 0,18 |
| video-starfield | 2,34 | **1,01** | 0,10 | 0 | 0,01 (0,75) | 0,22 |
| video-band | 1,95 | **0,75** | 0 | 0 | 0,01 (0,56) | 0,19 |
| program-mandelbrot | 1,76 | 0 | **0,68** | 0 | 0,01 (0,22) | 0,07 |
| cpu-gpu/gpu-scheduler/test-scheduler-c | 1,65 | 0,35 | 0,06 | 0,10 | 0,09 (0,69) | 0,06 |
| program-bresenham-circles-core | 2,03 | 0 | 0 | 0 | **0,86** (1,19) | 0,17 |
| program-bresenham-lines-core | 2,11 | 0 | 0 | 0 | **0,77** (1,36) | 0,33 |
| cpu-gpu/libc/string-c | 2,17 | 0,46 | 0,02 | 0,04 | **0,44** (1,22) | 0,21 |

"ID vacio" incluye ya la burbuja de cada acierto de la BTB. Lo que queda en
salto es bresenham y string-c: saltos que dependen del dato, que fallan con
cualquier contador. En video manda el STORE que espera al volcado; en
mandelbrot, la MUL.

"Recuperaria" es un techo estimado:

| Mejora | Motivo | Recuperaria | Coste |
|---|---|---|---|
| Volcados: mas de una linea en el bufer de combinacion | EX con memoria | 0,5-0,8 en video | medio |
| MUL en 1-2 ciclos (ALU54B para sumar los parciales) | MUL/DIV | ~0,4 en mandelbrot | bajo |
| D-cache segmentada y etapa MEM aparte: un acierto en 1 ciclo sin bloquear EX | EX con memoria | ~1 ciclo por LOAD que acierta | alto |
| BTB sin la burbuja del acierto | ID vacio | ~0,2 | alto: el reloj (ver arriba) |
| MMIO un ciclo menos | EX con memoria | 0,05-0,2 en video | bajo |
| AGI (base recien calculada) | Dependencia | ~0 | no compensa |
| Prefetch | ID vacio | 0 en estos casos: caben en 8 KB | hace falta un caso grande (cubo de mini-gl) |

## Donde se pierde el CPI (build `icache-ebr`)

Reparto de `--measure` ponderado por instrucciones, para que los programas
largos pesen lo que deben. Entre parentesis, la parte de lo perdido (CPI - 1):

| Grupo | CPI | EX con memoria | Dependencia | Salto | ID vacio |
|---|---:|---:|---:|---:|---:|
| Video (6 casos, 25,6 M instr.) | 3,96 | 1,48 (50 %) | 0,50 (17 %) | 0,98 (33 %) | 0 |
| Programas largos sin video (5 casos, 1,9 M) | 3,92 | 1,17 (40 %) | 1,04 (35 %) | 0,71 (24 %) | 0 |
| Casos cortos (< 1000 instr.) | 4,96 | 1,66 | 0,58 | 0,85 | 0,85 |

"ID vacio" ya es 0 en todo lo que dura: la busqueda esta resuelta. Lo que queda
se ve entero en el bucle que domina el video, el fondo de `video/bounce`:

```text
bg_word: STORE R23, R6, 0     ; dos pixeles al framebuffer
         ADDI  R6, R6, 4
         ADDI  R3, R3, 1
         BLT   R3, R25, bg_word
```

Cuatro instrucciones que deberian costar 4 ciclos y cuestan ~15,8:

- **Salto, ~3,8 ciclos por vuelta**: el BLT tomado deja 3 burbujas.
- **Dependencia, ~2**: el BLT usa el R3 del ADDI de justo antes y, sin
  adelantamiento, espera a que llegue a WB.
- **EX con memoria, ~5,6**: tres de cada cuatro STORE se funden en el bufer de
  combinacion; el cuarto cambia de linea y arranca un volcado, y con UNA sola
  linea de bufer el adaptador no acepta nada mas (`dmem_ready` bajo) hasta que
  la SDRAM contesta, unos 18 ciclos. El STORE siguiente los espera. (Resuelto
  despues con los volcados sin esperar respuesta: video-bounce 3,85 -> 2,61.)

## Pasos siguientes

En orden de lo que mas promete segun las medidas:

1. **Partir las etapas antes de optimizar** (plan para 80-100 MHz). Primero
   se estabilizan las etapas, de modo que cada camino largo salga de
   registros, y despues se meten adelantamiento y prediccion sobre esa base:

   | Paso | Que | Estado |
   |---|---|---|
   | 1 | Predecodificar las fuentes en la cabeza de la cola de IF | hecho |
   | 2 | Redireccion del salto registrada | hecho (+2 burbujas por salto tomado) |
   | 2b | Respuesta de la I-cache registrada, cola de 4 | hecho, CPU 63,2 MHz |
   | — | Acierto de la D-cache en 2 ciclos, comparacion registrada | hecho, CPU 65,4 MHz |
   | 3 | ALU y decision de salto en EX, con adelantamiento WB -> EX | hecho, CPU 69,4 MHz (+1 burbuja por salto tomado) |
   | 4 | Prediccion de saltos, fase 1: estatica y pila de retornos | hecho, CPU 69,8 MHz |
   | 4b | Prediccion de saltos, fase 2: BTB (consulta registrada) | hecho, CPU 69,1 MHz |
   | 5 | Subir el reloj (pasos 8 y 9) | pendiente |

   El camino critico ahora es la comprobacion de division por cero en EX
   (`ex_forward_b` -> `ex_b == 0` -> `ex_class`, 14,4 ns), seguida de la cola
   de IF (13,8 ns). La primera se quita comprobando `md_divisor` un ciclo
   despues.
2. **Saltos mas baratos**, en dos fases que comparten la comprobacion en EX
   (llevar "predicho tomado y a donde" por el pipeline y corregir si falla):
   - **Fase 1, en la cabeza de la cola de IF: hecha** (ver Estado actual).
     mini-cc llama con `JAL R31` / `JALR R31` y retorna con `JR R31`.
   - **Fase 2, al pedir la instruccion: hecha**, con la consulta registrada
     (1 burbuja por acierto; ver Estado actual).
   - Ademas, respuesta directa a ID cuando la cola esta vacia, sin pasar por
     ella (abarata tambien los fallos de prediccion).
3. **Adelantamiento: hecho** con el paso 3 (ver Estado actual). Queda solo
   la burbuja del AGI, que no compensa quitar.
4. **Menos fallos de primer acceso**: traer la linea siguiente por adelantado
   (prefetch) en las dos caches, o lineas de 32 bytes.
5. **Un programa grande para medir tamaños.** Los casos actuales caben en
   8 KB (el mayor con MUL/DIV, serial-forth, son 4,4 KB; pacman, 3 KB de
   codigo y unos 7,5 KB de datos). Los sketches 3D de `39.mini-gl` si pasan:
   racer ~209 KB de codigo, skimmer ~60, tanks ~50, rotating_cube/boxes ~30
   (la base del renderer) y tie_fighter/x_wing ~29 KB de codigo con 18-30 KB
   de datos. En 3D renderiza la CPU (`MGL_VERSION` 0), asi que en principio
   corren en la 38. Falta comprobar que no tocan MMIO que la 38 no tiene, que
   corren sin teclado de forma determinista (parar en el swap N) y cuanto
   tardan por frame. Con `IMEM_MISSES` y `DMEM_MISSES` se veria si 16 KB o
   dos vias servirian; rotating_cube para la I-cache, tie_fighter para la
   D-cache.
6. **Reloj de la SDRAM por la celda de IO** (`ODDRX1F` con `D0=1, D1=0`, como
   el DVI). Hoy `assign sdram_clk = clk` va por rutado general y la ventana de
   fase aun se mueve entre builds (2-21 en uno, 8-29 en otro). Tambien `dq_oe`,
   replicado por pin, para que quepa en las celdas de IO.
7. **MMIO, solo si aparece un caso que lo necesite.** El "EX con memoria"
   alto de input-keys-and-mouse (2,33) NO es tiempo perdido: es una espera
   activa (`LOAD STATUS / ANDI / BEQ`) hasta que el PC manda una tecla, y
   preguntar mas deprisa solo da mas vueltas. Lo mismo el `wait_swap` del
   video. Un acceso MMIO cuesta unos 5-6 ciclos. Una escritura MMIO NO puede
   simplemente no esperar como las de SDRAM: puede dar error (hueco del mapa,
   registro de solo lectura, el dispositivo la rechaza) y la ISA pide errores
   precisos, con el PC en la instruccion culpable. Solo se podria si el error
   se decidiera por la direccion al aceptar, o con un error pegajoso impreciso
   (cambio de ISA). Ningun caso medido hace MMIO util en cantidad.
   Lo que si se puede recortar es la latencia, hoy ~7 ciclos por acceso:
   la etapa 1 de `mmio_decoder` (decodificacion registrada) se puso en la 30
   para cerrar 80 MHz y a 25-50 MHz sobra. Con un parametro (y `EXTRA_CYCLES`
   del `mmio_mux` a juego) seria un ciclo menos. La etapa 2 no se puede quitar:
   el error de SWAP y el byte del puerto serie solo valen despues de escribir.
8. **Subir el reloj de la CPU a 40-50 MHz, aplazado.** A 25 MHz sobra margen
   (cierra a 65) para los saltos y el adelantamiento, que alargan el camino
   critico; se sube al final. PLL y divisor UART 100 -> 200.
   A 50 hay que barrer semillas y, si no cumplen, quedarse en 40. Medir antes y despues contra la 35 (`bench-all -p 35 -p 38`;
   la 35 va a 80 MHz y necesita antes `syn_useioff` para volver a cumplir).
9. **Mas alla de ~50 MHz hay que partir ID** (en marcha: paso 1 de esta lista), que es todo el camino critico
   (decodificar -> banco -> comparar -> salto -> enable de IF e ID): pipeline
   clasico IF/ID/EX/MEM/WB con adelantamiento a EX. La predecodificacion en la
   cola de IF y la redireccion registrada ya estan; falta sacar la ALU de ID y
   la prediccion para no pagar la redireccion. Techo realista 70-80 MHz, por
   rutado. Ver `timing-etapas.md`.
10. **Scoreboard: todavia no.** Con el pipeline en orden y cada instruccion en
    una posicion fija, comparar las fuentes de ID con `ex_rd`/`wb_rd` ya es un
    scoreboard de dos entradas, y el adelantamiento usa esas mismas
    comparaciones. Hara falta cuando algo termine fuera de su posicion: una DIV
    que corra de fondo mientras siguen entrando instrucciones independientes
    (hoy para EX ~35 ciclos; medir antes si pesa), o LOADs que no bloqueen EX mientras falla la
    D-cache (y entonces tambien reglas para que los errores sigan siendo
    precisos).
11. **Instruction buffer y fabric de la 35-37**: la 38 tiene ya su propia
    version de `instruction_buffer.v` (protocolo partido y EBR). Si se quiere
    llevar a los otros prototipos, hay que cambiar tambien su CPU.

### Resuelto: el acierto de la D-cache cuesta 2 ciclos de EX

Eran 3. Medido en `cpu_data_path_tb` con CPU, D-cache y adaptador reales;
justo detras de un STORE, 1,62 (eran 3,31). Ciclo a ciclo:

```text
E0  el LOAD entra en EX; la D-cache lo acepta y lee la EBR
E1  compara la etiqueta y la registra (ST_LOOKUP -> ST_DECIDE)
E2  rvalid sale de esos registros; el LOAD pasa a WB y en el MISMO ciclo
    entra en EX la instruccion siguiente (ctl_advance mira ex_mem_done)
```

Antes la siguiente no entraba hasta el ciclo despues de `rvalid`. Registrar
la comparacion no cuesta latencia y saco la etiqueta del camino critico.
Un LOAD por ciclo necesitaria una etapa MEM aparte.
