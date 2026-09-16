# Contrato del modelo 25

## Fuentes estudiadas antes de implementar

- `1.isa/isa.md`: semántica vigente, incluidas capabilities.
- `2.cpu-sim-func/minicpu_sim.py`: referencia escalar independiente.
- `11.gpu-sim-func/minigpu_sim.py` y documentación de regiones reutilizables.
- `22.fpga-gpu-bl8/{gpu_sm,gpu_lane,gpu_register_file,gpu_lsu2,
  gpu_imem_buffer,instruction_buffer,gpu_perf_counters}.v`.
- `22.fpga-gpu-bl8/{profiling,sm-pipeline,lsu-v2}.md`.
- Modelos 23 y 24; dirección acordada conservada en `README.md` de 25.

El SM existente tiene un `current` global y una FSM serial. Las lanes
conservan DECODE/EXECUTE/RETIRE y estados de handshake. RF tiene dos lecturas
registradas y una escritura por lane, direccionadas por warp. LSU2 tiene ocho
slots vectoriales y coalesce por líneas de 16 bytes; vuelve a arbitrar entre
grupos. PICK prioriza respuestas LSU, barreras y normalización antes de elegir
warp. El buffer de instrucciones es directo, con líneas de 16 bytes.

## Separación

`isa.py` evalúa operandos inmutables y devuelve resultados o peticiones de
memoria. No conoce warps, reloj, memoria global ni FSM. `simt.py` controla
regiones, caminos, barreras y máscaras. `resources.py` define registros y
latencias. El motor de ciclos conecta las piezas.

Se reutiliza de 11 el contenedor de estado arquitectónico y su validación de
lanzamientos, **nunca** `System.step`, `Warp.step` ni `CPU.evaluate`. Los
evaluadores de CPU y GPU quedan independientes para comparación diferencial.
Se reutiliza el ensamblador y la infraestructura de tests del repositorio.

## Hitos y aceptación

1. Datapath puro: ALU, extensiones y encodings frente a MiniCPU.
2. Registros S/F/I/D/X/W, ALU y scheduler: latencias exactas, ninguna escritura
   anticipada, ninguna reemisión del warp en su ciclo de commit.
3. X multiciclo: latencias parametrizables, operandos retenidos, orden FIFO y
   contrapresión hasta S; varios warps.
4. LSU: captura de peticiones, coalescencia, latencia, respuesta y errores
   atómicos; memoria visible solo en su finalización.
5. SIMT: branches, regiones reutilizables, una operación de pila por ciclo,
   EXIT parcial, barreras por grupo y generaciones.
6. Buffer de instrucciones, trazas, contadores, conformidad y programas reales.

Cada hito añade pruebas al lanzador común `tools/test --prototype 25 --quick`.

## Discrepancias y decisiones explícitas

1. El modelo 24 llama a `warp.step()` en D: registros, memoria, PC y máscaras
   cambian antes de completar la latencia. Además libera `in_flight` de memoria
   al emitir. No es un contrato de commit válido para este modelo.
2. `sm-pipeline.md` mezcla propuestas históricas (X de 4, 2 o 1 ciclos). La
   dirección de 25 sustituye las FSM de lane: D captura operandos, X simple
   dura 1 y W escribe. No se importan `exec_base` ni los CPI de 23/24.
3. El funcional GPU solo soporta el repertorio antiguo. Aquí se añaden
   `alu_extended`, `compare`, `shift_immediate` y `subword_memory`, contrastados
   con CPU. `calls` queda fuera: la ISA no define soporte SIMT para llamadas.
4. Las referencias documentales a un RTL con semántica antigua estaban
   desactualizadas y se han corregido: los RTL de 12/14/17/22 contienen
   REGION/PATH separados y reutilización por `ssy_pc`, igual que los modelos
   actuales. La diferencia de 25 es la temporización, no otra semántica SIMT.
5. El comentario de JR en MiniCPU todavía dice que R0 es general; la ISA y el
   código que descarta escrituras establecen R0=0. Aquí R0 siempre es cero.
6. El RTL comprueba SSY con `target[31:17]` (128 KiB), mientras su memoria de
   programa puede alcanzar 32 MiB. Aquí se valida contra la memoria configurada,
   como el funcional y la especificación arquitectónica.
7. El funcional garantiza fallo atómico de warp; el RTL puede haber escrito
   lanes antes de detectar un error de otra. Aquí se valida toda la instrucción
   antes de publicar resultados. No se pretende reproducir ese efecto parcial.
8. `LANE_OPS` cuenta aquí la máscara capturada al emitir, también para branches
   y EXIT. El RTL tiene rutas que cuentan `active` después de cambiar la máscara;
   hay que alinear ese punto de muestreo antes de comparar contadores.
9. El buffer RTL presupone un único fetch pendiente y descarta `rsp_ready`.
   El modelo retiene la respuesta con backpressure, imprescindible al segmentar.

## Alcance físico

