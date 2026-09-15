# Propuesta: segmentar el cauce del SM

Documento de diseño. **Nada de esto está implementado.**

El perfil (`profiling.md`) dice que el SM tarda **17,6 ciclos por instrucción de
warp** con el fetch acertando el 100% y cero stalls de memoria, y que las ocho
ALU de lane están paradas el **94% del tiempo**. El hardware de cálculo ya está
ahí, pagado en LUT; lo que falta es alimentarlo.

## Lo que hay hoy

`gpu_sm.v` es **una sola máquina de estados con un solo `current`**. Recorre
once estados por instrucción y no vuelve a `PICK` hasta retirar, así que en
todo momento hay como mucho una instrucción viva en toda la GPU.

| Estado | Qué hace | Ciclos |
| --- | --- | --- |
| `PICK` | Planificación y tareas de cierre, todo junto: retira respuestas de la LSU, libera barreras, detecta reconvergencia pendiente, y elige el siguiente warp ejecutable por round-robin sobre `live && !wait_mem && !wait_bar`. Fija `current`. | 1 |
| `CONTEXT` | `context_pc <= pc[current]`: lee el PC del warp elegido del array por warp. | 1 |
| `RECON` | Reconvergencia SIMT: si toca, saca una entrada de la pila (restaura máscara y PC) y vuelve a `CONTEXT`. Si no, sigue. | 1, o más si desapila |
| `FETCH` | `sequential_pc <= context_pc+4` y handshake con el bufer de instrucciones. | 1 |
| `FETCH_WAIT` | Espera `imem_rsp_valid` y latchea `instruction`. | 1 (eran 3 antes de acortar el handshake) |
| `RF_WAIT` | Calcula `target` y `branch_target` desde el inmediato. Existe sobre todo para cubrir la latencia de lectura del banco de registros, que es registrado. | 1 |
| `DECODE` | Decodifica. `SSY`, `BAR` y `EXIT` se resuelven aquí mismo; `LOAD`/`STORE` van a `MEMORY`; el resto pone `done <= ~active` y sigue. | 1 |
| `START` | Lanza las lanes (`step_request`). | 1 |
| `EXEC` | Espera a que todas las lanes activas señalen `lane_retired`. Multiciclo en `MUL` (4), desplazamientos (uno por bit) y `DIV`. | 1 o más |
| `FINISH` | Resolución de saltos y divergencia: empuja o saca de la pila de caminos, calcula el PC siguiente. | 1 |
| `RETIRE` | Contadores, y vuelta a `PICK`. | 1 |
| `MEMORY` | Solo `LOAD`/`STORE`: entrega la petición a la LSU, marca `wait_mem[current]` y vuelve a `PICK`. La respuesta se retira después, en `PICK`. | 1 |

Mínimo para una instrucción de ALU: **11 ciclos**. Medido: 17,6 de media, y la
diferencia son los `EXEC` multiciclo, las vueltas extra de `RECON` y el trabajo
de `PICK`.

## Qué se puede solapar y qué no

Antes de proponer etapas, conviene saber qué recursos son únicos.

| Recurso | ¿Replicado por warp? | Consecuencia |
| --- | --- | --- |
| `pc[w]`, `active[w]`, `live[w]`, pila SIMT | Sí, ya son arrays | No estorban |
| `context_pc`, `sequential_pc`, `instruction`, `target`, `branch_target`, `done` | **No, copia única** | Tienen que pasar a ser registros de etapa |
| Las 8 `gpu_lane` | **No** | Solo un warp puede estar ejecutando: riesgo estructural |
| Banco de registros | 2 puertos de lectura, 1 de escritura, direccionados por `{current, r}` | Ver abajo |

El banco de registros parecía el problema gordo, pero no lo es: la lane
**latchea sus operandos en un solo ciclo**

```verilog
// gpu_lane.v, STATE_DECODE
operand_a <= register_a;
operand_b <= register_b;
```

así que los puertos de lectura solo hacen falta durante el primer ciclo de la
ejecución. Después quedan libres para que otro warp lea los suyos.

