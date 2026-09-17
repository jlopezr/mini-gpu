# Mapa de memoria de MiniCPU y MiniGPU

Referencia única del espacio de direcciones del repositorio: RAM y MMIO, en
todos los prototipos. Tiene tres capas, y conviene no confundirlas:

- **Estado actual** (§2 a §5): lo que hay implementado hoy, prototipo a prototipo.
- **Contrato objetivo** (§6): el reparto al que se quiere converger, para que el
  mismo programa valga en varias versiones. **No está aplicado al RTL.**
- **Validación** (§7): qué nivel responde a qué pregunta.

Las direcciones de las tablas son inclusivas, salvo cuando se indica
expresamente un límite exclusivo. Las palabras en memoria son little-endian.

La referencia CPU más completa es [21.fpga-cpu-hdmi-alu](../21.fpga-cpu-hdmi-alu/README.md);
la GPU más completa es [22.fpga-gpu-bl8](../22.fpga-gpu-bl8/README.md). El porqué
y el cómo de la ventana MMIO de la 22 —el camino escalar en la LSU, el mux, las
trampas de la ISA— están en [`22.fpga-gpu-bl8/mmio.md`](../22.fpga-gpu-bl8/mmio.md);
aquí está el contrato de direcciones, no la historia de diseño.

## 1. El espacio de direcciones

Dos regiones, y nada entre ellas:

| Rango | Uso |
|---|---|
| `0x00000000–0x01FFFFFF` | RAM de programa y datos, 32 MiB (menos en los prototipos con EBR) |
| `0x80000000–0x80000FFF` | Página MMIO de 4 KiB, en todos los prototipos que tienen periféricos |

Todo el MMIO del repositorio cabe en esa única página de 4 KiB, y ningún
prototipo usa hoy más del 5,1 % de ella. La escasez no es de espacio: es de
acuerdo sobre dónde va cada cosa.

### Resumen por prototipo

| Backend / versión | Carpeta | Memoria de programa y datos | MMIO | Monitor |
|---|---|---|---|---|
| `cpusim / current` | `2.cpu-sim-func` | 32 MiB en el runner | Vídeo y serie opcionales según el caso | — |
| `cpu-fpga / ebr` | `6.fpga-cpu` | 32 KiB EBR continuos (dos bancos) | — | 3.6 |
| `cpu-fpga / sdram` | `10.fpga-cpu-ram` | 32 MiB SDRAM | — | 3.10 |
| `cpu-fpga / hdmi` | `16.fpga-cpu-hdmi` | 32 MiB SDRAM | Vídeo | 3.16 |
| `cpu-fpga / bl8` | `18.fpga-cpu-hdmi-bl8` | 32 MiB SDRAM | Vídeo y captura de frames | 3.18 |
| `cpu-fpga / subword` | `19.fpga-cpu-hdmi-ls` | 32 MiB SDRAM | Vídeo, captura y serie | 4.19 |
| `cpu-fpga / alu` | `21.fpga-cpu-hdmi-alu` | 32 MiB SDRAM | Mismo mapa que la 19 | 4.21 |
| `gpusim / current` | `11.gpu-sim-func` | 32 MiB por defecto | Configuración por API Python, sin MMIO | — |
| `gpu-fpga / bram` | `12.fpga-gpu` | 128 KiB EBR continuos | Warps y depuración, solo host | 3.12 |
| `gpu-fpga / sdram` | `14.fpga-gpu-ram` | 32 MiB SDRAM | Warps y depuración, solo host | 3.14 |
| GPU SDRAM optimizada | `17.fpga-gpu-ram-v2` | 32 MiB SDRAM | Mismo mapa que la 14 | 3.17 |
| GPU BL8 | `22.fpga-gpu-bl8` | 32 MiB SDRAM | Warps, depuración, vídeo y contadores | 3.22 |

La 17 comparte perfil funcional con la 14. Los números de monitor identifican
contratos de bitstream y no ordenan capacidades: la 21 conserva 1.15 aunque
otras CPU tengan números mayores tras el backport de R0. Todas las
implementaciones vigentes usan R0 cableado a cero.

Las capabilities de instrucciones y las de periféricos son independientes del
tamaño de RAM: el mapa de memoria no basta para decidir si un binario es
ejecutable.

## 2. Memoria de programa y datos

### CPU con EBR: carpeta 6

| Rango | Tamaño | Uso convencional |
|---|---:|---|
| `0x00000000–0x00003FFF` | 16 KiB | Programa (banco EBR 0) |
| `0x00004000–0x00007FFF` | 16 KiB | Datos (banco EBR 1) |

**El espacio es contiguo**: 32 KiB seguidos, y el bit 14 de la dirección elige
banco. Los puertos de instrucciones y datos alcanzan ambos, así que la separación
de usos es solo una convención — un programa puede pasar de 16 KiB sin cruzar
ningún hueco. Fuera de `0x00008000` el bus da error.

Los bancos estuvieron en `0x00000000` y `0x00100000`, con 1 MiB de hueco entre
ellos. Juntarlos abarató el decodificador —un comparador por puerto en vez de
dos, y hay tres puertos— y dejó a la 6 con el mismo aspecto que el resto de
prototipos, que son todos un bloque de RAM seguido.

El cliente declara el intervalo en [monitor.py](../6.fpga-cpu/monitor.py); el
validador de bloques y la respuesta del bus comprueban aspectos distintos, por lo
que no basta con validar un tamaño total. Desde que los bancos son contiguos un
bloque **sí** puede cruzar `0x4000`: se transfiere byte a byte y cada uno se
encamina por su cuenta.

### CPU y GPU con SDRAM

| Rango | Tamaño | Significado |
|---|---:|---|
| `0x00000000–0x01FFFFFF` | 32 MiB | Memoria unificada de programa y datos |
| `0x02000000` | — | Primer byte fuera de SDRAM |

