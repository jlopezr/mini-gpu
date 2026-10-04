# Contrato MMIO v2 de MiniCPU y MiniGPU

**Qué es este documento.** La referencia de direcciones del proyecto: el espacio
físico, los dispositivos, sus registros y las reglas de acceso. Dice **cómo
tiene que quedar todo** — MiniCPU, MiniGPU, el sistema integrado, los
simuladores, el monitor y las herramientas.

**Qué no es.** No describe lo que hay implementado hoy. Ningún prototipo cumple
todavía este contrato: lo que implementa cada uno está en
[`../docs/resumen-prototipos.md`](../docs/resumen-prototipos.md), con su tabla
de conformidad.

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
8060_0000 - 8060_FFFF    INPUT
8061_0000 - 80FF_FFFF    RESERVED PERIPHERALS

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
bit 11    INPUT

bits 31:12 reservados
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
| `+0x1C` | `HALT_AT` | RW | Parar tras N intercambios (captura determinista) |
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
HALT_AT = N     VIDEO pide detener los targets seleccionados al completarse
                el intercambio número N desde que se arma
```

Es una alarma de **un disparo** y **relativa al momento de armarla**: «para dentro
de N intercambios», no «para en el intercambio N desde el encendido», que solo
serviría una vez por arranque. VIDEO cuenta los intercambios desde el armado en
un contador **interno**; armar no toca `FRAME_COUNT` ni `SWAP_COUNT`, que solo
reinicia el reset de VIDEO.

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

**`HALT_AT` cuenta intercambios, no frames de vídeo.** Parar al llegar el frame N
deja al núcleo en un punto cualquiera de su dibujo: el buffer trasero está a
medias y lo que se capture depende de la velocidad relativa entre el programa y
el barrido. En el intercambio N completado, en cambio, el frame recién
intercambiado está entero y en el buffer frontal, aunque el programa tarde lo
que tarde y se salte frames: la captura es repetible.

Un programa que se cuelga sin pedir swaps no dispara la alarma. Eso no deja al
host esperando: el límite de tiempo (o de instrucciones, en el simulador) lo
detiene, y con el núcleo parado la memoria y los registros se pueden leer igual.

> **Historia.** La v1 contaba intercambios. MMIO v2 lo cambió a `FRAME_COUNT`
> para que un programa colgado también pudiera capturarse con la alarma, y eso
> costó la propiedad de arriba: el número de swaps al disparar dependía de la
> velocidad del programa, y el arnés tuvo que parar sondeando `SWAP_COUNT` desde
> el host. Se vuelve a contar intercambios (decisión 17, revisada); el caso
> colgado lo cubre el límite de tiempo.

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

INPUT (teclado y ratón, `0x80600000`) se define en §25. Se numera al final para no
renumerar las secciones existentes (§1.5).

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
| 6 | `+0x18` | `STALL_FETCH` (extensión) |
| 7 | `+0x1C` | `STALL_MMIO` (extensión) |

Con `CYCLES`, `STALL_MEM` e `IMEM_MISSES` se separa cómputo de memoria y de
fetch sin instrumentar nada más, y **un programa se mide a sí mismo en la
placa**, sin simular y sin cronómetro. Las ranuras 6 y 7 son las dos siguientes
libres, como pide §12.6, y separan lo que `STALL_MEM` junta.

**Qué cuenta cada uno.** Todos siguen §12: 32 bits, dan la vuelta, tienen su
bandera en `PERF_OVF0` (el bit `n` es el de la ranura `n`) y avanzan solo con el
núcleo corriendo, salvo `RETIRED` (abajo).

| Contador | Cuenta |
|---|---|
| `CYCLES` | Ciclos en los que el núcleo no está parado. Incluye los que espera a memoria o a un dispositivo. |
| `RETIRED` | Instrucciones retiradas, una por pulso. **No** se condiciona a que el núcleo corra: el `HALT` se retira en el mismo ciclo en que el núcleo se para, y contarlo es lo que hace que coincida con el simulador. Sí se congela con `PERF_CTRL.ENABLE`. |
| `IMEM_HITS` | Búsquedas de instrucción cacheables servidas por el búfer, sin ir a memoria. |
| `IMEM_MISSES` | Búsquedas cacheables que necesitaron leer una línea de memoria. Una búsqueda cacheable es la que cae dentro de la memoria y llega con la inicialización terminada: las demás se contestan con error y no cuentan. |
| `MEM_TX` | Peticiones que el núcleo hace al fabric de memoria: cada relleno de línea de instrucciones y cada lectura o volcado de datos. Una petición cuenta **una vez**, se acepte cuando se acepte. El volcado del búfer de escrituras que sigue a un `halt` no cuenta, porque el núcleo ya no corre (§12.3). |
| `STALL_MEM` | Ciclos con una petición de memoria del núcleo pendiente, sea búsqueda de instrucción o acceso a datos a memoria, y sin respuesta todavía. |
| `STALL_FETCH` | De los de `STALL_MEM`, los de la búsqueda de instrucción. Los de datos son `STALL_MEM − STALL_FETCH`. |
| `STALL_MMIO` | Ciclos con un acceso a datos a un dispositivo MMIO pendiente. **No** se suman a `STALL_MEM`: un dispositivo no es memoria. |

**Identidades.** Con ellas se comprueba una implementación y se reparte el
tiempo:

```text
CYCLES = cálculo + STALL_MEM + STALL_MMIO
IMEM_HITS + IMEM_MISSES  ≈  RETIRED            (una búsqueda por instrucción)
CPI = CYCLES / RETIRED         IPC = RETIRED / CYCLES
```

La primera se cumple salvo por uno o dos ciclos: los eventos cruzan un registro
antes de contarse, así que llegan un ciclo tarde. Es un retraso constante, no un
error acumulado.

**Qué implementa cada carpeta.** Un bloque declara las ranuras que tiene y las
demás dan error (§12.6), no cero. Las CPU de las carpetas 16 a 21 implementan las
ranuras 0 y 1; la 30 implementa las ocho. El software que quiera las ocho lo
detecta por la capacidad `perf_stalls` (`tools/capabilities.json`), que sale del
RTL. Las ranuras 6 y 7 de GPU PERFORMANCE (§14.4) son otra cosa de esa familia:
son bloques distintos y no chocan.

**Cómo se leen.** Con el núcleo parado, o congelando el bloque con
`PERF_CTRL.ENABLE = 0` (§12.5) si sigue corriendo: leer ocho contadores son ocho
instantes distintos con el programa corriendo entre medias. Un programa que
lleva más de 53 s a 80 MHz ya ha dado la vuelta en `CYCLES` (y en unos siete
minutos en `RETIRED`, con un CPI de 8): sus valores absolutos no significan nada
—`PERF_OVF0` lo dice—, pero la resta de dos lecturas sigue valiendo (§12.2). En
el PC, `monitor.py perf [segundos]` y `x.tests/run_tests.py --measure` hacen todo
esto.

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
SERIAL, VIDEO, INPUT  RW
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
SERIAL, VIDEO, INPUT  RW, por acceso MMIO escalar (§4.2)
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
INPUT       KEY_STATE = 0, MOUSE_BUTTONS = 0, EVENT FIFO vacía, COUNT = 0,
            OVERFLOW = 0, KEYBOARD_PRESENT = 0, MOUSE_PRESENT = 0
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
`define MMIO_INPUT_BASE        32'h8060_0000
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
17. `HALT_AT` cuenta intercambios completados desde que se arma, con comparación
    `>=` (revisada: antes contaba contra `FRAME_COUNT`; ver §9.6).
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
45. INPUT ocupa `0x80600000` y tiene el bit 11 de `SYSTEM.DEVICES`.
46. INPUT v1 soporta un teclado y un ratón, sin `device_id`.
47. El teclado usa directamente USB HID Keyboard/Keypad Usage IDs de 8 bits,
    Usage Page `0x07`.
