# Contrato MMIO v2 unificado de MiniCPU y MiniGPU

**Estado:** propuesta consolidada para implementación.  
**Compatibilidad:** MMIO v2 no mantiene compatibilidad binaria con los mapas MMIO de prototipos anteriores.

Este documento define el contrato objetivo del espacio físico de direcciones y de los dispositivos MMIO para:

- MiniCPU.
- MiniGPU.
- Sistema integrado MiniCPU + MiniGPU.
- Simulador MiniCPU.
- Simulador MiniGPU.
- Monitor y herramientas de depuración.

Los mapas de los prototipos históricos siguen siendo válidos para documentar esas implementaciones, pero no condicionan MMIO v2.

---

# 1. Principios de diseño

## 1.1. Un único espacio físico

CPU, GPU, monitor y futuros masters comparten el mismo espacio físico de direcciones.

La regla fundamental es:

> **Una dirección física identifica un único recurso del sistema. Su significado nunca depende del master que realiza el acceso.**

Si:

```text
0x80200004 = VIDEO.FB_FRONT
```

esa dirección significa siempre `VIDEO.FB_FRONT`, independientemente de que acceda:

- CPU;
- GPU;
- monitor;
- DMA;
- cualquier master futuro.

No existen alias cuyo significado dependa del origen de la transacción.

---

## 1.2. Dirección y permisos son independientes

El mapa físico determina:

> **qué dispositivo corresponde a una dirección.**

Una política independiente determina:

> **qué masters pueden acceder al dispositivo o registro.**

Conceptualmente:

```text
master
  |
  v
address
  |
  v
+-------------+
| address map |
+-------------+
  |
  v
device/register
  |
  v
permissions
  |
  +----> access
  |
  +----> error
```

Esto permite introducir en el futuro protección o nuevos masters sin modificar el mapa físico.

---

## 1.3. El mapa no depende de la SDRAM actual

La implementación actual utiliza normalmente 32 MiB:

```text
0x00000000 - 0x01FFFFFF    SDRAM
```

pero MMIO no se coloca inmediatamente después.

Se reserva una región amplia para memoria y expansión futura.

---

## 1.4. Los huecos no consumen memoria FPGA

Reservar una región grande de direcciones para un dispositivo no implica implementar físicamente toda esa memoria.

Los bloques grandes y alineados proporcionan:

- decodificación sencilla;
- direcciones estables;
- expansión futura;
- organización jerárquica;
- ausencia de renumeraciones innecesarias.

MMIO v2 no intenta compactar registros para ahorrar espacio de direcciones.

---

# 2. Tamaños de acceso

## 2.1. RAM

La memoria ordinaria puede admitir los tamaños definidos por MiniISA:

```text
byte
halfword
word
```

según las instrucciones disponibles en cada perfil de ISA.

---

## 2.2. MMIO

Todos los registros MMIO son palabras de 32 bits.

Sólo son válidos:

```text
LW
SW
```

sobre direcciones alineadas:

```text
address[1:0] == 2'b00
```

Por tanto:

```text
LB / LBU    → error
SB          → error
LH / LHU    → error
SH          → error
LW / SW     → permitido
```

Esta regla es arquitectónica y no limita el fabric.

El fabric puede transportar información como:

```text
address
read/write
wdata[31:0]
size
wstrb[3:0]
```

porque RAM puede necesitar accesos sub-palabra.

> **La capacidad del fabric para transportar accesos sub-palabra es independiente del contrato MMIO.**

Incluso periféricos que conceptualmente manipulan bytes, como SERIAL, exponen registros MMIO de 32 bits.

---

# 3. Mapa físico global

```text
0000_0000 - 3FFF_FFFF    MEMORY / expansión de memoria
4000_0000 - 7FFF_FFFF    RESERVED

8000_0000 - 8000_FFFF    SYSTEM
8001_0000 - 8001_FFFF    FABRIC
8002_0000 - 8002_FFFF    SDRAM
8003_0000 - 800F_FFFF    RESERVED SYSTEM

8010_0000 - 8010_FFFF    SERIAL
8020_0000 - 8020_FFFF    VIDEO
8030_0000 - 8030_FFFF    TIMER
8040_0000 - 8040_FFFF    INTERRUPT CONTROLLER
8050_0000 - 8050_FFFF    DMA
8060_0000 - 80FF_FFFF    RESERVED PERIPHERALS

8100_0000 - 8100_FFFF    CPU CORE
8101_0000 - 8101_FFFF    CPU PERFORMANCE
8102_0000 - 8102_FFFF    CPU DEBUG
8103_0000 - 81FF_FFFF    RESERVED CPU

8200_0000 - 8200_FFFF    GPU CORE / CONTROL
8201_0000 - 8201_FFFF    GPU WARPS
8202_0000 - 8202_FFFF    GPU SIMT DEBUG
8203_0000 - 8203_FFFF    GPU PERFORMANCE
8204_0000 - 82FF_FFFF    RESERVED GPU

8300_0000 - FFFF_FFFF    RESERVED / FUTURE ACCELERATORS
```

---

# 4. Memoria principal

La implementación SDRAM actual:

```text
MEM_BASE = 0x00000000
MEM_SIZE = 0x02000000
```

corresponde a 32 MiB.

Las direcciones posteriores dentro de la región MEMORY permanecen sin implementar hasta que exista memoria física detrás.

Un acceso a memoria no implementada genera error.

---

## 4.1. Prototipos EBR

Los prototipos que utilizan EBR deben utilizar preferentemente una región contigua.

En lugar de separar artificialmente programa y datos:

