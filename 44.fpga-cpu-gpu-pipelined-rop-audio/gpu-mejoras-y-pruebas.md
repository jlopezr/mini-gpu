# GPU 44: plan de mejora, perfil y validación

Este documento reúne las mejoras que conviene evaluar en la GPU de este
prototipo y las pruebas que deben acompañarlas. No es una lista de cambios que
se puedan aplicar todos a la vez: el orden evita optimizar una parte que luego
no resulta ser el cuello de botella.

La regla es siempre la misma:

1. medir un caso representativo;
2. cambiar **una** hipótesis de coste;
3. mantener la equivalencia funcional;
4. comparar ciclos, recursos y Fmax antes de conservar el cambio.

## 1. Punto de partida

El SM tiene las fronteras registradas `SCH -> IS -> IF -> ID -> RR -> EX ->
MEM -> WB`. El retiro arquitectónico se concentra en WB. Hay un scoreboard por
warp y se permite una única instrucción joven detrás de un `LOAD` si no depende
de él. Aún no hay forwarding de resultados a RR.

La LSU agrupa las direcciones de las ocho lanes por línea de 16 bytes y las
sirve por el puerto de memoria de la GPU. Esto es *coalescing*, no una cache de
datos: una línea leída no permanece para reutilizarse en una carga posterior.

La GPU sí tiene una I-cache/buffer de instrucciones directo y pequeño:
16 líneas de 16 bytes (256 B). La D-cache de 16 KiB del prototipo pertenece a
la CPU; no forma parte de `gpu_system`.

Por tanto, el estado actual es una buena base para explotar latencia entre
warps, pero todavía no una GPU que esconda de forma agresiva las dependencias o
las muchas líneas de una carga dispersa.

## 2. Instrumentación disponible

GPU PERFORMANCE empieza en `0x82030000`. Todos estos registros son de 32 bits,
solo lectura y cuentan únicamente mientras la GPU corre.

| Offset | Registro | Qué responde |
|---:|---|---|
| `+0x00` | `CYCLES` | Tiempo de ejecución de GPU. |
| `+0x04` | `RETIRED` | Instrucciones de warp retiradas. |
| `+0x08` / `+0x0c` | `IMEM_HITS` / `IMEM_MISSES` | Reutilización del código. |
| `+0x10` | `LSU_TX` | Transacciones de línea emitidas por la LSU. |
| `+0x14` | `STALL_MEM` | LSU sin poder aceptar una petición. |
| `+0x18` | `LANE_OPS` | Suma de lanes que retiraron; mide divergencia. |
| `+0x1c` | `NO_WARP_STALL` | SCH tenía hueco, pero no había warp elegible. |
| `+0x20` | `RR_RAW_STALL` | RR esperaba un registro pendiente del scoreboard. |
| `+0x24` | `LSU_RSP_BLOCKED` | La respuesta de LSU esperaba espacio en MEM/WB. |
| `+0x28` | `ISSUE_AFTER_LOAD` | Instrucción joven independiente admitida tras un `LOAD`. |
| `+0x2c` | `WB_ARB_MEM_WAIT` | Una respuesta MEM cedió WB a otro packet. |
| `+0x30` | `SCH_ISSUED` | Tokens admitidos desde SCH; denominador de latencia. |
| `+0x34`–`+0x44` | `IS/IF/ID/RR/EX_CYCLES` | Ciclos-token de residencia de cada registro de etapa. |
| `+0x48` | `MEM_WARP_CYCLES` | Suma de warps con token de memoria pendiente. |
| `+0x4c` | `WB_PACKET_CYCLES` | Suma de packets en las dos colas físicas de WB. |

Dos ratios útiles son:

```text
CPI de warp              = CYCLES / RETIRED
lanes medias/instrucción  = LANE_OPS / RETIRED
transacciones/LOAD        = LSU_TX / cargas retiradas    (si el kernel las cuenta)
latencia media de IS      = IS_CYCLES / SCH_ISSUED
```

La última identidad se aplica igual a IF, ID, RR y EX. No se debe sumar las
residencias para reconstruir `CYCLES`: varias etapas y varios warps pueden
estar ocupados simultáneamente. En particular MEM y WB cuentan ciclos-token o
ciclos-packet y pueden superar los ciclos de reloj; esa diferencia muestra
precisamente el solapamiento que interesa explotar.

No se debe interpretar un contador aislado. Por ejemplo, `NO_WARP_STALL` alto
con `RR_RAW_STALL` bajo suele indicar espera en memoria o escasez de warps; con
`RR_RAW_STALL` alto, en cambio, apunta a forwarding o a reordenación.