Las latencias de las unidades son parámetros de la **nueva** microarquitectura:
MUL/MULFX/MULHI 4 ciclos, divisiones/restos 32; shifts iterativos
`max(1, cantidad * shift_per_bit)`. Cantidad máxima de las lanes activas; cero
en `shift_per_bit` selecciona un barrel shifter de 1 ciclo. Son contratos de
latencia, no una simulación de productos parciales o bits del divisor.

No se modelan reset/INIT, Fmax, SDRAM eléctrica, scanout, MMIO, refresco ni
arbitraje del fabric. Las latencias de memoria son experimentales (17 por
transacción por defecto), no una promesa de ciclos del RTL actual. Programas
con vídeo/MMIO deben usar variantes sin MMIO, como `plasma_nommio.asm`.

El buffer guarda datos y tags, no solo penalizaciones; el código es inmutable
durante la ejecución, igual que el contrato documentado del buffer RTL.
La memoria es unificada little-endian, limitada al tamaño configurado.

## Reloj y registros de etapa

`cycle()` transforma el estado de comienzo del ciclo C en el de C+1. Los
paquetes son dataclasses inmutables; una etapa vacía se representa con `None`.
Se calculan elegibilidad, mantenimiento y decisiones de avance sobre el estado
anterior; se construyen registros siguientes y se publican los efectos al final.
El orden textual W→X→D sirve para propagar **ready**, no datos recién escritos.
Una instrucción no puede cruzar dos registros en un ciclo.

| Etapa | Contrato |
|---|---|
| S | Round-robin, captura warp/PC/máscara, asigna serial y reserva `in_flight`. El token S se conserva ante contrapresión. |
| F | Un fetch pendiente; acierto de un ciclo, fallo añade `imem_miss_cycles`. Captura datos y retiene respuesta si I no acepta. |
| I | Registro de instrucción, desacopla respuesta de fetch de decode. |
| D | Decodificación, destinos y captura de operandos. Encaminamiento a X, LSU o W. El snapshot completo del RF es una comodidad del modelo: la ISA solo consume los operandos de la instrucción. |
| X | Un recurso vectorial no segmentado, una operación simple por ciclo; una larga conserva el token y aplica backpressure. Produce resultados privados. |
| W | Publica resultados y control SIMT, contabiliza retiro y libera `in_flight`. |

La primera elección ocurre en C=0 y deja el registro S válido para C=1.
Con fetch ideal, la primera ALU retira al flanco final de C=6. Un warp aislado
se vuelve a elegir en C=7: **no hay bypass W→S**, ni LSU→S, ni mantenimiento→S.
Por ello el intervalo entre ALU de un solo warp es 7 ciclos en este contrato,
aunque ocupe seis registros de etapa. Con suficientes warps se puede aceptar
una instrucción por ciclo. El arranque vacío cuenta como un ciclo real.
SSY/BAR/EXIT/HALT van D→W; esperan que no haya un X anterior. No ocupan X ni
adelantan a instrucciones previas del mismo camino de finalización.

El opcode y sus campos reservados se validan en D; los fallos viajan como
resultados y se publican al completar. No hay cambios arquitectónicos
especulativos. División por cero identifica la primera lane activa que falla;
TRAP es un fallo global del warp, sin lane. Un error global cancela todos los
tokens pendientes. Entre recursos se conserva el primer error observado, con
prioridad W si coinciden; no se promete un prefijo global preciso del programa.

## Memoria, orden y puerto de escritura

Decisión confirmada por el usuario: **orden por recurso**. X/W conserva el
orden de sus instrucciones; LSU usa FIFO y también completa en orden.
Una operación LSU puede terminar antes o después de una ALU de otro warp.
No hay scoreboard, ROB ni selección por antigüedad entre ambos caminos.

D captura direcciones y datos, valida todas las lanes, y reserva un slot LSU.
El warp mantiene `in_flight` hasta la finalización, incluidas las esperas del
puerto RF. `wait_mem` se deriva de la pertenencia a la cola; no existe una
segunda copia del bit que pueda quedar desincronizada. La cola llena bloquea D;
el resto del front-end se llena hasta que propaga la contrapresión.

El modelo de memoria es deliberadamente sencillo: canal FIFO, un vector en
servicio, latencia `transacciones_coalescidas × memory_cycles`; cada transacción
ocupa exactamente ese número de ciclos. Loads duplicados se fusionan y stores
solapados requieren rondas separadas. Un vector de stores se publica
atómicamente, en orden creciente de lane (gana la última en direcciones
duplicadas). Los loads capturan datos al llegar la respuesta vectorial, antes
de arbitrar RF. Si la respuesta espera, sus datos **no se vuelven a leer**.

Este contrato no reproduce el round-robin entre grupos de `gpu_lsu2`: mantiene
FIFO por vector para cumplir el orden sencillo acordado. Tampoco hay
intercalación de visibilidad entre transacciones de un mismo vector. El buffer
de instrucciones y LSU tienen canales de latencia independientes; modelar el
fabric compartido será una extensión explícita, no una penalización oculta.