```text
00000000    programa
00100000    datos
```

se utilizará una región física continua, por ejemplo:

```text
00000000 - 00007FFF    32 KiB EBR
```

La separación entre:

```text
.text
.rodata
.data
.bss
stack
```

es responsabilidad del software, assembler/linker y no del mapa físico.

Esto permite que `MEM_BASE/MEM_SIZE` describan también los prototipos EBR de forma natural.

---

# 5. Política de errores

Un acceso MMIO es inválido cuando:

1. el dispositivo no está implementado;
2. el offset no corresponde a un registro;
3. se escribe un registro RO;
4. se utiliza un acceso distinto de 32 bits;
5. la dirección está desalineada;
6. se escribe un valor arquitectónicamente inválido;
7. el master no tiene permiso;
8. una operación de control se solicita en un estado donde no es válida.

Los accesos inválidos no:

- devuelven cero silenciosamente;
- ignoran escrituras;
- corrigen valores automáticamente.

Generan error.

Conceptualmente se distinguen:

```text
ACCESS_FAULT
ALIGNMENT_FAULT
```

aunque las implementaciones actuales puedan convertir ambos en una detención del core y un código de error para el monitor.

Una futura arquitectura de excepciones podrá mapearlos a traps.

---

# 6. Acceso MMIO desde MiniGPU

MiniGPU ejecuta instrucciones SIMT, por lo que una misma instrucción puede producir accesos desde múltiples lanes.

MMIO v2 establece:

> **Una instrucción SIMT que accede a MMIO sólo es válida cuando exactamente una lane activa realiza el acceso MMIO.**

Por ejemplo:

```c
if (lane_id == 0)
    VIDEO_CTRL = VIDEO_SCANOUT;
```

es válido.

También:

```c
if (lane_id == 0)
    SERIAL_DATA = 'A';
```

es válido.

Si dos o más lanes intentan acceder a MMIO mediante la misma instrucción:

```text
MMIO access → error
```

aunque:

- utilicen la misma dirección;
- escriban el mismo valor.

No existe coalescing, broadcast ni elección implícita de una lane para MMIO.

Esta regla no se aplica a RAM.

---

# 7. SYSTEM — `0x80000000`

SYSTEM describe el sistema global.

| Offset | Registro | Acceso | Función |
|---:|---|---|---|
| `+0x00` | `MAGIC` | R | Identificación MMIO |
| `+0x04` | `MMIO_VERSION` | R | Versión del contrato |
| `+0x08` | `SYSTEM_ID` | R | Tipo/revisión del sistema |
| `+0x0C` | `DEVICES` | R | Dispositivos presentes |
| `+0x10` | `MEM_BASE` | R | Base de memoria principal |
| `+0x14` | `MEM_SIZE` | R | Tamaño de memoria |
| `+0x18` | `MONITOR_VERSION` | R | Versión del protocolo monitor |

Los offsets restantes están reservados.

---

## 7.1. MAGIC

Valor inicialmente propuesto:

```text
0x4D474155
```

Permite reconocer MMIO v2.

---

## 7.2. MMIO_VERSION

Formato:

```text
bits 15:8    major
bits  7:0    minor
bits 31:16   0
```

Un cambio incompatible incrementa `major`.

Una extensión compatible incrementa `minor`.

---

## 7.3. SYSTEM_ID

Describe el sistema global.

Debe poder distinguir configuraciones como:

```text
MiniCPU
MiniGPU
MiniCPU + MiniGPU
```

No sustituye a `CPU_ID` ni `GPU_ID`.

---

# 8. SYSTEM.DEVICES

`DEVICES` es un bitmap estable.

```text
bit  0    SYSTEM
bit  1    FABRIC
bit  2    SDRAM
bit  3    EBR
bit  4    SERIAL
bit  5    VIDEO
bit  6    TIMER
bit  7    INTERRUPT_CONTROLLER
bit  8    DMA
bit  9    CPU
bit 10    GPU

bits 31:11 reserved
```

Aunque `SYSTEM` sea necesariamente presente para leer `DEVICES`, se mantiene su bit para que el bitmap sea una descripción completa y uniforme.

Una asignación de bit congelada:

> **Nunca cambia de significado ni se reutiliza para otro dispositivo.**

Los dispositivos reservados pero no implementados tienen su bit a cero.

Ejemplos:

```text
CPU + EBR + SERIAL:

SYSTEM = 1
EBR    = 1
SERIAL = 1
CPU    = 1
```

```text
MiniGPU + SDRAM + VIDEO:

SYSTEM = 1
FABRIC = 1
SDRAM  = 1
VIDEO  = 1
GPU    = 1
```

FABRIC y SDRAM tienen bits separados porque existen configuraciones que pueden carecer de uno de ellos.

---

# 9. Descubrimiento del sistema

No se descubren dispositivos sondeando direcciones MMIO.

El procedimiento correcto es:

```text
leer SYSTEM.MAGIC
        ↓
comprobar MMIO_VERSION
        ↓
leer SYSTEM.DEVICES
        ↓
consultar los dispositivos presentes
```

Una dirección perteneciente a un dispositivo cuyo bit `DEVICES` está a cero genera error.

---

# 10. FABRIC — `0x80010000`

Se reserva un bloque propio para estado, configuración e instrumentación del fabric.

```text
0x80010000 - 0x8001FFFF
```

El bloque existe sólo en sistemas que incorporan el fabric correspondiente.

Su contenido interno no se congela todavía.

En particular, podrán incorporarse posteriormente contadores como:

- transacciones por master;
- ciclos de espera;
- arbitraje;
- utilización;
- congestión;
- stalls.

Los contadores se definirán cuando exista necesidad real de medirlos.

---

# 11. SDRAM — `0x80020000`

Se reserva:

```text
0x80020000 - 0x8002FFFF
```

para información, configuración e instrumentación específica del controlador SDRAM.

El bloque sólo existe cuando `DEVICES.SDRAM = 1`.

Su contenido se diseñará cuando sea necesario.

Posibles métricas futuras incluyen:

- lecturas;
- escrituras;
- bursts;
- ciclos busy;
- stalls;
- comportamiento de filas/bancos.

No se congelan todavía registros concretos.

---

# 12. SERIAL — `0x80100000`

| Offset | Registro | Acceso | Función |
|---:|---|---|---|
| `+0x00` | `DATA` | RW | RX/TX |
| `+0x04` | `STATUS` | RW | Estado |
| `+0x08` | `PEEK` | R | RX sin extraer |

SERIAL continúa siendo un periférico lógico aunque físicamente pueda multiplexarse sobre el UART utilizado por el monitor.

---

## 12.1. DATA

Lectura:

```text
bits 7:0     byte RX
bits 31:8    0
```

La lectura consume el byte.

Si no existe dato:

```text
DATA = 0
```

Escritura:

```text
bits 7:0     byte TX
bits 31:8    reservados/ignorados
```

La transacción MMIO sigue siendo de 32 bits.

---

## 12.2. STATUS

Inicialmente:

```text
bits  7:0     bytes disponibles RX
bits 15:8     huecos disponibles TX
bit  16       RX_OVERRUN
bits 31:17    reserved
```

`RX_OVERRUN` es sticky.

Se limpia escribiendo uno en el bit correspondiente, W1C.

---

## 12.3. PEEK

Devuelve el siguiente byte RX sin extraerlo.

Permite inspección desde monitor/debug sin introducir efectos laterales.

---

# 13. VIDEO — `0x80200000`

VIDEO agrupa:

- generación de salida;
- scanout;
- framebuffers;
- swap;
- contadores de vídeo;
- captura determinista para validación.

No se separa FRAME_CAPTURE en un periférico independiente.

La separación existente en algunos prototipos es histórica y no forma parte del contrato v2.

VIDEO es un periférico del sistema, no propiedad de CPU ni GPU.

---

# 14. Registros VIDEO

| Offset | Registro | Acceso | Función |
|---:|---|---|---|
| `+0x00` | `CTRL` | RW | Modo |
| `+0x04` | `FB_FRONT` | RW | Framebuffer visible |
| `+0x08` | `FB_BACK` | RW | Framebuffer secundario |
| `+0x0C` | `SWAP` | RW | Solicitud/estado swap |
| `+0x10` | `STATUS` | RW | Estado |
| `+0x14` | `FRAME_COUNT` | R | Frames emitidos |
| `+0x18` | `SWAP_COUNT` | R | Swaps completados |
| `+0x1C` | `HALT_AT` | RW | Captura determinista |
| `+0x20` | `HALT_TARGET` | RW | Cores a detener |
| `+0x24` | `VIDEO_TX` | R | Transacciones generadas |

---

# 15. VIDEO.CTRL

Inicialmente:

```text
bits 1:0

0    BLANK
1    PATTERN
2    SCANOUT
3    reserved

bits 31:2 = 0
```

Escribir un modo reservado genera error.

---

# 16. VIDEO.FB_FRONT / FB_BACK

Contienen direcciones físicas de byte en memoria.

Los framebuffers son RAM ordinaria.

Las bases deben estar alineadas a:

```text
16 bytes
```

Una dirección incorrectamente alineada genera error.

No se trunca ni corrige automáticamente.

---

# 17. VIDEO.SWAP

Escribir solicita:

```text
FB_FRONT <-> FB_BACK
```

El intercambio se completa en vsync.

Lectura:

```text
bit 0    SWAP_PENDING
bits 31:1 0
```

---

# 18. VIDEO.STATUS

```text
bit 0    UNDERFLOW
bit 1    SWAP_PENDING
bits 31:2 reserved
```

`UNDERFLOW` es sticky.

Se limpia mediante W1C.

Los contadores no se mezclan con STATUS.

---

# 19. VIDEO.FRAME_COUNT

Contador de 32 bits de frames emitidos.

Incrementa una vez por frame independientemente de que haya habido swap.

Wrap-around natural.

---

# 20. VIDEO.SWAP_COUNT

Contador de 32 bits de swaps completados.

Por tanto:

```text
FRAME_COUNT
```

y:

```text
SWAP_COUNT
```

miden eventos diferentes.

---

# 21. VIDEO.HALT_AT

Proporciona ejecución determinista para validación/captura.

```text
HALT_AT = 0
```

desactiva el mecanismo.

Para:

```text
HALT_AT = N
```

VIDEO solicita detener los targets seleccionados cuando:

```text
FRAME_COUNT >= N
```

La comparación es `>=` y no exclusivamente `==`.

---

# 22. VIDEO.HALT_TARGET

```text
bit 0    CPU
bit 1    GPU
bits 31:2 reserved
```

Ejemplos:

```text
0x0    ninguno
0x1    CPU
0x2    GPU
0x3    CPU + GPU
```

Esto permite que el productor de los frames y el core detenido no tengan que ser necesariamente el mismo.

---

# 23. VIDEO.VIDEO_TX

Contador de 32 bits de transacciones de memoria generadas por VIDEO.

Pertenece a VIDEO porque mide actividad originada por el dispositivo.

