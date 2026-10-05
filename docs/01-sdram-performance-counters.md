# MiniGPU --- SDRAM Performance Counters

## Objetivo

Añadir instrumentación permanente al subsistema SDRAM antes de construir
el benchmark y antes de optimizar el controlador.

Los contadores deben permitir responder no sólo **cuánto ancho de banda
se obtiene**, sino también **por qué**: cuánto tiempo está ocupado el
controlador, cuánto tiempo el bus DQ mueve datos, cuánto cuesta refresh
y, en fases posteriores, si existen row hits o colas saturadas.

La instrumentación debe ser suficientemente barata para permanecer en el
diseño y poder utilizarse con programas reales.

## Principios

-   Los contadores básicos existen desde la versión BL8 closed-page
    actual.
-   Las métricas deben tener una semántica precisa y estable.
-   Debe poder medirse un intervalo delimitado por software.
-   Debe existir snapshot para leer un conjunto coherente de valores.
-   Los contadores específicos de características futuras sólo se añaden
    cuando exista esa característica.
-   No confundir `controller busy` con utilización real del bus de
    datos.

## Contadores V1

### `perf_cycles`

Incrementa cada ciclo del dominio SDRAM mientras la instrumentación está
habilitada.

Es el denominador principal de las métricas.

### `perf_busy_cycles`

Incrementa cuando el controlador no está en `IDLE`, excluyendo
opcionalmente la inicialización.

Mide ocupación de la máquina de estados, no ancho de banda útil.

### `perf_data_cycles`

Incrementa cada ciclo en el que el bus DQ transporta un beat válido
perteneciente a un READ o WRITE.

En un BL8 completo deben contabilizarse 8 ciclos de datos.

Ésta es la métrica principal de utilización física del bus:

``` text
bus_utilization = data_cycles / perf_cycles
```

### `perf_read_bursts`

Incrementa una vez por READ BL8 completado correctamente.

Bytes leídos:

``` text
read_bytes = perf_read_bursts × 16
```

### `perf_write_bursts`

Incrementa una vez por WRITE BL8 completado correctamente.

Bytes escritos:

``` text
write_bytes = perf_write_bursts × 16
```

### `perf_requests`

Opcional si se desea un contador agregado:

``` text
perf_requests = read_bursts + write_bursts
```

Puede calcularse por software y no necesita necesariamente un registro
físico.

### `perf_refresh_cycles`

Incrementa durante los ciclos consumidos por una operación de refresh,
incluyendo las esperas asociadas que impiden servir tráfico normal.

Debe documentarse exactamente qué estados de la FSM se consideran parte
del refresh y mantenerse esa definición en futuras versiones.

### `perf_refresh_count`

Incrementa una vez por refresh ejecutado.

Permite verificar que la tasa observada es coherente con la
configuración.

## Métricas derivadas

### Controller busy

``` text
busy_% = 100 × busy_cycles / perf_cycles
```

Indica cuánto tiempo existe actividad interna.

### Bus utilization

``` text
bus_% = 100 × data_cycles / perf_cycles
```

Es más importante que `busy_%` para conocer cuánto se aprovecha
realmente el bus.

### Refresh overhead

``` text
refresh_% = 100 × refresh_cycles / perf_cycles
```

### Throughput

Con reloj `F`:

``` text
read_Bps  = read_bursts  × 16 × F / perf_cycles
write_Bps = write_bursts × 16 × F / perf_cycles
total_Bps = (read_bursts + write_bursts) × 16 × F / perf_cycles
```

### Eficiencia respecto al bus físico

Para bus SDRAM de 16 bits:

``` text
peak_Bps = F × 2
efficiency = total_Bps / peak_Bps
```

Idealmente esta cifra debe coincidir aproximadamente con
`data_cycles / perf_cycles`.

## Average y peak utilization

El promedio global se obtiene directamente de
`perf_data_cycles / perf_cycles`.

El pico debe medirse sobre una ventana; un máximo instantáneo carece de
utilidad porque cualquier BL8 puede alcanzar momentáneamente el 100%.

Propuesta inicial:

``` text
PERF_WINDOW_CYCLES = 1024
```

Durante cada ventana:

``` text
window_data_cycles
window_busy_cycles
```

Al terminar:

``` text
last_bus_util
last_busy_util

peak_bus_data_cycles = max(peak_bus_data_cycles, window_data_cycles)
peak_busy_cycles     = max(peak_busy_cycles, window_busy_cycles)
```

Es preferible almacenar el número de ciclos de la ventana y convertir a
porcentaje por software, evitando divisores hardware.

Ejemplo:

``` text
peak_bus_% = 100 × peak_bus_data_cycles / 1024
```