48. `KEY_STATE0..7` es el estado autoritativo de 256 teclas; los modificadores
    `0xE0..0xE7` también aparecen en STATE.
49. `MOUSE_BUTTONS` es un bitmap autoritativo de 32 botones.
50. INPUT tiene una única EVENT FIFO ordenada para teclado y ratón; la
    implementación inicial usa 16 entradas, pero la profundidad no forma parte
    del ABI.
51. `STATUS` contiene `COUNT[15:0]`, `OVERFLOW`, `KEYBOARD_PRESENT` y
    `MOUSE_PRESENT`; `COUNT` es la autoridad para la validez de `EVENT_DATA`.
52. La FIFO usa `TYPE_KEY=0x00`, `TYPE_MOUSE_BUTTON=0x01` y
    `TYPE_MOUSE_MOVE=0x02`.
53. Los modificadores no generan eventos de tecla propios: un cambio de
    modificadores genera `KEY=0`, `DOWN=0` y el nuevo bitmap completo en
    `MODIFIERS`.
54. En un report de teclado el orden es KEY UP ascendente, cambio de
    modificadores si existe y KEY DOWN ascendente; todos llevan los
    modificadores del nuevo report.
55. En un report de ratón el orden es BUTTON UP ascendente, BUTTON DOWN
    ascendente y después MOUSE_MOVE.
