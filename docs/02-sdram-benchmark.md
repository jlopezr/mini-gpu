# MiniGPU --- Benchmark del controlador SDRAM

## Objetivo

Obtener un baseline reproducible del ancho de banda y eficiencia reales
del subsistema SDRAM, utilizando los performance counters definidos en
`01-sdram-performance-counters.md`.

El benchmark no debe limitarse a responder "cuántos MB/s"; debe permitir
identificar dónde se pierden ciclos.

El controlador actual relevante usa:

-   bus SDRAM de 16 bits;
-   burst length 8;
-   128 bits / 16 bytes por request;
-   política closed-page en el baseline.

Scanout y prefetch de instrucciones ya utilizan requests de 128 bits.

## Requisito previo

Implementar al menos los contadores V1:

``` text
perf_cycles
perf_busy_cycles
perf_data_cycles
perf_read_bursts
perf_write_bursts
perf_refresh_cycles
perf_refresh_count
perf_peak_data_cycles
perf_peak_busy_cycles
```

y las operaciones:

``` text
RESET
ENABLE
SNAPSHOT
```

## Metodología común

Para cada test:

1.  preparar memoria/datos fuera de la región medida;
2.  `PERF_RESET`;
3.  habilitar contadores;
4.  arrancar un contador de ciclos independiente del benchmark;
5.  ejecutar el workload;
6.  detener la medida;
7.  solicitar `PERF_SNAPSHOT`;
8.  leer los performance counters;
9.  registrar también los ciclos externos;
10. verificar integridad de datos cuando corresponda.

La medición externa de ciclos es una comprobación independiente. Los
performance counters son la fuente principal para diagnosticar el
comportamiento interno.

## Métricas a registrar

``` text
elapsed cycles
external cycles

controller busy %
bus utilization %
peak bus utilization %
peak controller busy %
refresh %

read bursts
write bursts
read MB/s
write MB/s
total MB/s

cycles/request
% del pico físico
```

En versiones futuras:

``` text
row hit %
row miss %
row conflict %

queue average
queue maximum
request wait %
```

## Tamaños

     Tamaño   Requests BL8
  --------- --------------
      1 KiB             64
     16 KiB          1.024
    256 KiB         16.384
      1 MiB         65.536

Las pruebas grandes determinan throughput sostenido; las pequeñas
muestran costes fijos.

# Test A --- Controller directo / READ secuencial

Camino:

``` text
benchmark generator
      ↓
SDRAM controller
      ↓
SDRAM
```

Direcciones:

``` text
BASE
BASE + 16
BASE + 32
BASE + 48
...
```

Objetivo: mejor caso de lectura streaming BL8 del controlador actual.

Registrar todos los contadores estándar.

Interpretación:

-   `busy` alto + `bus` bajo: overhead interno/timings;
-   `bus` próximo al máximo posible: controlador eficiente;
-   `refresh` permite cuantificar el coste real de refresh.

# Test B --- Controller directo / WRITE secuencial

Mismo patrón con escrituras de 128 bits.

Después del intervalo medido realizar una lectura de verificación.

No considerar válido un resultado si existen errores de datos.

Comparar READ vs WRITE.

# Test C --- Memory Fabric

Repetir A y B:

``` text
benchmark
    ↓
Memory Fabric
    ↓
SDRAM controller
    ↓
SDRAM
```

Comparar contra controller directo.

La diferencia cuantifica pérdidas por:

-   handshake;
-   arbitraje;
-   burbujas;
-   buffering insuficiente.

# Test D --- CPU

Ejecutar un workload equivalente desde la CPU.

Medir por separado cuando sea posible:

-   lectura secuencial;
-   escritura secuencial;
-   instruction prefetch;
-   opcionalmente copia SDRAM → SDRAM.

Comparar:

``` text
controller directo
vs
fabric
vs
CPU
```

para identificar dónde aparece cada pérdida.

# Test E --- Scanout

El scanout es un consumidor real de streaming y ya solicita 128 bits por
bloque.

Durante una carga de vídeo estable registrar:

``` text
bus utilization
busy
read MB/s
peak bus utilization
refresh
underflows
```

Si existen FIFO/linebuffer counters, registrar también sus
mínimos/máximos.