No hay traducción implícita por banco. La última palabra alineada comienza en
`0x01FFFFFC`. Las tecnologías de transferencia BL1/BL8, arbitraje y buffers
cambian según la implementación, no las direcciones.

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
ventana de configuración MMIO del monitor FPGA. En 23 eso es una decisión, no una
carencia: `plasma.asm` lee `FB_BACK` y escribe `SWAP`, así que para comparar RTL
y modelo existe `plasma_nommio.asm`, la misma carga sin accesos a MMIO. Añadir
una ventana MMIO al simulador funcional para que el programa no falle sería la
peor manera de resolverlo.

## 3. Estado actual del MMIO

### Qué dispositivo tiene cada prototipo

| Prototipo | Vídeo | Captura de frames | Puerto serie | Config. de warps | Depuración SIMT | Contadores perf | Quién accede |
|---|---|---|---|---|---|---|---|
| 2.cpu-sim-func | opcional | — | opcional | — | — | — | el programa, si el caso lo configura |
| 6.fpga-cpu | — | — | — | — | — | — | — |
| 10.fpga-cpu-ram | — | — | — | — | — | — | — |
| 11.gpu-sim-func | — | — | — | API Python | API Python | — | host, sin ventana MMIO |
| 12.fpga-gpu | — | — | — | ✓ | ✓ | — | solo host, GPU parada |
| 14.fpga-gpu-ram | — | — | — | ✓ | ✓ | — | solo host, GPU parada |
| 16.fpga-cpu-hdmi | ✓ | — | — | — | — | — | CPU + monitor |
| 17.fpga-gpu-ram-v2 | — | — | — | ✓ | ✓ | — | solo host, GPU parada |
| 18.fpga-cpu-hdmi-bl8 | ✓ | ✓ | — | — | — | — | CPU + monitor |
| 19.fpga-cpu-hdmi-ls | ✓ | ✓ | ✓ | — | — | — | CPU + monitor |
| 21.fpga-cpu-hdmi-alu | ✓ | ✓ | ✓ | — | — | — | CPU + monitor |
| 22.fpga-gpu-bl8 | ✓ | ✓ | — | ✓ | ✓ | ✓ | mixto, ver §4 |
| 23.gpu-sim-uarch | — | — | — | — | — | modelado, no MMIO | — |
| 24.gpu-sim-pipeline | — | — | — | — | — | — | — |
| **Usado / reservado** | 16 B/16 B (16)<br>24 B/32 B (18)<br>24 B/256 B (19, 21)<br>24 B/64 B (22) | dentro de vídeo:<br>8 B (18, 19, 21)<br>4 B (22) | 12 B / 256 B | 128 B / 128 B | 24 B / 256 B (19, 21)<br>24 B / 24 B (12, 14, 17, 22) | 28 B / 64 B | dentro de la página de 4 KiB |

Ocupación total de la página: 0,4 % en 16; 0,9 % en 21; 5,1 % en 22.

La columna de reserva dice más que la de uso. El salto de 18 a 19 no añade
registros —siguen siendo los mismos 24 B— sino que trocea la página en 16 slots
de 256 B; el puerto serie entró después en ese hueco sin volver a tocar el
decodificador. Y la configuración de warps es la única ventana llena al 100 %:
8 warps × 16 B, sin un hueco, que es justo lo que la hace incómoda de ampliar.

### Ventanas publicadas por el cliente

| Carpeta | Ventana | Decodificación |
|---|---|---|
| 16 | `0x80000000–0x8000000F` | `address[31:4]`, cuatro registros de vídeo |
| 18 | `0x80000000–0x8000001F` | `address[31:5]`, añade `SWAP_COUNT` y `HALT_AT` |
| 19, 21 | `0x80000000–0x80000FFF` | `address[31:12]`, 16 slots de 256 B por `address[11:8]` |
| 22 | `0x80000000–0x80000FFF` | `address[31:12]`, regiones por `address[11:6]` y palabras sueltas |
| 12, 14, 17 | `0x80000000–0x80001FFF` | `address[31:13]`, **dos páginas**: `address[12]` separa lo compartido del control exclusivo de la GPU |

12, 14 y 17 ya están migradas al contrato de §6: su configuración de warps está
en `0x80001000` y no en `0x80000000`. Falta la 22; el orden y el estado de la
migración están en [`unificacion-mmio.md`](unificacion-mmio.md).

La ventana publicada no significa que cada dirección tenga un registro útil. En
la 21, CPU y monitor se arbitran sobre el mismo bus MMIO.

### Qué pasa en una dirección sin registro

Una dirección sin registro es un error de acceso en ambas familias. En CPU el
decodificador propaga el error al núcleo o al monitor; en GPU se propaga como
`bad`. Los slots y offsets reservados no se usan para descubrir hardware: un
programa consulta `SYS_ID` y los registros definidos por el contrato.

## 4. Contrato de cada dispositivo

### Vídeo

El framebuffer con doble buffer. En 16, 18, 19, 21 y 22.

Los offsets son **los mismos en todos los prototipos que tienen vídeo**, y están
en el orden en que aparecen en el bloque:

| Registro | Acceso | Función |
|---|---|---|
| `FB_FRONT` | RW | Dirección de byte del buffer que se muestra |
| `FB_BACK` | RW | Dirección de byte del buffer que se dibuja |
| `SWAP` | RW | Escribir pide intercambio; leer bit 0 indica pendiente |
| `STATUS` | RW | Bit 0 underflow pegajoso, bit 1 swap pendiente, bits 31:16 contador de frames; escribir bit 0 a 1 borra el underflow |
| `SWAP_COUNT` | R | Intercambios completados. **Desde 18** |
| `HALT_AT` | RW | Parar la CPU tras N intercambios. **Solo CPU, desde 18.** En 22 la dirección existe pero lee cero y la escritura se ignora |
| `VIDEO_CTRL` | RW | Modo: 0 BLANK, 1 PATTERN, 2 SCANOUT, 3 reservado. **Solo 22** |