## La propuesta: seis etapas

| Etapa | Qué hace | Registros de etapa que produce |
| --- | --- | --- |
| **S** — Schedule | Elige warp ejecutable (round-robin sobre `live && !wait_mem && !wait_bar && !in_flight`), marca `in_flight[w]`, y lee `pc[w]`. | `warp`, `pc` |
| **F** — Fetch | Presenta la dirección al bufer de instrucciones. | `warp`, `pc`, `seq_pc = pc+4` |
| **I** — Instruction | Captura la instrucción (el bufer ya la entrega registrada) y calcula `target` y `branch_target`. | `+ instruction, target, branch_target` |
| **D** — Decode | Decodifica y emite la lectura del banco de registros (`{warp,ra}`, `{warp,rb}`). Resuelve aquí mismo `SSY`/`BAR`/`EXIT`, y desvía `LOAD`/`STORE` a la LSU. | `+ opcode, rd, control` |
| **X** — Execute | Las lanes latchean operandos y ejecutan. **Longitud variable**: 1 para ALU simple, 4 para `MUL`, N para desplazamientos. | `+ resultados` |
| **W** — Writeback | Resolución de salto y divergencia, actualización de `pc[w]` y `active[w]`, pila SIMT, contadores. Limpia `in_flight[w]`. | — |

Seis etapas en vez de once estados, y **solapadas**: mientras el warp A está en
X, el B puede estar en D, el C en I, el D en F y el E en S.

### Cómo mapea cada estado de hoy

| Hoy (14 estados) | Mañana | Qué pasa con él |
| --- | --- | --- |
| `INIT` | — | Bucle de 256 ciclos al reset. Fuera del cauce, no cambia |
| `PICK` *(elegir warp)* | **S** | Se queda, más `in_flight[w]` |
| `PICK` *(retirar LSU, liberar barreras)* | — | **Sale del cauce**: unidad de cierre |
| `NORMALIZE` (+ su `CONTEXT`) | — | **Sale del cauce**: mantenimiento de reconvergencia |
| `CONTEXT` | **S** | Leer `pc[w]` es parte de elegir |
| `RECON` | — | A la unidad de cierre |
| `FETCH` | **F** | 1:1 |
| `FETCH_WAIT` | **I** | 1:1 |
| `RF_WAIT` | **I** + **D** | `target`/`branch_target` a I; la latencia del banco la cubre D→X |
| `DECODE` | **D** | 1:1 |
| `MEMORY` | **D** | El desvío a la LSU se decide en el decode |
| `START` | **D→X** | Deja de ser estado: es la frontera entre etapas |
| `EXEC` | **X** | 1:1, sigue multiciclo |
| `FINISH` | **W** | 1:1 |
| `RETIRE` | **W** | Se fusiona con `FINISH` |

Tres avisos para no leer mal la tabla:

- **No es una mejora de latencia.** Una instrucción suelta tarda casi lo mismo.
  Lo que cambia es que hoy esos ciclos son *exclusivos* —el SM no vuelve a
  `PICK` hasta retirar— y mañana se solapan entre warps.
- **Lo que más gana no es lo que se fusiona, es lo que se va.** Ver abajo.
- **La longitud de `X` no la fija el SM**, la fija la lane: cuatro ciclos
  (`HALTED→DECODE→EXECUTE→RETIRE`) para una ALU simple. Por eso el modelo de
  `24.gpu-sim-pipeline` tiene `exec_base` separado de `pipe_front`.

`PICK` hoy mezcla planificación con cierre de operaciones de memoria y barreras.
En la propuesta eso se separa: la **retirada de respuestas de la LSU y la
liberación de barreras pasan a una unidad de cierre independiente** que corre en
paralelo y solo toca `wait_mem`/`wait_bar`/`pc`. No compite por el cauce.

Lo que hace esto medible es el ORDEN de esas tareas. En `gpu_sm.v` la cadena de
`else if` de `PICK` pone primero retirar la respuesta de la LSU, luego liberar
barreras, luego `normalize_found`, y **elegir warp es la última**: cada ciclo
que hay algo que cerrar, no se elige a nadie. `NORMALIZE` es el caso extremo —
se lleva además un `CONTEXT` de ida y vuelve a `PICK` sin haber ejecutado nada.