56. `MOUSE_MOVE` usa `DX` y `DY` signed12; X positivo es derecha e Y positivo
    es abajo; `(0,0)` no genera evento y no existe posición/acumulador MMIO.
57. La rueda del ratón queda fuera de INPUT v1.
58. `EVENT_DATA` es read-and-pop. POP y PUSH simultáneos están permitidos,
    incluso con FIFO llena.
59. Con FIFO llena y sin POP simultáneo se aplica drop-new y `OVERFLOW` sticky;
    STATE se actualiza siempre y el movimiento perdido no puede reconstruirse.
60. `FLUSH` y `CLEAR_OVERFLOW` son independientes; FLUSH tiene prioridad sobre
    PUSH y no modifica STATE, PRESENT ni OVERFLOW.
61. INPUT v1 no genera IRQ; se consume mediante polling de `STATUS.COUNT`.
62. Reset deja STATE a cero, FIFO vacía, `OVERFLOW=0` y PRESENT a cero.
63. Conexión inicial se procesa como transición desde estado vacío;
    desconexión genera las liberaciones correspondientes y deja STATE/PRESENT
    a cero.
64. Typematic, layout, caracteres y política de `getch()` pertenecen al
    software.
65. INPUT normaliza el backend: USB HID, reports, endpoints, `full_report`,
    4KRO/6KRO/NKRO y señales concretas de RTL no forman parte del ABI.
66. El monitor y los simuladores reproducen exactamente el mismo ABI, orden y
    semántica de INPUT que la FPGA.

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
8060_0000 │ INPUT     STATE · EVENT FIFO · mouse move │

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

---

## 25. INPUT — `0x80600000`

INPUT es el periférico normalizado de entrada del sistema. Su contrato **no
expone USB, HID reports, endpoints ni el formato particular del backend**. La
FPGA puede alimentarlo desde un host USB HID y el monitor desde los eventos de
teclado y ratón del anfitrión; ambos deben producir exactamente el mismo ABI
MMIO y el mismo orden de eventos.

INPUT v1 soporta **un teclado y un ratón**. No hay `device_id` ni agregación de
varios dispositivos.

INPUT ofrece dos vistas complementarias:

```text
STATE        qué está pulsado ahora
EVENT FIFO   qué ha ocurrido y en qué orden
```

STATE es la vista completa del estado físico normalizado. La FIFO está
orientada al consumo cómodo por software, por ejemplo `getch()`, terminales y
typematic.

