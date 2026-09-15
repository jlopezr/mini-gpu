# La LSU de `17.fpga-gpu-ram-v2`


## Estado de este documento

Las secciones **"Visión general"**, **"Entradas y salidas"**, **"El
algoritmo"** y **"Estados actuales"** describen el RTL tal como está hoy en
el árbol de trabajo de `17.fpga-gpu-ram-v2/gpu_lsu.v`:

- Pasos 1 y 2 de `docs/optimizacion.md` (arbitraje/direccionamiento en
  estados distintos, `has_pending` fuera del lazo de prioridad): aplicados.
- Paso 7 (máscara one-hot rotada, documentado ahí mismo): aplicado en el
  árbol de trabajo, **sin comitear todavía**. Funcionalmente verificado (las
  6 testbenches RTL pasan, incluidos los 32 casos diferenciales). Su efecto
  en Fmax está **a falta de confirmar con barrido de semillas** — hay uno en
  curso; el número de una sola semilla (+3,2%) no es fiable por sí solo.

La sección **"Propuesta: segmentación con solapamiento"**, al final, es
**diseño, no código**. No hay ni una línea de RTL escrita para `PICK_NEXT`,
`ADDR_NEXT` ni `READY_NEXT` — son nombres de estados propuestos para discutir
la idea, no implementación en curso. Todo lo que hay bajo ese título es
hipotético hasta que se decida construirlo.

## Visión general
La LSU (`gpu_lsu.v`) es el único punto de acceso a la SDRAM. Todo lo que toca
memoria pasa por ella, por tres puertos distintos, arbitrados internamente:

```text
                 ┌────────────┐
  gpu_sm ───────►│            │
  (vector,       │            │
   8 tags,       │            │◄──── fetch de instrucciones (gpu_sm.imem_*)
   256 bits)     │   gpu_lsu  │◄──── host/monitor (UART, byte a byte, con GPU
                 │            │      halted), ambos por el mismo puerto "aux"
                 │            │
                 └─────┬──────┘
                       │ mem_req_*/mem_done/mem_rdata (16 bits, un acceso
                       │ en vuelo, sin colas)
                       ▼
                 sdram_controller (top.v)
```

- **Puerto vectorial** (`req_*`/`rsp_*`): viene de `gpu_sm`. Hasta 8 peticiones
  en vuelo identificadas por `req_tag` (una por warp), cada una con una
  máscara de 8 bits (`req_mask`) que dice qué lanes participan, y 256 bits de
  direcciones/datos (32 bits × 8 lanes).
- **Puerto auxiliar** (`aux_*`): compartido en `gpu_system.v` entre dos
  usuarios que nunca coinciden en el tiempo — el *fetch* de instrucciones
  (cuando la GPU corre) y el acceso del *host* vía monitor/UART, byte a byte
  (cuando está `halted`). `gpu_system.v` decide cuál de los dos conecta a
  `aux_valid`/`aux_address`/etc. según `halted`; la LSU no sabe cuál es.
- **Puerto de memoria** (`mem_req_*`/`mem_done`/`mem_rdata`): hacia
  `sdram_controller`, cableado 1:1 en `top.v`. Es un canal único, sin colas:
  una petición de 16 bits en vuelo cada vez.

## Entradas y salidas