Ahí es donde hay que mirar primero para explicar los ~1,3 ciclos por
instrucción que el modelo de costes de `23.gpu-sim-uarch` no reproduce.

## La decisión que lo simplifica todo: una instrucción en vuelo por warp

`S` no elige un warp que ya tenga una instrucción en el cauce (`in_flight[w]`).

Parece una restricción y es la clave del diseño, porque **elimina de golpe las
dos familias de riesgos**:

- **RAW entre instrucciones del mismo warp: imposible.** La instrucción `i+1`
  de un warp no entra en `S` hasta que la `i` ha pasado por `W`. Cuando `D` lee
  el banco de registros, la escritura anterior de ese warp ya está hecha.
  **No hacen falta bypasses de registros.**
- **Riesgo de control: imposible.** El PC se resuelve en `W`, y el warp no se
  vuelve a elegir hasta entonces. Nunca se busca por un PC especulativo.
  **No hace falta predicción de saltos ni descartar instrucciones.**

Es el compromiso clásico de un procesador *barrel*, y encaja especialmente bien
aquí: con 8 warps y 6 etapas, hay warps de sobra para llenar el cauce sin que
ninguno tenga dos instrucciones dentro.

Lo que se pierde: **un warp solo no se acelera**. Si solo hay un warp
ejecutable, sigue costando las 6 etapas por instrucción. Mejor que 17,6, pero
sin solapamiento. El rendimiento pleno necesita ≥6 warps ejecutables.

## Stalls

Con lo anterior, los únicos stalls que quedan son estos.

### 1. `X` ocupada — estructural, inevitable

Las 8 lanes son un recurso único. Si `X` está ejecutando un `MUL` de 4 ciclos,
`D` no puede entregar la siguiente instrucción y el cauce se para aguas arriba.

**Es el límite duro del diseño**: el caudal no puede bajar de la ocupación media
de `X`.

Aquí estimé a ojo "2-4 ciclos, o sea 5-6×", y **el modelo de ciclos de
`23.gpu-sim-uarch` dice que son 2,5×**, no 5-6. La razón es concreta y no la vi:
con el front-end segmentado, `X` queda ocupada el **83%** del tiempo, porque
duraba 6 ciclos — la lane recorría `HALTED → FETCH_REQUEST → FETCH_WAIT →
DECODE → EXECUTE → RETIRE` **haciendo su propio fetch**, aunque el SM ya le
entregara la instrucción.

Eran **dos ciclos por instrucción tirados**, y ya están quitados
(`gpu_lane #(.EXTERNAL_FETCH(1))`). Con `X` en 4 ciclos el modelo da ahora
**CPI 4,75 y X ocupada el 77,0%**, con 38 ciclos de burbuja en todo el frame.

#### ¿Y las instrucciones largas paran a las demás etapas?

Sí: `X` es recurso único, así que un `MUL` de 4 ciclos deja quietas a S/F/I/D.
La pregunta útil es cuánto cuesta. Mismo frame, variando **solo** el coste de
las operaciones largas:

| variante | ciclos | CPI | X ocupada |
| --- | --- | --- | --- |
| tal cual (MUL 4, shift 1 bit/ciclo) | 721 750 | **4,75** | 77,0% |
| MUL de 1 ciclo | 672 761 | 4,43 | 75,3% |
| shift de 1 ciclo | 698 695 | 4,60 | 76,2% |
| los dos de 1 ciclo | 649 710 | **4,28** | 74,4% |

**El multiciclo cuesta un 10%.** Lo que domina no es que `MUL` tarde 4 de vez
en cuando, sino que `X` tarda 4 en **toda** instrucción, incluido un `ADD`: eso
solo ya fija CPI ≈ 4. Las etapas de un ciclo no son el cuello — solo tienen que
mantener `X` alimentada, y con 8 warps lo consiguen de sobra.