Para 640×480 RGB565 @60 Hz, el consumo teórico de framebuffer es:

``` text
640 × 480 × 2 × 60
= 36.864.000 B/s
≈ 36,9 MB/s
```

La medida real debe ser coherente con la configuración efectiva de
vídeo.

# Frecuencias

Cuando el prototipo lo permita, ejecutar los mismos tests a:

``` text
25 MHz
80 MHz
```

El pico físico del bus de 16 bits es:

``` text
25 MHz → 50 MB/s
80 MHz → 160 MB/s
```

Son techos, no benchmarks esperados.

Registrar siempre la frecuencia real junto con los resultados.

# Refresh

Las pruebas normales se ejecutan con refresh habilitado.

Opcionalmente puede hacerse una prueba controlada sin refresh
exclusivamente para cuantificar overhead, pero nunca debe sustituir al
resultado normal.

# Patrones adicionales

Después del baseline:

## Cambios frecuentes de fila

Útil para comparar posteriormente closed-page vs open-page.

## Alternancia entre bancos

Preparará la evaluación de bank interleaving.

## READ/WRITE alternado

Cuantifica turnaround:

``` text
READ
WRITE
READ
WRITE
...
```

Estos tests no son requisito para el primer baseline.

# Formato estándar de resultado

Cada ejecución debe producir un bloque comparable:

``` text
Test:       sequential-read-1MiB
Path:       controller-direct
Clock:      80 MHz
Policy:     BL8 closed-page
Size:       1 MiB

Perf cycles:          xxxxxxxxx
External cycles:      xxxxxxxxx

Throughput:              xx.xx MB/s
Read:                    xx.xx MB/s
Write:                    xx.xx MB/s

Bus utilization:         xx.xx %
Peak bus utilization:    xx.xx %
Controller busy:         xx.xx %
Peak controller busy:    xx.xx %
Refresh:                  x.xx %

Requests:              xxxxxxxx
Cycles/request:           xx.xx
Physical-bus efficiency: xx.xx %

Errors:                       0
```

Cuando existan las funciones:

``` text
Row hit:                  xx.xx %
Row miss:                 xx.xx %
Row conflict:              x.xx %

Queue average:              x.xx
Queue maximum:                 x
Request wait:              xx.xx %
```

# Tabla resumen

  --------------------------------------------------------------------------------------------
  Camino           MHz Test      Tamaño    MB/s   Bus %  Busy %    Peak Refresh %   Cycles/req
                                                                  bus %           
  ------------ ------- ------- -------- ------- ------- ------- ------- --------- ------------
  Controller        80 READ       1 MiB                                           
                       seq                                                        

  Controller        80 WRITE      1 MiB                                           
                       seq                                                        

  Fabric            80 READ       1 MiB                                           
                       seq                                                        

  Fabric            80 WRITE      1 MiB                                           
                       seq                                                        

  CPU               80 READ       1 MiB                                           
                       seq                                                        
  --------------------------------------------------------------------------------------------

# Relación con 640×480 RGB565

Framebuffer:

``` text
640 × 480 × 2 = 614.400 bytes
```

Scanout @60:

``` text
≈ 36,9 MB/s
```

Una escritura completa de color por la GPU añade aproximadamente:

``` text
30 FPS → 18,4 MB/s
60 FPS → 36,9 MB/s
```

sin contar texturas, depth, CPU, instrucciones ni motor 2D.

Después de medir:

``` text
available_after_scanout =
    measured_sustained_bandwidth - scanout_bandwidth
```

Este cálculo es sólo un primer presupuesto. La contención, latencias y
picos también importan, por lo que deben observarse `peak`, colas y
underflows.

# Criterio de éxito

El baseline debe permitir responder con datos medidos:

1.  throughput READ/WRITE real del BL8;
2.  utilización media y pico del bus;
3.  diferencia entre `busy` y transferencia útil;
4.  coste de refresh;
5.  pérdida introducida por Memory Fabric;
6.  ancho de banda realmente alcanzable por CPU;
7.  presión introducida por scanout;
8.  margen disponible para GPU y 2D.

El mismo benchmark debe ejecutarse después de cada fase de optimización.