En el futuro FABRIC podrá exponer adicionalmente su propia visión del tráfico VIDEO.

Conceptualmente:

```text
VIDEO
  |
  | VIDEO_TX
  v
FABRIC
  |
  | fabric counters
  v
SDRAM
  |
  | controller counters
  v
memory
```

Estos contadores pueden medir puntos diferentes del camino.

---

# 24. Reset de VIDEO

Tras reset:

```text
CTRL          = PATTERN
FB_FRONT      = 0
FB_BACK       = 0
FRAME_COUNT   = 0
SWAP_COUNT    = 0
HALT_AT       = 0
HALT_TARGET   = 0
VIDEO_TX      = 0
```

El sistema no arranca directamente en SCANOUT.

PATTERN proporciona diagnóstico independiente de SDRAM.

---

# 25. TIMER — `0x80300000`

Se reserva:

```text
0x80300000 - 0x8030FFFF
```

para el futuro timer del sistema.

No se define todavía su interfaz.

Mientras no esté implementado:

```text
DEVICES.TIMER = 0
```

y cualquier acceso genera error.

---

# 26. INTERRUPT CONTROLLER — `0x80400000`

Se reserva:

```text
0x80400000 - 0x8040FFFF
```

para el futuro controlador de interrupciones.

No se congela todavía su interfaz.

Fuentes futuras previstas incluyen al menos:

```text
GPU WARP_DONE
GPU ERROR
```

además de TIMER y futuros periféricos.

---

# 27. DMA — `0x80500000`

Se reserva:

```text
0x80500000 - 0x8050FFFF
```

para un futuro motor DMA.

Mientras no exista:

```text
DEVICES.DMA = 0
```

---

# 28. CPU CORE — `0x81000000`

Registros iniciales:

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `CPU_ID` | R |
| `+0x04` | `CPU_VERSION` | R |
| `+0x08` | `CPU_ISA` | R |
| `+0x0C` | `CPU_FEATURES` | R |
| `+0x10` | `CPU_STATUS` | R |

`CPU_ISA` describe capacidades arquitectónicas.

`CPU_FEATURES` describe características de la implementación.

Las asignaciones concretas de bits se documentarán junto con MiniISA.

---

# 29. CPU PERFORMANCE — `0x81010000`

Registros iniciales:

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `CYCLES` | R |
| `+0x04` | `RETIRED` | R |
| `+0x08` | `IMEM_HITS` | R |
| `+0x0C` | `IMEM_MISSES` | R |
| `+0x10` | `MEM_TX` | R |
| `+0x14` | `STALL_MEM` | R |
| `+0x18` | `PERF_CTRL` | RW |

Inicialmente los contadores son de 32 bits y realizan wrap-around.

`PERF_CTRL`:

```text
bit 0    RESET_COUNTERS
bits 31:1 reserved
```

Escribir `1` pone los contadores a cero.

---

# 30. CPU DEBUG — `0x81020000`

Se reserva un bloque separado para estado de depuración específico de CPU.

No se congelan registros adicionales hasta que exista una necesidad concreta.

---

# 31. GPU CORE / CONTROL — `0x82000000`

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `GPU_ID` | R |
| `+0x04` | `GPU_VERSION` | R |
| `+0x08` | `GPU_ISA` | R |
| `+0x0C` | `GPU_FEATURES` | R |
| `+0x10` | `GPU_CAPS` | R |
| `+0x14` | `GPU_STATUS` | R |
| `+0x18` | `GPU_CONTROL` | RW |
| `+0x1C` | `WARP_START` | W |
| `+0x20` | `WARP_LIVE` | R |
| `+0x24` | `WARP_DONE` | RW |

---

# 32. GPU_CAPS

Formato inicial:

```text
bits  7:0    NUM_WARPS
bits 15:8    NUM_LANES
bits 31:16   reserved
```

La implementación actual:

```text
NUM_WARPS = 8
NUM_LANES = 8
```

El software no debe asumir estos valores.

MMIO v2 reserva máscaras de 32 bits para gestión de warps, permitiendo hasta 32 warps sin modificar el ABI.

Una futura GPU con más de 32 warps podrá extender el bloque mediante registros adicionales.

---

# 33. GPU_STATUS

```text
bit 0       RUNNING
bit 1       HALTED
bit 2       IDLE
bit 3       ERROR
bits 15:8   LIVE_WARPS
bits 31:16  reserved
```

Semántica:

```text
RUNNING
    existe ejecución GPU activa

HALTED
    ejecución global pausada

IDLE
    no queda ningún warp vivo

ERROR
    existe un error GPU pendiente

LIVE_WARPS
    número actual de warps vivos
```

`IDLE` es preferible a un `DONE` global porque la GPU puede recibir nuevos warps dinámicamente.

---

# 34. GPU_CONTROL

Bits de comando:

```text
bit 0    RUN
bit 1    HALT
bit 2    RESUME
bit 3    STEP
bit 4    RESET
bits 31:5 reserved
```

Los bits son comandos.

Escribir uno ejecuta la acción correspondiente.

Leer devuelve cero en los bits de comando.

No deben escribirse simultáneamente comandos incompatibles.

---

# 35. GPU_CONTROL.RUN

`RUN` proporciona el mecanismo sencillo de lanzamiento global.

Antes de `RUN`, software configura los descriptores de warp.

`RUN` arranca todos los warps implementados cuya máscara inicial de lanes sea distinta de cero.

Conceptualmente:

```text
for each implemented warp n:

    if WARP[n].ACTIVE != 0:
        start warp n
```