El bloqueo además es **barato de implementar**: con una instrucción en vuelo
por warp no hay riesgos de datos ni de control, así que `X` ocupada se resuelve
con contrapresión pura, sin vaciados ni repeticiones. Y como `X` no está
segmentada, dentro solo hay una instrucción: no pueden acabar desordenadas.

Para pasar de ~3,4× hay que tocar `X`, no el front-end: acortar más la lane,
segmentar `X`, o replicar lanes — y esto último multiplica el área del cálculo
para unas unidades que hoy están al 6% de uso.

#### Coste en `X` de cada instrucción

Contado en estados de `gpu_lane.v`. La columna es lo que ocupa el recurso
único, que es lo que fija el caudal.

| Instrucción | Op | Ciclos `X` | Camino en la lane |
| --- | --- | --- | --- |
| `NOP` `ADD` `SUB` `AND` `OR` `XOR` | 00-06 | **4** | HALTED→DECODE→EXECUTE→RETIRE |
| `MOVI` `ADDI` `ANDI` `ORI` `XORI` `MOVHI` | 10-17 | **4** | ídem |
| `GETTID` | 30 | **4** | ídem |
| `BRA` | 2F | **5** | + BRANCH_COMMIT |
| `SHL` `SHR` `SAR` | 07-09 | **n+5** (5…36) | + SHIFT_STEP×n + SHIFT_WRITE, `n = rb[4:0]` |
| `BEQ` `BNE` `BLT` `BGE` `BLTU` `BGEU` | 20-25 | **6** | + BRANCH_COMPARE + BRANCH_COMMIT |
| `MUL` `MULFX` | 0A, 03 | **8** | + PRODUCTS + CROSS + COMBINE + WRITE |
| `DIV` | 0C | **37** | + DIV_STEP×32 + MUL_WRITE |
| `TRAP` | 3E | 3, no retira | para con error |

Y las que **no pisan las lanes**, resueltas en el `DECODE` del SM, que por tanto
cuestan **0 ciclos de `X`**:

| Instrucción | Op | Coste hoy |
| --- | --- | --- |
| `SSY` `BAR` `EXIT` `HALT` | 31-33, 3F | 7 ciclos, retira en `DECODE` |
| `LOAD` `STORE` | 15, 16 | 8 ciclos de SM + latencia de memoria (solapable) |

Que un `LOAD` no bloquee `X` **en absoluto** es importante: la respuesta de la
LSU escribe el banco de registros directamente (`response_commit` en
`gpu_sm.v`), sin pasar por la lane. Por eso los programas con mucha memoria no
sufren el cuello de `X`.

Hoy el total por instrucción es `X + 10` (ocho estados de `PICK`…`START` más
`FINISH` y `RETIRE`): un `ADD` son 14 ciclos, un `MUL` 18, una división 47.
Segmentado, esos 10 se solapan y en serie solo queda la columna `X`.

Aviso: el ensamblador acepta `MULHI`, `DIVU`, `REM`, `REMU`, los accesos de byte
y media palabra, `SLT`/`SLTU` y `JAL`/`JALR`/`JR`, que **este core no
implementa** — caen en el `default` de `gpu_lane.v` y dan
`ERROR_INVALID_OPCODE`. Es el conjunto que traerá el core nuevo.

#### Reparto real: ¿de qué sirve acortar `X`?

Un frame de `plasma_nommio.asm`, contando instrucciones ejecutadas:

| instr | veces | % instr | ciclos `X` | % de `X` | `X` c/u |
| --- | --- | --- | --- | --- | --- |
| `ADD` | 72 016 | 47,4% | 288 064 | 41,0% | 4,0 |
| `ADDI` | 21 136 | 13,9% | 84 544 | 12,0% | 4,0 |
| `MUL` | 16 328 | 10,8% | 130 624 | 18,6% | 8,0 |
| `XOR` | 9 600 | 6,3% | 38 400 | 5,5% | 4,0 |
| `ANDI` | 9 600 | 6,3% | 38 400 | 5,5% | 4,0 |
| `SHR` | 6 728 | 4,4% | 56 696 | 8,1% | 8,4 |
| `BNE` | 4 808 | 3,2% | 28 848 | 4,1% | 6,0 |
| `STORE` | 4 800 | 3,2% | 0 | 0,0% | 0,0 |
| `BLT` | 4 800 | 3,2% | 28 800 | 4,1% | 6,0 |
| `SUB` | 1 920 | 1,3% | 7 680 | 1,1% | 4,0 |
| resto | 144 | 0,1% | 416 | 0,1% | — |
| **TOTAL** | **151 880** | 100% | **702 472** | 100% | **4,6** |

**El 75% de las instrucciones cuestan 4 ciclos**, y son el 65% de todo el
tiempo de `X`. Así que sí: el caso común manda.

#### Colapsar antes que segmentar

La conclusión tentadora es partir `X` en `X1 X2 X3 X4` y emitir una por ciclo.
Pero esos cuatro ciclos **no son cuatro etapas de un cálculo**:

| Ciclo | Qué hace | ¿Cómputo? |
| --- | --- | --- |
| `HALTED` | Espera `step_request` | No — handshake |
| `DECODE` | `operand_a <= register_a` | Sí, y **por timing**: rompe el camino del mux del banco al sumador de 32 bits |
| `EXECUTE` | La ALU | Sí |
| `RETIRE` | Escribe el resultado y señala retirado | Sí, pero `W` ya lo hace |

`HALTED` y `RETIRE` son **la misma redundancia que el fetch que ya quitamos**:
el SM haciendo una cosa y la lane repitiéndola. Y los saltos añaden
`BRANCH_COMPARE`+`BRANCH_COMMIT` cuando `W` ya resuelve saltos y divergencia:
otros dos ciclos duplicados, en el 6,4% de las instrucciones.

Así que el orden sensato es **colapsar primero**:

- `HALTED` desaparece — el paso `D`→`X` sustituye al handshake.
- `RETIRE` se funde en `W`, y el camino de salto también.
- Queda `DECODE`+`EXECUTE`: **`X` de 2 ciclos**.

`DECODE` es justo el que **no** hay que colapsar: existe para cortar el camino
crítico, y el Fmax está en 36,5 MHz corriendo a 25. En un cauce deja de ser "un
ciclo extra de una máquina multiciclo" —como dice el comentario del RTL— y pasa
a ser una etapa legítima de búsqueda de operandos.

Barrido del modelo variando la longitud del camino corto:

| `X` | ciclos | CPI | `X` ocupada |
| --- | --- | --- | --- |
| 4 (hoy) | 721 750 | 4,75 | 77,0% |
| 3 | 574 730 | 3,78 | 71,1% |
| 2 | 427 713 | 2,82 | 61,1% |
| 1 | 280 755 | **1,85** | 40,7% |

Y sólo **después** tiene sentido segmentar los dos restantes (operandos / ALU),
que sí es pipelining de verdad. Ahí aparece el problema nuevo: **la latencia
variable**. `MUL` son 8, los desplazamientos `n+5`, `DIV` 37 — y es el **35% de
los ciclos de `X`**. Con `X` segmentada acaban fuera de orden y chocan en la
escritura, así que hace falta arbitraje de writeback y bloquear la emisión
detrás de las largas.

| Paso | CPI | Ganancia | Coste |
| --- | --- | --- | --- |
| Hoy (medido en placa) | 15,6 | — | — |
| Segmentar el front-end | 4,75 | 3,3× | S/F/I/D/X/W + registros de etapa |
| Colapsar la lane (`X` 4→2) | 2,82 | 1,7× | quitar `HALTED`, `RETIRE` y el camino de salto |
| Segmentar `X` (2→1) | 1,85 | 1,5× | arbitraje de writeback para latencia variable |

Los dos primeros son del mismo tipo que lo ya hecho y validado. El tercero es el
único que introduce una clase de problema nueva.

### 2. No hay warp elegible — burbuja