El banco `gpu_mem_x_overlap_tb.v` comprueba además que las cuatro extensiones
nuevas se leen por MMIO. Su caso inicial da actualmente `ISSUE_AFTER_LOAD=1` y
los otros tres a cero: es una prueba de cableado y de un solapamiento concreto,
no un objetivo de rendimiento ni una referencia que deba permanecer constante.

## 3. Método de medida

Antes de alterar RTL, cada trabajo debe tener un microbenchmark y al menos un
kernel real. El primero explica el resultado; el segundo decide si merece el
coste en silicio.

Para cada medición registrar:

- versión/commit, parámetros de la GPU, frecuencia conseguida y recursos;
- número de warps, máscara activa, tamaño/alineamiento del acceso y latencia de
  memoria usada en simulación;
- `CYCLES`, `RETIRED`, los contadores que explican el cuello y el resultado
  funcional del kernel;
- media y peor caso si el arbitraje o la latencia son aleatorios.

El test de RTL es la puerta mínima:

```bash
./tools/test --prototype 44 --jobs 1
```

Toda síntesis se debe comparar con una referencia conocida usando los
lanzadores del repositorio (`build --prototype 44 --background`, seguido de
`build-status` y `build-log`). Un CPI menor no compensa una Fmax menor si el
tiempo absoluto `CYCLES / Fmax` empeora.

## 4. Mejoras priorizadas

### 4.1. Primero: convertir el perfil en evidencia

**Objetivo.** Que cada benchmark imprima o exporte los contadores relevantes,
no solo ciclos y CPI.

**Trabajo.** Extender `gpu_mem_x_overlap_tb.v` con filas para cada patrón y un
pequeño programa de placa que lea PERFORMANCE antes/después de un despacho.
Separar siempre los resultados de `LOAD independiente`, `LOAD->uso RAW`,
accesos contiguos, dispersos y código que no cabe en la I-cache.

**Éxito.** Los contadores explican el orden de los CPI observados. Si no lo
hacen, hay que instrumentar antes de optimizar: por ejemplo, añadir número de
grupos de línea LSU, ciclos de `x_valid`, o ciclos de barrera.

**Riesgo.** Bajo. No modifica el datapath.

### 4.2. Forwarding controlado a RR/WB

**Hipótesis.** Los consumidores de un resultado ya disponible en MEM/WB no
deben esperar a que el banco de registros lo observe un ciclo posterior.

**Diseño.** Añadir bypass de los datos y máscara de escritura de `mem_q` y
`wb_q` hacia los operandos capturados por RR. El scoreboard deja de bloquear
una fuente únicamente cuando el valor exacto está estable y el productor
retirará en orden. Mantener la dependencia para resultados de EX/multiciclo que
aún no tengan datos definitivos.

No conviene eliminar `pending_write` de golpe: debe seguir detectando RAW y
WAW, y el bypass decide por cada fuente si satisface la dependencia. La
prioridad de valores debe ser inequívoca si dos productores del mismo warp
escriben el mismo registro.

**Pruebas necesarias.**

- `LOAD r1; ADD r2,r1,r3`, `LOAD r1; STORE r1,[...]`, byte/halfword con signo y
  sin signo; comprobar valor, máscara de lanes y PC.
- cadenas ALU, WAW (`MOVI r1; MOVI r1; uso r1`) y dos fuentes reenviadas a la
  vez (`ADD r3,r1,r2`);
- productor que falla, división larga, branch/JALR y salida de una región SIMT:
  nunca se debe reenviar un valor especulativo o de un camino equivocado;
- mismo programa con uno, dos, cuatro y ocho warps; comparar `RR_RAW_STALL`,
  CPI y el diferencial funcional existente.

**Criterio de adopción.** `RR_RAW_STALL` baja en el microbenchmark RAW y en al
menos un kernel real sin degradar Fmax. No basta mejorar un test artificial.

**Riesgo.** Medio: RR, MEM y WB comparten la semántica de retiro en orden.

### 4.3. Más tolerancia a memoria entre warps

**Hipótesis.** Una carga de un warp no debería dejar hueco vacío si otro warp
puede pasar por RR/EX y no entra en conflicto con la estructura de una entrada
por etapa.

**Diseño por etapas.**

1. Medir con 1/2/4/8 warps y latencias de RAM fija y aleatoria.
2. Permitir, de forma explícita, más de una instrucción joven o varios tokens
   por warp solo cuando exista una cola de retiro por warp y un scoreboard por
   registro que lo soporte.
3. Si la evidencia lo pide, separar la aceptación de petición LSU de la espera
   de respuesta: conservar tag, PC, destino, máscara y error por transacción.