El lanzamiento inicializa el estado runtime a partir del descriptor.

`RUN` sólo es válido cuando no existen warps vivos.

Ejecutar `RUN` mientras algún warp está vivo genera error.

---

# 36. GPU_CONTROL.HALT

`HALT` pausa globalmente la ejecución GPU.

Conserva:

- PCs;
- máscaras live;
- SIMT stacks;
- waits;
- estado LSU necesario;
- estado de barreras;
- demás estado runtime.

Los warps no se reinicializan.

---

# 37. GPU_CONTROL.RESUME

Continúa una GPU detenida mediante `HALT`.

Sólo es válido cuando:

```text
HALTED = 1
```

En otro estado genera error.

---

# 38. GPU_CONTROL.STEP

Ejecuta una unidad de avance de depuración estando la GPU detenida.

Su semántica debe coincidir con la operación STEP utilizada por el monitor.

Sólo es válido con:

```text
HALTED = 1
```

Tras STEP la GPU permanece detenida.

---

# 39. GPU_CONTROL.RESET

`RESET` descarta el estado runtime de ejecución GPU:

- warps vivos;
- SIMT stacks;
- waits;
- barreras;
- errores runtime;
- estado temporal del lanzamiento.

No modifica los descriptores programados en `GPU_WARPS`.

Por tanto puede hacerse:

```text
GPU_CONTROL.RESET
GPU_CONTROL.RUN
```

para repetir un lanzamiento utilizando la misma configuración.

El reset físico del SoC sigue siendo una operación distinta y reinicia también los registros arquitectónicos que corresponda.

---

# 40. WARP_START

`WARP_START` es una máscara de 32 bits.

```text
bit n = 1
```

solicita arrancar el warp `n`.

Permite añadir trabajo mientras otros warps siguen ejecutando.

Ejemplo:

```text
WARP_LIVE  = 00001011

warp 2 está libre
```

CPU configura `WARP[2]` y escribe:

```text
WARP_START = 00000100
```

El warp 2 comienza a ejecutar sin afectar a los demás.

Es error intentar arrancar:

- un warp no implementado;
- un warp que ya está vivo;
- un descriptor cuya máscara inicial de lanes sea cero.

---

# 41. WARP_LIVE

Máscara de 32 bits de solo lectura.

```text
bit n = 1    warp n está vivo
bit n = 0    warp n está libre/no ejecutando
```

Los bits correspondientes a warps no implementados son cero.

---

# 42. WARP_DONE

Máscara sticky de 32 bits.

Cuando un warp termina:

```text
WARP_DONE[n] = 1
```

Los eventos no se pierden aunque CPU tarde en observarlos.

Ejemplo:

```text
warp 0 termina
warp 3 termina

WARP_DONE = 00001001
```

Los bits son W1C:

```text
write 1 → clear
write 0 → unchanged
```

Cuando `RUN` o `WARP_START` arranca un warp:

```text
WARP_DONE[n] = 0
```

automáticamente.

Esto permite reutilizar slots de ejecución de forma natural.

En el futuro:

```text
WARP_DONE != 0
```

podrá generar una interrupción GPU.

---

# 43. Scheduling software de GPU

MMIO v2 permite dos modelos.

## Modelo sencillo

```text
configurar todos los warps
        |
        v
GPU_CONTROL.RUN
        |
        v
ejecutar hasta IDLE
```

Adecuado para programas sencillos y GPU autónoma.

## Scheduler dinámico

```text
CPU mantiene cola de trabajo en RAM
        |
        v
consulta WARP_LIVE / WARP_DONE
        |
        v
encuentra slot libre
        |
        v
programa WARP[n]
        |
        v
WARP_START[n]
```

Esto permite mantener la GPU ocupada reutilizando warps físicos sin necesidad inicial de un command processor hardware.

---

# 44. GPU WARPS — `0x82010000`

Cada warp dispone de un descriptor de 16 bytes:

```text
base + 16*n
```

Formato:

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `PC` | RW |
| `+0x04` | `ACTIVE` | RW |
| `+0x08` | `WORKGROUP_ID` | RW |
| `+0x0C` | `SIMT_STATE` | R |

---

# 45. WARP.ACTIVE

Es la máscara inicial de lanes.

Para la implementación actual de 8 lanes:

```text
0x00    warp deshabilitado
0x01    lane 0
0x0F    lanes 0..3
0xFF    lanes 0..7
```

Los bits superiores a `NUM_LANES` deben ser cero.

No existe un `WARP_ENABLE` independiente.

> **ACTIVE == 0 significa descriptor deshabilitado para RUN.**

---

# 46. WARP.SIMT_STATE

Estado runtime de solo lectura.

Inicialmente:

```text
bits  7:0     REGION depth
bits 15:8     PATH depth
bit  16       WAIT_MEM
bit  17       WAIT_BAR
bits 31:18    reserved
```

Escribir genera error.

La información global `LIVE` se obtiene mediante `WARP_LIVE`, evitando mezclar configuración y scheduling dentro del descriptor.

---

# 47. GPU SIMT DEBUG — `0x82020000`

El bloque contiene exclusivamente información de depuración/microarquitectura SIMT.

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `CONTEXT` | RW |
| `+0x04` | `LSU_SLOTS` | R |
| `+0x08` | `FIRST_ERROR` | R |
| `+0x0C` | `FIRST_ERROR_PC` | R |
| `+0x10` | `WARP_RETIRED` | R |

Se elimina el contador global `RETIRED` de este bloque.

Pertenece a GPU PERFORMANCE.

---

# 48. SIMT_DEBUG.CONTEXT

