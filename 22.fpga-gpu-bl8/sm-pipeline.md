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

`PICK` hoy mezcla planificación con cierre de operaciones de memoria y barreras.
En la propuesta eso se separa: la **retirada de respuestas de la LSU y la
liberación de barreras pasan a una unidad de cierre independiente** que corre en
paralelo y solo toca `wait_mem`/`wait_bar`/`pc`. No compite por el cauce.

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
dura 6 ciclos — la lane recorre `HALTED → FETCH_REQUEST → FETCH_WAIT → DECODE
→ EXECUTE → RETIRE` **haciendo su propio fetch**, aunque el SM ya le entregue
la instrucción.

O sea que hay **dos ciclos por instrucción tirados** en un fetch redundante
dentro de `gpu_lane.v`. Quitarlos llevaría `X` de 6 a 4 ciclos y el CPI de 6,5
a ~4,5: otro **1,4× encima del 2,5×**. Y es un cambio local, del mismo tipo que
acortar el handshake de `gpu_imem_buffer`.

Quitarlo de verdad exigiría replicar las lanes, que es multiplicar el área del
cálculo. No merece la pena mientras estén al 6% de uso.

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
