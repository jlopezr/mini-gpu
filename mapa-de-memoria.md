# Mapa de memoria de MiniCPU y MiniGPU

Este documento distingue **los mapas implementados** del **mapa propuesto para
una FPGA con CPU + GPU**. Las direcciones de las tablas son inclusivas, salvo
cuando se indica expresamente un límite exclusivo.

La referencia CPU más completa es [21.fpga-cpu-hdmi-alu](21.fpga-cpu-hdmi-alu/README.md).
Para GPU se consideran [12.fpga-gpu](12.fpga-gpu/README.md),
[14.fpga-gpu-ram](14.fpga-gpu-ram/README.md) y
[17.fpga-gpu-ram-v2](17.fpga-gpu-ram-v2/README.md).
La propuesta de integración de §6 **no está aplicada al RTL ni a los monitores**.

## 1. Resumen de implementaciones actuales

| Backend / versión | Carpeta | Memoria de programa y datos | MMIO / dispositivos | Monitor esperado |
|---|---|---|---|---|
| `cpu-simulator / current` | `2.cpu-sim-func` | 32 MiB en el runner | Vídeo y serie opcionales según configuración del caso | — |
| `cpu-fpga / ebr` | `6.fpga-cpu` | Dos bancos EBR de 16 KiB | Sin MMIO de periféricos | 1.16 |
| `cpu-fpga / sdram` | `10.fpga-cpu-ram` | 32 MiB SDRAM | Sin MMIO de periféricos | 1.17 |
| `cpu-fpga / hdmi` | `16.fpga-cpu-hdmi` | 32 MiB SDRAM | Vídeo | 1.18 |
| `cpu-fpga / bl8` | `18.fpga-cpu-hdmi-bl8` | 32 MiB SDRAM | Vídeo y control de captura | 1.19 |
| `cpu-fpga / subword` | `19.fpga-cpu-hdmi-ls` | 32 MiB SDRAM | Vídeo, captura y serie | 1.20 |
| `cpu-fpga / alu` | `21.fpga-cpu-hdmi-alu` | 32 MiB SDRAM | Mismo mapa de periféricos que la 19 | 1.15 |
| `gpu-simulator / current` | `11.gpu-sim-func` | 32 MiB por defecto | Configuración por API Python, sin ventanas MMIO equivalentes | — |
| `gpu-fpga / bram` | `12.fpga-gpu` | 128 KiB EBR continuos | Configuración y depuración, solo host | 2.3 |
| `gpu-fpga / sdram` | `14.fpga-gpu-ram` | 32 MiB SDRAM | Configuración y depuración, solo host | 2.4 |
| GPU SDRAM con optimizaciones | `17.fpga-gpu-ram-v2` | 32 MiB SDRAM | Mismo mapa que la 14 | 2.4 |

La 17 comparte perfil funcional con la 14; no tiene un nombre de versión propio
en la tabla del backend GPU. Los números de monitor identifican contratos de
bitstream y no ordenan capacidades: la 21 conserva 1.15, aunque otras CPU tengan
números mayores tras el backport de R0. Todas las implementaciones vigentes
usan R0 cableado a cero.

Fuentes de selección: [backend CPU FPGA](x.cpu-tests/backends/fpga.py),
[backend CPU simulado](x.cpu-tests/backends/simulator.py) y
[backend GPU FPGA](x.cpu-tests/backends/gpu_fpga.py).
Las capabilities de instrucciones y las de periféricos son independientes del
tamaño de RAM; el mapa de memoria no basta para decidir si un binario es ejecutable.

## 2. Memoria de programa y datos

### CPU con EBR: carpeta 6

| Rango | Tamaño | Uso convencional |
|---|---:|---|
| `0x00000000–0x00003FFF` | 16 KiB | Programa |
| `0x00100000–0x00103FFF` | 16 KiB | Datos |

El espacio no es contiguo. Los puertos de instrucciones y datos alcanzan ambos
bancos: la separación de usos es una convención. Los huecos no son memoria
válida. El cliente declara ambos intervalos en
[monitor.py](6.fpga-cpu/monitor.py); el validador de bloques y la respuesta del
bus comprueban aspectos distintos, por lo que no basta con validar un tamaño total.

### CPU y GPU con SDRAM

| Rango | Tamaño | Significado |
|---|---:|---|
| `0x00000000–0x01FFFFFF` | 32 MiB | Memoria unificada de programa y datos |
| `0x02000000` | — | Primer byte fuera de SDRAM |

No hay traducción implícita por banco. La última palabra alineada comienza en
`0x01FFFFFC`. La memoria es little-endian. Las tecnologías de transferencia
BL1/BL8, arbitraje y buffers cambian según la implementación, no las direcciones.

