# Contrato MMIO v2 de MiniCPU y MiniGPU

**Qué es este documento.** La referencia de direcciones del proyecto: el espacio
físico, los dispositivos, sus registros y las reglas de acceso. Dice **cómo
tiene que quedar todo** — MiniCPU, MiniGPU, el sistema integrado, los
simuladores, el monitor y las herramientas.

**Qué no es.** No describe lo que hay implementado hoy. Ningún prototipo cumple
todavía este contrato: lo que implementa cada uno está en
[`../docs/resumen-prototipos.md`](../docs/resumen-prototipos.md), con su tabla
de conformidad. Y lo que se hizo para llegar hasta aquí está en
[`../docs/unificacion-mmio.md`](../docs/unificacion-mmio.md), que es un log
cerrado, no una referencia.

**Compatibilidad.** MMIO v2 **no** mantiene compatibilidad binaria con el mapa
de la página única de 4 KiB que implementan los prototipos actuales. La
migración es trabajo pendiente y está en [`../TODO.md`](../TODO.md).

Las palabras en memoria son little-endian. Los rangos de las tablas son
inclusivos salvo que se diga lo contrario.

---

## 1. Principios

### 1.1. Un único espacio físico

CPU, GPU, monitor y futuros masters comparten el mismo espacio de direcciones.

> **Una dirección física identifica un único recurso. Su significado nunca
> depende del master que accede.**

`0x80200004` es `VIDEO.FB_FRONT` tanto si lo lee la CPU como si lo escribe un
warp o lo sondea el monitor. No existen alias cuyo significado dependa del
origen de la transacción.

Esto es lo que hace que un binario de vídeo valga en varios prototipos sin
cambiar constantes.

### 1.2. Dirección y permiso son cosas distintas

El mapa determina **qué dispositivo corresponde a una dirección**. Una política
aparte determina **quién puede acceder a él**.

```text
master ──> address ──> [ mapa ] ──> dispositivo/registro ──> [ permisos ] ──> acceso
                                                                          └─> error
```

Separarlos permite añadir protección o nuevos masters sin tocar el mapa.

### 1.3. Los bloques son grandes y alineados

Reservar direcciones no implementa memoria: un hueco de 64 KiB en el mapa no
cuesta ni un LUT. A cambio da decodificación sencilla, direcciones estables y
sitio para crecer.

**MMIO v2 no compacta registros para ahorrar espacio de direcciones.** El mapa
anterior sí lo hacía —una página de 4 KiB troceada en slots de 256 B— y el
resultado fue que la ventana de configuración de warps quedó llena al 100 %,
con ocho descriptores y ni un hueco, que es justo lo que la hizo imposible de
ampliar.

### 1.4. Los arrays crecen hacia arriba y el control va detrás

> Cuando un bloque contiene un **array** —contadores, descriptores de warp,
> futuros canales de DMA—, el array empieza en el **offset 0** del bloque, se le
> reserva de una vez el espacio de su tamaño máximo, y los registros de control
> van **detrás de esa extensión máxima**, nunca intercalados.

Así el índice del elemento **es** su offset, no hace falta ninguna tabla de
correspondencia, y añadir un elemento no mueve nada.

Es una regla con nombre propio porque la alternativa se paga cara: con el
control pegado detrás del último elemento, el primer elemento que añades obliga
a moverlo, y mover un registro es renumerar — lo único que §1.5 prohíbe.

### 1.5. Las direcciones congeladas son ABI

No se renumeran dispositivos para mantener un orden conceptual. Un periférico
nuevo ocupa una región libre; `0x80600000` es preferible a mover TIMER.

---

## 2. Mapa físico global

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

La organización tiene tres niveles y conviene verlos:

- **`0x8000xxxx`–`0x800Fxxxx`**: el sistema en sí. Identificación, fabric,
  controlador de memoria.
- **`0x801xxxxx`–`0x80Fxxxxx`**: periféricos **compartidos**. Ni VIDEO ni SERIAL
  son propiedad de la CPU o de la GPU: son del sistema, y por eso un programa de
  cualquiera de las dos familias los ve en la misma dirección.
- **`0x81xxxxxx` y `0x82xxxxxx`**: lo **exclusivo** de cada núcleo. Aquí sí hay
  dueño, y por eso CPU y GPU pueden tener cada una su bloque de contadores sin
  pelearse por una dirección.

Esa separación entre compartido y exclusivo es lo que permite que un bitstream
con CPU y GPU a la vez no tenga que recolocar nada.

### 2.1. Alcance desde el código

Todas las bases están alineadas a 64 KiB, así que una sola instrucción carga
cualquiera de ellas:

```asm
MOVHI R1, 0x8020        ; R1 = 0x80200000, base de VIDEO
LOAD  R2, R1, 0x04      ; R2 = FB_FRONT
```

`imm16` con signo cubre ±32 KiB desde el registro base, de sobra para cualquier
bloque. Un programa que use tres dispositivos sostiene tres registros base, y
hay 31 registros generales.

---

## 3. Memoria principal

```text
MEM_BASE = 0x00000000
MEM_SIZE = 0x02000000     (32 MiB en las implementaciones con SDRAM)
```

Los dos son legibles en `SYSTEM` (§5), de modo que **un binario puede preguntar
cuánta RAM hay** en vez de suponerlo. Las direcciones de la región MEMORY sin
memoria física detrás generan error.

### 3.1. Prototipos con EBR

Los prototipos sin SDRAM usan una región **contigua**, no dos bancos separados
por un hueco:

```text
0000_0000 - 0000_7FFF    32 KiB EBR
```

La separación entre `.text`, `.rodata`, `.data`, `.bss` y pila es cosa del
software —ensamblador y, en su día, linker—, no del mapa físico. Así
`MEM_BASE`/`MEM_SIZE` describen también estos prototipos sin ninguna excepción,
y un bloque de transferencia puede cruzar cualquier dirección interior.

### 3.2. Framebuffers

Los framebuffers son **RAM ordinaria**. Separar ventanas MMIO no obliga a
duplicar memoria ni proporciona coherencia por sí solo. Sus direcciones son
configuración, no reservas impuestas a todos los programas.

---

## 4. Reglas de acceso

### 4.1. Tamaños

La RAM admite los tamaños que defina MiniISA: byte, media palabra y palabra,
según el perfil de ISA del prototipo.

**MMIO admite exclusivamente palabras de 32 bits alineadas.**