| Offset | Registro | Acceso | Función |
|---:|---|---|---|
| `+0x00` | `EVENT_DATA` | R | Lee y consume el evento más antiguo |
| `+0x04` | `STATUS` | R | Ocupación, overflow y presencia de dispositivos |
| `+0x08` | `EVENT_CTRL` | W | Control de la FIFO |
| `+0x10` | `KEY_STATE0` | R | HID usages `0x00..0x1F` |
| `+0x14` | `KEY_STATE1` | R | HID usages `0x20..0x3F` |
| `+0x18` | `KEY_STATE2` | R | HID usages `0x40..0x5F` |
| `+0x1C` | `KEY_STATE3` | R | HID usages `0x60..0x7F` |
| `+0x20` | `KEY_STATE4` | R | HID usages `0x80..0x9F` |
| `+0x24` | `KEY_STATE5` | R | HID usages `0xA0..0xBF` |
| `+0x28` | `KEY_STATE6` | R | HID usages `0xC0..0xDF` |
| `+0x2C` | `KEY_STATE7` | R | HID usages `0xE0..0xFF` |
| `+0x30` | `MOUSE_BUTTONS` | R | Estado actual de los botones 0..31 |

El resto del bloque queda reservado y da error. Escribir en registros de solo
lectura da error MMIO. Leer `EVENT_CTRL`, que es write-only, también da error.

### 25.1. Mapa arquitectónico de teclado

Los identificadores de tecla son directamente los **USB HID Keyboard/Keypad
Usage IDs de 8 bits, Usage Page `0x07`**. INPUT no define una segunda tabla de
scancodes.

```text
A            0x04
B            0x05
Space        0x2C
Right        0x4F
Left         0x50
Down         0x51
Up           0x52
Left Ctrl    0xE0
Left Shift   0xE1
Right GUI    0xE7
```

Estos códigos identifican teclas físicas, no caracteres. La conversión a ASCII,
Unicode, `ñ`, mayúsculas, dead keys o cualquier layout nacional pertenece al
software.

### 25.2. `KEY_STATE0..7`

Los ocho registros forman un bitmap autoritativo de 256 bits. Para un Usage ID
`u`:

```text
registro = u >> 5
bit      = u & 31

0 = tecla suelta
1 = tecla pulsada
```

Los modificadores HID `0xE0..0xE7` (Ctrl, Shift, Alt y GUI) también aparecen en
este bitmap, en `KEY_STATE7`.

Las ocho palabras se leen de forma independiente: **no existe snapshot
multiword atómico**. Esta vista tampoco depende de cuántas teclas simultáneas
soporte el backend; pasar de 4KRO a 6KRO o NKRO no cambia el ABI.

### 25.3. `MOUSE_BUTTONS`

`MOUSE_BUTTONS` es un bitmap autoritativo de 32 bits:

```text
bit N = estado del botón N, N=0..31

0 = suelto
1 = pulsado
```

La asignación inicial es:

```text
0  = left
1  = right
2  = middle
3  = button 4
4  = button 5
...
31 = button 32
```

Un backend que implemente menos botones mantiene los restantes a cero.

### 25.4. `STATUS`

```text
bits 15:0    COUNT              eventos almacenados
bit  16      OVERFLOW           sticky; se perdió al menos un evento
bit  17      KEYBOARD_PRESENT   teclado enumerado, reconocido y operativo
bit  18      MOUSE_PRESENT      ratón enumerado, reconocido y operativo
bits 31:19   0
```

`PRESENT` significa que el dispositivo está listo para producir input, no mera
presencia eléctrica durante la enumeración.

Se mantienen estos invariantes:

```text
KEYBOARD_PRESENT = 0  ->  KEY_STATE0..7 = 0
MOUSE_PRESENT    = 0  ->  MOUSE_BUTTONS = 0
```

No se expone la capacidad física de la FIFO. `COUNT` es la autoridad para saber
si `EVENT_DATA` contiene un evento válido.

### 25.5. EVENT FIFO

Existe una única FIFO ordenada para teclado y ratón:

```text
TYPE 0x00    KEY
TYPE 0x01    MOUSE_BUTTON
TYPE 0x02    MOUSE_MOVE
0x03..0xFF   reservados
```