La longitud de ventana debería ser parametrizable.

## Control de medición

Propuesta conceptual de MMIO:

``` text
PERF_CTRL
    ENABLE
    RESET
    SNAPSHOT
```

### RESET

Pone a cero los contadores activos y los máximos de ventana.

### ENABLE

Permite delimitar una región de medida sin contar actividad anterior o
posterior.

### SNAPSHOT

Copia atómicamente los contadores activos a registros shadow.

El software lee los shadow registers, de forma que todos los valores
representan el mismo instante aunque la memoria continúe funcionando.

## Registros de snapshot

Como mínimo:

``` text
PERF_CYCLES
PERF_BUSY_CYCLES
PERF_DATA_CYCLES

PERF_READ_BURSTS
PERF_WRITE_BURSTS

PERF_REFRESH_CYCLES
PERF_REFRESH_COUNT

PERF_PEAK_DATA_CYCLES
PERF_PEAK_BUSY_CYCLES
```

Si los contadores son de 64 bits, pueden exponerse como pares de
registros de 32 bits. El snapshot evita inconsistencias entre parte alta
y baja.

## Anchura de contadores

Para programas reales se recomiendan **64 bits** para los acumuladores
principales.

Los contadores de ventana pueden ser mucho menores; para ventana de 1024
ciclos bastan 11 bits para los valores internos.

## Contadores futuros: open-page

No implementar todavía en el controlador closed-page.

Cuando exista estado de fila abierta por banco:

### `perf_row_hits`

La petición encuentra abierto el banco y exactamente la fila requerida,
evitando PRE/ACT.

### `perf_row_misses`

La petición encuentra el banco cerrado y requiere ACT.

### `perf_row_conflicts`

La petición encuentra abierta una fila distinta y requiere PRE + ACT.

Debe cumplirse, para las peticiones clasificables:

``` text
row_hits + row_misses + row_conflicts = requests
```

Métrica principal:

``` text
row_hit_rate = row_hits / requests
```

## Contadores futuros: queues / Memory Fabric

Añadir sólo cuando existan colas que permitan medirlos correctamente.

### `request_wait_cycles`

Ciclos acumulados durante los cuales existe al menos una petición
pendiente que no puede ser servida.

### `queue_occupancy_sum`

Cada ciclo:

``` text
queue_occupancy_sum += queue_depth
```

Permite obtener:

``` text
average_queue_depth = queue_occupancy_sum / perf_cycles
```

### `queue_max_occupancy`

Máxima ocupación observada durante el intervalo.

Estos valores permiten distinguir situaciones muy diferentes:

``` text
BUS alto + cola llena
→ memoria realmente saturada

BUS bajo + cola llena
→ controlador/fabric desaprovechando oportunidades

BUS bajo + cola vacía
→ los clientes no demandan más ancho de banda
```

## Posible instrumentación por cliente

No es necesaria para V1, pero puede ser útil cuando CPU, GPU, scanout y
2D compartan memoria.

Por master:

``` text
master_read_bursts
master_write_bursts
master_wait_cycles
```

Esto permitiría responder cuánto ancho de banda consume cada subsistema
sin modificar los programas.

## Coste hardware

Los contadores son lógica de diagnóstico, no parte del datapath crítico.

Prioridades:

1.  no degradar timing del controlador;
2.  registrar eventos simples producidos por la FSM;
3.  realizar porcentajes y MB/s por software;
4.  evitar divisores hardware;
5.  permitir deshabilitar o parametrizar instrumentación si fuese
    necesario.

## Formato estándar de lectura

Un monitor o herramienta puede presentar:

``` text
SDRAM PERF
Clock             80.000 MHz
Window              1024 cycles

Elapsed         xxxxxxxxx cycles
Busy                xx.xx %
Bus                 xx.xx %
Peak bus            xx.xx %
Peak busy           xx.xx %
Refresh              x.xx %

Read                xx.xx MB/s
Write               xx.xx MB/s
Total               xx.xx MB/s

Read bursts       xxxxxxxx
Write bursts      xxxxxxxx
Refreshes         xxxxxxxx
```

Más adelante:

``` text
Row hit             xx.xx %
Row miss            xx.xx %
Row conflict         x.xx %

Queue avg             x.xx
Queue max                x
Wait                xx.xx %
```

## Uso

Estos contadores se implementan **antes del benchmark**.

El benchmark utilizará los performance counters como fuente principal de
diagnóstico y mantendrá además una medición externa de ciclos/tiempo
como comprobación independiente.

Posteriormente, cada fase de optimización del controlador debe
compararse con el mismo conjunto de métricas.