Selecciona inicialmente:

```text
bits 2:0    lane
bits 5:3    warp
bits 31:6   reserved
```

Permite que monitor/debug consulte estado correspondiente a una lane/warp concreta.

---

# 49. SIMT_DEBUG.LSU_SLOTS

Describe el estado instantáneo de slots de la LSU.

Permanece en DEBUG porque es información microarquitectónica instantánea, no un contador de rendimiento.

La LSU forma parte de MiniGPU.

---

# 50. SIMT_DEBUG.FIRST_ERROR

Conserva el primer error detectado.

Formato inicial:

```text
bits 2:0     lane
bits 5:3     warp
bit  6       lane_valid
bits 15:8    error_code
bits 31:16   reserved
```

`FIRST_ERROR_PC` contiene el PC correspondiente.

---

# 51. GPU PERFORMANCE — `0x82030000`

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `CYCLES` | R |
| `+0x04` | `RETIRED` | R |
| `+0x08` | `IMEM_HITS` | R |
| `+0x0C` | `IMEM_MISSES` | R |
| `+0x10` | `LSU_TX` | R |
| `+0x14` | `STALL_MEM` | R |
| `+0x18` | `PERF_CTRL` | RW |

`VIDEO_TX` ya no pertenece a GPU PERFORMANCE.

La LSU sí pertenece a GPU, por lo que:

```text
LSU_TX
STALL_MEM
```

permanecen aquí.

---

# 52. Separación de performance

MMIO v2 distingue:

```text
CPU PERFORMANCE
GPU PERFORMANCE
VIDEO counters
FABRIC instrumentation
SDRAM instrumentation
```

Cada contador debe pertenecer al componente que genera u observa el evento.

Esto permite localizar posteriormente dónde aparece un cuello de botella:

```text
GPU LSU
   |
   v
FABRIC
   |
   v
SDRAM
```

sin mezclar eventos de capas diferentes.

---

# 53. Visibilidad inicial por master

## CPU

En un SoC integrado, CPU puede acceder a:

```text
SYSTEM              R
FABRIC              según registro
SDRAM               según registro
SERIAL              RW
VIDEO               RW
TIMER                futuro
INTC                 futuro
DMA                  futuro

CPU CORE             según registro
CPU PERFORMANCE      según registro
CPU DEBUG            según registro

GPU CORE/CONTROL     RW según registro
GPU WARPS            RW
GPU SIMT DEBUG       R / debug
GPU PERFORMANCE      R / control autorizado
```

La CPU configura y lanza GPU exclusivamente mediante MMIO.

No necesita instrucciones especiales para ello.

---

## GPU

Inicialmente puede acceder a:

```text
SYSTEM              R
SERIAL              RW mediante acceso MMIO escalar
VIDEO               RW mediante acceso MMIO escalar
GPU information      R
GPU PERFORMANCE      según registro
```

El acceso desde warp a registros de scheduling/control puede restringirse.

En particular, un warp no debe reprogramarse a sí mismo accidentalmente mediante `GPU_WARPS` o `WARP_START`.

---

## Monitor

El monitor puede alcanzar todos los dispositivos implementados para depuración.

Sigue sujeto a:

- RO/RW;
- alineamiento;
- tamaños;
- efectos laterales;
- valores válidos.

---

# 54. Monitor: tamaños de acceso

El protocolo del monitor debe distinguir RAM y MMIO correctamente.

Se mantienen:

```text
READ_BYTE
WRITE_BYTE
```

para RAM.

Se añaden:

```text
READ_WORD
WRITE_WORD
```

para accesos de 32 bits.

`READ_WORD/WRITE_WORD` pueden utilizarse tanto para RAM como para MMIO.

Un `READ_BYTE/WRITE_BYTE` dirigido a MMIO no debe convertirse en un acceso sub-palabra al periférico.

Las transferencias de bloque pueden mantenerse para carga eficiente de memoria.

---

# 55. Monitor e identidad del hardware

`MONITOR_VERSION` describe únicamente el protocolo.

La identidad del hardware se obtiene mediante:

```text
SYSTEM
CPU CORE
GPU CORE
DEVICES
FEATURES
CAPS
```

Esto permite utilizar un monitor común o parametrizado sin asociar artificialmente una versión de protocolo a una configuración concreta de FPGA.

---

# 56. Simuladores

Los simuladores deben implementar el mismo contrato que RTL:

- mismas direcciones;
- mismos registros;
- mismos tamaños;
- mismo reset;
- mismos errores;
- mismas restricciones;
- mismos efectos laterales arquitectónicos.

No existirán programas separados `*_nommio` por limitaciones artificiales del simulador.

VIDEO puede modelarse funcionalmente sin reproducir eléctricamente HDMI.

---

# 57. Orden CPU-GPU

En el SoC integrado debe garantizarse:

```text
CPU escribe código/datos
        ↓
CPU escribe descriptores GPU
        ↓
escrituras anteriores visibles
        ↓
RUN / WARP_START
        ↓
GPU ejecuta
        ↓
GPU completa sus escrituras
        ↓
WARP_DONE / IDLE visible
        ↓
CPU consume resultados
```

Un evento de finalización no debe hacerse visible antes de que las escrituras arquitectónicamente asociadas al trabajo hayan alcanzado el punto de coherencia acordado.

El mecanismo concreto puede utilizar:

- orden fuerte de MMIO;
- drain de buffers;
- fences;
- protocolo del fabric.

Se definirá al integrar CPU y GPU.

---

# 58. Dominios de reloj

El mapa físico es independiente de las frecuencias.