El mecanismo es el mismo en todas partes: escribir `SWAP` no intercambia nada,
solo levanta `swap_pending`. El intercambio ocurre **en el vsync**, porque
cambiar la dirección a mitad de frame partiría la imagen en dos — que es
exactamente el defecto que el doble buffer viene a quitar. El underflow del line
buffer es un nivel pegajoso: si se pone a uno, ahí se queda hasta que alguien
escriba un uno en el bit 0. Un underflow de un solo frame sería invisible si el
bit se recargara cada vsync.

`frame_count` (bits 31:16 de `STATUS`) y `SWAP_COUNT` **no son lo mismo**: el
primero cuenta frames emitidos por el scanout, corra o no el programa; el segundo
cuenta intercambios completados. Un programa que no pide swaps hace avanzar el
primero y deja el segundo quieto.

#### Discrepancias

**Resueltas.** La dirección base y los offsets ya coinciden: el bloque empieza en
`0x80000000` en las dos familias y `VIDEO_CTRL` —que solo tiene la 22— está al
final, en `+0x18`, para que `FB_FRONT` quede en `+0x00` en todas partes. Y la 22
implementa el bit 1 de `STATUS` (`swap_pending`), que antes era cero fijo: código
que sondease ese bit esperando al swap funcionaba en CPU y se colgaba en 22.

**`HALT_AT` (`+0x14`) solo existe en CPU**, pero la dirección es legible en las
dos: en 22 lee cero y la escritura se ignora, igual que hace la CPU con cualquier
registro ausente del bloque. No se implementa el mecanismo porque pararía el SM
desde un registro de un periférico, y los kernels de la 22 ya terminan con `HALT`.
Lo que sí diverge es la consecuencia: `SWAP_COUNT` cuenta en 22 desde el reset y
nada más, mientras que en 18, 19 y 21 cuenta desde el reset **o desde el último
armado de `HALT_AT`**.

**El alineamiento de las bases.** CPU alinea a 4 bytes
(`{merged_front[31:2], 2'b00}`); la 22 alinea a **16 bytes**
(`{fb_front[31:4], 4'b0000}`), porque el scanout lee en ráfagas. Escribir una base
no alineada a 16 no da error: se truncan los bits bajos en silencio. **No se
unifica a propósito**: las dos conviven si los programas alinean a 16, que es lo
que hay que respetar para que un binario de vídeo valga en las dos familias.

**Quién pide el intercambio.** En CPU, la CPU. En 22, la GPU — y solo es posible
desde que la ventana MMIO está abierta a la LSU: a ~8 fps el host va por serie y
llega tarde.

**El estado tras el reset.** La 21 arranca con bases cableadas (`FB_FRONT_RESET`).
La 22 arranca con `fb_front = fb_back = 0` y en modo **PATTERN, no SCANOUT**: la
SDRAM recién encendida contiene basura, así que arrancar en SCANOUT sería elegir
por defecto una salida indefinida. Con PATTERN, ver el patrón demuestra que HDMI,
PLL, cable y monitor funcionan, y no verlo señala aguas arriba.

**El tamaño de la ventana.** 16 B en 16, 32 B en 18, un slot de 256 B en 19 y 21,
un bloque de 64 B en 22. Solo importa para saber qué direcciones responden más
allá del contrato; los siete registros del contrato están en todas.

### Captura de frames

No es un dispositivo aparte: son dos registros dentro de la ventana de vídeo,
`SWAP_COUNT` y `HALT_AT`. Por eso la ventana de 18 pasa de 16 a 32 bytes — no se
añadió un dispositivo, se ensanchó uno.

Sirve para que el host capture un frame determinista. Se escribe `HALT_AT = N`,
lo que **arma** el mecanismo y reinicia `SWAP_COUNT`; la CPU se para sola al
completar el intercambio número N y el host lee el framebuffer con la imagen
quieta. Escribir cero desarma. La comparación es `>=` y no `==`, como defensa
barata por si el contador se pasa de largo.

`HALT_AT` es control de prueba de CPU. No es un comando de lanzamiento, y no
tiene nada que ver con las señales run/halt/step que el monitor manda a la GPU.

#### Discrepancias

**La 22 no implementa `HALT_AT`**, solo `SWAP_COUNT`. La dirección responde —lee
cero, escribir no hace nada— para que el bloque de vídeo se pueda leer entero de
una vez y para que sondearla no se comporte distinto en cada familia, pero el
mecanismo no está: la GPU no se detiene sola al llegar a N frames, se para con
las órdenes del monitor, y sus kernels terminan con `HALT`. Implementarlo
obligaría a que un registro de un periférico alcanzase el control de ejecución
del SM, que es justo lo que el reparto de señales separa. En consecuencia,
`SWAP_COUNT` cuenta en 22 desde el reset y nada más, mientras que en 18, 19 y 21
cuenta desde el reset **o desde el último armado de `HALT_AT`**.

### Puerto serie

Solo en 19 y 21. Es un dispositivo de colas, no un segundo UART físico: los bytes
viajan encapsulados sobre el UART del monitor mediante `SEND_BYTES`/`RECV_BYTES`.

| Registro | Acceso | Función |
|---|---|---|
| `+0x00` `DATA` | RW | Leer extrae un byte de RX, o cero si está vacía; escribir inserta el byte bajo en TX, descartándolo si está llena |
| `+0x04` `STATUS` | RW | Bits 7:0 bytes en RX, 15:8 huecos en TX, bit 16 overrun; escribir un uno en el bit 16 lo borra |
| `+0x08` `PEEK` | R | Consulta la cabeza de RX **sin extraerla** |

