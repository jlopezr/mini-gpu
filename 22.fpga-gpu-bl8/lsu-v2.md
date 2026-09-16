# Propuesta: LSU v2, sobre el fabric y el controlador BL8

Este documento es una propuesta de diseño, no código. Nada de lo que hay aquí
está implementado. El objetivo es dejar de invertir en pulir
`17.fpga-gpu-ram-v2/gpu_lsu.v` (rendimientos decrecientes, ver
`docs/optimizacion.md` paso 7 y `lsu.md`) y en su lugar diseñar una LSU nueva
que se apoye en piezas que la CPU (`21.fpga-cpu-hdmi-alu`) ya tiene
construidas, medidas y validadas: `memory_fabric_4.v` y
`sdram_controller_128.v`.

## Por qué el pivote

- El paso 7 de la LSU actual (encoder one-hot rotado) dio +3,2% de Fmax
  confirmado por barrido de semillas, a cambio de +3,4% de área — una mejora
  real pero modesta, con rendimientos claramente decrecientes.
- El camino crítico del chip completo ya no vive en la LSU, vive en el SM.
- El proyecto ya resolvió, para la CPU, el mismo problema de fondo que tiene
  la GPU hoy: un canal de 16 bits BL1 compartido por varios clientes con
  arbitraje casero. La solución — fabric de 4 puertos + controlador BL8 de
  128 bits — está en producción en `18.fpga-cpu-hdmi-bl8`,
  `19.fpga-cpu-hdmi-ls` y `21.fpga-cpu-hdmi-alu`, con sus bancos de pruebas
  pasando y con lecciones de Fmax ya incorporadas (concesión registrada,
  máscara de bits altos en vez de comparador de magnitud, `urgent`
  registrado).