```text
LW / SW  sobre address[1:0] == 2'b00    permitido
LB / LBU / SB                           error
LH / LHU / SH                           error
cualquier dirección desalineada         error
```

Es una regla **arquitectónica**, no una limitación del fabric. El fabric puede
transportar `size` y `wstrb` porque la RAM los necesita; el contrato MMIO es
independiente de eso. Incluso los periféricos que manipulan bytes, como SERIAL,
exponen registros de 32 bits.

La razón es que un registro no es memoria: leerlo puede tener efectos laterales,
y media lectura no tiene un significado definido. `SERIAL.DATA` extrae un byte
de la cola — leerlo cuatro veces byte a byte extrae cuatro bytes, que no es lo
que quería quien escribió `LW`.

### 4.2. Acceso a MMIO desde código SIMT

> **Una instrucción SIMT que accede a MMIO solo es válida cuando exactamente
> una lane activa realiza el acceso.**

```c
if (lane_id == 0)
    VIDEO_CTRL = VIDEO_SCANOUT;     // válido
```

Si dos o más lanes acceden a MMIO en la misma instrucción, el acceso genera
**error**, aunque usen la misma dirección y escriban el mismo valor. No hay
coalescing, ni broadcast, ni elección implícita de una lane.

La regla no se aplica a la RAM, donde el coalescing es precisamente lo que se
quiere.

El motivo es que un registro de 32 bits no es una línea de caché, y ocho lanes
escribiendo registros distintos a la vez no tiene semántica útil. Serializarlas
en silencio sería peor que el error: el mismo kernel haría cosas distintas según
cuántas lanes estuvieran activas.

**Trampa conocida al escribir ese `if`:** un salto divergente necesita `SSY`
delante marcando dónde reconvergen los caminos. Sin él el SM para con
`ERROR_SIMT` (`0x06`), y el síntoma no se parece en nada a un problema de MMIO.

### 4.3. Errores

Un acceso MMIO es inválido cuando:

1. el dispositivo no está implementado;
2. el offset no corresponde a un registro;
3. se escribe un registro de solo lectura;
4. el acceso no es de 32 bits;
5. la dirección está desalineada;
6. se escribe un valor arquitectónicamente inválido;
7. el master no tiene permiso;
8. se pide una operación de control en un estado donde no es válida.

Los accesos inválidos **no** devuelven cero en silencio, **no** ignoran la
escritura y **no** corrigen el valor. Generan error.

La regla alcanza los accesos del programa **y los del monitor**, sueltos y por
bloques. Filtrar solo los comandos del monitor no la implementa para el núcleo.
El núcleo debe señalar el error de acceso a memoria y el monitor debe rechazar
la transacción, sin presentar el cero del bus como lectura válida ni confirmar
una escritura descartada.

Una lectura cero solo es válida si el contrato del registro la define
expresamente — `DEVICES` leyendo cero significa «sin declarar», y eso es un
valor, no un error.

Conceptualmente se distinguen:

```text
ACCESS_FAULT        dispositivo ausente, offset reservado, permiso, estado
ALIGNMENT_FAULT     dirección desalineada o tamaño no permitido
```

Las implementaciones actuales pueden convertir ambos en una detención del
núcleo y un código de error para el monitor. Una futura arquitectura de
excepciones podrá mapearlos a traps.

**Por qué error y no cero:** una lectura cero no distingue «este dispositivo no
existe» de «este registro vale cero legítimamente». Rechazar el acceso preserva
el diagnóstico de direcciones equivocadas, que es la clase de fallo que de otro
modo aparece tres capas más arriba y sin pista de dónde vino.

---

## 5. SYSTEM — `0x80000000`

| Offset | Registro | Acceso | Función |
|---:|---|---|---|
| `+0x00` | `MAGIC` | R | Identificación de MMIO v2 |
| `+0x04` | `MMIO_VERSION` | R | Versión de este contrato |
| `+0x08` | `SYSTEM_ID` | R | Qué sistema es |
| `+0x0C` | `DEVICES` | R | Bitmap de dispositivos presentes |
| `+0x10` | `MEM_BASE` | R | Base de la memoria principal |
| `+0x14` | `MEM_SIZE` | R | Tamaño de la memoria principal |
| `+0x18` | `MONITOR_VERSION` | R | Versión del protocolo del monitor |

Las siete palabras son de **solo lectura**; escribirlas da error. El resto del
bloque está reservado y también da error: no devuelve cero ni repite las
palabras por alias.

### 5.1. `MAGIC`

```text
0x4D474155
```

Permite reconocer MMIO v2 sin ambigüedad, y distinguirlo del `SYS_ID` del mapa
anterior, que llevaba el magic `0x4D47` en los bits 31:16 de otra dirección. El
magic existe para que el valor 0 no sea ambiguo entre «prototipo sin bloque de
identificación» y «prototipo número 0».

### 5.2. `MMIO_VERSION`

```text
bits 15:8    major      un cambio incompatible lo incrementa
bits  7:0    minor      una extensión compatible lo incrementa
bits 31:16   0
```

### 5.3. `SYSTEM_ID`

Identifica qué sistema hay en la placa. Su valor es el **número de carpeta del
prototipo**:

```text
bits  7:0    número de carpeta       22 → 0x16
bits 31:8    reservado, cero
```

Elegir el número de carpeta tiene una virtud que ningún identificador asignado a
mano iguala: **no hay nada que registrar al añadir un prototipo, y es imposible
duplicarlo**, porque lo impone el nombre del directorio. La alternativa —una
tabla de identificadores mantenida a mano— es una gemela más que sincronizar.

`SYSTEM_ID` no sustituye a `CPU_ID` ni a `GPU_ID`, que describen los núcleos.
Describe la configuración completa: MiniCPU, MiniGPU o MiniCPU + MiniGPU.

### 5.4. `DEVICES`

Bitmap estable de dispositivos presentes.

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