La distinción entre `DATA` y `PEEK` es la razón de que `PEEK` exista: leer `DATA`
tiene efecto lateral, y una herramienta de inspección del host que sondee la cola
no puede permitirse consumir el byte que mira. De ahí también que leer una palabra
byte a byte no equivalga a una única lectura de CPU.

El control de flujo lo hace el PC con `host_rx_free`, que viaja en la respuesta de
cada `SEND_BYTES`; `rx_overrun` no debería levantarse nunca, y si lo hace es que
el host ignoró ese campo.

Sin discrepancias: 19 y 21 son idénticas.

### Configuración de warps

En 12, 14, 17 y 22. Ocho descriptores de 16 bytes, la interfaz de lanzamiento.

| Palabra | Contenido | Acceso |
|---|---|---|
| `+0x00 + 16*w` | PC del warp | RW |
| `+0x04 + 16*w` | `active` en bits 7:0, `live` en bits 15:8; escribir el byte bajo fija ambas | RW |
| `+0x08 + 16*w` | `workgroup_id` | RW |
| `+0x0C + 16*w` | Estado SIMT: profundidad REGION en 7:0, PATH en 15:8, WAIT_MEM bit 16, WAIT_BAR bit 17 | **R** |

Escribir la cuarta palabra es error de bus (`address[3:2]==3 && writing` → `bad`),
y esto importa más de lo que parece: esa palabra es **estado vivo del SM**, no un
hueco libre. Si alguna vez entra `GETWID`, `warp_user_id` no cabe ahí.

Escribir la configuración reinicia el estado de reconvergencia y barrera del warp
y su contador local, según el contrato del SM. No es una interfaz para modificar
contexto mientras el warp ejecuta — de hecho no se puede: el puerto host rechaza
toda transacción con la GPU corriendo.

Los comandos run/halt/step/reset **no están aquí**. Llegan por señales desde el
monitor, no por registros de lanzamiento.

#### Discrepancias

En el mapa, una: 12, 14 y 17 ya migraron la ventana a `0x80001000` y la 22 sigue
en `0x80000000`. El contenido y el decodificador son los mismos; lo que cambia
es el prefijo. La otra diferencia es de acceso, y es de 22: **la GPU no llega a
esta ventana**. Que un warp
reconfigure los warps no tiene caso de uso y sí modos de fallo.

### Depuración SIMT

En `0x80000100–0x80000117`, en 12, 14, 17 y 22. Todo de solo lectura salvo la
selección de contexto; escribir en el resto es error de bus.

| Dirección | Contenido | Acceso |
|---|---|---|
| `+0x00` | Contexto seleccionado: lane en bits 2:0, warp en bits 5:3 | RW |
| `+0x04` | Slots de la LSU ocupados, bits 7:0 | R |
| `+0x08` | Instrucciones retiradas, global | R |
| `+0x0C` | Primer error: lane 2:0, warp 5:3, `lane_valid` bit 6, `error_code` 15:8 | R |
| `+0x10` | PC del primer error | R |
| `+0x14` | Instrucciones retiradas del warp seleccionado | R |

El registro de error guarda **el primero**, no el último: cuando algo se rompe en
ocho lanes a la vez, el que informa es el que causó la parada. `error_code` es el
espacio de códigos del SM — `0x06` es `ERROR_SIMT`, el que aparece cuando un salto
divergente no lleva `SSY` delante.

La selección de contexto gobierna también el comando `READ_REG` del monitor. No
hay una ventana MMIO de 32 registros: los registros se leen por comando UART y
esta dirección solo dice de quién.

#### Discrepancias

Ninguna: mismo decodificador en 12, 14, 17 y 22. En 22 la GPU tampoco llega aquí.

### Contadores de rendimiento

Solo en 22. Siete contadores de 32 bits, legibles por host y GPU; **escribir es
fault**.

La CPU tiene los dos primeros —ciclos e instrucciones retiradas— pero **fuera del
MMIO**: son registros de `top.v` que solo alcanza el host, con los comandos de
monitor `GET_CYCLES` (`0x36`) y `GET_INSTRUCTIONS` (`0x37`). Un programa de CPU
no puede medirse a sí mismo. Pasarlos a este slot está en
[`unificacion-mmio.md`](unificacion-mmio.md), fase 3.5; el bloque de CPU sería un
prefijo del de GPU, porque `+0x00` y `+0x04` ya son `CYCLES` y `RETIRED`. Ojo a
que la CPU **satura** a `0xFFFFFFFF` y la GPU **da la vuelta**: a 80 MHz son 53
segundos hasta saturar.

| Dirección | Contador |
|---|---|
| `+0x00` | `CYCLES`, ciclos con la GPU corriendo (da la vuelta) |
| `+0x04` | `RETIRED`, instrucciones retiradas |
| `+0x08` | `IMEM_HITS`, aciertos del búfer de instrucciones |
| `+0x0C` | `IMEM_MISSES`, fallos del búfer de instrucciones |
| `+0x10` | `LSU_TX`, transacciones de la LSU vectorial |
| `+0x14` | `VIDEO_TX`, transacciones del scanout |
| `+0x18` | `STALL_MEM`, ciclos con la LSU sin poder aceptar petición |

Con `CYCLES`, `STALL_MEM` e `IMEM_MISSES` se separa cómputo de memoria y de fetch
sin instrumentar nada más, y un programa se mide a sí mismo en la placa.

Todos avanzan **solo con la GPU corriendo**, y eso no es un detalle de
implementación sino el punto: un contador libre sirve para que un programa se mida
a sí mismo, pero no para que lo mida el host, porque entre sus dos lecturas caben
las órdenes por serie y el bucle que sondea si ha parado. Con `CYCLES` libre,
`profile.py` daba un CPI de 43 en vez de 15,6 — medía el reloj de pared.
`VIDEO_TX` se cuenta igual, porque el scanout sigue leyendo SDRAM con la GPU
parada y ese tráfico no es del programa.