| Puerto | Dirección | Ancho | Qué es |
| --- | --- | --- | --- |
| `clk`, `reset` | in | 1 | Reloj y reset (dominio único, el de la SDRAM) |
| **Vectorial (hacia `gpu_sm`)** | | | |
| `req_valid` / `req_ready` | in / out | 1 | Handshake de aceptación de una nueva petición vectorial |
| `req_tag` | in | 3 | Warp que pide (0-7), identifica el slot |
| `req_mask` | in | 8 | Qué lanes participan |
| `req_write` | in | 1 | 0=load, 1=store |
| `req_address` | in | 256 | 8 direcciones de 32 bits, una por lane |
| `req_data` | in | 256 | 8 datos de 32 bits, una por lane (solo store) |
| `rsp_valid` / `rsp_ready` | out / in | 1 | Handshake de respuesta vectorial completa |
| `rsp_tag` | out | 3 | Warp al que corresponde la respuesta |
| `rsp_data` | out | 256 | Datos leídos, una por lane (solo load) |
| `rsp_error` | out | 8 | Bit de fault por lane (fuera de rango) |
| `occupied` | out | 8 | Alias de `busy`: qué slots siguen en vuelo |
| **Auxiliar (fetch u host, mutuamente excluyentes)** | | | |
| `aux_valid` / `aux_ready` | in / out | 1 | Handshake de aceptación |
| `aux_address` | in | 32 | Dirección de 32 bits |
| `aux_write_data` | in | 32 | Dato a escribir |
| `aux_strobe` | in | 4 | Máscara de bytes (0 = lectura) |
| `aux_rsp_valid` / `aux_rsp_ready` | out / in | 1 | Handshake de respuesta |
| `aux_read_data` | out | 32 | Dato leído |
| `aux_error` | out | 1 | Fault (fuera de rango) |
| **Memoria (hacia `sdram_controller`)** | | | |
| `init_done` | in | 1 | La SDRAM ya salió de secuencia de arranque |
| `mem_req_valid` / `mem_req_ready` | out / in | 1 | Handshake de un acceso de 16 bits |
| `mem_req_write` | out | 1 | 0=lectura, 1=escritura |
| `mem_req_addr` | out | 24 | Dirección de palabra de 16 bits |
| `mem_req_wdata` / `mem_req_wmask` | out | 16 / 2 | Dato y máscara de bytes a escribir |
| `mem_done` | in | 1 | Pulso: el acceso terminó (con `rdata` válido si era lectura) |
| `mem_rdata` | in | 16 | Dato leído |

## El algoritmo

Es un **planificador round-robin de dos niveles** sobre un recurso único
(un solo acceso de 16 bits en vuelo hacia la SDRAM):

1. **Nivel warp.** 8 slots (uno por `req_tag`), cada uno con `busy[i]`
   (petición en vuelo) y `pending[i][0:7]` (qué lanes de ese warp siguen sin
   servir). Un registro `cursor` marca por dónde va la ronda. Cada ciclo en
   `IDLE`, se calcula `pick`: el primer warp `busy` y con trabajo pendiente
   (`has_pending[i]`, o sin ella si aún no se ha emitido la respuesta:
   `!rsp_valid`), empezando a mirar en `cursor` y dando la vuelta. Desde el
   paso 7, esto es una máscara plana `eligible` rotada por `cursor` más un
   priority encoder fijo, en vez de una cadena de comparadores indexados por
   `cursor+k`.
2. **Nivel lane.** Dentro del warp elegido (`pick`), otra prioridad de 8 vías
   sobre `pending[pick]` para elegir la siguiente lane a servir (`lane_pick`).
3. **Transferencia.** La lane elegida se sirve con **dos accesos de 16 bits**
   a la SDRAM (`SEND_LOW`→`WAIT_LOW`→`SEND_HIGH`→`WAIT_HIGH`), porque el
   controlador está configurado a ráfaga BL1 (un acceso = una palabra de 16
   bits con precarga automática).
4. **Cursor de grano fino.** Tras servir **una sola lane**, `cursor<=selected+1`.
   El round-robin es por lane, no por warp completo: no se drena un warp
   entero antes de mirar el siguiente, se entrelaza. Esto reparte la latencia
   de forma justa entre warps en vez de dejar que uno acapare el puerto.
5. **Cierre.** Cuando un warp se queda sin lanes pendientes
   (`lane_found=0`), se forma `VECTOR_RESPONSE` con los 256 bits acumulados
   lane a lane en registros `words[]` (uno por lane, escrito bajo demanda
   conforme cada lane termina).
6. **Auxiliar con turnos alternos.** El puerto auxiliar (fetch/host) compite
   por el mismo canal de memoria que el vectorial. `take_aux = aux_valid &&
   (prefer_aux || !found)`: si no hay ningún warp vectorial listo, gana aux
   siempre; si los hay, se alterna con `prefer_aux`, que se pone a 1 tras
   servir un vectorial y a 0 tras servir aux — así ninguno de los dos
   acapara el puerto indefinidamente si ambos piden constantemente.

## Estados actuales