La profundidad física es **implementation-defined** y no forma parte del ABI. La
primera implementación RTL usa **16 entradas de 32 bits**.

La lectura de `EVENT_DATA` es **read-and-pop**:

```text
COUNT != 0:  devuelve el evento más antiguo y lo consume

COUNT == 0:  devuelve 0 y no tiene efecto lateral
```

El valor de `EVENT_DATA` por sí solo no indica si había un evento: `COUNT` debe
ser distinto de cero.

Un POP y un PUSH pueden ocurrir simultáneamente. El POP devuelve el evento
antiguo, el PUSH inserta el nuevo y `COUNT` no cambia. Esto también se permite
cuando la FIFO estaba llena: el PUSH ocupa el hueco liberado por el POP y **no**
se produce overflow.

Si la FIFO está llena y no hay POP simultáneo, la política es **drop-new**: se
conserva todo lo ya almacenado, se descarta el evento nuevo y `OVERFLOW` pasa a
uno. Un report que produce varios eventos no es atómico respecto a la FIFO:
entran, en orden, todos los que quepan y los siguientes se pierden.

`OVERFLOW` es sticky e informativo; no bloquea la FIFO. Cuando vuelve a haber
espacio, los eventos nuevos vuelven a entrar normalmente aunque `OVERFLOW` siga
a uno.

STATE siempre se actualiza aunque se pierdan eventos. Tras overflow,
`KEY_STATE` y `MOUSE_BUTTONS` permiten recuperar el estado discreto actual, pero
los `MOUSE_MOVE` perdidos **no pueden reconstruirse**.

### 25.6. Evento `KEY`

Formato:

```text
bits  7:0    KEY         USB HID Usage ID, Usage Page 0x07
bit   8      DOWN        KEY != 0: 1 = down, 0 = up
bits 15:9    0
bits 23:16   MODIFIERS   bitmap HID completo de modificadores
bits 31:24   0x00        TYPE_KEY
```

La FIFO conserva el enfoque del HID para los modificadores: Ctrl, Shift, Alt y
GUI forman parte de STATE mediante los Usage IDs `0xE0..0xE7`, pero **no generan
eventos KEY propios**.

Cuando cambia el bitmap de modificadores se genera un único evento:

```text
KEY       = 0x00
DOWN      = 0
MODIFIERS = nuevo bitmap completo
TYPE      = KEY
```

Por tanto, `KEY=0` tiene significado arquitectónico: cambio de modificadores. Un
cambio de varios modificadores en el mismo report produce un solo evento con el
nuevo bitmap completo.

Para `KEY != 0`, `DOWN` conserva su significado normal. Todos los eventos KEY
derivados de un report llevan `MODIFIERS` igual al estado de modificadores del
**nuevo report**.

Si un report cambia varias cosas, el orden es determinista:

```text
1. KEY UP, Usage ID ascendente
2. KEY=0 / MODIFIERS_CHANGED, si cambiaron los modificadores
3. KEY DOWN, Usage ID ascendente
```

Las teclas normales que permanecen pulsadas no se reemiten cuando cambia un
modificador. El evento `KEY=0` permite al software actualizar su contexto sin
confundirlo con una nueva pulsación.

### 25.7. Evento `MOUSE_BUTTON`

Formato:

```text
bits  7:0    BUTTON   0..31
bit   8      DOWN     1 = down, 0 = up
bits 23:9    0
bits 31:24   0x01     TYPE_MOUSE_BUTTON
```

Si varios botones cambian en el mismo report, primero se generan todos los UP en
número de botón ascendente y después todos los DOWN en número de botón
ascendente.

### 25.8. Evento `MOUSE_MOVE`

Formato:

```text
bits 11:0    DX       signed12, complemento a dos
bits 23:12   DY       signed12, complemento a dos
bits 31:24   0x02     TYPE_MOUSE_MOVE
```

Convención:

```text
DX > 0   derecha
DX < 0   izquierda
DY > 0   abajo
DY < 0   arriba
```

