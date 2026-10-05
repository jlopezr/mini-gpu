# MiniGPU --- Plan por fases para mejorar el controlador SDRAM

## Regla de trabajo

No optimizar a ciegas.

Antes de esta hoja de ruta deben existir:

1.  `01-sdram-performance-counters.md`
2.  `02-sdram-benchmark.md`

Cada fase se conserva sólo si mejora métricas medibles sin introducir
errores o problemas de timing.

El baseline actual es un controlador:

``` text
16-bit SDRAM
BL8
128 bits / request
closed-page / auto-precharge
```

Scanout y CPU instruction prefetch ya utilizan bloques de 128 bits, por
lo que inicialmente se mantiene esa interfaz.

# Fase 0 --- Instrumentación y baseline

Implementar los performance counters V1 y ejecutar el benchmark completo
del controlador actual.

Métricas principales:

``` text
MB/s
bus utilization
peak bus utilization
controller busy
refresh %
cycles/request
```

Objetivo: disponer de una referencia reproducible antes de cambiar la
FSM.

# Fase 1 --- Open-page + row-hit fast path

Mantener por banco:

``` text
open
open_row
```

Clasificar cada petición:

``` text
bank closed
    → row miss → ACT → access

same row open
    → row hit → access directo

different row open
    → row conflict → PRE → ACT → access
```

Añadir:

``` text
perf_row_hits
perf_row_misses
perf_row_conflicts
```

Validar con:

-   READ/WRITE secuencial;
-   patrón de cambios de fila;
-   scanout;
-   instruction prefetch.

Éxito esperado conceptualmente: subir `bus utilization` y reducir
`cycles/request` en streams con muchos row hits.

No fijar una cifra objetivo hasta medir el baseline.

# Fase 2 --- Request queue / visibilidad de la siguiente petición

Añadir una pequeña cola para que el controlador pueda conocer trabajo
futuro antes de terminar la operación actual.

Inicialmente mantener orden FIFO; no reordenar.

Añadir:

``` text
queue_occupancy_sum
queue_max_occupancy
request_wait_cycles
```

Métricas:

``` text
average queue depth
max queue depth
request wait %
bus utilization
```

Interpretación:

``` text
BUS alto + queue alta
→ SDRAM cerca de saturación

BUS bajo + queue alta
→ quedan burbujas/ineficiencias en controlador

BUS bajo + queue baja
→ falta demanda; no es problema de SDRAM
```

# Fase 3 --- Memory Fabric orientado a tráfico sostenido

Revisar que el fabric pueda alimentar la request queue sin introducir
huecos innecesarios.

Mantener fairness entre masters.

Para scanout usar prioridad dependiente de watermark si existe
FIFO/linebuffer, en vez de prioridad absoluta permanente.

Medir:

-   controller-direct vs fabric;
-   wait por master si se instrumenta;
-   bus utilization;
-   underflows de scanout.

Objetivo: que la pérdida `fabric vs controller-direct` sea pequeña y
explicable.

# Fase 4 --- Dominios de reloj separados

Motivación observada:

``` text
CPU + BL8 SDRAM ha funcionado a 80 MHz
GPU completa ha requerido aproximadamente 25 MHz
```

La frecuencia de la GPU no debe obligar a reducir la frecuencia de
memoria.

Arquitectura:

``` text
GPU ~25 MHz                       Memory 80 MHz

GPU / LSU
   │
request async FIFO
   ├──────────────────────────► Memory Fabric
   │                                │
   │                           SDRAM controller
   │                                │
response async FIFO ◄───────────────┘
   │
   ▼
GPU
```

Cruzar requests/responses de 128 bits, no beats SDRAM individuales.

Scanout puede tener su propio CDC:

``` text
Memory @80
    │
128-bit blocks
    ▼
async FIFO / linebuffer
    │
pixel clock
    ▼
scanout
```

Validación:

-   repetir benchmark desde el dominio lento;
-   comparar controller-direct @80 con tráfico a través del CDC;
-   medir queue occupancy;
-   medir wait;
-   verificar que scanout no sufre underflow.