bits 31:11 reservados
```

> Una asignación de bit, una vez hecha, **nunca cambia de significado ni se
> reutiliza** para otro dispositivo.

`SYSTEM` conserva su bit aunque sea necesariamente presente para poder leer
`DEVICES`, para que el bitmap sea una descripción completa y uniforme.

FABRIC y SDRAM tienen bits separados porque hay configuraciones que carecen de
uno de los dos.

Un `DEVICES` que lee cero con `MMIO_VERSION` major 1 significa **«sin
declarar»**, no «ningún dispositivo». Es un valor legítimo, no un error.

**De dónde sale.** `DEVICES` no se escribe a mano en cada `top.v`. Se deriva de
lo que hay en el RTL, por el mismo camino que ya siguen las capacidades:
[`../tools/capabilities.json`](../tools/capabilities.json) dice qué buscar en el
RTL para saber si un prototipo tiene cada cosa, y
[`../tools/rtl_facts.py`](../tools/rtl_facts.py) lo lee. Lo que no pueda salir
del RTL va en el `version.json` de la carpeta. Un bitmap escrito a mano sería
una tercera gemela junto a las ventanas del decodificador y la lista del
cliente Python, que es exactamente lo que este contrato quiere quitar.

### 5.5. `MEM_BASE` y `MEM_SIZE`

Describen la memoria principal, de modo que un programa pueda colocarse sin
suponer el tamaño. Un binario que quiera su framebuffer al final de la RAM lo
calcula en vez de llevarlo compilado.

### 5.6. Descubrimiento

**No se descubren dispositivos sondeando direcciones.** Sondear no distingue un
dispositivo ausente de un registro cuyo valor legítimo es cero, y con la
política de §4.3 un sondeo a un dispositivo ausente además detiene el núcleo.

El procedimiento es:

```text
leer SYSTEM.MAGIC
      ↓
comprobar MMIO_VERSION
      ↓
leer SYSTEM.DEVICES
      ↓
acceder solo a los dispositivos cuyo bit está a uno
```

Una dirección de un dispositivo con su bit a cero genera error.

**Compatibilidad con bitstreams antiguos.** Es responsabilidad del host, no del
RTL nuevo. El host debe distinguir cuatro cosas: identificación válida, la
lectura cero histórica de un bitstream anterior al bloque, un rechazo explícito
del acceso, y un fallo de transporte. Un rechazo no demuestra por sí solo que el
bitstream sea antiguo, y un timeout no debe convertirse en «sin
identificación». Cambiar este contrato no modifica el comportamiento de un
bitstream que ya está flasheado, así que no hace falta ninguna excepción en el
RTL nuevo para conservar esa compatibilidad.

---

## 6. FABRIC — `0x80010000`

Bloque propio para estado, configuración e instrumentación de la interconexión.
Existe solo en sistemas que incorporan un fabric, y su bit en `DEVICES` lo dice.

Su contenido **no se congela todavía**. Cuando haya necesidad real de medir se
definirán contadores de transacciones por master, ciclos de espera, arbitraje,
utilización, congestión y stalls.

---

## 7. SDRAM — `0x80020000`

Bloque propio para información, configuración e instrumentación del controlador
de SDRAM. Existe solo con `DEVICES.SDRAM = 1`.

Su contenido **no se congela todavía**. Posibles métricas futuras: lecturas,
escrituras, ráfagas, ciclos ocupado, stalls y comportamiento de filas y bancos.

---

## 8. SERIAL — `0x80100000`

Periférico lógico de colas, no un segundo UART físico: los bytes pueden viajar
encapsulados sobre el UART del monitor. Es un periférico **del sistema**,
accesible desde CPU y desde GPU.

| Offset | Registro | Acceso | Función |
|---:|---|---|---|
| `+0x00` | `DATA` | RW | Leer extrae un byte de RX; escribir inserta el byte bajo en TX |
| `+0x04` | `STATUS` | RW | Ocupación de las colas y overrun |
| `+0x08` | `PEEK` | R | Consulta la cabeza de RX **sin extraerla** |

### 8.1. `DATA`

```text
lectura     bits  7:0   byte de RX, o cero si la cola está vacía
            bits 31:8   cero
escritura   bits  7:0   byte a insertar en TX
            bits 31:8   ignorados
```

La transacción sigue siendo de 32 bits. La lectura **consume** el byte.

### 8.2. `STATUS`

```text
bits  7:0    bytes disponibles en RX
bits 15:8    huecos disponibles en TX
bit  16      RX_OVERRUN, pegajoso, se limpia escribiendo uno (W1C)
bits 31:17   reservados
```

`RX_OVERRUN` no debería levantarse nunca: el control de flujo lo hace el host
con el campo de huecos libres que viaja en la respuesta de cada envío. Si se
levanta, es que el host lo ignoró.

### 8.3. `PEEK`

Devuelve la cabeza de RX **sin extraerla**.

Existe porque leer `DATA` tiene efecto lateral, y una herramienta de inspección
que sondee la cola no puede permitirse consumir el byte que mira.

---

## 9. VIDEO — `0x80200000`

Un solo dispositivo, que agrupa generación de salida, scanout, framebuffers,
swap, contadores de vídeo y captura determinista.

**No existe `FRAME_CAPTURE` como dispositivo independiente.** La separación que
había en algunos prototipos era histórica: no se había añadido un dispositivo,
se había ensanchado uno.

VIDEO es del **sistema**, no de la CPU ni de la GPU.

| Offset | Registro | Acceso | Función |
|---:|---|---|---|
| `+0x00` | `CTRL` | RW | Modo de salida |
| `+0x04` | `FB_FRONT` | RW | Dirección del buffer que se muestra |
| `+0x08` | `FB_BACK` | RW | Dirección del buffer que se dibuja |
| `+0x0C` | `SWAP` | RW | Solicitud y estado de intercambio |
| `+0x10` | `STATUS` | RW | Underflow y swap pendiente |
| `+0x14` | `FRAME_COUNT` | R | Frames emitidos |
| `+0x18` | `SWAP_COUNT` | R | Intercambios completados |
| `+0x1C` | `HALT_AT` | RW | Captura determinista |
| `+0x20` | `HALT_TARGET` | RW | A quién parar |
| `+0x24` | `VIDEO_TX` | R | Transacciones de memoria del scanout |

### 9.1. `CTRL`

```text
bits 1:0     0  BLANK
             1  PATTERN
             2  SCANOUT
             3  reservado