El rango por eje y evento es `-2048..+2047`. Si un backend entrega un delta
mayor, INPUT lo divide en varios eventos cuya suma conserva exactamente el
movimiento original.

`DX=0 && DY=0` no genera evento. Si un report cambia botones y además contiene
movimiento, el orden es:

```text
1. MOUSE_BUTTON UP, botón ascendente
2. MOUSE_BUTTON DOWN, botón ascendente
3. MOUSE_MOVE
```

INPUT no mantiene posición `X/Y` ni acumuladores de movimiento. La rueda queda
fuera de v1 y podrá añadirse mediante un nuevo `TYPE`.

### 25.9. `EVENT_CTRL`, FLUSH y overflow

`EVENT_CTRL` es write-only:

```text
bit 0        FLUSH
bit 1        CLEAR_OVERFLOW
bits 31:2    deben escribirse a cero
```

Escribir cero no hace nada. Una escritura con cualquier bit reservado a uno
produce error MMIO y **no ejecuta ninguna operación**.

`FLUSH` y `CLEAR_OVERFLOW` son independientes:

```text
FLUSH:
  vacía la FIFO
  COUNT = 0
  no modifica OVERFLOW
  no modifica STATE ni PRESENT

CLEAR_OVERFLOW:
  limpia OVERFLOW
  no modifica la FIFO
```

Se pueden activar ambos bits en una misma escritura.

FLUSH tiene prioridad sobre PUSH. Si coinciden, la FIFO termina vacía y el
evento nuevo se descarta, aunque STATE sí se actualiza. FLUSH no produce por sí
mismo overflow.

Si `CLEAR_OVERFLOW` coincide con una nueva pérdida de evento, la nueva pérdida
tiene prioridad y `OVERFLOW` queda a uno.

### 25.10. Typematic y política de software

INPUT **no genera typematic repeat**. Layout, composición de caracteres, dead
keys, Unicode, repetición y política de `getch()` pertenecen al software.

La FIFO contiene suficiente contexto para que un driver siga los modificadores
sin leer STATE. Por ejemplo:

```text
A DOWN, MOD=0
KEY=0, DOWN=0, MOD=SHIFT
KEY=0, DOWN=0, MOD=0
A UP, MOD=0
```

El software decide cómo afecta el cambio de modificadores a una tecla mantenida
y al typematic. STATE sigue siendo la vista autoritativa para polling, juegos o
consulta del estado físico actual.

### 25.11. Reset, conexión y desconexión

Tras reset:

```text
KEY_STATE0..7      0
MOUSE_BUTTONS      0
EVENT FIFO         vacía
COUNT              0
OVERFLOW           0
KEYBOARD_PRESENT   0
MOUSE_PRESENT      0
```

La conexión inicial se procesa como una transición desde estado vacío. Si el
primer estado válido ya contiene teclas, modificadores o botones pulsados, se
generan los eventos correspondientes siguiendo el orden normal.

La desconexión se procesa como transición al estado vacío:

```text
teclado:
  KEY UP de las teclas normales pulsadas
  KEY=0, DOWN=0, MODIFIERS=0 si cambiaron los modificadores
  KEY_STATE0..7 = 0
  KEYBOARD_PRESENT = 0

ratón:
  MOUSE_BUTTON UP de los botones pulsados
  MOUSE_BUTTONS = 0
  MOUSE_PRESENT = 0
```

Estos eventos no tienen privilegios especiales: están sujetos a la misma
capacidad, orden y política de overflow que cualquier otro evento. STATE y
PRESENT sí alcanzan siempre el nuevo estado.

### 25.12. Polling y simulación

INPUT v1 **no genera IRQ**. El software consulta `STATUS.COUNT` y consume
`EVENT_DATA` mediante polling.

El monitor y los simuladores modelan INPUT, no USB. Deben reproducir
exactamente el mismo STATE, formatos, orden de eventos, semántica de overflow y
reglas de conexión/desconexión que la FPGA.