El objetivo no es que el CDC sea gratis, sino que permita mantener SDRAM
a 80 MHz independientemente del timing de GPU.

# Fase 5 --- Scheduling consciente de bancos

Sólo si las métricas muestran cola pendiente y bus infrautilizado.

Con varias peticiones visibles, favorecer cuando sea seguro:

-   row hits;
-   bancos disponibles;
-   reducción de PRE/ACT;
-   fairness.

Si se reordenan requests, será necesario preservar la asociación de
respuestas, posiblemente mediante tags.

Métricas:

``` text
row hit rate
bus utilization
queue depth
request wait
latencia por master
```

Vigilar starvation.

# Fase 6 --- Bank interleaving

Intentar ocultar `tRP/tRCD` preparando un banco mientras otro transfiere
datos.

Sólo implementar si el benchmark demuestra que las activaciones/cambios
de fila siguen siendo una fracción relevante del tiempo perdido.

Comparar contra Fase 5 con exactamente los mismos workloads.

# Fase 7 --- READ/WRITE turnaround

Medir primero:

``` text
READ continuo
WRITE continuo
READ/WRITE alternado
```

Si el turnaround es significativo, estudiar agrupación temporal de
operaciones del mismo sentido.

No perjudicar las garantías de scanout ni introducir latencias excesivas
a clientes interactivos.

# Fase 8 --- Métricas por master y políticas de QoS

Cuando CPU, GPU, scanout y 2D compartan el fabric, puede ser útil
añadir:

``` text
master_read_bursts
master_write_bursts
master_wait_cycles
```

Esto permite presupuestar ancho de banda real por subsistema.

Posibles políticas:

## Scanout

-   prioridad por watermark;
-   prefetch;
-   FIFO/linebuffer;
-   evitar underflow.

## GPU

-   async request/response FIFOs;
-   coalescer;
-   múltiples peticiones pendientes si la arquitectura futura lo
    permite.

## CPU

-   instruction prefetch BL8;
-   tráfico de datos más irregular;
-   latencia razonable aunque exista tráfico GPU.

## Motor 2D

-   prefetch por scanline;
-   tiles/glyphs/bitmaps por bloques;
-   BRAM como buffers/cache;
-   evitar accesos SDRAM por píxel.

# Orden recomendado

``` text
0. Performance counters + baseline
            ↓
1. Open-page / row hits
            ↓
2. Request queue
            ↓
3. Afinar Memory Fabric
            ↓
4. GPU~25 / Memory80 mediante async FIFOs
            ↓
5. Volver a medir workloads reales
            ↓
6. Scheduler consciente de bancos si hace falta
            ↓
7. Bank interleaving / turnaround si los datos lo justifican
            ↓
8. QoS y métricas por master
```

Las fases de CDC y optimización interna pueden intercambiarse por
conveniencia de implementación, pero sus efectos deben medirse por
separado.

# Presupuesto de referencia: 640×480 RGB565

Scanout @60 Hz:

``` text
≈ 36,9 MB/s
```

GPU escribiendo sólo color:

``` text
30 FPS → ≈18,4 MB/s
60 FPS → ≈36,9 MB/s
```

No incluye:

-   texturas;
-   depth;
-   CPU;
-   instruction fetch;
-   motor 2D;
-   otros masters.

Por eso el criterio importante no es sólo "MB/s máximos", sino:

``` text
ancho de banda restante
+
picos
+
latencia
+
colas
+
ausencia de underflow
```

# Validación obligatoria de cada fase

Cada modificación debe:

1.  pasar pruebas funcionales;
2.  producir cero errores de datos;
3.  mantener refresh correcto;
4.  mantener estabilidad en placa;
5.  no introducir underflow en configuraciones soportadas;
6.  ejecutar el mismo benchmark anterior;
7.  comparar performance counters antes/después;
8.  documentar frecuencia y configuración;
9.  distinguir siempre resultados medidos de estimaciones.

Así la evolución desde BL8 closed-page hacia un controlador más
sofisticado queda guiada por datos y no por complejidad teórica.