## 5. El reparto entre familias

**Ya no chocan.** Vista por slots de 256 B (`address[11:8]`, el troceado de la
19/21, que es el que se tomó como base):

| Slot | Dirección | CPU 19/21 | GPU 12/14/17/22 | ¿Coincide? |
|---|---|---|---|---|
| 0 | `0x80000000` | Vídeo | Vídeo (22) | ✓ |
| 1 | `0x80000100` | Reservado depuración | Depuración SIMT | ✓ |
| 2 | `0x80000200` | Puerto serie | Libre | ✓ |
| 3 | `0x80000300` | Libre | Contadores perf (22) | ✓ |
| 4–15 | `0x80000400+` | Libres | Libres | ✓ |
| — | `0x80001000` | — | Configuración de warps | solo GPU |

Los dos choques que había —`0x80000000` era vídeo o warps según la familia, y
`0x80000200` era serie o vídeo— se resolvieron con los dos únicos movimientos que
hacían falta: los warps a la segunda página y el vídeo de la 22 de vuelta a
`0x80000000`. Depuración y contadores nunca se movieron.

Siguen siendo mapas de sistemas separados y hoy no conviven en ningún bitstream,
pero ya **no hay que trasladar ningún bloque** para conectarlos a un bus común: lo
compartido está en la primera página con la misma dirección y los mismos offsets,
y lo exclusivo de la GPU en la segunda. Lo que falta para que convivan de verdad
—arbitraje, dominios de reloj, orden de escrituras— está en §6, y no es de
direcciones.

## 6. Contrato objetivo

**Propuesta, no implementada.** El objetivo es doble: que el mismo programa valga
en varios prototipos que tengan el dispositivo, y que un día puedan convivir CPU y
GPU en la misma FPGA.

### Reparto de slots

La página `0x80000000` queda para **periféricos compartidos**, con el slot fijo
por dispositivo, y la GPU se lleva su control exclusivo a una **segunda página**:

| Rango | Dispositivo | Quién lo tiene |
|---|---|---|
| `0x80000000–0x800000FF` | Vídeo | CPU y GPU |
| `0x80000100–0x800001FF` | Depuración SIMT | GPU |
| `0x80000200–0x800002FF` | Puerto serie | CPU |
| `0x80000300–0x800003FF` | Contadores de rendimiento | GPU, ampliable a CPU |
| `0x80000400–0x80000EFF` | Libres | — |
| `0x80000F00–0x80000FFF` | Identificación y capabilities | todos |
| `0x80001000–0x8000107F` | Configuración de warps | GPU |
| `0x80001080–0x80001FFF` | Control de lanzamiento y estado GPU, reservado | GPU |
| Desde `0x80002000` | Futuras páginas de sistema | — |

Eran **dos movimientos**, y los dos están **aplicados** (§5): la configuración de
warps salió de `0x80000000` a `0x80001000` en 12, 14, 17 y 22, y el vídeo de la 22
volvió de `0x80000200` a `0x80000000`. Depuración y contadores se quedaron donde
estaban, y ningún core de CPU cambió de dirección. Lo único de esta sección que
sigue sin implementar es el bloque de identificación de `0x80000F00`.

Mandar los warps a una segunda página, en vez de a un slot libre de la primera, es
lo que hace que el reparto siga valiendo el día que CPU y GPU compartan bitstream:
lo exclusivo de la GPU queda separado de lo compartido, en vez de intercalado. El
coste es un bit más en el comparador de prefijo del decodificador GPU.

### Uniformar los registros de vídeo

Que el slot coincida no basta si los offsets dentro del slot no coinciden. Hecho:

1. **`VIDEO_CTRL` se fue al final del bloque**, a `+0x18`, y `FB_FRONT` volvió a
   `+0x00`. Así ningún programa de CPU cambió y solo se tocó la 22, que es la más
   nueva.

   La fase 3.5 añadió `VIDEO_CTRL` también a **16, 18, 19 y 21**. Las cuatro
   decodifican ahora la página MMIO completa y dedican un slot de 256 B al vídeo;
   `+0x18` ya no cae en SDRAM en la 16. La validación en placa está pendiente.
2. **La 22 implementa el bit 1 de `STATUS`** (`swap_pending`).
3. **El alineamiento no se tocó.** 4 bytes en CPU y 16 en GPU conviven si los
   programas escriben bases alineadas a 16, que es lo que hay que documentar.
4. **`HALT_AT` (`+0x14`) no se implementó en la GPU**, pero la dirección lee cero
   y la escritura se ignora, como hace la CPU con un registro ausente del bloque.
   Así el bloque se puede leer entero de una vez y sondear el registro no da
   resultados distintos según la familia.

Offsets resultantes, iguales en todos los prototipos que tengan vídeo:

| Offset | Registro | Presente en |
|---|---|---|
| `+0x00` | `FB_FRONT` | todos |
| `+0x04` | `FB_BACK` | todos |
| `+0x08` | `SWAP` | todos |
| `+0x0C` | `STATUS` | todos |
| `+0x10` | `SWAP_COUNT` | desde 18 |
| `+0x14` | `HALT_AT` | implementado solo en CPU; en GPU lee cero |
| `+0x18` | `VIDEO_CTRL` | 16, 18, 19, 21 y 22 |

### Descubrimiento en tiempo de ejecución

Para que un binario se adapte al prototipo hace falta identificación explícita:
sondear direcciones vacías no distingue un dispositivo ausente de un registro
cuyo valor legítimo es cero. El bloque fijo de identificación está en
`0x80000F00`. En bitstreams CPU antiguos, una lectura cero en esa dirección
permite reconocer la ausencia del bloque; es compatibilidad histórica del host,
no una regla para los nuevos diseños.

Son cuatro palabras:

| Offset | Registro | Contenido |
|---|---|---|
| `+0x00` | `SYS_ID` | Magic `0x4D47` en 31:16, byte libre, **número de carpeta** en 7:0 |
| `+0x04` | `CONTRACT` | Versión de este contrato de mapa de memoria |
| `+0x08` | `DEV_BITMAP` | Un bit por dispositivo presente |
| `+0x0C` | `ISA_PROFILE` | Perfil de ISA |

`SYS_ID` es el número de la carpeta —`0x4D470016` en `22.fpga-gpu-bl8`— de modo
que no hay ningún identificador que asignar ni registrar al añadir un prototipo,
y no se puede duplicar porque lo impone el nombre del directorio. El magic evita
que el valor 0 sea ambiguo entre «prototipo antiguo» y «prototipo 0». El byte
libre se deja sin usar: CPU-vs-GPU ya se deriva del RTL y las capacidades son
trabajo de `DEV_BITMAP` e `ISA_PROFILE`.

La regla es **un prototipo con ventana MMIO expone el bloque**. Los prototipos 6 y
10 lo exponen por el monitor, sin ventana de periféricos para el núcleo. Los bits
de `DEV_BITMAP` no están asignados todavía: van generados desde
`tools/capabilities.json`, no escritos a mano. El orden y el coste por carpeta
están en [`unificacion-mmio.md`](unificacion-mmio.md), fase 4.

### Política de dirección inexistente — decisión del 17/09/2026

**Un acceso a un dispositivo inexistente debe dar error, tanto en lectura como
en escritura, en CPU y GPU.** La regla alcanza los accesos del programa y los
del monitor, sueltos y por bloques; filtrar únicamente comandos del monitor no
la implementa para el núcleo. El núcleo debe señalar el error de acceso a
memoria y el monitor debe rechazar la transacción, sin presentar el cero del bus
como una lectura válida ni confirmar una escritura descartada.

Dentro de un dispositivo, un offset reservado también da error por defecto.
Una lectura cero solo es válida si el contrato de ese registro la define
expresamente. Los registros implementados conservan sus efectos y permisos
documentados; esta regla no convierte un valor cero legítimo en un error.

**El slot de identificación no tiene una excepción general.** Las cuatro
palabras de `0x80000F00–0x80000F0F` son de solo lectura; escribirlas da error.
El resto del slot está reservado y da error: no devuelve cero ni repite las
cuatro palabras por alias. `DEV_BITMAP` sí existe y sigue leyendo cero con
`CONTRACT = 1`, con el significado de «sin declarar».

La compatibilidad con bitstreams antiguos corresponde al host: debe distinguir
identificación válida, lectura cero histórica y rechazo explícito del acceso.
Un rechazo no demuestra por sí solo que el bitstream sea antiguo, y un timeout
o un fallo de comunicación no debe convertirse en «sin identificación».
Cambiar el contrato nuevo no modifica el comportamiento de un bitstream antiguo
que sigue flasheado; no se necesita una excepción en el RTL nuevo para conservar
esa compatibilidad.

La decisión preserva el diagnóstico de direcciones equivocadas y periféricos
ausentes. **Su aplicación sigue pendiente**: incluye propagar el error por la
ruta MMIO de CPU, eliminar alias y contrastar RTL, simuladores y monitor. El
plan de trabajo está en `unificacion-mmio.md`.

### Conformidad

Qué le falta a cada prototipo para cumplir el contrato:

| Prototipo | Estado | Qué le falta |
|---|---|---|
| 6, 10 | identificación implementada | `SYS_ID` por el monitor; sin ventana de periféricos por diseño |
| 16 | mapa e identificación implementados | `VIDEO_CTRL` en `+0x18`; sin captura ni `SWAP_COUNT` por capacidad |
| 18, 19, 21 | mapa e identificación implementados | Pendiente validación en placa de la fase 3.5 |
| 12, 14, 17 | mapa e identificación implementados | Warps en `0x80001000`; pendiente ronda de placa |
| 22 | mapa e identificación implementados | Warps en `0x80001000`, vídeo en `0x80000000`; pendiente ronda de placa |
| 2, 11, 25 | periféricos funcionales compartidos | `SYS_ID`, vídeo con `HALT_AT` y serie; MMIO integrado en los tres motores. Vídeo/serie opcionales en la API y CLI |

Los simuladores comparten `tools/sim_devices.py`: no declaran conformidad temporal
con la placa. Sus bases de vídeo se alinean a 4 bytes y cualquier escritura a
`SWAP` solicita intercambio; para portabilidad al RTL GPU usar alineación de 16
bytes y escribir 1. `HALT_AT` y serie siguen sin existir en el RTL GPU. Las
opciones comunes de consola están en [`tools/README.md`](../tools/README.md).

La política de direcciones inexistentes está decidida; su implementación sigue
pendiente de unificación. La
convergencia de los monitores requiere resíntesis y verificación en placa antes
de dar por cerrado el contrato; véase `unificacion-mmio.md`.

Los cores de CPU con slots de 256 B ya cumplen el reparto sin tocar nada, que es
la razón de tomar su troceado como base en vez de inventar uno.

### Lo que falta por resolver

1. La interfaz host de la GPU es byte a byte y solo funciona con la GPU parada; no
   basta con conectar direcciones a las señales actuales para que la CPU escriba
   registros GPU.
2. Hay que poder consultar estado de ejecución mientras la GPU trabaja, manteniendo
   restringidas las escrituras de configuración que exigen GPU detenida.
3. Arbitrar CPU, GPU, monitor y vídeo sobre memoria compartida, y controlar los
   cruces de reloj si los bloques usan dominios distintos.
4. Definir el orden: las escrituras CPU de datos y descriptores deben completarse
   antes del arranque GPU, y `done` debe indicar que terminaron las escrituras GPU
   relevantes. La 21 ya drena su búfer de escrituras antes de MMIO; la integración
   debe conservar esa propiedad.