| Estado | Código | Qué hace |
| --- | --- | --- |
| `IDLE` | 0 | Combinacional: calcula `pick` (warp) y `lane_pick` (lane) del ciclo. Si gana aux (`take_aux`), registra la dirección/dato auxiliares y decide entre `AUX_RESPONSE` (fault) o `SEND_LOW`. Si gana un vectorial (`found`), registra `selected`/`selected_lane` y pasa a `SELECT` (o directo a `VECTOR_RESPONSE` si el warp ya no tenía lanes pendientes). |
| `SELECT` | 7 | Lee `addresses[selected][selected_lane]`/`values[...]` con el índice ya registrado (evita encadenar el mux de 2048→32 bits tras la prioridad). Si la dirección está fuera de rango, marca fault y vuelve a `IDLE`; si no, registra `word_address`/`word_data`/`word_strobe` y pasa a `SEND_LOW`. |
| `SEND_LOW` | 1 | Presenta la mitad baja de la palabra al controlador SDRAM (`mem_req_valid`); espera `mem_req_ready`. |
| `WAIT_LOW` | 2 | Espera `mem_done` de la mitad baja; captura `low_data` si es lectura. |
| `SEND_HIGH` | 3 | Presenta la mitad alta. |
| `WAIT_HIGH` | 4 | Espera `mem_done` de la mitad alta. Si el dueño era aux, forma `aux_read_data` y pasa a `AUX_RESPONSE`; si era vectorial, marca la lane como servida (`pending[selected][selected_lane]<=0`), avanza `cursor` y vuelve a `IDLE`. |
| `AUX_RESPONSE` | 5 | Sostiene `aux_rsp_valid` hasta que el receptor (fetch u host) hace `aux_rsp_ready`; vuelve a `IDLE`. |
| `VECTOR_RESPONSE` | 6 | Forma `rsp_data`/`rsp_error` con los 256 bits acumulados, sostiene `rsp_valid`, avanza `cursor` y vuelve a `IDLE`. |

Todo es estrictamente secuencial: mientras una lane está en
`SEND_LOW..WAIT_HIGH` (unos 12 ciclos por palabra de 32 bits, sumando la
latencia de activación/CAS/precarga de la SDRAM en cada mitad), no se arbitra
nada más. El único trabajo que se solapa con la espera de memoria es ninguno:
`IDLE`/`SELECT` (2 ciclos de arbitraje y lectura de dirección) se pagan **en
cada frontera de lane**, aunque el resultado de esa arbitración no depende de
nada que cambie durante la transferencia en curso.

## Propuesta: segmentación con solapamiento

La idea: mientras una lane está siendo transferida (`SEND_LOW..WAIT_HIGH`,
~12 ciclos), preparar la siguiente en la sombra, para que al terminar la
transferencia actual se pueda saltar directamente a `SEND_LOW` sin volver a
pasar por `IDLE`/`SELECT`. Esto no es una mejora de Fmax (como los pasos 1 y
7): es una mejora de **caudal** — menos ciclos totales para drenar N lanes
pendientes.

### Nuevos estados (una segunda "vía" que corre en paralelo a la principal)

La FSM principal (`SEND_LOW`..`WAIT_HIGH`) no cambia. Se añade un pequeño
proceso independiente, con su propio registro de 2 bits, que avanza mientras
la vía principal está ocupada:

| Estado nuevo | Qué hace | Cuándo corre |
| --- | --- | --- |
| `PICK_NEXT` | Igual que la parte de `IDLE` que calcula `pick`/`lane_pick`, pero para la *siguiente* transacción, sin tocar `selected`/`selected_lane` (los de la transacción en curso). | Tan pronto como la vía principal entra en `SEND_LOW` de una transacción vectorial. |
| `ADDR_NEXT` | Registra `next_selected`/`next_selected_lane`, y al ciclo siguiente lee `addresses[next_selected][...]`/`values[...]`, comprueba rango. | Justo después de `PICK_NEXT`, en paralelo con `WAIT_LOW`/`SEND_HIGH` de la transacción actual. |
| `READY_NEXT` | La siguiente transacción ya está lista: `next_word_address`/`next_word_data`/`next_word_strobe`/`next_fault` precalculados, esperando a ser promovidos. | Desde que `ADDR_NEXT` termina hasta que se promueve. |

Con ~12 ciclos de margen por transacción y 2-3 ciclos de trabajo para esta vía
paralela, sobra tiempo de sobra salvo en los casos frontera que se listan
abajo como *stalls* iniciales.

### Promoción al terminar