bits 31:2    cero
```

Escribir el modo reservado genera error.

### 9.2. `FB_FRONT` y `FB_BACK`

Direcciones físicas de byte, en RAM ordinaria.

**Deben estar alineadas a 16 bytes.** Una dirección mal alineada genera
**error**: no se trunca ni se corrige.

Los 16 bytes salen de que el scanout lee en ráfagas. El truncamiento silencioso
—que es lo que hacían los prototipos anteriores— es peor que el error por una
razón concreta: era distinto en cada familia, 4 bytes en CPU y 16 en GPU, así
que el mismo programa dibujaba bien en una placa y torcido en la otra sin que
nada avisara.

### 9.3. `SWAP`

Escribir solicita intercambiar `FB_FRONT` y `FB_BACK`.

```text
lectura   bit 0     SWAP_PENDING
          bits 31:1 cero
```

**Escribir no intercambia nada**: solo levanta la petición. El intercambio
ocurre **en el vsync**, porque cambiar la dirección a mitad de frame partiría la
imagen en dos — que es exactamente el defecto que el doble buffer viene a
quitar.

### 9.4. `STATUS`

```text
bit 0        UNDERFLOW, pegajoso, W1C
bit 1        SWAP_PENDING
bits 31:2    reservados
```

`UNDERFLOW` es un nivel pegajoso: si se pone a uno, ahí se queda hasta que
alguien escriba un uno en el bit 0. Si se recargara cada vsync, un underflow de
un solo frame sería invisible.

**Los contadores no se mezclan con `STATUS`.** `FRAME_COUNT` tiene su propio
registro de 32 bits, no un hueco en los bits altos de éste.

### 9.5. `FRAME_COUNT` y `SWAP_COUNT`

Dos contadores de 32 bits que miden **eventos distintos**:

- `FRAME_COUNT` cuenta frames emitidos por el scanout, corra o no el programa.
- `SWAP_COUNT` cuenta intercambios completados.

Un programa que no pide swaps hace avanzar el primero y deja el segundo quieto.
Los dos dan la vuelta; a 60 Hz tardan 2,3 años, así que no llevan bandera de
desbordamiento (§12.4).

### 9.6. `HALT_AT` y `HALT_TARGET`

Sirven para que el host capture un frame determinista: se arma la alarma, el
núcleo se para solo, y el host lee el framebuffer con la imagen quieta.

```text
HALT_AT = 0     desarmado
HALT_AT = N     VIDEO pide detener los targets seleccionados cuando
                FRAME_COUNT >= N
```

La comparación es `>=` y no `==`, como defensa barata por si el contador se pasa
de largo.

```text
HALT_TARGET   bit 0    CPU
              bit 1    GPU
              bits 31:2 reservados
```

`HALT_TARGET` existe porque **quien produce los frames y quien se para no tienen
por qué ser el mismo**. En un sistema donde dibuja la GPU y la CPU orquesta,
querer parar una, otra o las dos son tres casos reales.

`HALT_AT` cuenta contra `FRAME_COUNT`, no contra `SWAP_COUNT`: un programa que
se cuelga sin pedir swaps también tiene que poder capturarse.

### 9.7. `VIDEO_TX`

Contador de 32 bits de transacciones de memoria generadas por el scanout.

Pertenece a VIDEO, no al bloque de contadores de la GPU, por la regla de §12.1:
cada contador pertenece al componente que **genera** el evento. En su día vivió
en los contadores de la GPU, y eso era un accidente de que solo la GPU tenía
contadores.

### 9.8. Estado tras reset

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

**El sistema no arranca en SCANOUT**, y es deliberado: la SDRAM recién encendida
contiene basura, así que arrancar en SCANOUT sería elegir por defecto una salida
indefinida. Con PATTERN, ver el patrón demuestra que HDMI, PLL, cable y monitor
funcionan, y no verlo señala aguas arriba.

---

## 10. TIMER — `0x80300000`

Reservado para el timer del sistema. Su interfaz **no se define todavía**.
Mientras no exista, `DEVICES.TIMER = 0` y cualquier acceso genera error.

**Aquí vive el reloj de pared**, y esa es la razón de que no esté en los bloques
de PERFORMANCE. Medir trabajo y medir tiempo son dos preguntas distintas, y
§12.3 explica por qué mezclarlas da respuestas falsas.

---

## 11. INTERRUPT CONTROLLER — `0x80400000` · DMA — `0x80500000`

Reservados. Sus interfaces no se congelan todavía, y sus bits de `DEVICES` están
a cero mientras no existan.

Del controlador de interrupciones se prevén al menos estas fuentes:
`GPU.WARP_DONE`, error de GPU y TIMER.

---

## 12. Contadores de rendimiento: reglas comunes

Estas reglas valen para `CPU PERFORMANCE` y `GPU PERFORMANCE`, y para los
bloques de FABRIC y SDRAM cuando se definan.

### 12.1. Cada contador pertenece a quien genera el evento

```text
GPU LSU ──> FABRIC ──> SDRAM ──> memoria
   │           │          │
 LSU_TX    contadores  contadores
           de fabric   del controlador