5. Definir tamaños de acceso y efectos laterales de forma uniforme.
6. Decidir quién solicita los swaps y cómo se interpreta `HALT_AT` cuando el
   productor de imagen sea la GPU.
7. Adaptar modelos, monitores, constantes de programas y tests, sin presentar la
   migración como aplicada a las carpetas históricas.

Los framebuffers pueden seguir siendo memoria ordinaria compartida. Separar
ventanas MMIO no obliga a duplicar RAM, ni proporciona coherencia o sincronización
por sí solo.

## 6.5. El monitor: versión, identidad y unificación

El registro de identificación de §6 tiene una consecuencia sobre el monitor, y
conviene verla antes de implementarlo: **el número de versión de monitor hace hoy
dos trabajos que tiran en direcciones opuestas.**

### Lo que hay: diez números para cuatro juegos de comandos

Los `monitor.v` del repositorio solo tienen cuatro conjuntos de comandos
distintos, y CPU y GPU comparten exactamente los mismos opcodes base — no hay
ni un comando exclusivo de una familia:

| Juego | Comandos | Añade | Prototipos |
|---|---:|---|---|
| base | 12 | — | 6, 10, 16, y **todas las GPU**: 12, 14, 17, 22 |
| +contadores | 14 | `GET_CYCLES` `0x36`, `GET_INSTRUCTIONS` `0x37` | 18 |
| +serie | 16 | `SEND_BYTES` `0x38`, `RECV_BYTES` `0x39` | 19, 21 |

Los 12 comandos base: `PING` `0x01`, `GET_VERSION` `0x02`, `WRITE_BYTE` `0x10`,
`READ_BYTE` `0x11`, `WRITE_BLOCK` `0x20`, `READ_BLOCK` `0x21`, `RUN` `0x30`,
`HALT` `0x31`, `STEP` `0x32`, `GET_STATUS` `0x33`, `READ_REGISTER` `0x34`,
`RESET_CPU` `0x35`.

Frente a eso hay **diez números de versión** en uso: 1.15 a 1.20 y 2.3 a 2.4. La
desproporción se ve mejor con dos ejemplos:

- 6, 10 y 16 tienen el mismo juego de comandos y llevan 1.16, 1.17 y 1.18.
- 19 y 21 tienen el mismo juego de 16 y llevan 1.20 y **1.15**.
- 14 y 17 tienen el `monitor.v` **byte a byte idéntico**, y ahí sí comparten 2.4.

El número no dice qué comandos entiende la placa: dice qué revisión de hardware
es. Y como identidad tampoco alcanza, porque 14, 17 y 22 responden todos 2.4
siendo hardware distinto. Con `--version sdram` contra una placa con la 22
flasheada, la comprobación de bitstream pasa y se miden prestaciones del
hardware equivocado.

### En qué se diferencian de verdad los monitores

Quitando los comandos, las diferencias entre los diez ficheros se reducen a dos
cosas, y una de ellas es una asimetría entre familias que conviene conocer:

**La lista blanca de direcciones.** En GPU vive **dentro** de `monitor.v`, como
gemela a mano de `MONITOR_REGIONS` en `monitor.py`:

| Prototipo | Rangos que acepta el monitor |
|---|---|
| 12 | `< 0x00020000`, `0x80000100–0x80000118`, `0x80001000–0x80001080` |
| 14, 17 | `< 0x02000000`, `0x80000100–0x80000118`, `0x80001000–0x80001080` |
| 22 | lo de 14 más `0x80000200–0x80000218` y `0x80000300–0x80000320` |

En CPU **no está en `monitor.v`**: ahí lo único que hay es un rechazo de bloques
por encima de `0x02000000`, y el encaminamiento a MMIO lo hace el adaptador de
memoria, fuera del monitor (`MMIO_PREFIX = 20'h80000` en
[monitor_mem_adapter_128.v](../21.fpga-cpu-hdmi-alu/monitor_mem_adapter_128.v)).
La 6 no tiene comprobación ninguna: responde el bus.

De ahí salen dos consecuencias que sorprenden si no se sabe: en CPU el host llega
al MMIO **byte a byte** con `WRITE_BYTE`/`READ_BYTE` pero no con bloques, y
`MONITOR_REGIONS` está vacío aunque el host sí pueda tocar los registros de vídeo.
En GPU los bloques a las ventanas MMIO sí valen, que es como el monitor escribe
los descriptores de warp.

**El cableado de reset y lectura de registros.** CPU y GPU usan los mismos
opcodes, pero `READ_REGISTER` y `RESET_CPU` van a sitios distintos. Es la única
diferencia estructural de verdad, y la única que no se resuelve con parámetros.

La diferencia completa entre el monitor de la 14 y el de la 22 son **14 líneas**,
todas de la lista blanca. Y el propio fichero avisa de lo que cuesta mantener esa
duplicación a mano:

> Esta lista es la GEMELA de MONITOR_REGIONS en monitor.py, y las dos tienen que
> decir lo mismo. Añadir una ventana en gpu_system_bl8 no basta: si no se añade
> también aquí, el monitor rechaza el comando antes de que llegue al
> decodificador, y el síntoma es un NACK que parece un bitstream viejo.

### Lo propuesto: dos campos, dos preguntas

- **Versión de monitor** = contrato de protocolo y semántica. Sube cuando cambian
  los comandos, o cuando algo se vuelve incompatible **en silencio**. Pasaría de
  diez valores a cuatro, uno por juego de comandos.
- **Registro de identificación** (§6) = qué hardware hay en la placa. Bitmap de
  dispositivos, perfil de ISA, identificador de sistema.

El caso que justifica conservar el número es el backport de R0: mismos comandos,
mismos dispositivos, misma lista de rangos, y un bitstream viejo no da error —
da otro resultado. Un bitmap de dispositivos no detecta eso. Es exactamente para
lo que sirve una versión, y por eso no se sustituye por capabilities.