- El propio código del fabric reserva el puerto 1 para la GPU
  (`docs/camino-de-memoria.md` de 21: "el puerto 1 está pensado... para una
  GPU"). No hay que inventar el hueco, ya existe.

## Qué se reutiliza sin tocar

| Módulo | De dónde | Por qué no hace falta cambiarlo |
| --- | --- | --- |
| `memory_fabric_4.v` | `21.fpga-cpu-hdmi-alu/` | Árbitro de 4 puertos genérico: no sabe qué hay detrás de cada puerto. Ya tiene concesión registrada y comparación por máscara de bits altos, las dos correcciones de Fmax que a nuestra LSU le faltan. Para un sistema **sin CPU** (como `17.fpga-gpu-ram-v2`) no hace falta ensancharlo a más de 4 puertos: los 4 clientes de la GPU caben en los que ya hay (ver mapeo más abajo). |
| `sdram_controller_128.v` | `21.fpga-cpu-hdmi-alu/` | Controlador BL8, 128 bits por transacción, con máscara de byte de 16 bits — sin necesidad de lectura-modificación-escritura para escrituras parciales. Ya validado con `sdram_controller_128_tb.v`. |

Ninguno de los dos sabe nada de "warps" ni "lanes". Son piezas de transporte
genéricas — coalescencia y arbitraje quedan claramente separados, que es
justo la distinción que motivó este documento.

## Qué se reutiliza como plantilla (no verbatim)

| Módulo original | Qué hace hoy (CPU) | Qué cambia para la GPU |
| --- | --- | --- |
| `instruction_buffer.v` | Intercepta el puerto `imem` de `cpu.v` (32 bits, un acceso), lo traduce a peticiones de 128 bits contra el fabric, y cachea 4 líneas de 16 bytes de mapeo directo. | El contrato con `gpu_sm.imem_*` es **prácticamente idéntico** al de `cpu.v` (`imem_valid`/`imem_address`/`imem_rsp_valid`/`imem_data`, ver `gpu_system.v:71-73`). Candidato a reuso casi directo, cambiando el nombre de las señales del lado CPU. El único matiz: la GPU tiene 8 warps con PC independiente, así que las 4 líneas de mapeo directo pueden fallar más a menudo que con una sola CPU secuencial — a medir, no a asumir. |
| `monitor_mem_adapter_128.v` | Traduce accesos byte a byte del monitor UART a peticiones de 128 bits, y decodifica la ventana de vídeo 0x80000000 y el `wb_dirty` del buffer de combinación de la CPU. | La GPU **no tiene** buffer de combinación de escrituras (no hace falta: no hay concepto de vídeo leyendo el framebuffer por detrás en `17.fpga-gpu-ram-v2` todavía) ni la misma ventana MMIO. Sirve como **esqueleto** (pulso de un ciclo del monitor, traducción byte→máscara de 16 bits) pero hay que quitar lo específico de vídeo/CPU y enganchar el MMIO que ya decodifica `gpu_system.v` (`cfg_read_data`, `retired_count`, etc.), que además usa el mismo prefijo `0x80000` por casualidad de convención, no por acoplamiento real. |

## Lo único genuinamente nuevo: el motor de coalescencia

Esta es la LSU v2 en sentido estricto. Todo lo anterior es plomería ya
resuelta; esto es el diseño que falta.

### Interfaz sin cambios hacia `gpu_sm`

El lado `gpu_sm` no se toca: mismo protocolo con tag de hoy (`req_valid` /
`req_tag` / `req_mask` / `req_address` (256 bits) / `req_data` (256 bits),
`rsp_valid` / `rsp_tag` / `rsp_data` / `rsp_error`, 8 slots). `gpu_sm.v` no
necesita saber que cambió el backend.

### Lo que cambia es la trasera: de "una lane, un acceso BL1" a "un grupo, una ráfaga BL8"

Hoy, `gpu_lsu.v` sirve una lane a la vez con dos accesos de 16 bits (12
ciclos aprox., ver `lsu.md`). El algoritmo nuevo:

1. **Arbitraje de warp: igual que hoy.** Reutilizar tal cual el encoder
   one-hot rotado del paso 7 (`eligible`/rotar por `cursor`/priority encoder
   fijo) para elegir `pick`. No hace falta rediseñarlo, ya está medido y
   validado.
2. **Agrupar por línea de 16 bytes, no elegir una sola lane.** Del warp
   elegido, mirar `pending[pick]` y las direcciones de las 8 lanes. Agrupar
   las lanes cuya dirección cae en la misma ventana alineada a 16 bytes
   (`address[31:4]` igual) — hasta 4 lanes por grupo, porque 128 bits / 32
   bits = 4. Elegir el primer grupo no vacío (por ejemplo, el de la lane de
   menor índice pendiente).
3. **Una transacción de 128 bits por grupo:**
   - **Load:** pedir la línea completa (128 bits); al llegar la respuesta,
     repartir cada palabra de 32 bits a las lanes del grupo según su
     `address[3:2]`, limpiar `pending` solo de esas lanes.
     Las lanes fuera del grupo no se tocan.
   - **Store:** construir `wdata`/`wmask` de 128 bits colocando cada lane del
     grupo en su posición (mismo patrón `shifted_data`/`shifted_mask` que ya
     usa `cpu_dmem_adapter.v`), y emitir con la máscara — **sin leer antes**,
     igual que ya está validado ahí. Lanes fuera del grupo no participan en
     esta escritura.
4. **Tras cada grupo, volver a arbitrar** (`cursor<=selected+1`, igual
   filosofía que hoy: repartir el canal entre warps en vez de drenar uno
   entero). Si el warp elegido aún tiene lanes pendientes en otras líneas, se
   le volverá a dar prioridad en una vuelta posterior según el round-robin
   normal — no se le fuerza a terminar antes de ceder el turno.
5. **Cierre del warp:** igual que hoy — cuando `pending[pick]==0`, se forma
   `VECTOR_RESPONSE` con los datos acumulados.

### Por qué esto es la mejora real, no solo un cambio de ancho

El caso más común de una GPU SIMT — accesos coalescidos, donde las 8 lanes
piden direcciones consecutivas (`base + lane*4`) — pasa de **8 accesos** (uno
por lane, ~12 ciclos cada uno con BL1) a **2 transacciones** de 128 bits (una
por cada mitad de 4 lanes). El caso peor (direcciones dispersas, 8 líneas
distintas) sigue costando 8 transacciones, pero cada una ya no necesita el
doble acceso BL1 de hoy. Es la pieza de "coalescencia" que
`14.fpga-gpu-ram/docs/sintesis.md` señalaba desde el principio como pendiente
y que la LSU actual nunca ha tenido — hoy agrupa por *warp*, nunca por
*dirección*.

### Qué se recicla directamente del trabajo ya hecho en v1

- El encoder one-hot rotado del paso 7 (arbitraje de warp): reusar sin
  cambios, es independiente del ancho del backend.
- La idea de segmentación con solapamiento de `lsu.md` (preparar el
  siguiente grupo en la sombra mientras el actual está en la ráfaga BL8):
  sigue aplicando igual, solo que ahora esconde la latencia de una
  transacción de 128 bits en vez de una de 16 bits. Vale la pena revisar esa
  propuesta *después* de tener el motor de coalescencia funcionando, no
  antes.
- Nada del arbitraje aux/`prefer_aux`/`take_aux` se recicla: desaparece,
  sustituido por el fabric.

## Mapeo de puertos propuesto (sistema solo-GPU, sin CPU)

```text
p0  motor de coalescencia GPU (vectorial, dmem-like)
p1  buffer de fetch GPU (imem-like, adaptado de instruction_buffer.v)
p2  sin usar — reservado para vídeo/HDMI si se añade escaneo por SDRAM
p3  monitor/host (adaptado de monitor_mem_adapter_128.v)
    memory_fabric_4  ──►  sdram_controller_128
```

No hace falta ensanchar el fabric a más de 4 puertos porque este prototipo
no tiene CPU real compitiendo por la SDRAM. El día que la GPU y una CPU
convivan en el mismo sistema, esa sí es la "conversación con el reparto ya
medido" que menciona `docs/camino-de-memoria.md` — y en ese momento hará
falta un fabric de más puertos o una jerarquía de dos niveles, no antes.

## Plan de validación

1. **`memory_fabric_4.v` y `sdram_controller_128.v` no se tocan** → sus
   bancos existentes (`memory_fabric_tb.v`, `sdram_controller_128_tb.v`)
   siguen sirviendo como prueba de que esas piezas funcionan; no hace falta
   revalidarlas para la GPU.
2. **Banco de pruebas nuevo para el motor de coalescencia**, con los casos
   que `gpu_lsu_tb.v` no cubre porque no existían antes: lanes coalescidas
   (direcciones consecutivas, debe salir en 1-2 transacciones), lanes
   dispersas (una por línea, debe seguir siendo correcto aunque no gane
   nada), mezcla de ambas dentro del mismo warp, y solapamiento de dos warps
   con líneas distintas.
3. **Reusar el buffer de fetch casi tal cual**, con un banco equivalente a
   `instruction_buffer_tb.v` (si existe) adaptado a 8 PCs independientes en
   vez de uno.
4. **Medida de ciclos**, mismo método que el paso 6 de
   `docs/optimizacion.md`: correr los 32 casos diferenciales de
   `gpu_system_tb.v` antes/después y comparar la suma de ciclos, no solo el
   Fmax — aquí el objetivo principal es caudal (menos transacciones por
   warp), así que el número que importa es distinto del de los pasos 1-7.

## Estados propuestos y segmentación

Sigue siendo diseño, no código. Esta sección concreta el "motor de
coalescencia" de arriba en una máquina de estados, partiendo de la de v1
(`lsu.md`, "Estados actuales") y de la propuesta de solapamiento de v1
(`lsu.md`, "Propuesta: segmentación con solapamiento"), que aquí se rehace
sobre el backend nuevo.

### La restricción que manda: el fabric solo admite una transacción en vuelo

`memory_fabric_4.v` es un árbitro de **una transacción global** a la vez:
su FSM es `ST_IDLE → ST_ISSUE → ST_WAIT → ST_RESP` con un único
`active_master` latcheado, y no concede a nadie más hasta cerrar la actual.

Consecuencia directa para el diseño: **no se puede pipelinear la memoria**
(varias transacciones de la LSU en vuelo a la vez). Lo que sí se puede — y es
lo que propone esta sección — es pipelinear el **front-end**: arbitraje de
warp, formación de grupo y lectura de direcciones ocurren *en la sombra* de
la transacción anterior, de modo que al cerrar una ráfaga BL8 se emita la
siguiente en el ciclo siguiente, sin pagar ciclos de arbitraje en cada
frontera. Es el mismo principio que `lsu.md`, pero ahora lo que se esconde es
la latencia de una transacción de 128 bits, y lo que se prepara es un *grupo*
de lanes, no una lane suelta.

Lo que el fabric sí regala gratis respecto a v1: **desaparece todo el
arbitraje auxiliar** (`prefer_aux` / `take_aux` / `AUX_RESPONSE`). El fetch y
el monitor van por sus propios puertos del fabric, así que la LSU v2 no los
ve. La FSM se queda con un solo cliente lógico: el puerto vectorial.

### Etapas conceptuales

```text
  A  arbitrar warp      ┐
  G  formar grupo       ├── vía de preparación (en la sombra)
  R  leer direcciones   ┘
  X  emitir al fabric   ┐
  W  esperar respuesta  ├── vía principal (ocupa el canal)
  D  repartir/retirar   ┘
```

`A/G/R` cuestan ~3 ciclos; `X/W` cuesta decenas (activación + CAS + BL8 +
los 3 ciclos de la FSM del fabric). El margen es incluso mayor que en v1, así
que la vía de preparación va sobrada.

### Vía principal

| Estado | Qué hace |
| --- | --- |
| `IDLE` | No hay grupo listo ni transacción en curso. Arranque en frío: dispara la vía de preparación y espera a que llegue a `PREP_READY`. |
| `ISSUE` | Presenta la transacción de 128 bits al fabric (`req_valid`/`req_write`/`req_addr` alineada a 16 bytes/`req_wdata`/`req_wmask`); espera `req_ready`. Registra `grp_warp`, `grp_lanes` (máscara de 8 bits: qué lanes cubre este grupo) y `grp_sel[lane]` (`address[3:2]` de cada lane, para el reparto posterior). |
| `WAIT` | Espera `rsp_valid`. Captura `rsp_rdata` (128 bits) y `rsp_error`. |
| `RETIRE` | Load: reparte las 4 palabras de 32 bits a `words[grp_warp][lane]` según `grp_sel[lane]`, para cada lane de `grp_lanes`. Store: nada que repartir. En ambos casos `pending[grp_warp] &= ~grp_lanes`, `cursor <= grp_warp + 1`. Si el warp queda sin pendientes → `VECTOR_RESPONSE`. Si la vía de preparación tiene otro grupo listo → salta a `ISSUE` directamente. Si no → `IDLE`. |
| `VECTOR_RESPONSE` | Igual que en v1: sostiene `rsp_valid` con los 256 bits acumulados hasta `rsp_ready`. **Importante:** no debe bloquear la vía principal — mientras se sostiene la respuesta de un warp, otro warp puede seguir emitiendo. Ver "punto a decidir" abajo. |

`RETIRE` puede fusionarse con el ciclo de `rsp_valid` si el camino crítico lo
permite; se deja como estado separado en la primera versión porque el reparto
(mux de 4→1 por lane, 8 lanes) no es trivial y encadenarlo con la lógica de
`ISSUE` del siguiente grupo es justo el tipo de cadena larga que costó Fmax en
los pasos 1-7 de v1.

### Vía de preparación (registro propio de 2 bits, corre en paralelo)

| Estado | Qué hace |
| --- | --- |
| `PREP_PICK` | Encoder one-hot rotado del paso 7 sobre `eligible`: elige `nxt_warp`. Reutilizado tal cual de v1. |
| `PREP_GROUP` | Con `nxt_warp` ya registrado, lee `addresses[nxt_warp]` (8×32 bits) y forma el grupo: toma la lane pendiente de menor índice como *líder*, y añade toda lane pendiente cuyo `address[31:4]` coincida con el de la líder. Sale `nxt_lanes` (≤4 lanes, porque solo caben 4 palabras de 32 bits en 128), `nxt_addr`, `nxt_sel[]`, y las lanes fuera de rango marcadas como fault. |
| `PREP_READY` | Grupo listo y esperando promoción. Si la vía principal está en `RETIRE`/`IDLE`, se promueve y vuelve a `PREP_PICK`. |

La comparación no es "8 direcciones contra 8": es **7 comparaciones de
`address[31:4]` contra la de la líder**, en paralelo, que es barato. Luego un
recorte a las 4 primeras coincidencias, porque la línea solo tiene 4 huecos.

### El hazard, y por qué aquí se resuelve mejor que en v1

En v1 el problema era que `PICK_NEXT` no podía saber si el warp en curso
seguiría teniendo lanes pendientes, porque eso no se sabía hasta que
`WAIT_HIGH` cerraba; la salida era **excluir `selected` de la ronda**.

En v2 ese dato se conoce **antes**: `grp_lanes` queda fijado en `ISSUE`, es
decir, mucho antes de que llegue la respuesta. Así que se puede llevar un
registro especulativo:

```text
pending_spec[w] = pending[w] menos las lanes ya comprometidas a un grupo en vuelo
```

`PREP_PICK`/`PREP_GROUP` miran `pending_spec`, no `pending`. `pending` real
sigue actualizándose en `RETIRE` (es lo que decide el cierre del warp). Con
esto **no hace falta excluir el warp en curso**: un warp coalescido que
necesita 2 grupos puede encadenarlos back-to-back, que es justo el caso
común y el que más se beneficia.

El coste es un registro de 8×8 bits extra y un camino de rollback: si el
fabric devuelve `rsp_error`, hay que devolver esas lanes a `pending_spec`
(o, más simple, marcarlas como fault definitivo y no reintentarlas nunca —
que es lo que ya hace v1 con los faults de rango).

### Faults: fuera de la vía de memoria

Las lanes con dirección fuera de rango **no entran en ningún grupo**. Se
detectan en `PREP_GROUP` y se retiran ahí mismo: `pending[w] &= ~fault_lanes`,
`error[w] |= fault_lanes`, sin gastar una transacción. Esto elimina el estado
de fault de la vía principal de v1 y es estrictamente más rápido: hoy un warp
con 8 direcciones malas paga 8 vueltas de `IDLE`/`SELECT`.

### Qué stalls se aceptan en la primera versión

1. **Arranque en frío** (primer grupo tras reset o tras un hueco sin
   trabajo): paga `PREP_PICK`+`PREP_GROUP` sin solapar. Igual que en v1.
2. **Petición vectorial que llega en el mismo ciclo** en que `PREP_PICK` la
   necesitaría ver: no visible hasta el ciclo siguiente. No es un bug, solo
   una oportunidad perdida — mismo comportamiento que `IDLE` hoy.
3. **`VECTOR_RESPONSE` con `rsp_ready` bajo**: en la primera versión, si
   `gpu_sm` tarda en aceptar la respuesta, la vía principal se para. Ver la
   pregunta abierta de abajo.

### Orden de construcción sugerido

Merece la pena separarlo en dos entregas medibles, no hacerlo de golpe:

1. **v2.0 — coalescencia sin segmentación.** FSM principal
   `IDLE→PREP→ISSUE→WAIT→RETIRE`, la vía de preparación en serie (sin
   solapar). Ya se lleva la mejora grande: de 8 accesos BL1 dobles a 2
   transacciones BL8 en el caso coalescido. Es lo que hay que medir primero
   con el método del paso 6 de `docs/optimizacion.md`.
2. **v2.1 — segmentación.** Separar la vía de preparación a su propio
   registro de estado, añadir `pending_spec` y la promoción en `RETIRE`.
   Diferencia esperada: ~3 ciclos por grupo. Sobre un caso coalescido de 2
   grupos por warp eso es ruido; sobre un caso disperso de 8 grupos empieza a
   contar. **Ese reparto de ganancia es exactamente el motivo de medir v2.0
   antes de construir v2.1**: si el tráfico real resulta estar casi siempre
   coalescido, v2.1 puede no merecer la complejidad.

## Primera medida: v2.0 implementada y sintetizada en aislado

`gpu_lsu2.v` existe ya en esta carpeta (v2.0: coalescencia, sin
segmentación) y `gpu_lsu2_tb.v` pasa: load coalescido en **2 transacciones**
en vez de 8, disperso en 8, store coalescido en 2 y su relectura, máscara
parcial, faults de rango y alineación, y dos warps entrelazados.

Para responder "¿es esta lógica muy lenta?" sin tener el sistema entero
integrado, hay dos envs de síntesis en `apio.ini` que miden **la LSU sola en
un chip vacío**, vía `lsu_timing_top.v` (v2) y `lsu1_timing_top.v` (v1). Los
dos envoltorios son gemelos: un LFSR alimenta todas las entradas anchas y un
XOR registrado reduce las salidas a los LED, porque la LSU tiene ~800 bits de
E/S y la placa no tiene tantos pines.

| | Fmax aislado | TRELLIS_COMB | TRELLIS_FF | segmentos |
| --- | --- | --- | --- | --- |
| LSU v1 (`gpu_lsu.v`) | 75,92 MHz | 2682 | 632 | — |
| LSU v2.0, lazo serie | 37,52 MHz | 4260 | 792 | 57 |
| LSU v2.0, grupo en paralelo | **38,84 MHz** | 5178 | 776 | 45 |
| LSU v2.0, con el MMIO conectado | **39,78 MHz** | 5815 | 750 | — |

La última fila corrige a las anteriores. `lsu_timing_top.v` dejaba los nueve
puertos MMIO sin conectar, así que yosys podaba ese camino entero y las tres
primeras filas midieron una LSU **sin ventana MMIO**. Al cablearlos al LFSR:

- el **área sube un 12%** (5178 → 5815 LUT), que es la lógica que antes
  desaparecía sin avisar. El número publicado la infravaloraba;
- el **Fmax no se mueve** (38,84 → 39,78 MHz, por debajo del ruido de semilla).
  El MMIO no está en el camino crítico, así que la conclusión de este capítulo
  se sostiene — pero se sostenía por suerte, no porque estuviera medida.

La fila de la v1 sale idéntica a la publicada (75,92 MHz, 2682, 632), lo cual
es la comprobación de que el método es el mismo: la v1 no tiene puertos MMIO,
así que nunca hubo nada que podar.

**Estos números son de una sola semilla y no son comparables con el Fmax del
sistema completo** — la LSU está aquí sola en un chip vacío, sin competir por
rutado ni fanout con el SM, así que son optimistas por construcción. Lo que
sí es válido es la comparación entre las dos filas, que usan el mismo
envoltorio y el mismo chip. Y un factor 2 está muy por encima del ruido de
semilla que documenta `docs/optimizacion.md` (~10%).

Así que sí: **la v2.0 es, hoy, claramente más lenta que la v1 por
transacción**. Pero el camino crítico está localizado y es el esperado:

```text
dut.cand_lanes[0] → dut.n_lanes[2] → n_lanes[3] → n_lanes[5] → n_lanes[7]
57 segmentos
```

Es el bucle de formación de grupo, y es lento por una razón concreta: los
acumuladores `leader_found` y `slot_used` se propagan **lane a lane en
serie**, así que el lazo de 8 iteraciones se sintetiza como una cadena de 8
niveles. No es la coalescencia lo que es caro; es esta forma de escribirla.

Lo que esto **no** dice todavía: si importa. La v2.0 reemplaza ~12 ciclos de
dos accesos BL1 por lane por una transacción BL8 por grupo de hasta 4 lanes.
Un 50% de Fmax a cambio de 4× menos transacciones sigue siendo ganancia neta
en caudal — pero eso hay que medirlo con el sistema integrado, no deducirlo.
Además, 37,52 MHz sigue estando **por encima** de los 25 MHz del `.lpf` y del
Fmax del sistema de 17 (~37-47 MHz según semilla), o sea que la LSU podría no
llegar a ser el camino crítico del chip aunque sea el doble de lenta que la v1.

### La reescritura en paralelo: hecha, y NO funcionó

La tercera fila es el resultado de quitar las dos cadenas serie del lazo de
formación de grupo: líder por priority encoder fijo (el mismo del arbitraje de
warp) en vez de propagar un `leader_found`; dedup de slot como cuatro
prefix-OR independientes en vez de un acumulador `slot_used` recorriendo
lanes; `wdata` por mux one-hot por slot en vez de escrituras indexadas
encadenadas; y `n_sel` como pura concatenación.

Funcionalmente es equivalente (el banco pasa igual) y **la profundidad bajó de
57 a 45 segmentos**, que era justo lo que se buscaba. Pero:

- **Fmax: +3,5%.** Está dentro del ruido de semilla que documenta
  `docs/optimizacion.md` (~10%), así que con una sola semilla **no se puede
  afirmar que haya mejorado nada**.
- **Área: +21% de LUT** (4260 → 5178). Esto sí es determinista, y es una
  regresión real: los cuatro muxes one-hot y las 32 comparaciones de slot
  cuestan más que el lazo encadenado.

O sea: se pagó un 21% de área por una mejora de timing que no se distingue del
ruido. Es el mismo patrón que el paso 5 de `docs/optimizacion.md` — menos
segmentos no implica más Fmax.

**Por qué no bastó.** El camino crítico que queda sigue naciendo en el mismo
sitio, solo que más corto:

```text
dut.grp_line[0] → dut.n_lanes[7]   (45 segmentos)
```

Son tres etapas **inherentemente dependientes** dentro de un solo ciclo:
elegir líder → mux de 28 bits para sacar su línea → comparar las 8 lanes
contra ella → dedup → `n_lanes`. Paralelizar cada etapa no elimina la
dependencia *entre* etapas. Y todo eso cuelga además del mux de 2048 bits
indexado por `selected`.

### Lo que queda: partir `GROUP` en dos estados

Es el plan B que quedaba, y ahora es la opción obvia: registrar `grp_line` (y
`match`) al final de un primer ciclo, y hacer dedup, `wdata` y `wmask` en el
segundo. Eso corta la cadena en un flip-flop, que es lo único que sí rompe una
dependencia serie de verdad.

Cuesta **un ciclo por grupo** — pero en el caso coalescido eso son 2 ciclos por
instrucción vectorial frente a una transacción SDRAM de decenas de ciclos, y en
cuanto exista la segmentación de v2.1 el coste desaparece del todo, porque el
grupo se prepara en la sombra de la transacción anterior.

**Decisión pendiente antes de seguir tocando esto:** medir primero el sistema
integrado. 38,84 MHz en aislado sigue estando por encima del Fmax del sistema
de 17 (37-47 MHz según semilla), así que es perfectamente posible que la LSU no
llegue a ser el camino crítico del chip y que todo este capítulo de Fmax sea
optimización prematura. El número que falta es el de ciclos, no el de MHz.

## Sistema integrado y medido: el resultado cambia el plan entero

`gpu_system_bl8.v` + `top_bl8.v` cablean la LSU v2 y un adaptador nuevo
(`gpu_aux_adapter_128.v`, fetch/host de 32 bits → puerto del fabric) sobre
`memory_fabric_4` + `sdram_controller_128`. **Los 32 casos diferenciales
pasan** (`gpu_system_bl8_tb.v`), así que el camino nuevo es funcionalmente
correcto de punta a punta.

Y entonces, la medida de ciclos — la que de verdad importaba:

| | Ciclos, 32 casos diferenciales |
| --- | --- |
| Base (`gpu_system.v`, LSU v1, BL1) | 139 533 |
| BL8 (`gpu_system_bl8.v`, LSU v2, fabric) | 142 622 |
| | **+2,2% — es más LENTO** |

### Por qué, y es el dato más útil de todo este documento

Contando ciclos de transacción por puerto del fabric sobre los mismos 32
casos:

```text
p0 (LSU vectorial):   401
p1 (fetch de instrucciones / host): 168 209
```

**El tráfico de memoria de esta GPU es fetch de instrucciones en un 99,8%.**
Los accesos vectoriales son ruido estadístico al lado.

Eso invalida la premisa con la que empezó este documento. La coalescencia
funciona — el banco de la LSU demuestra 8 accesos → 2 transacciones — pero
está optimizando el 0,2% del tráfico. Y a cambio, mover el fetch de BL1 a BL8
lo hizo **más caro**: donde antes pagaba dos accesos de 16 bits, ahora paga una
ráfaga BL8 entera más los 3 ciclos de la FSM del fabric, y no reutiliza nada de
los 16 bytes que trae. De ahí el 2,2%.

### Lo que esto implica

1. **La pieza que falta no es la LSU, es el `instruction_buffer`.** En 21 el
   puerto 1 del fabric lo ocupa un buffer que cachea 4 líneas de 16 bytes, y
   ahora se ve por qué: sin él, ensanchar el canal del fetch es una regresión.
   Con él, cada línea de 16 bytes sirve 4 instrucciones consecutivas y el
   tráfico de fetch debería caer en un factor cercano a 4. `gpu_aux_adapter_128`
   se escribió a propósito sin cache para poder medir esto por separado, y la
   medida dice que la cache es justamente donde está todo.
2. **Toda la discusión de Fmax de la LSU era prematura**, como ya se sospechaba
   arriba. No solo no es el camino crítico: es que tampoco mueve el tráfico.
3. **La LSU v2 no se tira.** Es correcta, es más rápida por acceso vectorial, y
   el día que haya programas con tráfico de datos de verdad (los 32 casos
   diferenciales son pruebas de ISA, no cargas realistas) será la pieza que
   haga falta. Pero su prioridad baja mucho.

## Con el buffer de instrucciones: el número bueno

`gpu_imem_buffer.v` pone `instruction_buffer.v` (el de 21, sin tocar) detrás
del puerto `imem` de `gpu_sm` — es solo el pegamento entre los dos contratos de
handshake, que se parecen pero no son iguales. Con él, fetch y host dejan de
compartir puerto: fetch va al p1, host al p3, y el arbitraje lo hace el fabric.

| | Ciclos, 32 casos | vs base |
| --- | --- | --- |
| Base (LSU v1, BL1, sin buffer) | 139 533 | — |
| BL8 + LSU v2, **sin** buffer | 142 622 | +2,2% |
| BL8 + LSU v2 + **buffer de instrucciones** | **80 491** | **−42,3%** |

Los 32 casos diferenciales pasan en las tres configuraciones.

Y el tráfico de fetch, que era el problema:

```text
sin buffer:  p1 (fetch) = 168 209 ciclos de emisión
con buffer:  p1 (fetch) =     103
```

Cuatro líneas de 16 bytes bastan para que los programas de prueba dejen de ir
a la SDRAM casi por completo. Era exactamente lo que el comentario de cabecera
de `instruction_buffer.v` anticipaba para la CPU ("lo que hace falta es que
quepa un bucle"), y resulta que vale igual con 8 warps: la preocupación de que
8 PC independientes hicieran fallar un mapeo directo de 4 líneas **no se
materializó** en estas cargas. Sigue sin estar descartada para programas con
warps divergiendo por regiones de código muy separadas — eso no lo cubre
ninguno de los 32 casos.

### El chip entero, sintetizado

| Sistema | Fmax | TRELLIS_COMB | TRELLIS_FF |
| --- | --- | --- | --- |
| `default` (base: LSU v1, BL1) | 44,14 MHz | 31 076 | 10 090 |
| `bl8` (LSU v2 + buffer + fabric) | 36,57 MHz | 31 012 | 11 169 |

Área prácticamente igual (−64 LUT, +1079 FF, que son las 4 líneas del buffer).
Fmax **−17,2%**.

Combinando las dos medidas — trabajo por segundo ∝ Fmax / ciclos:

```text
base:  44,14 / 139 533
bl8:   36,57 /  80 491     ->  x1,44 de rendimiento neto
```

**Un 44% más rápido en tiempo real**, pagando 17% de Fmax por un 42% menos de
ciclos.

Y el camino crítico del chip completo ahora es:

```text
gpu.lsu.grp_line[19] -> gpu.lsu.n_lanes[7]   (49 segmentos)
```

O sea: **el camino crítico se ha mudado al motor de coalescencia de la LSU
v2**. Esto valida la medida en aislado — 38,84 MHz sueltos predecían bien que
la LSU quedaría por debajo de los 44 MHz del sistema base y se convertiría en
el cuello de botella. Y cambia la conclusión de la sección anterior: partir
`GROUP` en dos estados ya **no** es optimización prematura, es ahora mismo lo
único que hay entre este diseño y recuperar el Fmax de la base.

### Con una carga memory-bound: aquí sí se ve la LSU

Los 32 casos diferenciales son pruebas de ISA: programas cortos, casi sin
tráfico de datos. Por eso su medida estaba dominada por el fetch y la
coalescencia no se notaba. `examples/bench.asm` es lo contrario — un bucle de
`LOAD`/`ADD`/`STORE` con direcciones `base + lane*4` (o sea, el caso
coalescido) y 2000 iteraciones:

| | Ciclos | |
| --- | --- | --- |
| Base (LSU v1, BL1) | 5 929 432 | |
| BL8 + LSU v2 + buffer | 2 313 343 | **x2,56** |

Los dos paran limpiamente en `pc=0x38` sin error. Bancos:
`gpu_bench_tb.v` y `gpu_bench_base_tb.v`, mismo programa en los dos.

Y esto es lo que hay que comparar con el x1,73 de los casos diferenciales: la
ganancia depende mucho de cuánto tráfico de datos tenga el programa. Con
tráfico real, la coalescencia deja de ser el 0,2% y empieza a pagar.

### El Fmax no cuesta nada en la placa

La cuenta de "x1,44 de rendimiento neto" de más arriba supone correr cada
diseño a SU Fmax. **En la placa no es así:** los dos prototipos van a 25 MHz
nativos (`clk_25mhz`, sin PLL), muy por debajo de los 36,57 MHz que aguanta
este y de los 44,14 del base. Es decir, en hardware la penalización de Fmax
no se paga, y la ventaja en ciclos se traduce 1:1 a tiempo real.

Lo que sí significa es que **hay margen de reloj sin usar en los dos**, y que
el día que se meta un PLL, el Fmax vuelve a importar — y ahí el camino crítico
de `gpu_lsu2` (`grp_line` → `n_lanes`) sería lo primero que limitaría.

### Qué hay que leer de todo esto

El −42,3% **no es mérito de la LSU v2**. Es casi todo del buffer de
instrucciones. La secuencia de medidas lo deja claro: el camino de memoria
ancho por sí solo era una regresión, y lo que lo convierte en una ganancia
grande es cachear el fetch. La coalescencia vectorial sigue siendo correcta y
sigue moviendo el 0,2% del tráfico.

## Preguntas abiertas (a decidir, no a asumir)

- **¿`VECTOR_RESPONSE` bloquea o no la vía principal?** Si `gpu_sm` no acepta
  la respuesta al instante, un warp terminado congela el canal de memoria para
  todos los demás. La alternativa es una cola de respuestas de 1-2 entradas
  que desacople el cierre del warp de la emisión del siguiente grupo. No está
  medido cuánto tarda `gpu_sm` en levantar `rsp_ready`; si es siempre 1 ciclo,
  no hace falta nada.
- **¿`pending_spec` desde v2.0 o solo en v2.1?** Sin segmentación no hace
  falta (no hay nada en vuelo cuando se forma el grupo siguiente), pero
  meterlo desde el principio evita rehacer la lógica de retirada después.

- **¿Drenar todas las líneas de un warp antes de ceder el turno, o una líneay volver a arbitrar?** El diseño de arriba propone lo segundo (mantener la
  filosofía de reparto fino de hoy), pero no está medido si conviene más
  drenar un warp entero cuando ya se le ha dado el turno, especialmente si
  sus lanes están muy coalescidas (pocas transacciones, poco coste de
  monopolizar el canal un momento).
- **Tamaño de agrupación:** ¿agrupar solo por línea de 16 bytes exacta, o
  intentar detectar el patrón "lane i → base+i*4" explícitamente (más barato
  de calcular, cubre el caso común sin comparar 8 direcciones completas entre
  sí)? La primera opción es más general; la segunda es más barata en lógica
  si el patrón dominante es siempre ese.
- **Profundidad de 8 tags:** ¿se mantiene igual que hoy, o con el ahorro de
  ciclos por warp compensa tener menos tags en vuelo y más ancho por tag?
  No hay datos todavía.
- **Buffer de combinación de escrituras tipo `cpu_dmem_adapter`:** la CPU lo
  usa porque su patrón típico es 4 `STORE` secuenciales de 32 bits. El patrón
  de la GPU (8 lanes en paralelo por instrucción) ya coalesce de forma
  natural dentro de una sola instrucción vectorial; no está claro que un
  buffer de combinación *entre instrucciones* aporte tanto aquí. A evaluar
  con tráfico real, no a copiar por analogía.