CPU, GPU, fabric, SDRAM y VIDEO pueden utilizar dominios distintos.

Los adaptadores/fabric resuelven:

- CDC;
- handshake;
- arbitraje;
- backpressure.

Una diferencia de reloj nunca modifica el significado de una dirección.

---

# 59. Estado global tras reset

Principio:

> **El sistema arranca en un estado seguro, reproducible y diagnosticable.**

Como mínimo:

```text
VIDEO
    PATTERN
    FB_FRONT = 0
    FB_BACK = 0
    HALT_AT = 0

GPU
    ningún warp vivo
    WARP_DONE = 0
    no HALTED
    sin error runtime

CPU PERF
    counters = 0

GPU PERF
    counters = 0

SERIAL
    queues empty
```

---

# 60. Fuente única de constantes arquitectónicas

La fuente maestra del mapa MMIO será un include Verilog simple, por ejemplo:

```text
rtl/include/mmio_map.vh
```

Contendrá exclusivamente constantes arquitectónicas.

Ejemplo:

```verilog
`define MMIO_SYSTEM_BASE       32'h8000_0000
`define MMIO_FABRIC_BASE       32'h8001_0000
`define MMIO_SDRAM_BASE        32'h8002_0000

`define MMIO_SERIAL_BASE       32'h8010_0000
`define MMIO_VIDEO_BASE        32'h8020_0000
`define MMIO_TIMER_BASE        32'h8030_0000
`define MMIO_INTC_BASE         32'h8040_0000
`define MMIO_DMA_BASE          32'h8050_0000

`define MMIO_CPU_BASE          32'h8100_0000
`define MMIO_CPU_PERF_BASE     32'h8101_0000
`define MMIO_CPU_DEBUG_BASE    32'h8102_0000

`define MMIO_GPU_BASE          32'h8200_0000
`define MMIO_GPU_WARPS_BASE    32'h8201_0000
`define MMIO_GPU_SIMT_BASE     32'h8202_0000
`define MMIO_GPU_PERF_BASE     32'h8203_0000
```

También contendrá offsets y bits arquitectónicos.

---

# 61. Generación de constantes para software

`mmio_map.vh` se mantendrá deliberadamente sencillo:

```text
define + nombre + constante
```

sin lógica RTL ni expresiones complejas.

Una herramienta podrá generar:

```text
mmio_map.vh
     |
     +----> minisoc.inc
     |
     +----> minisoc.h
     |
     +----> minisoc_mmio.py
```

para:

- assembler;
- C;
- monitor;
- simuladores;
- herramientas.

Así las direcciones no se duplican manualmente.

---

# 62. Assembler y futuro linker

A corto plazo el assembler debe poder compartir definiciones arquitectónicas, por ejemplo mediante:

```asm
.include "minisoc.inc"
```

El fichero generado podrá contener:

```asm
.equ VIDEO_BASE,       0x80200000
.equ VIDEO_CTRL,       0x80200000
.equ VIDEO_FB_FRONT,   0x80200004

.equ GPU_BASE,         0x82000000
.equ GPU_CONTROL,      0x82000018
...
```

A medio plazo será conveniente soportar:

- múltiples archivos;
- símbolos externos;
- relocations;
- `.text`;
- `.rodata`;
- `.data`;
- `.bss`;
- linker script.

La existencia del futuro linker no bloquea MMIO v2.

---

# 63. Evolución del mapa

Las direcciones congeladas son ABI.

No se renumeran dispositivos para mantener un supuesto orden conceptual.

Los nuevos dispositivos utilizan regiones libres.

Por ejemplo, si aparece posteriormente otro periférico:

```text
8060_xxxx    NEW_DEVICE
```

es preferible a mover TIMER, INTC o DMA.

Igualmente CPU/GPU pueden añadir nuevos sub-bloques dentro de sus regiones sin afectar al resto.

---

# 64. Decisiones congeladas de MMIO v2

Quedan fijados los siguientes principios:

1. Un único espacio físico global.
2. Una dirección tiene un único significado.
3. Los permisos son independientes del mapa.
4. MMIO comienza en `0x80000000`.
5. La región de memoria dispone de amplio margen de crecimiento.
6. Se abandona la página MMIO única de 4 KiB.
7. Se abandonan los slots globales de 256 bytes.
8. Los dispositivos utilizan bloques grandes y alineados.
9. CPU y GPU disponen de regiones propias.
10. FABRIC y SDRAM disponen de bloques propios.
11. TIMER, INTC y DMA tienen espacio reservado.
12. MMIO sólo admite palabras de 32 bits alineadas.
13. RAM puede admitir accesos sub-palabra.
14. Los accesos inválidos producen error.
15. MMIO SIMT requiere exactamente una lane realizando el acceso.
16. VIDEO es un único dispositivo.
17. FRAME_CAPTURE no existe como dispositivo independiente.
18. FRAME_COUNT y SWAP_COUNT son registros de 32 bits separados.
19. HALT_AT utiliza FRAME_COUNT.
20. HALT_TARGET puede seleccionar CPU, GPU o ambos.
21. VIDEO_TX pertenece a VIDEO.
22. CPU PERFORMANCE y GPU PERFORMANCE tienen direcciones diferentes.
23. LSU pertenece a GPU.
24. SIMT DEBUG y GPU PERFORMANCE permanecen separados.
25. RUN lanza de forma sencilla los descriptores habilitados.
26. WARP_START permite scheduling dinámico.
27. WARP_LIVE representa los slots actualmente ocupados.
28. WARP_DONE es sticky y W1C.
29. MMIO v2 reserva máscaras para hasta 32 warps.
30. GPU_CAPS declara NUM_WARPS y NUM_LANES reales.
31. HALT/RESUME/STEP/RESET forman parte de GPU_CONTROL.
32. GPU_CONTROL.RESET conserva los descriptores.
33. La CPU controla GPU mediante MMIO.
34. El monitor utilizará READ_WORD/WRITE_WORD para MMIO.
35. READ_BYTE/WRITE_BYTE permanecen disponibles para RAM.
36. DEVICES tiene asignaciones estables.
37. FABRIC y SDRAM tienen bits DEVICES independientes.
38. EBR debe mapearse preferentemente como memoria contigua.
39. Simuladores y RTL implementan el mismo contrato.
40. Las constantes arquitectónicas parten de una fuente Verilog común.
41. Las direcciones congeladas no se renumeran.

---

# 65. Aspectos deliberadamente pospuestos

No son cuestiones abiertas del contrato básico, sino interfaces que se definirán cuando se implemente el hardware correspondiente:

### FABRIC

Registros internos y contadores de rendimiento.

### SDRAM

Registros internos y contadores del controlador.

### TIMER

Interfaz y frecuencia.

### INTERRUPT CONTROLLER

Fuentes, pending, masks, enables, prioridades y vectores.

Se prevén al menos futuras fuentes:

```text
GPU WARP_DONE
GPU ERROR
TIMER
```

### DMA

Canales, descriptores, tamaños y política de arbitraje.

### CPU/GPU memory ordering

El mecanismo exacto de fence/drain necesario para garantizar visibilidad entre CPU y GPU se definirá durante la integración del SoC.

---

# 66. Resumen visual

```text
0000_0000 ┌─────────────────────────────────────────────┐
          │ MEMORY                                      │
          │ actual SDRAM: 0000_0000 - 01FF_FFFF       │