En `WAIT_HIGH`, cuando `mem_done` cierra la transacción actual, en vez de
volver siempre a `IDLE`:

- Si `READY_NEXT` está listo y sin fault: `selected<=next_selected;
  selected_lane<=next_selected_lane; word_address<=next_word_address; ...;
  state<=SEND_LOW` directamente. Se ahorran los 2 ciclos de `IDLE`+`SELECT`
  en cada frontera de lane.
- Si `READY_NEXT` tiene fault: mismo tratamiento que hoy en `SELECT`
  (marcar error, avanzar cursor, volver a `IDLE` para re-arbitrar desde cero
  en vez de encadenar faults).
- Si `READY_NEXT` no está listo (casos frontera de abajo): cae al camino de
  hoy, `IDLE`.

### Bypass que hace falta — y el que se puede evitar

El riesgo de solapar es leer un registro (`has_pending`, `cursor`) *antes* de
que la transacción en curso termine de actualizarlo. Hay un caso real y uno
que se puede esquivar sin bypass:

- **Se puede esquivar sin bypass:** que `PICK_NEXT` elija el **mismo warp**
  que está en curso (`candidate==selected`). Ese candidato depende de
  `pending_after_lane`, que no se comete hasta que `WAIT_HIGH` cierra — leer
  el registro `has_pending[selected]` en ese momento daría un valor
  desactualizado. La salida fácil: **excluir `selected` de la ronda de
  `PICK_NEXT`** mientras la transacción está en curso. No cuesta apenas nada,
  porque el propio diseño ya reparte por lane (`cursor<=selected+1`), así que
  volver a elegir el mismo warp dos veces seguidas ya era el caso menos
  probable del round-robin, no el común.
- **No hace falta bypass, solo se pierde una oportunidad:** una petición
  vectorial que llega (`req_valid && req_ready`) en el mismo ciclo en que
  `PICK_NEXT` la necesitaría ver, no es visible hasta el ciclo siguiente
  (mismo comportamiento que ya tiene `IDLE` hoy). No es un bug, solo significa
  que esa ronda de `PICK_NEXT` no la contempla y hay que esperar a la
  siguiente — coste aceptable, no rompe nada.

### Stalls iniciales (para no complicar la primera versión)

Casos que, en vez de resolverse con más lógica, simplemente **no se
solapan** y caen al camino de hoy (`IDLE`/`SELECT` sin atajos):

1. **El propio candidato es `selected`** (arriba). Sin bypass en v1; se
   revisita más adelante si el perfil de tráfico lo justifica.
2. **El puerto auxiliar (fetch/host) también quiere el turno.** En v1,
   `PICK_NEXT` solo especula sobre el camino vectorial; si al promover
   resulta que `aux_valid` debería haber ganado (por `prefer_aux`/`!found`),
   se descarta la especulación y se entra por `IDLE` como hoy. El aux es
   comparativamente poco frecuente frente al drenado de lanes de un load/store
   vectorial, así que no vale la pena duplicar la lógica de arbitraje aux
   dentro de la vía paralela todavía.
3. **La transacción en curso hace fault en `SELECT`.** Ese camino ya vuelve a
   `IDLE` en 1 ciclo (no hay 12 ciclos de SDRAM que aprovechar), así que no
   merece la pena arrancar `PICK_NEXT` para ella.
4. **Arranque en frío** (primera transacción tras reset, o justo tras un
   `AUX_RESPONSE`): no hay transacción en curso de la que colgar la
   especulación, así que la primera de cada ráfaga siempre paga `IDLE`+`SELECT`
   normal; el ahorro empieza a partir de la segunda lane en adelante.

### Qué se gana

Para un load/store vectorial típico con varias lanes pendientes del mismo
warp o de varios, el coste por lane baja de "12 ciclos de transferencia + 2
de arbitraje" a "12 ciclos de transferencia" a secas (arbitraje escondido
detrás de la espera de SDRAM), salvo en las fronteras de los 4 casos de
arriba. Es una mejora de caudal independiente de la de Fmax — se pueden hacer
las dos: primero esto (más estados, mismo camino crítico por transacción o
incluso más corto al quitar trabajo de `IDLE`), y sobre esa base seguir
aplicando los cambios de Fmax ya identificados (partir warp/lane, EBR para
`addresses`/`values`).