Si todos los warps están en `wait_mem`, `wait_bar` o `in_flight`, `S` no emite y
entra una burbuja. Ocurrirá en:

- programas con pocos warps activos,
- divergencia fuerte (warps con `active==0` esperando reconvergencia),
- ráfagas de barreras, donde por definición todos esperan.

Aquí escribí que "con 8 warps y 6 etapas el margen es escaso" y que sería el
argumento más fuerte para subir el número de warps. **Medido, es falso**: el
modelo de `23.gpu-sim-uarch` da **43 ciclos de burbuja en un frame entero**.
Ocho warps sobran para llenar seis etapas con esta carga, y subir el número no
compraría nada.

Sigue siendo cierto que una carga con mucha divergencia o muchas barreras
tendría menos warps elegibles. Pero eso hay que medirlo con esa carga, no
suponerlo con esta.

### 3. Fallo del bufer de instrucciones

Hoy un fallo para todo. En el cauce pararía `F`/`I` y con ellas el resto.

Mitigación opcional, y creo que vale la pena: **tratar un fallo de fetch como se
trata hoy un acceso a memoria**. El bufer señala "fallo, voy a tardar", el warp
se marca con un `wait_imem` análogo a `wait_mem`, suelta su hueco en el cauce y
`S` elige otro. Se recupera cuando llega la línea.

Cuesta un bit por warp y algo de lógica de rearranque. Con la medida actual (17
fallos por frame) **no compraría nada**, pero con programas más grandes que no
quepan en las 16 líneas sí.

### 4. LSU llena

`lsu_ready` bajo en `D` para un `LOAD`/`STORE`. Medido hoy: `STALL_MEM = 0`, o
sea que **nunca pasa** con 8 slots vectoriales. Hay que dejar el camino, pero no
es un problema real.

## Bypasses

**Ninguno para registros ni para el PC especulativo**, por la regla de una
instrucción en vuelo por warp. Esto es lo mejor de la propuesta y conviene no
perderlo por optimizar de más.

Quedan dos colisiones menores de lectura-tras-escritura sobre el estado por
warp, y para las dos propongo **no bypassear**:

| Colisión | Bypass posible | Recomendación |
| --- | --- | --- |
| `W` escribe `pc[w]` y `S` elige ese mismo warp en el mismo ciclo | Comparador + mux del PC | **No.** Excluir el warp de `S` durante un ciclo. Con 8 warps hay otro que elegir, así que no cuesta caudal, y ahorra un camino combinacional de `W` a `S` que iría directo al camino crítico. |
| Igual con `active[w]` y la cima de la pila SIMT | Mismo patrón | **No**, por lo mismo. |

El criterio: un bypass compra un ciclo en un caso poco frecuente, y a cambio
mete un camino combinacional entre la última etapa y la primera. Con `gpu_lsu2`
ya en el camino crítico del chip, no es el momento de añadir lazos largos.

## Cómo verificarlo

El instrumental ya está puesto, así que el plan de medida es concreto:

1. **Los 32 casos diferenciales** tienen que seguir pasando. Es la red de
   seguridad: cualquier error de riesgo o de reconvergencia sale ahí.
2. **`profiling.md` da la línea base**: 2 917 419 ciclos y 166 046
   instrucciones por frame, 17,57 ciclos por instrucción.
3. El objetivo es **ciclos por instrucción ≈ ocupación media de `X`**. Si sale
   mucho peor, el sospechoso es la burbuja por falta de warps elegibles, y se
   confirma contando ciclos sin emisión en `S` — que sería un contador nuevo
   obvio para `gpu_perf_counters`.
4. En placa, `profile.py` da el antes y el después en segundos.

## Riesgo principal

No es funcional, es de **Fmax**. Hoy el camino crítico del chip está en
`gpu_lsu2` (`grp_line → n_lanes`), a 39,8 MHz. Un cauce segmentado añade muxes
de selección por etapa y lógica de control que podrían disputarle el puesto.

Conviene medirlo pronto y no al final: sintetizar en cuanto el cauce compile,
aunque no funcione todavía, solo para ver dónde queda el camino crítico.