3FFF_FFFF └─────────────────────────────────────────────┘

4000_0000 ┌─────────────────────────────────────────────┐
          │ RESERVED                                    │
7FFF_FFFF └─────────────────────────────────────────────┘


8000_0000 ┌─────────────────────────────────────────────┐
          │ SYSTEM                                      │
8000_FFFF └─────────────────────────────────────────────┘

8001_0000 ┌─────────────────────────────────────────────┐
          │ FABRIC                                      │
8001_FFFF └─────────────────────────────────────────────┘

8002_0000 ┌─────────────────────────────────────────────┐
          │ SDRAM                                       │
8002_FFFF └─────────────────────────────────────────────┘


8010_0000 ┌─────────────────────────────────────────────┐
          │ SERIAL                                      │
8010_FFFF └─────────────────────────────────────────────┘

8020_0000 ┌─────────────────────────────────────────────┐
          │ VIDEO                                       │
8020_FFFF └─────────────────────────────────────────────┘

8030_0000 ┌─────────────────────────────────────────────┐
          │ TIMER                  [reserved]            │
8030_FFFF └─────────────────────────────────────────────┘

8040_0000 ┌─────────────────────────────────────────────┐
          │ INTERRUPT CONTROLLER   [reserved]            │
8040_FFFF └─────────────────────────────────────────────┘

8050_0000 ┌─────────────────────────────────────────────┐
          │ DMA                    [reserved]            │
8050_FFFF └─────────────────────────────────────────────┘


8100_0000 ┌─────────────────────────────────────────────┐
          │ CPU CORE                                    │
8100_FFFF └─────────────────────────────────────────────┘

8101_0000 ┌─────────────────────────────────────────────┐
          │ CPU PERFORMANCE                             │
8101_FFFF └─────────────────────────────────────────────┘

8102_0000 ┌─────────────────────────────────────────────┐
          │ CPU DEBUG                                   │
8102_FFFF └─────────────────────────────────────────────┘


8200_0000 ┌─────────────────────────────────────────────┐
          │ GPU CORE / CONTROL                          │
          │                                             │
          │ ID / VERSION / ISA / FEATURES / CAPS        │
          │ STATUS / CONTROL                            │
          │ WARP_START / WARP_LIVE / WARP_DONE          │
8200_FFFF └─────────────────────────────────────────────┘

8201_0000 ┌─────────────────────────────────────────────┐
          │ GPU WARP DESCRIPTORS                        │
8201_FFFF └─────────────────────────────────────────────┘

8202_0000 ┌─────────────────────────────────────────────┐
          │ GPU SIMT DEBUG                              │
8202_FFFF └─────────────────────────────────────────────┘

8203_0000 ┌─────────────────────────────────────────────┐
          │ GPU PERFORMANCE                             │
8203_FFFF └─────────────────────────────────────────────┘


8300_0000 ┌─────────────────────────────────────────────┐
          │ RESERVED / FUTURE ACCELERATORS              │
FFFF_FFFF └─────────────────────────────────────────────┘
```

---

# 67. Regla arquitectónica final

MMIO v2 puede resumirse mediante cuatro reglas:

> **Una dirección, un significado.**

> **El mapa identifica hardware; los permisos determinan quién puede utilizarlo.**

> **RAM admite los tamaños definidos por MiniISA; MMIO opera siempre sobre registros completos de 32 bits alineados.**

> **MiniGPU puede acceder a MMIO desde código SIMT únicamente cuando la instrucción produce una única transacción escalar desde una lane.**

Estas reglas deben mantenerse aunque el sistema evolucione hacia múltiples masters, interrupciones, DMA, protección de memoria, nuevos aceleradores o configuraciones de CPU/GPU diferentes.