La traducción del teclado anfitrión se hace a Usage ID físico, no a carácter.
Así el software MiniCPU observa el mismo ABI con independencia del backend.

---

## Apéndice A. Integración prevista con `m1nl/usb_hid_host`

Este apéndice describe una estrategia de implementación, **no una ampliación del
ABI**. El software no debe depender del core USB concreto ni de sus señales
internas.

La frontera prevista es:

```text
USB físico
    ↓
m1nl/usb_hid_host
    ↓
report/estado HID del core
    ↓
adaptador INPUT
    ├── KEY_STATE0..7
    ├── MOUSE_BUTTONS
    ├── STATUS.PRESENT
    └── EVENT FIFO
          ↓
         MMIO
```

### A.1. Teclado

El Boot Keyboard Report separa el bitmap de modificadores de los slots de teclas
normales. El adaptador reconstruye a partir de ambos un estado normalizado:

```text
modifiers bitmap  ->  KEY_STATE[0xE0..0xE7]
key slots         ->  KEY_STATE[usage]
```

Una implementación inicial puede usar las salidas de tecla disponibles en el
core, por ejemplo `key_0..key_3`, junto con `key_modifiers` y el strobe de
report completo. El número de slots **no forma parte del ABI**.

Para cada report válido se conserva el estado anterior y se calculan los cambios
de las teclas normales. La FSM de adaptación serializa:

```text
1. KEY UP, Usage ID ascendente
2. KEY=0, DOWN=0, MODIFIERS=new_modifiers, si cambió el bitmap
3. KEY DOWN, Usage ID ascendente
```

Todos los eventos KEY del report llevan `MODIFIERS=new_modifiers`. Los
modificadores se reflejan siempre en `KEY_STATE`, pero no generan eventos
`KEY=0xE0..0xE7` propios.

`full_report`, o el strobe equivalente del core, significa que existe un nuevo
report completo que puede compararse con el anterior; su nombre y temporización
exactos son detalle RTL.

### A.2. Ratón

Cuando llega un report completo de ratón, el adaptador compara el bitmap de
botones anterior y nuevo y toma los deltas relativos `dx/dy`.

El orden de serialización es:

```text
1. MOUSE_BUTTON UP, botón ascendente
2. MOUSE_BUTTON DOWN, botón ascendente
3. MOUSE_MOVE, solo si dx != 0 || dy != 0
```

Si el delta del backend excede signed12, se divide en varios `MOUSE_MOVE` cuya
suma sea exactamente el movimiento original. INPUT no acumula posición ni
movimiento.

### A.3. Serialización y FIFO

Un único report puede producir varios eventos. No es necesario emitirlos todos
en el mismo ciclo: una FSM puede serializarlos hacia la FIFO.

STATE se actualiza al nuevo estado completo aunque la FIFO no tenga espacio para
todos los eventos. La FIFO aplica las reglas arquitectónicas normales de
drop-new y `OVERFLOW`.

La primera implementación usa 16 entradas de 32 bits. Esta profundidad es
privada del RTL.

### A.4. Conexión y presencia

`KEYBOARD_PRESENT` o `MOUSE_PRESENT` pasan a uno solo cuando el dispositivo ha
sido enumerado, reconocido y está operativo.

El primer estado válido se procesa contra estado vacío. La desconexión se
procesa como transición a estado vacío y genera las liberaciones
correspondientes antes de dejar STATE y PRESENT a cero; esos eventos están
sujetos a las reglas normales de overflow.

### A.5. Lo que no forma parte del ABI

```text
m1nl/usb_hid_host como implementación concreta
nombres de señales RTL
key_0..key_N
full_report
Boot Protocol como detalle de transporte
4KRO, 6KRO o NKRO
Report Descriptor
endpoints USB
intervalo de polling USB
FSM o priority encoder concretos
profundidad física de FIFO
```

Esto permite sustituir el host USB, ampliar el soporte de rollover o alimentar
INPUT desde el monitor sin cambiar direcciones, formatos ni semántica MMIO.