Hay un puerto vectorial de escritura RF (uno por lane, con arbitraje común).
W tiene prioridad fija; una respuesta de load retenida conserva slot, datos,
PC e `in_flight`. Las escrituras a R0 se descartan y no piden puerto. Un store,
un branch o una instrucción SIMT sin escritura RF puede completar junto a la
otra ruta: son dos retiros posibles por ciclo, pero nunca dos escrituras RF.
La prioridad fija puede prolongar la espera LSU bajo tráfico ALU sostenido;
queda expuesto en los contadores y es una decisión que se puede experimentar.

## Mantenimiento independiente

Cada warp sin instrucción pendiente puede normalizar una entrada de REGION o
PATH por ciclo. No se ejecuta un bucle de desapilado de duración cero.
Los warps que necesitan normalización quedan fuera del scheduler hasta el
ciclo siguiente a terminarla. Hay control de mantenimiento por warp: hasta
ocho normalizaciones simultáneas, sin ocupar X ni S.

BAR retira al entrar en WAIT_BAR; conserva PC hasta liberarse. Los participantes
son los warps vivos del mismo workgroup; deben esperar en el mismo PC y
generación, con todas sus lanes vivas activas. La liberación de un grupo se
publica simultáneamente al flanco siguiente a observarlo completo. Memoria
previa ya está confirmada porque no puede emitirse BAR con un load/store del
mismo warp pendiente. EXIT puede reducir los participantes de una barrera.

## Contadores y trazas

Los contadores miden ciclos completos desde el arranque del modelo. No incluyen
inicialización RF/SDRAM ni ciclos posteriores a la parada. No hacen wrap a 32
bits. `retired` cuenta instrucciones de **warp**, incluido BAR al llegar,
HALT/EXIT y memoria al completar; nunca errores ni mantenimiento.

| Campo JSON | Unidad y punto de muestreo |
|---|---|
| `cycles`, `issued`, `retired`, `cancelled` | Reloj, reservas S, commits, tokens cancelados por fallo. Invariante: issued = retired + cancelled + pendientes. |
| `cpi` | cycles / retired; null si no hay retiros. |
| `lane_ops` | Suma de popcount de la máscara original en cada retiro. |
| `occupancy` / `stage_utilization` | Ciclos con registro válido al principio del ciclo / fracción de ciclos. |
| `x_utilization`, `multicycle` | Ocupación X / ciclos X de operaciones cuya latencia es mayor que 1, por mnemónico. |
| `stall_x` | D no puede avanzar por X ocupada o por orden del camino especial→W. |
| `stall_no_warp` | S tiene hueco, pero ningún warp es elegible en el estado anterior. |
| `stall_lsu_full` | D tiene memoria, pero no hay slot en el estado anterior. |
| `wait_mem_cycles` | Ciclos con al menos un warp en LSU. |
| `lsu_occupancy` | Suma de slots ocupados por ciclo, incluida respuesta retenida. |
| `lsu_busy` | Ciclos de servicio de memoria, excluye espera RF. |
| `lsu_transactions` | Transacciones que empiezan servicio, no peticiones encoladas ni lanes. |
| `stall_fetch` | Ciclos F esperando respuesta, excluye espera de I. |
| `imem_hits`, `imem_misses` | Una cuenta por fetch, incluso si luego se cancela por otro fallo. |
| `writeback_collisions` | Ciclos con escritura W y escritura LSU pendientes simultáneamente. Incluye respuesta LSU retenida. |
| `response_arrival_collisions` | Respuestas nuevas de load que encuentran el puerto ocupado al llegar. |
| `stall_writeback` | Ciclos adicionales de retención de respuesta LSU por el puerto RF. En esta política coincide con writeback_collisions. |
| `simultaneous_completions` | Ciclos con dos retiros efectivos y sin colisión RF. |
| `instructions` | Distribución de instrucciones retiradas por mnemónico. |

Los stalls pueden solaparse: **no deben sumarse como partición del tiempo**.
`CYCLES`, `RETIRED`, `LANE_OPS`, `IMEM_HITS/MISSES` y `LSU_TX` tienen equivalentes
conceptuales RTL. `STALL_MEM` del RTL observa una interfaz concreta del fabric;
no se equipara automáticamente con ninguno de los contadores de espera aquí.

La traza JSONL transmite un snapshot del estado anterior al flanco y eventos
de ese ciclo: issue, advance, fetch_hit/miss, stall, lsu_issue,
memory_transaction, lsu_response, retire, fault, reconverge y barrier_release.
Cada token tiene serial, warp, PC, instrucción y máscara. `retire` incluye
escrituras RF, stores y PC/máscaras siguientes. `lsu_response` incluye los datos
retenibles. `--trace-from`/`--trace-cycles` limitan la salida sin cambiar el
reloj. No se acumulan trazas en RAM si no lo pide expresamente el consumidor.

## Validación y límites de comparación

Los programas sin carreras deben concordar arquitectónicamente con el funcional
en su repertorio común. Programas con carreras entre warps pueden observar
resultados distintos por su diferente planificación; FIFO y puntos de visibilidad
están fijados arriba. Las extensiones se comparan con MiniCPU, no se atribuyen
capacidades inexistentes al funcional GPU. La comprobación futura con RTL debe
alinear configuración, arbitraje, puntos de commit y latencias: los resultados
actuales validan el modelo, **no certifican todavía un RTL segmentado**.