```

Los tres pueden medir puntos distintos del mismo camino, y eso es útil: así se
localiza dónde aparece un cuello de botella sin mezclar eventos de capas
diferentes. Lo que no se hace es meter el contador de tráfico de la pantalla
dentro de la unidad de cómputo.

### 12.2. Dan la vuelta, no saturan

Los contadores son de 32 bits y hacen **wrap-around**.

Saturar destruiría el uso normal, que es la **resta**: se lee antes, se lee
después y se restan. Con wrap, `después − antes` sigue siendo correcto aunque el
contador haya dado una vuelta en medio, porque la aritmética modular de 32 bits
lo arregla sola. Con saturación, en cuanto una de las dos lecturas llega al
máximo la medida se pierde entera y no hay forma de recuperarla.

A 80 MHz, 2³² ciclos son 54 segundos; a 25 MHz, 172.

### 12.3. Avanzan solo con el núcleo corriendo

**Los contadores no corren libres.** Solo avanzan mientras el núcleo al que
pertenecen ejecuta.

No es un detalle de implementación, es el punto. Un contador libre sirve para
que un programa se mida a sí mismo —las dos lecturas las hace él, y entre ellas
solo pasa lo que él hace— pero **no** para que lo mida el host: ahí, entre las
dos lecturas caben las órdenes por serie y el bucle que sondea si ha parado. Con
el contador de ciclos corriendo libre, un perfilado daba un CPI de 43 en vez de
15,6 — estaba midiendo el reloj de pared.

`VIDEO_TX` se cuenta con el mismo criterio, porque el scanout sigue leyendo
memoria con el núcleo parado y ese tráfico no es del programa.

Quien quiera reloj de pared tiene el TIMER (§10). Son dos eventos distintos, no
dos formas de contar lo mismo.

### 12.4. Bandera de desbordamiento

Cada contador tiene un bit pegajoso que dice si ha dado la vuelta, en
`PERF_OVF`. Se pone a uno en la transición `0xFFFFFFFF → 0x00000000` y se limpia
escribiendo un uno en ese bit (W1C).

Así la resta sigue funcionando **y además se puede saber si es de fiar**. Es el
mismo patrón que `VIDEO.STATUS.UNDERFLOW` y `SERIAL.STATUS.RX_OVERRUN`: un aviso
pegajoso que no se pierde si nadie mira a tiempo.

`RESET_COUNTERS` limpia también `PERF_OVF`. Si no lo hiciera, resetear para
medir limpio dejaría un aviso de la medida anterior — el falso positivo que la
bandera existe para evitar.

Los contadores de VIDEO **no** llevan bandera, y es una decisión, no un olvido:
dan la vuelta en horas (`VIDEO_TX`) o años (`FRAME_COUNT`, `SWAP_COUNT`), o sea
nunca dentro de una medida. Añadírsela sería uniformidad por uniformidad.

### 12.5. Congelar para leer

`PERF_CTRL` tiene un bit para parar y arrancar todos los contadores del bloque a
la vez.

Sin él, leer seis contadores son seis instantes distintos con el programa
corriendo entre medias, y el CPI que calcules es de una mezcla. Con freeze:
parar, leer los seis contadores y `PERF_OVF`, arrancar.

**`PERF_CTRL` nunca se replica.** Un segundo registro de control significaría
dos escrituras para congelar, o sea dos instantes, que es justo el problema que
el bit viene a resolver. Lo que crece con el número de contadores es `PERF_OVF`,
no `PERF_CTRL`.

### 12.6. Disposición del bloque

Aplicando la regla de §1.4:

```text
+0x000 … +0x0FC   ARRAY DE CONTADORES, hasta 64 ranuras     R
                  el contador n está en +4n
                  las ranuras sin contador dan error

+0x100            PERF_CTRL      RW
+0x104            PERF_OVF0      W1C    contadores  0–31
+0x108            PERF_OVF1      W1C    contadores 32–63
+0x10C … +0xFFFF  reservado
```

La regla completa cabe en una línea:

> El contador `n` está en `+4n`, y su bandera es el bit `n mod 32` de
> `PERF_OVF[n div 32]`.

Añadir un contador es ocupar la siguiente ranura libre: su bandera ya existe y
no se mueve nada. `PERF_OVF1` se declara desde ahora aunque lea cero, porque
añadirlo después obligaría a decidir dónde con el control ya congelado delante.

`PERF_CTRL`:

```text
bit 0    ENABLE      1 cuenta, 0 congela todos los contadores del bloque
bit 1    RESET       escribir uno pone a cero los contadores y PERF_OVF
bits 31:2 reservados
```

---

## 13. CPU — `0x81000000`

### 13.1. CPU CORE — `0x81000000`

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `CPU_ID` | R |
| `+0x04` | `CPU_VERSION` | R |
| `+0x08` | `CPU_ISA` | R |
| `+0x0C` | `CPU_FEATURES` | R |
| `+0x10` | `CPU_STATUS` | R |

`CPU_ISA` describe capacidades arquitectónicas; `CPU_FEATURES`, características
de la implementación. Sus bits se documentan junto a MiniISA, y se derivan del
RTL por el mismo camino que `DEVICES` (§5.4).

### 13.2. CPU PERFORMANCE — `0x81010000`

Array según §12.6.

| Ranura | Offset | Contador |
|---:|---:|---|
| 0 | `+0x00` | `CYCLES` |
| 1 | `+0x04` | `RETIRED` |
| 2 | `+0x08` | `IMEM_HITS` |
| 3 | `+0x0C` | `IMEM_MISSES` |
| 4 | `+0x10` | `MEM_TX` |
| 5 | `+0x14` | `STALL_MEM` |

Con `CYCLES`, `STALL_MEM` e `IMEM_MISSES` se separa cómputo de memoria y de
fetch sin instrumentar nada más, y **un programa se mide a sí mismo en la
placa**, sin simular y sin cronómetro.

### 13.3. CPU DEBUG — `0x81020000`

Reservado para estado de depuración de CPU. No se congelan registros hasta que
haya una necesidad concreta.

---

## 14. GPU — `0x82000000`

### 14.1. GPU CORE / CONTROL — `0x82000000`

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

### `GPU_CAPS`

```text
bits  7:0    NUM_WARPS
bits 15:8    NUM_LANES
bits 31:16   reservados
```

La implementación actual tiene 8 y 8. **El software no debe asumirlo**: lo lee.

### `GPU_STATUS`

```text
bit 0        RUNNING      hay ejecución activa
bit 1        HALTED       ejecución global pausada
bit 2        IDLE         no queda ningún warp vivo
bit 3        ERROR        hay un error pendiente
bits 15:8    LIVE_WARPS   número de warps vivos
bits 31:16   reservados
```

`IDLE` es preferible a un `DONE` global porque la GPU puede recibir warps
nuevos dinámicamente, así que «no queda trabajo» y «el trabajo terminó» no son
lo mismo.

### `GPU_CONTROL`

```text
bit 0    RUN
bit 1    HALT
bit 2    RESUME
bit 3    STEP
bit 4    RESET
bits 31:5 reservados
```

Son **comandos**: escribir un uno ejecuta la acción, y leer devuelve cero en
esos bits. No deben escribirse a la vez comandos incompatibles.

- **`RUN`** arranca todos los warps implementados cuya máscara inicial de lanes
  sea distinta de cero, inicializando su estado runtime desde el descriptor.
  Solo es válido cuando no hay warps vivos; con alguno vivo, error.
- **`HALT`** pausa globalmente y **conserva** PCs, máscaras, pilas SIMT, waits,
  estado de la LSU y barreras. Los warps no se reinicializan.
- **`RESUME`** continúa. Solo válido con `HALTED = 1`.
- **`STEP`** avanza una unidad de depuración con la GPU detenida, y la deja
  detenida. Su semántica coincide con la del comando `STEP` del monitor.
- **`RESET`** descarta el estado runtime —warps vivos, pilas, waits, barreras,
  errores— pero **no** los descriptores, de modo que `RESET` seguido de `RUN`
  repite un lanzamiento con la misma configuración. El reset físico del sistema
  es otra cosa.

**Este bloque es lo que permite que la CPU use la GPU como acelerador.** En el
mapa anterior, `run/halt/step/reset` llegaban por señales del monitor, así que
solo el host podía lanzar la GPU y solo con la GPU parada.

### `WARP_START`, `WARP_LIVE`, `WARP_DONE`

Tres máscaras de 32 bits, una por warp. Los bits de warps no implementados son
cero.

- **`WARP_START`** (W): escribir un uno en el bit `n` arranca el warp `n`.
  Permite **añadir trabajo mientras otros warps ejecutan**. Es error arrancar un
  warp no implementado, uno que ya está vivo, o un descriptor cuya máscara
  inicial de lanes sea cero.
- **`WARP_LIVE`** (R): qué warps están vivos ahora.
- **`WARP_DONE`** (RW, W1C): máscara **pegajosa** de warps terminados. El evento
  no se pierde aunque la CPU tarde en mirarlo. Arrancar un warp con `RUN` o
  `WARP_START` limpia su bit automáticamente, de modo que las ranuras se
  reutilizan sin ceremonia. En el futuro, `WARP_DONE != 0` podrá generar una
  interrupción.

Con estos tres registros caben dos modelos de uso: configurar todo y lanzar con
`RUN`, o mantener una cola en RAM y reponer warps según se liberan ranuras, sin
necesidad de un command processor en hardware.

### 14.2. GPU WARPS — `0x82010000`

Array de descriptores de 16 bytes, según la regla de §1.4: el descriptor `n`
está en `base + 16n`, y no hay ningún registro de control dentro del bloque.

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `PC` | RW |
| `+0x04` | `ACTIVE` | RW |
| `+0x08` | `WORKGROUP_ID` | RW |
| `+0x0C` | `SIMT_STATE` | R |

El bloque de 64 KiB da sitio a **32 warps sin tocar el ABI**, que es el mismo
número que cubren las máscaras de §14.1. Una GPU con más de 32 podrá extender
el bloque con registros adicionales.

### `ACTIVE`

Máscara inicial de lanes. Para 8 lanes: `0x00` deshabilitado, `0x01` solo la
lane 0, `0x0F` las cuatro primeras, `0xFF` las ocho. Los bits por encima de
`NUM_LANES` deben ser cero.

> **`ACTIVE == 0` significa descriptor deshabilitado para `RUN`.**

No hay un `WARP_ENABLE` aparte: sobraría.

### `SIMT_STATE`

```text
bits  7:0     profundidad de REGION
bits 15:8     profundidad de PATH
bit  16       WAIT_MEM
bit  17       WAIT_BAR
bits 31:18    reservados
```

Es estado runtime de **solo lectura**; escribirlo genera error. No es un hueco
libre: si algún día entra una instrucción que necesite un identificador de warp
por usuario, no cabe aquí.

La información global de qué warps están vivos se obtiene con `WARP_LIVE`, no
desde el descriptor, para no mezclar configuración con scheduling.

Escribir un descriptor reinicia el estado de reconvergencia, barrera y contador
local del warp. No es una interfaz para modificar contexto mientras el warp
ejecuta.

### 14.3. GPU SIMT DEBUG — `0x82020000`

Solo información de depuración y microarquitectura SIMT.

| Offset | Registro | Acceso |
|---:|---|---|
| `+0x00` | `CONTEXT` | RW |
| `+0x04` | `LSU_SLOTS` | R |
| `+0x08` | `FIRST_ERROR` | R |
| `+0x0C` | `FIRST_ERROR_PC` | R |
| `+0x10` | `WARP_RETIRED` | R |

El contador global de instrucciones retiradas **no** está aquí: pertenece a GPU
PERFORMANCE.

```text
CONTEXT       bits 2:0    lane
              bits 5:3    warp
              bits 31:6   reservados