La versión actual permite una joven detrás de un `LOAD`; ampliar esa ventana sin
una cola de retiro y sin controlar WAW rompería el orden arquitectónico.

**Pruebas necesarias.**

- ráfaga de cargas independientes seguida de consumos, con distintos warps;
- todos los warps esperando la misma línea, líneas distintas y mezcla de LOAD,
  STORE posted y MMIO;
- respuestas en cualquier orden permitido por el backend y error tardío de
  STORE; reset/soft-reset con respuestas aún pendientes;
- comprobar que una instrucción joven nunca retira antes de su LOAD y que STEP
  ejecuta exactamente una instrucción.

**Métricas.** `NO_WARP_STALL`, `ISSUE_AFTER_LOAD`, ocupación de LSU, `STALL_MEM`
y CPI según número de warps.

**Riesgo.** Alto a partir de dos jóvenes por warp; primero se debe demostrar que
la ventana actual se usa con frecuencia.

### 4.4. LSU y coalescing

**Hipótesis.** Muchos kernels perderán más tiempo por una lane por línea que
por el pipeline del SM.

**Posibles mejoras.**

- Reducir burbujas entre grupos de líneas de una misma instrucción vectorial.
- Mantener más de una lectura de línea en vuelo, con tags de grupo y una cola
  de ensamblado de respuesta.
- Mejorar el arbitraje entre warps cuando unos generan muchos grupos y otros
  solo uno; medir justicia, no solo rendimiento medio.
- Añadir prefetch únicamente si la traza demuestra localidades previsibles.

**Pruebas necesarias.** Para cada tamaño de acceso (`word`, `byte`, `halfword`)
crear patrones de 8 lanes: misma palabra, misma línea, dos líneas 4+4, una
línea por lane, stride creciente, desalineado legal y mezcla de máscaras
activas. Repetir para LOAD/STORE y con CPU/ROP/DMA compitiendo por SDRAM.

**Métricas.** Transacciones por instrucción de memoria, `STALL_MEM`, ciclos
desde emisión a respuesta y justicia entre warps. La referencia funcional debe
verificar datos y errores lane a lane.

**Riesgo.** Medio/alto: más peticiones simultáneas afectan tags, backpressure,
orden de STORE y la terminación de GPU.

### 4.5. I-cache de la GPU

**Hipótesis.** Los fallos de las 16 líneas actuales pueden dominar kernels con
código grande o muchos saltos.

**Orden correcto.** Primero medir `IMEM_MISSES / (IMEM_HITS + IMEM_MISSES)` por
kernel y hacer una traza de PCs. Solo si importa, probar en este orden:

1. capacidad (32, 64, … líneas);
2. asociatividad de dos vías para conflictos demostrados;
3. prefetch secuencial para código con saltos poco frecuentes.

**Pruebas necesarias.** Bucle que cabe, bucle que excede capacidad, dos bucles
que colisionan en el índice, saltos indirectos, reescritura de programa por el
monitor mientras la GPU está parada y reset durante un fill. Deben conservarse
las reglas actuales: la I-cache se vacía con la GPU parada y no ejecuta código
obsoleto.

**Métricas.** tasa de fallo, CPI, EBR/LUT/FF y Fmax. Un aumento de I-cache no se
acepta solo porque reduzca misses si roba EBR necesaria a vídeo o a la CPU.

### 4.6. D-cache GPU: investigación, no siguiente cambio

Una D-cache GPU podría acelerar cargas con reutilización real, pero no debe
introducirse por analogía con la CPU. El framebuffer, CPU, ROP, DMA y GPU
comparten SDRAM; hay que decidir una política de coherencia antes del RTL.

Alternativas a evaluar:

- sin cache, pero con mejor coalescing y más transacciones en vuelo;
- scratchpad explícito gestionado por software/DMA;
- cache de solo lectura con invalidación explícita antes/después de CPU/ROP;
- cache write-through con invalidación cruzada;
- regiones no cacheables, en particular framebuffer y MMIO.

**Pruebas obligatorias antes de aceptarla.** CPU escribe y GPU lee; GPU escribe
y CPU lee; ROP/DMA compiten sobre la misma línea; alias de líneas, stores
posted, invalidación con carga pendiente, reset y errores. Medir hit rate real
en kernels, no inferirlo de la CPU.

**Riesgo.** Muy alto. No abordar mientras `LSU_TX`, `STALL_MEM` y las trazas no
demuestren reutilización que el coalescing actual no pueda recuperar.

### 4.7. Ejecución, control y SIMT

**Líneas de trabajo.**