En las variantes CPU con vídeo, las bases iniciales de framebuffer son
`0x01000000` y `0x01025800`: dos imágenes RGB565 de 320 × 240, de 153600 bytes
cada una. Son regiones de RAM ordinaria elegidas por configuración, no MMIO ni
reservas impuestas a todos los programas. El flujo inicial de Mandelbrot usa
otra convención, una palabra por pixel a partir de `0x00100000`.

### GPU con EBR: carpeta 12

La GPU dispone de `0x00000000–0x0001FFFF`, 128 KiB continuos y compartidos para
código y datos de los warps. El límite exclusivo es `0x00020000`.

### Simuladores

El runner configura 32 MiB para MiniCPU. Su clase de CPU admite dispositivos
opcionales `VideoDevice` y `SerialDevice`, en las direcciones de las variantes
FPGA. Sin el dispositivo configurado, el acceso a esa dirección falla; no se
simula automáticamente toda la ventana de 4 KiB con el comportamiento del RTL.
Los accesos CPU sub-palabra a MMIO son rechazados por el simulador.

MiniGPU mantiene PC, máscaras y configuración de warps como estado del modelo,
accesible por la API de lanzamiento y observación. No ofrece a los kernels la
ventana de configuración MMIO del monitor FPGA.

## 3. MMIO de CPU: vídeo y serie

### Ventanas por versión

| Carpeta | Ventana publicada por el cliente | Registros implementados |
|---|---|---|
| 16 | `0x80000000–0x8000000F` | Cuatro registros de vídeo |
| 18 | `0x80000000–0x8000001F` | Añade `SWAP_COUNT` y `HALT_AT` |
| 19 y 21 | `0x80000000–0x80000FFF` | Dieciséis slots de dispositivo de 256 bytes |

La ventana publicada no significa que cada dirección tenga un registro útil.
En la 21, CPU y monitor se arbitran sobre el mismo bus MMIO. El adaptador de
CPU reconoce el prefijo `address[31:12] == 0x80000` y entrega el offset de 12 bits.

### Reparto de dispositivos de la 21

| Rango | Dispositivo |
|---|---|
| `0x80000000–0x800000FF` | Vídeo |
| `0x80000100–0x800001FF` | Reservado para depuración; no implementado en CPU |
| `0x80000200–0x800002FF` | Puerto serie |
| `0x80000300–0x80000FFF` | Slots libres |

El [decodificador MMIO](21.fpga-cpu-hdmi-alu/mmio_decoder.v) devuelve cero para
slots no implementados e ignora sus escrituras. Esto es distinto del error que
produce la GPU en direcciones de registro no válidas.

### Registros de vídeo

| Dirección | Registro | Acceso y efecto |
|---|---|---|
| `0x80000000` | `FB_FRONT` | R/W: dirección del framebuffer visible |
| `0x80000004` | `FB_BACK` | R/W: dirección del framebuffer trasero |
| `0x80000008` | `SWAP` | Escribir solicita intercambio; leer bit 0 indica pendiente |
| `0x8000000C` | `STATUS` | Bit 0 underflow, bit 1 swap pendiente, bits 31:16 contador de frames; escribir bit 0 borra underflow |
| `0x80000010` | `SWAP_COUNT` | R: intercambios desde reset o armado de `HALT_AT`; desde la 18 |
| `0x80000014` | `HALT_AT` | R/W: parar CPU tras N intercambios; armar reinicia el contador; cero desactiva; desde la 18 |

Las bases se alinean a cuatro bytes. El intercambio se aplica en el límite de
frame implementado por el scanout. `HALT_AT` es control de prueba de CPU, no un
comando de lanzamiento GPU. Fuente:
[video_registers.v](21.fpga-cpu-hdmi-alu/video_registers.v).

### Registros de serie

| Dirección | Registro | Acceso y efecto |
|---|---|---|
| `0x80000200` | `DATA` | Leer extrae un byte RX, o cero si vacío; escribir inserta el byte bajo en TX, descartándolo si está lleno |
| `0x80000204` | `STATUS` | Bits 7:0 bytes RX, 15:8 huecos TX, bit 16 overrun; escribir uno en bit 16 lo borra |
| `0x80000208` | `PEEK` | Leer consulta la cabeza RX sin extraerla |

Es un dispositivo de colas; los bytes del PC viajan encapsulados mediante
`SEND_BYTES/RECV_BYTES` del monitor. No es un segundo UART físico independiente.
Las lecturas de `DATA` tienen efectos laterales: para inspección desde el host
se usa `PEEK` y para transporte se usan los comandos de paquetes. Leer una
palabra mediante varios accesos byte a byte no equivale a una única lectura
CPU con efectos laterales. Fuente: [serial_port.v](21.fpga-cpu-hdmi-alu/serial_port.v).