FIRST_ERROR   bits 2:0    lane
              bits 5:3    warp
              bit  6      lane_valid
              bits 15:8   error_code
              bits 31:16  reservados
```

`FIRST_ERROR` guarda **el primero**, no el último: cuando algo se rompe en ocho
lanes a la vez, el que informa es el que causó la parada. `error_code` es el
espacio de códigos del SM — `0x06` es `ERROR_SIMT`, el de un salto divergente
sin `SSY` delante.

`LSU_SLOTS` está aquí y no en PERFORMANCE porque es un estado **instantáneo**,
no un contador acumulado.

`CONTEXT` gobierna también qué registros devuelve el comando de lectura de
registros del monitor. No hay una ventana MMIO con los 32 registros: se leen por
comando, y esta dirección solo dice de quién.

### 14.4. GPU PERFORMANCE — `0x82030000`

Array según §12.6.

| Ranura | Offset | Contador |
|---:|---:|---|
| 0 | `+0x00` | `CYCLES` |
| 1 | `+0x04` | `RETIRED` |
| 2 | `+0x08` | `IMEM_HITS` |
| 3 | `+0x0C` | `IMEM_MISSES` |
| 4 | `+0x10` | `LSU_TX` |
| 5 | `+0x14` | `STALL_MEM` |

`LSU_TX` y `STALL_MEM` están aquí, y no en FABRIC, porque la LSU es parte de la
GPU. `VIDEO_TX` **no** está aquí: es de VIDEO (§9.7).

---

## 15. Visibilidad por master

El mapa dice qué dispositivo hay en cada dirección; esta sección dice quién
puede tocarlo. Son cosas independientes (§1.2), y esta política puede cambiar
sin que cambie ni una dirección.

**CPU**

```text
SYSTEM                R
FABRIC, SDRAM         según registro
SERIAL, VIDEO         RW
TIMER, INTC, DMA      futuro
CPU CORE/PERF/DEBUG   según registro
GPU CORE / CONTROL    RW      ← la CPU configura y lanza la GPU por MMIO
GPU WARPS             RW
GPU SIMT DEBUG        R
GPU PERFORMANCE       R
```

La CPU no necesita instrucciones especiales para usar la GPU: le basta el mapa.

**GPU**

```text
SYSTEM                R
SERIAL, VIDEO         RW, por acceso MMIO escalar (§4.2)
GPU información       R
GPU PERFORMANCE       según registro
```

El acceso desde un warp a los registros de scheduling y control **está
restringido**: un warp no debe reprogramarse a sí mismo ni a sus vecinos por
accidente a través de `GPU WARPS` o `WARP_START`. No hay caso de uso que lo pida
y sí modos de fallo.

**Monitor**

Alcanza todos los dispositivos implementados, para depurar. Sigue sujeto a todo
lo demás: solo lectura donde lo haya, alineamiento, tamaños, efectos laterales y
valores válidos.

---

## 16. El monitor

### 16.1. Los comandos son una fachada

El protocolo del monitor conserva sus comandos de control —`RUN`, `HALT`,
`STEP`, `RESET`— para que el trabajo diario no cambie. Lo que cambia es que
**por dentro escriben `GPU_CONTROL`** en vez de mover señales propias.

Tiene dos consecuencias buenas:

- **Una sola implementación** de arrancar la GPU, no dos que puedan divergir.
- **Desaparece la única diferencia estructural entre el monitor de CPU y el de
  GPU.** Hasta ahora, los comandos de lectura de registros y de reset iban
  cableados a sitios distintos según la familia, y era lo único que no se
  resolvía con parámetros. Si el control es una dirección, es la misma dirección
  en las dos.

### 16.2. Tamaños de acceso

```text
READ_BYTE  / WRITE_BYTE     RAM
READ_WORD  / WRITE_WORD     RAM y MMIO
transferencias de bloque    RAM y ventanas MMIO declaradas
```

Un acceso byte a byte dirigido a MMIO **no** debe convertirse en un acceso
sub-palabra al periférico: violaría §4.1.

La razón de que `READ_WORD`/`WRITE_WORD` existan es que un registro no se puede
leer ni escribir a trozos. Un contador de frames avanza entre dos bytes; y en
un registro que rearma una alarma al escribirse, hacerlo en cuatro trozos la
rearma cuatro veces con valores intermedios.

### 16.3. La versión del monitor describe el protocolo, y solo eso

`MONITOR_VERSION` sube cuando cambian los comandos o cuando algo se vuelve
incompatible **en silencio**. No identifica el hardware.

La identidad del hardware se lee de `SYSTEM_ID`, `DEVICES`, `CPU_FEATURES`,
`GPU_CAPS` y compañía. Antes, un mismo número de versión lo llevaban prototipos
con hardware distinto, y una comprobación de bitstream podía pasar contra la
placa equivocada.

Conviene no confundir esto con eliminar la versión: hay cambios que un bitmap de
dispositivos **no** detecta. Un core al que se le corrige el comportamiento de
un registro tiene los mismos comandos, los mismos dispositivos y las mismas
capacidades — y da otro resultado. Para eso sirve una versión, y por eso no se
sustituye por capabilities.

### 16.4. La lista blanca se deriva, no se copia

Las ventanas que el monitor acepta **se derivan** de qué dispositivos declara
`DEVICES`. No se escriben a mano en el RTL y otra vez en el cliente Python.

Mantener dos listas gemelas a mano ya se cobró su precio: añadir una ventana en
el RTL sin añadirla en la lista del monitor hace que éste rechace el comando
antes de que llegue al decodificador, y el síntoma es un NACK que parece un
bitstream viejo.

---

## 17. Simuladores

Los simuladores implementan **el mismo contrato** que el RTL: mismas
direcciones, mismos registros, mismos tamaños, mismo reset, mismos errores,
mismas restricciones y mismos efectos laterales arquitectónicos.

**No habrá programas `*_nommio` por limitaciones del simulador.** Un programa
que se ejecuta en el modelo y en la placa tiene que ser el mismo programa, o la
comparación no compara.

Lo que el modelo funcional **no** reproduce, y conviene tener presente al leer
un resultado: contienda por la memoria, underflow, desgarro y el tiempo de
llegada de los bytes por serie. VIDEO se modela funcionalmente sin reproducir
HDMI eléctricamente.

**Lo que no se debe hacer nunca es aceptar un acceso MMIO sin modelar el
dispositivo**, para que un programa deje de fallar. Un dispositivo que acepta
todo y no hace nada convierte un error en un resultado silenciosamente
incorrecto.

---

## 18. Orden entre CPU y GPU

En el sistema integrado debe garantizarse:

```text
CPU escribe código y datos
        ↓