- Reducir la latencia de operaciones largas o hacer que su estado no ocupe EX
  cuando otro warp podría utilizarlo.
- Medir coste de branches, reconvergencia, SSY y barreras; no asumir que el
  problema es la ALU.
- Evaluar planificación consciente de warps listos, antigüedad y presión de
  LSU solo si el round-robin actual muestra injusticia.
- Evaluar empaquetar trabajo de warps diferentes en lanes libres únicamente
  tras medir `LANE_OPS / RETIRED`: con poca divergencia añade complejidad sin
  trabajo que recuperar.

**Pruebas necesarias.** DIV/MUL con otros warps de ALU y memoria; ramas
uniformes y divergentes; pilas SIMT al límite; barreras de grupos correctos e
incorrectos; HALT/EXIT parcial; STEP y errores en todos esos estados.

**Métricas que faltan si hicieran falta.** ciclos de EX ocupado por clase
(ALU/DIV/control), ciclos de barrera, número de reconvergencias y distribución
de espera por warp. Añadirlos solo después de que los contadores actuales no
puedan explicar un cuello concreto.

### 4.8. Fabric, Fmax y coste físico

Cada mejora de CPI debe compararse contra arbitraje de SDRAM y reloj. En
particular, más multiplexores de forwarding, tags o colas pueden desplazar el
camino crítico de RR/SCH o consumir EBR.

**Pruebas necesarias.** Síntesis de referencia y modificada, revisar ruta
crítica y recursos; ejecución en placa de los kernels que compiten con vídeo,
ROP, CPU y audio. Registrar tiempo absoluto, no solo ciclos simulados.

## 5. Matriz de regresión permanente

Todo cambio de la GPU debe conservar estos grupos de prueba:

| Grupo | Casos mínimos | Propiedad que protege |
|---|---|---|
| ISA y diferencial | bancos GPU existentes y programas aleatorios pequeños | estado final, memoria, errores y PC. |
| Pipeline | NOP, ALU, branch, SSY, RRFLT, HALT/EXIT | cada token retira una vez desde WB. |
| Dependencias | RAW/WAR/WAW, dos fuentes, carga/uso/store | scoreboard y forwarding, si existe. |
| Memoria | coalescing, subword, máscaras, error, STORE posted | datos lane a lane y orden de efectos. |
| Concurrencia | 1/2/4/8 warps, respuestas lentas/aleatorias | progreso, justicia y retiro en orden por warp. |
| Control | reset, soft-reset, HALT/RESUME/STEP | no quedan respuestas ni tokens huérfanos. |
| Perfil | lectura MMIO, reset, wrap de 32 bits, eventos conocidos | los contadores explican y no cambian el diseño. |
| Física | síntesis, timing y placa | mejora de tiempo absoluto y recursos aceptables. |

Para los casos temporales, usar aserciones de propiedades, no solo timeouts:

- una respuesta LSU aceptada termina en exactamente un retiro/fallo del token;
- ninguna escritura de RF viene de un warp o destino distinto;
- `pending_write` se pone y borra una vez por productor;
- una joven posterior a LOAD no retira antes que el LOAD;
- una petición MMIO o STORE posted no declara la GPU terminada antes de que su
  efecto/error sea visible;
- cuando hay un warp elegible y las estructuras destino están libres, el
  planificador hace progreso en un número acotado de ciclos.

Los timeouts siguen siendo útiles para detectar deadlock, pero deben imprimir
estado de las etapas, `busy`, `mem_valid`, `pending_write`, ocupación LSU y los
contadores para que el fallo sea diagnosticable.

## 6. Hoja de ruta recomendada

1. **Perfil y bancos.** Hacer que los microbenchmarks recojan todos los
   contadores y crear los patrones de coalescing/RAW que faltan.
2. **Forwarding MEM/WB -> RR.** Cambio acotado, con pruebas de dependencia y
   comparación de `RR_RAW_STALL`.
3. **Latencia de memoria entre warps.** Decidir, con datos, si abrir más
   ventana por warp o aumentar solicitudes LSU en vuelo.
4. **LSU.** Optimizar grupos, concurrencia y arbitraje si `LSU_TX` y
   `STALL_MEM` lo justifican.
5. **I-cache.** Tocar capacidad/asociatividad solamente si los misses de código
   justifican EBR y lógica adicional.
6. **D-cache/scratchpad y SIMT más agresivo.** Diseños de mayor alcance, tras
   fijar coherencia y demostrar reutilización/divergencia real.

La condición para avanzar de fase no es que el RTL funcione: es que la fase
anterior haya dejado una medición que explique por qué la siguiente mejora es
la que más tiempo puede recuperar.