## 4. MMIO de GPU: configuración y depuración del host

Las carpetas 12, 14 y 17 mantienen los mismos offsets. El decodificador reconoce
la página `0x80000000–0x80000FFF`, pero solo las ventanas siguientes son válidas.
Son accesibles por el puerto host del monitor, **con la GPU detenida**. Los
`LOAD/STORE` de los kernels no acceden a ellas.

### Configuración por warp: `0x80000000–0x8000007F`

Ocho descriptores de 16 bytes:

| Dirección | Contenido | Acceso |
|---|---|---|
| `0x80000000 + 16*w` | PC del warp | R/W |
| `0x80000004 + 16*w` | active en bits 7:0 y live en bits 15:8; escribir el byte bajo fija ambas | R/W |
| `0x80000008 + 16*w` | `workgroup_id` | R/W |
| `0x8000000C + 16*w` | Profundidad REGION en bits 7:0, PATH en 15:8, WAIT_MEM bit 16 y WAIT_BAR bit 17 | R |

La escritura de configuración reinicia el estado de reconvergencia/barrera y
el contador local del warp según el contrato del SM. No es una interfaz para
modificar contexto arbitrariamente mientras el warp ejecuta.
El cuarto word contiene estado: no está libre para `warp_user_id`.

### Depuración global: `0x80000100–0x80000117`

| Dirección | Contenido | Acceso |
|---|---|---|
| `0x80000100` | Contexto seleccionado: lane en bits 2:0 y warp en bits 5:3 | R/W |
| `0x80000104` | Slots LSU ocupados, bits 7:0 | R |
| `0x80000108` | Instrucciones retiradas globales | R |
| `0x8000010C` | Primer error: lane 2:0, warp 5:3, lane_valid bit 6, error_code 15:8 | R |
| `0x80000110` | PC del primer error | R |
| `0x80000114` | Instrucciones retiradas del warp seleccionado | R |

La selección de contexto también gobierna `READ_REG`. No se debe confundir el
comando UART de lectura de registros con una ventana de 32 registros MMIO.

Los comandos run/halt/step/reset llegan al sistema GPU mediante señales desde
el monitor, **no mediante registros de lanzamiento en estas ventanas**. El
puerto host rechaza transacciones mientras la GPU no está detenida. Una
transferencia aceptada conserva su petición hasta finalizar; el acceso a RAM
del host comparte el puerto auxiliar con fetch una vez drenada la LSU.

Fuentes: [gpu_system.v](17.fpga-gpu-ram-v2/gpu_system.v),
[top.v](17.fpga-gpu-ram-v2/top.v) y [monitor.py](17.fpga-gpu-ram-v2/monitor.py).
Las palabras en memoria son little-endian; el formato de la dirección dentro
del paquete UART pertenece al protocolo, no al orden de bytes de la ISA.

## 5. Colisión entre los mapas existentes

| Dirección | CPU 21 | GPU 17 |
|---|---|---|
| `0x80000000` | `FB_FRONT` | PC del warp 0 |
| `0x80000004` | `FB_BACK` | Máscaras del warp 0 |
| `0x80000008` | `SWAP` | `workgroup_id` del warp 0 |
| `0x8000000C` | `STATUS` de vídeo | Estado SIMT del warp 0 |
| `0x80000010` | `SWAP_COUNT` | PC del warp 1 |
| `0x80000014` | `HALT_AT` | Máscaras del warp 1 |
| `0x80000100–0x80000117` | Reservado | Depuración GPU |
| `0x80000200–0x8000020B` | Serie | Sin registros implementados |

Reservar el slot de depuración en CPU no resuelve la colisión de vídeo con los
descriptores GPU. Son mapas de sistemas separados; no pueden conectarse a un
bus global sin seleccionar o trasladar uno de los bloques.

## 6. Propuesta para una FPGA con CPU + GPU

**Diseño propuesto, no implementado.** Se plantea un mapa global por dispositivo,
con RAM compartida. La CPU y el monitor podrían controlar los mismos periféricos;
no se deduce que los kernels GPU deban poder acceder a todos ellos.

| Rango propuesto | Uso |
|---|---|
| `0x00000000–0x01FFFFFF` | SDRAM compartida por CPU, GPU y scanout |
| `0x80000000–0x80000FFF` | Periféricos existentes: vídeo y serie en sus direcciones actuales |
| `0x80001000–0x80001FFF` | Nueva página de control, configuración y depuración GPU |
| Desde `0x80002000` | Futuras páginas de sistema/aceleradores, sin asignaciones concretas |