CPU escribe descriptores de warp
        ↓
esas escrituras son visibles
        ↓
RUN / WARP_START
        ↓
GPU ejecuta
        ↓
GPU completa sus escrituras
        ↓
WARP_DONE / IDLE visibles
        ↓
CPU consume resultados
```

> Un evento de finalización no debe hacerse visible antes de que las escrituras
> asociadas a ese trabajo hayan alcanzado el punto de coherencia acordado.

El mecanismo concreto —orden fuerte de MMIO, drenado de buffers, fences, o
protocolo del fabric— se define al integrar. Lo que ya está decidido es la
propiedad, no cómo se consigue.

**Dominios de reloj.** CPU, GPU, fabric, SDRAM y VIDEO pueden ir a frecuencias
distintas; los adaptadores resuelven CDC, handshake, arbitraje y backpressure.
Una diferencia de reloj nunca modifica el significado de una dirección.

---

## 19. Estado global tras reset

> El sistema arranca en un estado seguro, reproducible y diagnosticable.

```text
VIDEO       CTRL = PATTERN, FB_FRONT = FB_BACK = 0, HALT_AT = 0
GPU         ningún warp vivo, WARP_DONE = 0, no HALTED, sin error
CPU PERF    contadores y PERF_OVF a cero
GPU PERF    contadores y PERF_OVF a cero
SERIAL      colas vacías
```

---

## 20. Fuente única de constantes

La fuente maestra del mapa es un include Verilog deliberadamente tonto —`define`,
nombre y constante, sin lógica ni expresiones—:

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

De ahí se generan las definiciones para el ensamblador, para C, para el monitor
y para los simuladores, de modo que las direcciones no se dupliquen a mano.

Que sea tonto es el requisito: un fichero con lógica no se puede leer desde
Python sin escribir un parser de Verilog.

**Advertencia que viene de la experiencia, y que hay que resolver antes de
construir esto:** un fichero generado se desincroniza en silencio si alguien
toca el RTL y no regenera, mientras que un test que compara falla a gritos. La
generación necesita, por tanto, un test que compruebe que lo generado está al
día — y no lo hay todavía; hoy solo se generan fixtures de simulación y
Markdown, nunca Verilog sintetizable.

---

## 21. Decisiones congeladas

1. Un único espacio físico global.
2. Una dirección tiene un único significado, sea quien sea el master.
3. Los permisos son independientes del mapa.
4. MMIO empieza en `0x80000000`.
5. La región de memoria tiene margen amplio de crecimiento.
6. Se abandona la página MMIO única de 4 KiB.
7. Se abandonan los slots globales de 256 bytes.
8. Los dispositivos ocupan bloques grandes y alineados a 64 KiB.
9. CPU y GPU tienen regiones propias; los periféricos son compartidos.
10. FABRIC y SDRAM tienen bloques y bits de `DEVICES` propios.
11. TIMER, INTC y DMA tienen espacio reservado.
12. MMIO solo admite palabras de 32 bits alineadas; la RAM admite sub-palabra.
13. Los accesos inválidos producen error, en lectura y en escritura.
14. Un acceso MMIO desde SIMT exige exactamente una lane activa.
15. VIDEO es un único dispositivo del sistema; `FRAME_CAPTURE` no existe aparte.
16. `FRAME_COUNT` y `SWAP_COUNT` son registros de 32 bits separados.
17. `HALT_AT` cuenta contra `FRAME_COUNT`, con comparación `>=`.
18. `HALT_TARGET` selecciona CPU, GPU o ambos.
19. Las bases de framebuffer se alinean a 16 bytes; desalinear es error.
20. `VIDEO_TX` pertenece a VIDEO.
21. CPU PERFORMANCE y GPU PERFORMANCE tienen direcciones distintas.
22. Cada contador pertenece al componente que genera el evento.
23. Los contadores dan la vuelta; no saturan.
24. Los contadores avanzan solo con su núcleo corriendo; el reloj de pared es
    del TIMER.
25. Cada contador tiene bandera pegajosa de desbordamiento, W1C, en `PERF_OVF`.
26. `PERF_CTRL` es único por bloque y congela todos sus contadores a la vez.
27. En un bloque con array, el array empieza en el offset 0 y el control va
    detrás de su extensión máxima.
28. SIMT DEBUG y GPU PERFORMANCE permanecen separados.
29. `RUN` lanza los descriptores habilitados; `WARP_START` permite scheduling
    dinámico.
30. `WARP_DONE` es pegajoso y W1C.
31. Las máscaras de warp son de 32 bits, para hasta 32 warps sin tocar el ABI.
32. `GPU_CAPS` declara `NUM_WARPS` y `NUM_LANES` reales.
33. `HALT`/`RESUME`/`STEP`/`RESET` forman parte de `GPU_CONTROL`.
34. `GPU_CONTROL.RESET` conserva los descriptores.
35. La CPU controla la GPU por MMIO, sin instrucciones especiales.
36. Los comandos del monitor son una fachada sobre los registros.
37. `MONITOR_VERSION` describe el protocolo; la identidad del hardware está en
    `SYSTEM`, `CPU CORE` y `GPU CORE`.
38. `SYSTEM_ID` es el número de carpeta del prototipo.
39. `DEVICES` tiene asignaciones de bit congeladas y se deriva del RTL.
40. La lista blanca del monitor se deriva de `DEVICES`, no se copia a mano.
41. Los prototipos con EBR mapean su memoria como una región contigua.
42. Simuladores y RTL implementan el mismo contrato; no hay programas `_nommio`.
43. Las constantes arquitectónicas parten de una fuente Verilog común.
44. Las direcciones congeladas no se renumeran.

---

## 22. Deliberadamente pospuesto

No son cuestiones abiertas del contrato, sino interfaces que se definirán cuando
exista el hardware correspondiente:

- **FABRIC** y **SDRAM**: registros internos y contadores.
- **TIMER**: interfaz y frecuencia.
- **INTERRUPT CONTROLLER**: fuentes, pending, máscaras, prioridades y vectores.
- **DMA**: canales, descriptores, tamaños y arbitraje.
- **Orden CPU-GPU**: el mecanismo concreto de fence o drenado (§18).
- **Bits de `CPU_ISA`, `CPU_FEATURES`, `GPU_ISA` y `GPU_FEATURES`**: se
  documentan junto a MiniISA.

---

## 23. Resumen visual

```text
0000_0000 ┌───────────────────────────────────────────┐
          │ MEMORY        SDRAM actual: 0000_0000     │