### Hacia un monitor único

Con los dos campos separados, un solo `monitor.v` parametrizado es viable: los
comandos opcionales se activan por parámetro y la lista blanca **se deriva** de
qué dispositivos hay, en vez de copiarse. Con los slots fijos de §6 esa derivación
es directa: dirección acordada por dispositivo, presencia declarada en el bitmap,
y una sola fuente para las tres cosas que hoy se mantienen por separado — el
bitmap, la lista blanca del RTL y lo que valida el cliente Python.

El orden importa, porque hacerlo al revés obliga a tocar el monitor dos veces:

1. Fijar los slots (§6). Sin direcciones acordadas, el bitmap no significa nada.
2. Añadir el registro de identificación y trasladarle el trabajo de identidad.
3. Renumerar las versiones de monitor por juego de comandos.
4. Unificar los `monitor.v`, derivando la lista blanca.

## 7. Validación y fuentes

Hay que comprobar las direcciones en todos los niveles, y cada uno responde a una
pregunta distinta:

- El **caso de prueba** describe accesos y capabilities requeridas.
- El **backend** identifica versión, capacidades y rangos de RAM; las pruebas de
  periféricos necesitan además sus requisitos específicos.
- El **cliente del monitor** valida rangos y modalidades de transferencia.
- Los **adaptadores y decodificadores RTL** determinan el dispositivo real y sus
  errores.

`ARCHITECTURAL_REGIONS` describe los intervalos de RAM usados para validar
programas. En GPU, `MONITOR_REGIONS` añade las ventanas solo host. En las CPU con
vídeo y serie está **vacío y los dispositivos existen igualmente**: no se puede
inferir la ausencia de MMIO de que `MONITOR_REGIONS` esté vacío. Los intervalos
Python son normalmente semiabiertos; el final `0x80000118` incluye los cuatro
bytes del registro que empieza en `0x80000114`.

Referencias principales:

- CPU: [mmio_decoder.v](../21.fpga-cpu-hdmi-alu/mmio_decoder.v),
  [video_registers.v](../21.fpga-cpu-hdmi-alu/video_registers.v),
  [serial_port.v](../21.fpga-cpu-hdmi-alu/serial_port.v),
  [cpu_dmem_adapter.v](../21.fpga-cpu-hdmi-alu/cpu_dmem_adapter.v),
  [top.v](../21.fpga-cpu-hdmi-alu/top.v), [monitor.py](../21.fpga-cpu-hdmi-alu/monitor.py).
- GPU: [gpu_system_bl8.v](../22.fpga-gpu-bl8/gpu_system_bl8.v),
  [gpu_video_regs.v](../22.fpga-gpu-bl8/gpu_video_regs.v),
  [gpu_perf_counters.v](../22.fpga-gpu-bl8/gpu_perf_counters.v),
  [monitor.py](../22.fpga-gpu-bl8/monitor.py),
  [gpu_system.v](../17.fpga-gpu-ram-v2/gpu_system.v).
- Diseño de la ventana MMIO de la 22: [mmio.md](../22.fpga-gpu-bl8/mmio.md).
- Simuladores: [minicpu_sim.py](../2.cpu-sim-func/minicpu_sim.py),
  [minigpu_sim.py](../11.gpu-sim-func/minigpu_sim.py).

### Capacidades declaradas por prototipo (generado)

`tools/generate-docs` mantiene esta tabla cruzando directamente
`x.tests/backends/{fpga,gpu_fpga}.py`, la misma fuente que valida
`ARCHITECTURAL_REGIONS`/`MONITOR_REGIONS` arriba:

<!-- BEGIN GENERATED: prototype-summary -->
| Prototype | Version | Monitor | Clock | Capabilities |
|---|---|---|---|---|
| [`6.fpga-cpu`](../6.fpga-cpu) | ebr | 3.6 | 120.0 MHz | mul_div, read_word, write_word |
| [`10.fpga-cpu-ram`](../10.fpga-cpu-ram) | sdram | 3.10 | 120.0 MHz | read_word, write_word |
| [`12.fpga-gpu`](../12.fpga-gpu) | bram | 3.12 | 25.0 MHz | read_word, write_word, warp_config, simt_debug |
| [`14.fpga-gpu-ram`](../14.fpga-gpu-ram) | sdram | 3.14 | 25.0 MHz | read_word, write_word, warp_config, simt_debug |
| [`16.fpga-cpu-hdmi`](../16.fpga-cpu-hdmi) | hdmi | 3.16 | 100.0 MHz | mul_div, video, read_word, write_word, perf_counters |
| [`17.fpga-gpu-ram-v2`](../17.fpga-gpu-ram-v2) | 17.fpga-gpu-ram-v2 | 3.17 | 25.0 MHz | read_word, write_word, warp_config, simt_debug |
| [`18.fpga-cpu-hdmi-bl8`](../18.fpga-cpu-hdmi-bl8) | bl8 | 3.18 | 80.0 MHz | mul_div, video, frame_capture, read_word, write_word, perf_counters |
| [`19.fpga-cpu-hdmi-ls`](../19.fpga-cpu-hdmi-ls) | subword | 4.19 | 80.0 MHz | mul_div, subword_memory, calls, video, frame_capture, serial, read_word, write_word, perf_counters |
| [`21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu) | alu | 4.21 | 80.0 MHz | mul_div, subword_memory, calls, shift_immediate, alu_extended, compare, video, frame_capture, serial, read_word, write_word, perf_counters |
| [`22.fpga-gpu-bl8`](../22.fpga-gpu-bl8) | lsu2 | 3.22 | 25.0 MHz | video, read_word, write_word, warp_config, simt_debug, perf_counters |
<!-- END GENERATED: prototype-summary -->