Dentro de la página GPU se propone conservar los offsets de las ventanas:

| Rango propuesto | Contenido |
|---|---|
| `0x80001000–0x8000107F` | Descriptores de los ocho warps, stride 16 bytes |
| `0x80001100–0x80001117` | Registros de depuración actuales |
| `0x80001200–0x800012FF` | Reserva para control de lanzamiento y estado |
| Otros offsets de la página GPU | Reservados |

La reserva de control necesita definir identificación/perfil de ISA y
capabilities, arranque, parada, reset y estado busy/done/error. No se asignan
bits ni registros individuales todavía. También debe asignarse espacio para
`warp_user_id` si se incorpora `GETWID`, sin sobrescribir los words existentes.

Esta distribución conserva vídeo y serie; traslada las dos ventanas GPU en
`+0x1000`. No debe mantenerse un alias GPU en las antiguas direcciones si
colisiona con vídeo. Los programas/monitores que controlaban la GPU por las
bases antiguas requerirían adaptación e identificación del nuevo sistema.

### Cambios necesarios para implementar la propuesta

1. Ampliar el encaminamiento MMIO de CPU y monitor: actualmente sus adaptadores
   de la 21 reconocen solo el prefijo de la página `0x80000000`.
2. Añadir una interfaz de registros GPU adecuada para el bus CPU. La interfaz
   host actual es byte a byte y solo funciona con GPU detenida; no basta con
   conectar direcciones a las señales actuales.
3. Permitir consultar estado de ejecución mientras la GPU trabaja, manteniendo
   restringidas las escrituras de configuración que requieren GPU detenida.
4. Arbitrar CPU, GPU, monitor y vídeo sobre memoria compartida y controlar los
   cruces de reloj si los bloques usan dominios distintos.
5. Definir el orden: las escrituras CPU de datos/descriptores deben completarse
   antes del arranque GPU; done debe indicar que terminaron las escrituras GPU
   relevantes. La 21 ya drena su buffer de escrituras antes de MMIO; la
   integración debe conservar esa propiedad y completar el protocolo global.
6. Definir tamaños de acceso y efectos laterales, y unificar el tratamiento de
   registros inexistentes y errores de bus. Las políticas CPU/GPU actuales difieren.
7. Adaptar modelos, monitores, constantes de programas y tests al mapa conjunto,
   sin presentar la migración como aplicada a las carpetas históricas.

Los framebuffers pueden seguir siendo memoria ordinaria compartida. Separar
ventanas MMIO no obliga a duplicar RAM, ni proporciona coherencia o sincronización
por sí solo. También habrá que decidir quién solicita swaps y cómo se interpreta
`HALT_AT` cuando el productor de imagen sea la GPU.

## 7. Validación y fuentes del mapa

Hay que comprobar las direcciones en todos los niveles:

- El caso de prueba describe accesos y capabilities requeridas.
- El backend identifica versión, capacidades y rangos de RAM; las pruebas de
  periféricos necesitan además sus requisitos específicos.
- El cliente del monitor valida rangos y modalidades de transferencia.
- Los adaptadores y decodificadores RTL determinan el dispositivo real y sus errores.

`ARCHITECTURAL_REGIONS` describe los intervalos de RAM usados para validar
programas. En GPU, `MONITOR_REGIONS` añade las ventanas solo host. En las CPU
con vídeo/serie también hay límites MMIO y rutas de acceso específicas: no se
puede inferir la ausencia de MMIO porque `MONITOR_REGIONS` esté vacío.
Los intervalos Python son normalmente semiabiertos; por ejemplo, el final
`0x80000118` incluye los cuatro bytes del registro que empieza en `0x80000114`.

Referencias principales:

- [Monitor CPU 21](21.fpga-cpu-hdmi-alu/monitor.py).
- [Adaptador de datos CPU](21.fpga-cpu-hdmi-alu/cpu_dmem_adapter.v).
- [Integración CPU, monitor y periféricos](21.fpga-cpu-hdmi-alu/top.v).
- [Monitor GPU 17](17.fpga-gpu-ram-v2/monitor.py).
- [Decodificación y acceso host GPU](17.fpga-gpu-ram-v2/gpu_system.v).
- [Simulador CPU y dispositivos](2.cpu-sim-func/minicpu_sim.py).
- [Simulador GPU](11.gpu-sim-func/minigpu_sim.py).

Este documento actualiza la descripción y registra una propuesta de integración.
No cambia direcciones implementadas, protocolos ni bitstreams.