3FFF_FFFF │                          .. 01FF_FFFF     │
          └───────────────────────────────────────────┘
4000_0000 ┌───────────────────────────────────────────┐
7FFF_FFFF │ RESERVED                                  │
          └───────────────────────────────────────────┘

          ══ sistema ═════════════════════════════════
8000_0000 │ SYSTEM    MAGIC · VERSION · ID · DEVICES  │
8001_0000 │ FABRIC                        [reservado] │
8002_0000 │ SDRAM                         [reservado] │

          ══ periféricos compartidos ═════════════════
8010_0000 │ SERIAL    DATA · STATUS · PEEK            │
8020_0000 │ VIDEO     CTRL · FB · SWAP · contadores   │
8030_0000 │ TIMER                         [reservado] │
8040_0000 │ INTC                          [reservado] │
8050_0000 │ DMA                           [reservado] │

          ══ exclusivo de CPU ════════════════════════
8100_0000 │ CPU CORE                                  │
8101_0000 │ CPU PERFORMANCE                           │
8102_0000 │ CPU DEBUG                                 │

          ══ exclusivo de GPU ════════════════════════
8200_0000 │ GPU CORE / CONTROL  STATUS · CONTROL      │
          │                     WARP_START/LIVE/DONE  │
8201_0000 │ GPU WARPS           32 descriptores       │
8202_0000 │ GPU SIMT DEBUG                            │
8203_0000 │ GPU PERFORMANCE                           │

8300_0000 ┌───────────────────────────────────────────┐
FFFF_FFFF │ RESERVED / FUTURE ACCELERATORS            │
          └───────────────────────────────────────────┘
```

---

## 24. Las cuatro reglas

> **Una dirección, un significado.**

> **El mapa identifica hardware; los permisos determinan quién puede usarlo.**

> **La RAM admite los tamaños de MiniISA; MMIO opera siempre sobre registros
> completos de 32 bits alineados.**

> **Desde código SIMT, un acceso a MMIO solo vale cuando lo hace exactamente una
> lane.**

Estas reglas se mantienen aunque el sistema evolucione hacia varios masters,
interrupciones, DMA, protección de memoria o nuevos aceleradores.
