<!-- trace:artifact DES-MINIGPU-2D-V05
type: design
kind: proposal
-->

<!-- trace:relations
supersedes:
  - DES-MINIGPU-2D-V04
-->
# MiniGPU 2D --- propuesta consolidada v0.5

**Estado:** propuesta de arquitectura consolidada para implementación.\
**Base MMIO:** `VIDEO = 0x80200000`.\
**Objetivo:** ampliar el subsistema de vídeo de MiniGPU con framebuffer
indexado, tiles, sprites, texto, HUD y composición 2D, manteniendo un
hardware pequeño, determinista y razonable para ECP5/ULX3S.

> Este documento consolida las decisiones tomadas durante el diseño.
> Sustituye las notas parciales de la propuesta 2D, pero no sustituye
> por sí solo al contrato MMIO global del SoC: los cambios aquí
> descritos deberán integrarse en su siguiente revisión.

------------------------------------------------------------------------

# 1. Principios de diseño

El subsistema 2D sigue estas reglas:

1.  El timing de vídeo **nunca espera** a CPU, GPU, SDRAM ni a los
    renderers 2D.
2.  El estado que debe cambiar atómicamente entre frames utiliza
    **shadow + active** y `FRAME_COMMIT`.
3.  Las memorias grandes que no necesitan doble buffer arquitectónico se
    modifican directamente.
4.  `VBLANK` permite al software realizar cambios directos sin tearing
    cuando sea necesario.
5.  Los line buffers usan ping-pong: un banco se consume mientras el
    otro se prepara.
6.  Tiles y sprites producen índices de paleta; el compositor resuelve
    primero el píxel indexado ganador y realiza una única consulta de
    paleta por píxel de esa capa. Las surfaces `INDEX8` se resuelven
    contra la paleta al escribirse sobre `RGB_NEXT` (ver sección 11).
7.  El HUD debe poder seguir siendo útil aunque CPU o GPU estén
    bloqueadas.
8.  Se prioriza simplicidad de RTL frente a cubrir en hardware casos
    poco frecuentes que software puede resolver.
9.  Los accesos MMIO inválidos producen error; no se corrigen ni truncan
    silenciosamente.
10. La implementación física exacta de EBR se validará al sintetizar;
    este documento fija el contrato lógico.

------------------------------------------------------------------------

# 2. Resolución y pipeline general

La imagen lógica es:

``` text
320 × 240
```

y la salida física es:

``` text
640 × 480
```

con escalado entero 2× en ambos ejes.

Conceptualmente:

``` text
FB_FRONT / Surface compositor ─┐
                               │
Tile renderer ─► TILE LB ──────┤
                               ├─► compositor RGB888 ─► RGB line buffer ─► scaler 2× ─► HDMI
Sprite renderer ► SPR LB ──────┤
                               │
Text/HUD ──────────────────────┘
```

El framebuffer clásico o, alternativamente, el compositor de surfaces forman
la imagen base. Tiles y sprites siguen siendo productores gráficos independientes
que convergen en el mismo compositor. Texto y HUD se aplican como overlays
posteriores. El formato interno de composición y de los RGB line buffers permanece
`RGB888`.

------------------------------------------------------------------------

# 3. Framebuffer

## 3.1. Formatos

Se soportan dos formatos:

``` text
RGB565
INDEX8
```

`RGB565` contiene color directo de 16 bits.

`INDEX8` contiene un índice de 8 bits a la paleta global de 256 colores.

## 3.2. Stride configurable

El framebuffer dispone de un registro `FB_STRIDE`, expresado en bytes.
Su semántica es:

``` text
FB_STRIDE = 0  → stride automático
FB_STRIDE != 0 → stride explícito en bytes
```

En modo automático el stride efectivo depende del formato activo:

``` text
RGB565:
    effective_stride = 320 × 2 = 640 bytes
    tamaño mínimo = 320 × 240 × 2 = 153600 bytes

INDEX8:
    effective_stride = 320 bytes
    tamaño mínimo = 320 × 240 = 76800 bytes
```

Por tanto, software que ignore `FB_STRIDE` conserva exactamente el
comportamiento anterior.

Con un valor explícito, el comienzo de cada línea lógica se obtiene como:

``` text
next_line_addr = current_line_addr + effective_stride
```

Esto permite introducir padding entre líneas o utilizar una ventana de una
superficie con un pitch mayor que los 320 píxeles visibles, sin modificar el
pipeline de píxeles dentro de la línea.

El valor explícito debe ser suficiente para contener una línea completa del
formato activo y mantener la alineación requerida por el fetch de framebuffer.
En particular, `effective_stride` debe ser múltiplo de 16 bytes para conservar
la alineación natural con las transacciones de 128 bits del fabric. Un valor
explícito inválido genera error MMIO.

`FB_STRIDE` pertenece al estado shadow/active de escena, junto con `CONFIG`: se
escribe en shadow y pasa a ACTIVE con `STATE_COMMIT`. Como su validez depende del
formato, la validación se reparte así:

``` text
escritura de FB_STRIDE:   error si != 0 y no es múltiplo de 16 bytes
STATE_COMMIT solicitado:  error si FB_STRIDE != 0 y es menor que una línea completa
                          del FB_FORMAT shadow (640 B RGB565 / 320 B INDEX8)
```

Si la comprobación falla al solicitar `STATE_COMMIT`, la escritura de
`FRAME_COMMIT` completa genera error y no se acepta ningún bit (atomicidad,
sección 15.5).

`FB_FRONT` y `FB_BACK` comparten el mismo `effective_stride`. Quien renderice en
`FB_BACK` (CPU o GPU) debe utilizar ese mismo stride; el hardware de scanout no
lo obtiene de ninguna otra fuente.

`FB_FRONT` y `FB_BACK` deben estar alineados a:

``` text
16 bytes
```

Una base no alineada genera error MMIO.

## 3.3. Fetch

El fetch del framebuffer conserva el ancho natural del memory fabric:

``` text
SDRAM 128b
   ↓
FIFO de palabras de 128 bits
   ↓
unpacker
```

En `RGB565`:

``` text
128 bits = 8 píxeles
```

En `INDEX8`:

``` text
128 bits = 16 píxeles
```

No se normaliza la FIFO a píxeles individuales.

------------------------------------------------------------------------

# 4. Paleta

La paleta global contiene:

``` text
256 × RGB888
```

El índice `0` tiene semántica especial para overlays indexados:
representa transparencia cuando corresponda.

La paleta se implementa lógicamente como memoria accesible por MMIO.

## 4.1. Uso desde texto/HUD

Los colores `PALETTE[1..15]` se replican además en:

``` text
15 × 24 bits de registros
```

Una escritura MMIO a esas entradas actualiza simultáneamente:

``` text
Palette RAM[n]
text_palette[n]
```

Así texto/HUD puede seleccionar FG/BG sin competir por los puertos de la
RAM de paleta.

## 4.2. Actualización

La paleta es directa, no shadowed.

El uso normal para una actualización limpia es:

``` text
esperar VBLANK
modificar PALETTE
```

Se permite escribir durante vídeo activo, lo que posibilita efectos
raster.

Si una escritura coincide exactamente con una lectura de la misma
entrada durante vídeo activo, el color observado para ese acceso queda
no especificado. Los accesos posteriores verán el nuevo valor.

------------------------------------------------------------------------

# 5. Tilemap y tiles

## 5.1. Tilemap

El tilemap lógico es:

``` text
64 × 64 entradas
4096 entradas
16 bits por entrada
8 KiB lógicos
```

Existe **un único tilemap**. No se duplica ni se mantiene una copia
shadow completa.

Las escrituras son directas.

Para cambios normales sin tearing:

``` text
esperar VBLANK
actualizar TILEMAP
```

Para una actualización masiva que no quepa cómodamente en un VBlank,
software puede desactivar temporalmente la capa, mostrar una pantalla de
carga o realizar la transición en varios frames.

## 5.2. Tileset

Los datos gráficos del tileset residen en SDRAM.

`TILESET_BASE` forma parte del estado shadow/active y puede cambiarse
mediante `STATE_COMMIT`.

Esto permite preparar un nuevo tileset en otra zona de SDRAM y cambiarlo
atómicamente entre frames modificando únicamente su base.

## 5.3. Scroll

`SCROLL_X` y `SCROLL_Y` pertenecen al estado shadow/active y se aplican
mediante `STATE_COMMIT`.

## 5.4. Tile line buffer

El renderer prepara una línea lógica en un line buffer con entradas:

``` text
{ PRIORITY, INDEX8 }
```

Se utiliza ping-pong:

``` text
TILE_CURRENT → compositor
TILE_NEXT    ← renderer
```

Al avanzar de línea lógica, si `NEXT` está completo, ambos bancos
intercambian sus papeles.

Si no está completo, el timing no espera: las posiciones no preparadas
permanecen transparentes y se registra underflow de tile.

------------------------------------------------------------------------

# 6. Sprites

Se prevén:

``` text
64 sprites
```

El estado de sprites usa dos conjuntos:

``` text
SPRITES_SHADOW
SPRITES_ACTIVE
```

Software modifica SHADOW. `STATE_COMMIT` inicia la transferencia
SHADOW→ACTIVE durante VBlank.

La copia puede tardar varios ciclos; `STATE_COMMIT_PENDING` sólo se
limpia cuando toda la operación ha terminado.

El renderer de sprites genera una línea indexada:

``` text
SPR_CURRENT → compositor
SPR_NEXT    ← sprite renderer
```

Cada entrada contiene `INDEX8`; `0` representa transparencia.

Si una línea no está terminada a tiempo, el vídeo no se detiene. Las
posiciones no generadas quedan transparentes y se registra underflow de
sprites.

------------------------------------------------------------------------

# 7. Texto

La salida física de 640×480 utiliza una rejilla de:

``` text
80 × 30 caracteres
```

con glifos:

``` text
8 × 16 píxeles
```

Por tanto:

``` text
char_x = px >> 3
char_y = py >> 4

cell_addr = char_y * 80 + char_x

glyph_x = px[2:0]
glyph_y = py[3:0]
```

La Text RAM contiene:

``` text
80 × 30 = 2400 celdas
```

y se implementa como EBR dual-port:

``` text
puerto A → renderer
puerto B → MMIO
```

Una escritura MMIO no detiene el scanout.

Una colisión lectura/escritura sobre exactamente la misma celda no
requiere sincronización adicional: durante ese instante puede observarse
el valor viejo o el nuevo; en el siguiente refresco el nuevo valor ya
debe ser visible.

## 7.1. Glifos

Cada fila de un glifo tiene 8 bits.

Se fija:

``` text
bit 7 → píxel izquierdo
bit 0 → píxel derecho
```

Por tanto:

``` text
glyph_pixel = glyph_row[7 - glyph_x]
```

Ejemplo:

``` text
00111100 → ..####..
```

## 7.2. Transparencia

FG y BG seleccionan colores de la paleta de texto.

El color `0` significa transparencia, permitiendo texto con fondo
transparente, foreground transparente o ambos.

------------------------------------------------------------------------

# 8. Font RAM

La fuente contiene:

``` text
256 glifos
8 × 16 píxeles por glifo
16 bytes por glifo
```

La Font RAM es dual-port:

``` text
puerto A → renderer
puerto B → font loader MMIO
```

Puede actualizarse con vídeo activo. Si software desea evitar artefactos
al modificar un glifo visible, debe hacerlo durante VBlank.

## 8.1. Fuente por defecto

La FPGA inicializa la Font RAM desde el bitstream con una fuente 8×16
por defecto.

Así el HUD, monitor y texto básico pueden utilizar caracteres sin
depender de una carga inicial realizada por CPU.

El font loader existe para reemplazar o modificar glifos en runtime.

## 8.2. Font loader

Registros:

``` text
+0x0080  FONT_COUNT
+0x0084  FONT_GLYPH
+0x0088  FONT_DATA0
+0x008C  FONT_DATA1
+0x0090  FONT_DATA2
+0x0094  FONT_DATA3
```

Secuencia:

``` text
1. escribir FONT_GLYPH = primer glifo
2. escribir FONT_COUNT = número de glifos
3. para cada glifo:
       escribir FONT_DATA0
       escribir FONT_DATA1
       escribir FONT_DATA2
       escribir FONT_DATA3
```

`FONT_DATA3` hace commit del glifo completo.

Después de cada glifo:

``` text
FONT_GLYPH++
FONT_COUNT--
```

La escritura de `FONT_COUNT` inicia y valida la transferencia.

Debe cumplirse:

``` text
FONT_COUNT > 0
FONT_GLYPH + FONT_COUNT <= 256
```

Si no se cumple, la escritura genera error y no comienza la
transferencia.

Escribir `FONT_DATA3` con `FONT_COUNT == 0` genera error MMIO y no
modifica Font RAM.

No existe wrap accidental de glifo 255 a 0.

------------------------------------------------------------------------

# 9. HUD hardware

El HUD no dispone de una Text RAM propia.

Genera directamente:

``` text
{ CHARACTER, FG, BG, valid }
```

a partir de las coordenadas de carácter y de señales internas de
diagnóstico.

Se inserta antes de Font RAM:

``` text
Text RAM ───────┐
                ├─► mux ─► Font RAM ─► FG/BG ─► RGB
HUD generator ──┘
```

El HUD tiene prioridad sobre el texto normal.

Reutiliza:

-   Font RAM;
-   renderer de glifos;
-   paleta de texto.

Esto permite que el HUD siga funcionando independientemente del estado
de CPU/GPU.

------------------------------------------------------------------------

# 10. Surfaces y compositor de ventanas

Las `SURFACE` generalizan la fuente de imagen base sin sustituir los motores de
tiles, sprites, texto o HUD. Su objetivo principal es permitir que distintos
programas mantengan sus propios framebuffers en SDRAM y que el hardware de vídeo
los coloque y componga por scanline sin copiar previamente una pantalla completa.

Se definen inicialmente:

``` text
8 surfaces programables
```

El orden de los slots define el orden de composición:

``` text
SURFACE[0]  fondo
SURFACE[1]  sobre SURFACE[0]
...
SURFACE[7]  primer plano de surfaces
```

No existe ordenación Z en hardware. Software reordena/copía descriptores cuando
necesita cambiar el apilado de ventanas.

## 10.1. Descriptor lógico

Cada surface dispone de estado shadow/active con:

``` text
BASE
STRIDE
X
Y
WIDTH
HEIGHT
FORMAT      RGB565 / INDEX8
ENABLE
```

`BASE` y `STRIDE` se expresan en bytes. Las mismas restricciones de alineación
del fetch de framebuffer se aplican a las surfaces: `BASE` y el stride efectivo
deben ser múltiplos de 16 bytes. `STRIDE = 0` selecciona el stride mínimo
automático derivado de `WIDTH` y `FORMAT`, redondeado hacia arriba al siguiente
múltiplo de 16 bytes.

`X`, `Y`, `WIDTH` y `HEIGHT` describen el rectángulo destino en coordenadas
lógicas de 320×240. El compositor realiza clipping contra la pantalla; una
surface puede quedar parcial o totalmente fuera de ella. El layout MMIO del
descriptor se propone en 21.9.

## 10.2. Formatos y transparencia

Una surface `RGB565` es opaca. Cada píxel se expande a `RGB888` antes de entrar
en el line buffer final.

Una surface `INDEX8` utiliza la única paleta global `PALETTE[256]` ya existente:

``` text
index 0      → transparente
index 1..255 → PALETTE[index] RGB888
```

No existen paletas por surface ni alpha blending. Tiles, sprites y todas las
surfaces `INDEX8` comparten la misma paleta global.

El framebuffer base `INDEX8` conserva semántica opaca: cuando se utiliza el modo
framebuffer clásico, los índices `0..255`, incluido `0`, representan colores.
La transparencia de índice 0 sólo se aplica a fuentes que actúan como overlay.

## 10.3. Relación con el framebuffer clásico

Conceptualmente, el framebuffer clásico es el caso degenerado de una surface
fullscreen opaca:

``` text
BASE   = FB_FRONT
STRIDE = effective FB_STRIDE
X      = 0
Y      = 0
WIDTH  = 320
HEIGHT = 240
FORMAT = FB_FORMAT
OPAQUE = 1
```

Se conserva, sin embargo, la interfaz arquitectónica `FB_FRONT` / `FB_BACK` y
`FB_SWAP`. Es especialmente cómoda para el caso común de renderizado fullscreen
con doble buffer: después del swap el antiguo front pasa automáticamente a ser
el nuevo back.

`CONFIG.SURFACE_ENABLE = 0` selecciona el framebuffer clásico como fuente base.
`CONFIG.SURFACE_ENABLE = 1` selecciona `SURFACE[0..7]` como fuentes de la imagen
base; en este modo `FB_FRONT` no se lee para scanout. Tiles, sprites y texto/HUD
siguen disponibles en ambos modos según sus enables.

## 10.4. Double buffering y presentación de surfaces

Una surface no impone `FRONT/BACK`. `BASE` forma parte de su descriptor
shadow/active. Software puede renderizar en cualquier buffer y publicar su
dirección escribiendo `BASE_SHADOW` y solicitando `STATE_COMMIT`.

Esto permite sin hardware adicional:

``` text
single buffering
A → A

double buffering
A → B → A ...

triple buffering
A → B → C ...
```

El buffer que no está siendo presentado y la política de reutilización son
responsabilidad del software. El hardware sólo conoce el `BASE_ACTIVE` que debe
leer y el `BASE_SHADOW` preparado para el siguiente commit.

En una misma entrada a VBlank, `STATE_COMMIT` puede actualizar atómicamente base,
posición, tamaño, stride, formato y enable de varias surfaces junto con el resto
del estado 2D shadow/active.

## 10.5. Preparación por scanline

No existe un line buffer por surface. Se reutiliza el RGB line buffer ping-pong
final ya existente.

Mientras `RGB_CURRENT` se consume, un fetcher secuencial prepara `RGB_NEXT`:

``` text
seleccionar surfaces que intersectan Y+1
    ↓
fetch scanline SURFACE[0] y componer
    ↓
fetch scanline SURFACE[1] y sobrescribir píxeles opacos
    ↓
...
    ↓
continuar con tiles / sprites / texto / HUD
    ↓
RGB_NEXT listo
```

Para una surface que intersecta la línea lógica `Y`:

``` text
src_y = Y - SURFACE.Y
line_addr = BASE + src_y * STRIDE
```

Sólo se solicita la región horizontal visible tras clipping (10.6). El timing de vídeo
nunca espera a que termine una surface: el presupuesto temporal sigue siendo el
de preparar la siguiente línea antes de necesitarla. Si no llega a tiempo se
aplica 14.4.

El límite práctico principal del número y tamaño de surfaces simultáneas es por
tanto el ancho de banda de SDRAM, no el almacenamiento en EBR. La primera
implementación debe medir este presupuesto antes de introducir lógica compleja
de oclusión.

## 10.6. Fetch alineado y recorte

El fetch de una surface se realiza siempre en palabras de 128 bits alineadas; nunca
se emiten accesos desalineados. Como `BASE` y `STRIDE` son múltiplos de 16 B, cada
línea de la surface empieza alineada. Los píxeles de las palabras de borde que
queden fuera de la región visible (recorte por la izquierda o por la derecha,
o un `WIDTH` que no llena la última palabra) se descartan en el unpacker.

Para una surface recortada por la izquierda (`X < 0`), con `bpp` = 2 (RGB565) o 1
(INDEX8):

``` text
src_x0     = -X                        primer píxel visible de la fuente
byte_off   = src_x0 × bpp
word_first = byte_off >> 4             primera palabra de 128 bits a pedir
skip       = (byte_off & 15) / bpp     píxeles a descartar de esa palabra
word_last  = ceil((src_x0 + visibles) × bpp / 16) - 1
```

El unpacker arranca directamente en el píxel `skip` (como máximo 7 en RGB565 y 15
en INDEX8). Al ser `STRIDE` múltiplo de 16 B y mayor o igual que `WIDTH × bpp`, la
última palabra pedida nunca sale de la fila de la surface. El coste es como mucho
una palabra adicional por borde, línea y surface, despreciable frente al resto
del presupuesto de SDRAM.

------------------------------------------------------------------------

# 11. Composición

El compositor combina la imagen base seleccionada (framebuffer clásico o surfaces)
con las fuentes gráficas de acuerdo con sus enables y prioridades.

## 11.1. Orden de capas

De abajo a arriba:

``` text
1. imagen base       framebuffer clásico  o  SURFACE[0..7]
2. tiles y sprites   el PRIORITY del tile decide entre tile y sprite
3. texto
4. HUD
```

La imagen base queda siempre por debajo de tiles y sprites, tanto en modo
framebuffer como en modo surfaces. `PRIORITY` no afecta a la relación con la imagen
base.

## 11.2. Resolución de paleta

Toda fuente `RGB565`, incluido framebuffer o surface, se expande a `RGB888` antes
de entrar en la composición final. Las fuentes `INDEX8` resuelven su color mediante
la paleta global. El RGB line buffer conserva `RGB888`, por lo que no se pierde
precisión de los colores de paleta.

La regla de una única consulta de paleta por píxel se aplica así:

-   Modo framebuffer clásico: el framebuffer `INDEX8` (opaco), los tiles y los
    sprites producen índices; el compositor resuelve primero el índice ganador y
    efectúa **una única consulta de paleta por píxel**.
-   Modo surfaces: cada surface `INDEX8` consulta la paleta al escribirse sobre
    `RGB_NEXT`. Un píxel cubierto por varias surfaces, o por una surface y después
    un tile/sprite, puede requerir más de una consulta. Al ser la preparación
    secuencial, todas comparten el puerto de lectura del compositor; el coste en
    ciclos debe medirse en la primera implementación (10.5).

Texto/HUD se aplican como overlay utilizando su propia selección rápida
de `PALETTE[1..15]`, sin consultar la RAM de paleta.

------------------------------------------------------------------------

# 12. RGB line buffers y escalado

El compositor produce una línea lógica completa en RGB888.

Se utilizan dos RGB line buffers ping-pong:

``` text
RGB_CURRENT → scaler/HDMI
RGB_NEXT    ← compositor
```

Una línea lógica se emite dos veces verticalmente:

``` text
RGB_CURRENT(Y) → línea física 2Y
RGB_CURRENT(Y) → línea física 2Y+1
```

Horizontalmente cada píxel se replica 2×.

El swap de RGB line buffer sólo se realiza cuando ya se han emitido las
dos líneas físicas correspondientes.

Los swaps de line buffer son internos y **no son `FRAME_COMMIT`**.

------------------------------------------------------------------------

# 13. Preparación de la primera línea

Al comienzo de cada frame el pipeline debe cebarse durante VBlank.

Secuencia conceptual:

``` text
entrada en VBlank
    ↓
procesar FRAME_COMMIT
    ↓
esperar a que ACTIVE quede estable
    ↓
preparar TILE Y=0
preparar SPRITE Y=0
    ↓
componer RGB Y=0
    ↓
RGB_CURRENT listo
    ↓
comienza zona visible
```

Así la primera línea visible ya utiliza íntegramente el estado del nuevo
frame.

Con `SURFACE_ENABLE = 1`, `componer RGB Y=0` incluye el fetch desde SDRAM de la
línea 0 de las surfaces; ese fetch forma parte del presupuesto del VBlank.

Durante la zona visible:

``` text
mostrar Y=0   mientras se prepara Y=1
mostrar Y=1   mientras se prepara Y=2
...
mostrar Y=239
```

No se prepara una Y=240.

------------------------------------------------------------------------

# 14. Underflow y política temporal

Regla fundamental:

> **El timing de vídeo nunca se detiene esperando datos.**

## 14.1. Tile underflow

Si llega la frontera de línea y `TILE_NEXT` no está completo:

-   se continúa;
-   lo no preparado queda transparente;
-   se registra el underflow correspondiente.

## 14.2. Sprite underflow

Misma política:

-   se continúa;
-   lo no preparado queda transparente;
-   se registra el underflow correspondiente.

## 14.3. Underflow final de vídeo

Si HDMI necesita un píxel y no existe RGB final válido:

``` text
RGB_OUT = 0xFF00FF
```

magenta deliberadamente visible.

Además:

``` text
HDMI_UNDERFLOW = 1
```

sticky.

No se detiene el timing, no se repite una línea anterior y no se
desplaza la temporización. En cuanto vuelven a existir datos válidos,
vuelve la imagen normal.

## 14.4. Surface underflow

La preparación de surfaces forma parte de la construcción de `RGB_NEXT` (10.5). Si
al llegar la frontera de línea el fetch de surfaces aún no ha terminado, `RGB_NEXT`
no es una línea válida y se aplica la política de 14.3: `RGB_OUT = 0xFF00FF` y
`HDMI_UNDERFLOW = 1`. No se aplica la política de "transparente" de tiles y
sprites, porque las surfaces forman la imagen base y no existe un valor neutro que
sustituya a los píxeles no leídos.

Además se registra el evento en `SURFACE_STATUS` y `SURFACE_UNDERFLOW_COUNT`, para
distinguir un agotamiento de ancho de banda de SDRAM de otras causas de underflow
final.

------------------------------------------------------------------------

# 15. FRAME_COMMIT

El antiguo `SWAP` se generaliza a:

``` text
VIDEO.FRAME_COMMIT  (+0x000C)
```

## 15.1. Escritura

``` text
bit 0  FB_SWAP
bit 1  STATE_COMMIT
bits 31:2 deben ser 0
```

Ejemplos:

``` text
1 → sólo framebuffer swap
2 → sólo commit del estado 2D
3 → ambos
```

Una escritura `3` permite presentar conjuntamente framebuffer y escena
2D en la misma frontera de frame.

## 15.2. Lectura

``` text
bit 0  FB_SWAP_PENDING
bit 1  STATE_COMMIT_PENDING
bits 31:2 = 0
```

Por tanto software puede esperar a ambas operaciones mediante:

``` asm
wait_commit:
    lw    r2, 0(r_frame_commit)
    bnez  r2, wait_commit
```

Leer cero garantiza que todas las operaciones solicitadas han terminado.

## 15.3. Momento de aplicación

El punto de commit es:

``` text
entrada a VBlank
```

Si una petición ya estaba pendiente al entrar en VBlank, se procesa en
ese VBlank.

Si se solicita después de haber pasado esa frontera, espera al VBlank
siguiente.

`FB_SWAP` y `STATE_COMMIT` son independientes y pueden procesarse en el
mismo frame.

## 15.4. Finalización

`FB_SWAP_PENDING` se limpia cuando se ha realizado:

``` text
FB_FRONT ↔ FB_BACK
```

`STATE_COMMIT_PENDING` se limpia sólo cuando toda la actualización
shadow→active, incluida la copia de sprites, ha terminado.

Puede observarse transitoriamente:

``` text
11 → ambos pendientes
10 → swap terminado, state commit aún trabajando
00 → todo terminado
```

## 15.5. Errores

La escritura es atómica.

Si cualquiera de los bits solicitados corresponde a una operación que ya
está pendiente:

-   la escritura completa genera error;
-   no se acepta parcialmente ningún bit nuevo.

Bits reservados distintos de cero también generan error.

------------------------------------------------------------------------

# 16. Estado shadow/active

El estado de escena sincronizado incluye al menos:

``` text
CONFIG
FB_STRIDE
SCROLL_X
SCROLL_Y
TILESET_BASE
SURFACES
SPRITES
```

Los registros pequeños se transfieren a ACTIVE al procesar
`STATE_COMMIT`.

Los sprites se copian durante VBlank.

Mientras `STATE_COMMIT` está pendiente, las escrituras al estado shadow
protegido deben seguir la política MMIO acordada para evitar modificar
una operación ya comprometida.

------------------------------------------------------------------------

# 17. VBLANK

`VBLANK` es un estado instantáneo visible en `VIDEO.STATUS`.

El loop normal de un juego **no necesita esperar explícitamente VBlank**
para presentar una escena. Utiliza `FRAME_COMMIT`, que ya sincroniza la
presentación.

Ejemplo:

``` text
actualizar lógica
renderizar FB_BACK si corresponde
actualizar sprites/config/scroll shadow
FRAME_COMMIT = operación necesaria
esperar FRAME_COMMIT == 0
siguiente iteración
```

`VBLANK` se utiliza principalmente para recursos directos:

-   `TILEMAP`;
-   `PALETTE`;
-   Font RAM si se quiere evitar artefacto;
-   otros efectos de bajo nivel.

Esperar simplemente `VBLANK == 1` significa "estar dentro de algún
VBlank". Si software necesita específicamente la siguiente entrada debe
observar primero `VBLANK == 0` y después esperar `VBLANK == 1`.

------------------------------------------------------------------------

# 18. VIDEO.STATUS

Se conserva deliberadamente cierta redundancia para mantener una vista
global y compatibilidad conceptual con el estado original.

``` text
VIDEO.STATUS (+0x0010)

bit 0  HDMI_UNDERFLOW          sticky, W1C
bit 1  FB_SWAP_PENDING         RO
bit 2  VBLANK                  RO
bit 3  STATE_COMMIT_PENDING    RO
bits 31:4 reserved
```

Los pending son los mismos estados físicos que se leen en
`FRAME_COMMIT`; no son copias independientes.

`FRAME_COMMIT` es la interfaz específica para solicitar/esperar
presentación.

`STATUS` es la fotografía global rápida del subsistema de vídeo.

------------------------------------------------------------------------

# 19. CTRL y CONFIG

## 19.1. CTRL

`CTRL` controla la salida inmediata:

``` text
bits 1:0 MODE

0  BLANK
1  PATTERN
2  SCANOUT
3  reserved

bit 2 HUD_ENABLE
bits restantes reserved
```

`CTRL` no es shadowed.

Esto permite, por ejemplo, pasar inmediatamente a BLANK o activar HUD de
diagnóstico sin esperar a un commit de escena.

## 19.2. CONFIG

`CONFIG` pertenece al estado shadow/active.

``` text
bit 0       TILE_ENABLE
bit 1       SPRITE_ENABLE
bit 2       TEXT_ENABLE
bit 3       SURFACE_ENABLE
bits 11:8   FB_FORMAT
```

Los valores concretos de `FB_FORMAT` deberán reflejar al menos:

``` text
RGB565
INDEX8
```

Cambiar formato requiere `STATE_COMMIT`; no puede ocurrir a mitad de
frame.

------------------------------------------------------------------------

# 20. Diagnóstico 2D

Se separan los diagnósticos por motor.

Bloque propuesto:

``` text
+0x0060  TILE_STATUS
+0x0064  TILE_UNDERFLOW_COUNT
+0x0068  SPRITE_STATUS
+0x006C  SPRITE_UNDERFLOW_COUNT
+0x0070  SURFACE_STATUS
+0x0074  SURFACE_UNDERFLOW_COUNT
```

Los underflows de tile y sprite son independientes del `HDMI_UNDERFLOW`. El
underflow de surfaces (14.4), en cambio, también activa `HDMI_UNDERFLOW` porque
deja `RGB_NEXT` inválido; `SURFACE_STATUS` y su contador permiten identificar la
causa.

No se espera un underflow equivalente de texto porque Text RAM y Font
RAM están en EBR y no dependen de SDRAM para el scanout normal.

Los contadores permiten observar cuántas líneas han resultado afectadas.

La semántica exacta de W1C/reset de los bits de `TILE_STATUS`,
`SPRITE_STATUS` y `SURFACE_STATUS` debe mantenerse coherente con la política general de
diagnósticos MMIO.

------------------------------------------------------------------------

# 21. Mapa MMIO VIDEO consolidado

``` text
VIDEO_BASE = 0x80200000
```

## 21.1. Control / frame

``` text
+0x0000  CTRL
+0x0004  FB_FRONT
+0x0008  FB_BACK
+0x000C  FRAME_COMMIT
+0x0010  STATUS
+0x0014  FRAME_COUNT
+0x0018  SWAP_COUNT
+0x001C  HALT_AT
+0x0020  HALT_TARGET
+0x0024  VIDEO_TX
+0x0028  FB_STRIDE
```

`SWAP_COUNT` continúa contando swaps de framebuffer completados.

`FB_STRIDE` se expresa en bytes. El valor `0` selecciona el stride automático
correspondiente al formato activo; cualquier otro valor selecciona un stride
explícito. `FB_STRIDE` es estado shadow/active (3.2, 16) aunque resida en este
bloque de control; su validación se describe en 3.2.

## 21.2. Configuración 2D shadow

``` text
+0x0040  CONFIG
+0x0044  SCROLL_X
+0x0048  SCROLL_Y
+0x004C  TILESET_BASE
```

## 21.3. Diagnóstico 2D

``` text
+0x0060  TILE_STATUS
+0x0064  TILE_UNDERFLOW_COUNT
+0x0068  SPRITE_STATUS
+0x006C  SPRITE_UNDERFLOW_COUNT
+0x0070  SURFACE_STATUS
+0x0074  SURFACE_UNDERFLOW_COUNT
```

## 21.4. Font loader

``` text
+0x0080  FONT_COUNT
+0x0084  FONT_GLYPH
+0x0088  FONT_DATA0
+0x008C  FONT_DATA1
+0x0090  FONT_DATA2
+0x0094  FONT_DATA3
```

## 21.5. Paleta

``` text
+0x1000 .. +0x13FC  PALETTE[256]
```

Una palabra MMIO por entrada; los bits de color útiles son RGB888.

## 21.6. Sprites shadow

``` text
+0x1800 .. +0x19FC  SPRITES[64]
```

Cada sprite dispone de dos registros de 32 bits.

## 21.7. Tilemap

``` text
+0x2000 .. +0x5FFC  TILEMAP[4096]
```

Una palabra MMIO por entrada lógica de 16 bits.

## 21.8. Text RAM

``` text
+0x6000 .. +0x857C  TEXT[2400]
```

Una palabra MMIO por celda.

## 21.9. Surfaces shadow

``` text
+0x0100 .. +0x01FC  SURFACES[8]
```

Cada surface ocupa 8 palabras de 32 bits (32 bytes); la surface `n` comienza en
`+0x0100 + 0x20 × n`:

``` text
+0x00  BASE      dirección en SDRAM, múltiplo de 16 B
+0x04  STRIDE    bytes; 0 = automático (según WIDTH y FORMAT, redondeado a 16 B)
+0x08  X         entero con signo de 16 bits (complemento a 2)
+0x0C  Y         entero con signo de 16 bits (complemento a 2)
+0x10  WIDTH     píxeles, sin signo
+0x14  HEIGHT    píxeles, sin signo
+0x18  FORMAT    misma codificación que CONFIG.FB_FORMAT
+0x1C  ENABLE    bit 0; resto reservado
```

Es un layout propuesto: una palabra por campo, sin empaquetar, para simplificar el
RTL y la validación por campo. Bits reservados distintos de cero y valores inválidos
(`BASE` o `STRIDE` no múltiplos de 16 B, `FORMAT` no soportado) generan error MMIO en
la escritura. Para las surfaces con `ENABLE = 1`, la comprobación de que un `STRIDE`
explícito cubre `WIDTH` en el `FORMAT` indicado se hace al solicitar `STATE_COMMIT`,
igual que para `FB_STRIDE` (3.2).

Los huecos entre bloques son deliberados y permiten crecimiento sin
renumerar el resto.

------------------------------------------------------------------------

# 22. Reset

Principio:

> **Resetear control, no recorrer memorias grandes para borrarlas.**

Tras reset, el estado de control debe ser seguro y reproducible.

Se propone:

``` text
FB_FRONT  = 0
FB_BACK   = 0
FB_STRIDE = 0

FB_SWAP_PENDING    = 0
STATE_COMMIT_PENDING = 0

SCROLL_X = 0
SCROLL_Y = 0
TILESET_BASE = 0

SURFACE_ENABLE = 0
SURFACE[0..7].ENABLE = 0

TILE_ENABLE   = 0
SPRITE_ENABLE = 0
TEXT_ENABLE   = 0

HDMI_UNDERFLOW = 0
TILE_UNDERFLOW = 0
SPRITE_UNDERFLOW = 0
SURFACE_UNDERFLOW = 0
contadores de underflow = 0

FONT_COUNT = 0
```

`FB_FORMAT` arranca en `RGB565`.

La Font RAM **sí** se inicializa desde el bitstream con la fuente 8×16
por defecto.

No se requiere inicializar a cero:

-   Text RAM;
-   tilemap;
-   paleta;
-   line buffers;
-   datos no necesarios de sprites.

Lo importante es que ninguna memoria indefinida pueda producir una capa
visible antes de que software la habilite.

El modo exacto de `CTRL` tras reset debe conservar la política segura
del contrato VIDEO integrado; históricamente `PATTERN` permite
diagnóstico independiente de SDRAM. La integración final del documento
MMIO debe mantener una única definición de este valor de reset.

------------------------------------------------------------------------

# 23. Actualización típica de un juego

## 23.1. Framebuffer + escena 2D

``` text
1. actualizar lógica
2. renderizar FB_BACK
3. modificar sprites/config/scroll shadow
4. escribir FRAME_COMMIT = 3
5. esperar FRAME_COMMIT == 0
6. repetir
```

En la siguiente entrada a VBlank:

``` text
FB_FRONT ↔ FB_BACK
CONFIG/SCROLL/TILESET_BASE → ACTIVE
SPRITES_SHADOW → SPRITES_ACTIVE
preparar línea 0
```

## 23.2. Sólo sprites/tiles/config

``` text
FRAME_COMMIT = 2
```

## 23.3. Sólo framebuffer

``` text
FRAME_COMMIT = 1
```

------------------------------------------------------------------------

# 24. Cambio de recursos grandes

`TILESET_BASE` permite preparar un tileset nuevo en SDRAM sin tocar el
que está siendo utilizado.

Ejemplo conceptual:

``` text
0x02000000  tileset nivel A
0x02100000  tileset nivel B
```

Mientras A está activo, CPU/GPU prepara B.

Después:

``` text
TILESET_BASE_SHADOW = 0x02100000
FRAME_COMMIT = STATE_COMMIT
```

En la siguiente frontera de frame el nuevo tileset queda activo sin
copiarlo durante VBlank.

El tilemap, en cambio, es único y directo. Para reemplazarlo entero
puede utilizarse VBlank si el tiempo basta o una transición/pantalla de
carga si la actualización es demasiado grande.

------------------------------------------------------------------------

# 25. Line buffers: regla general

Para todos los ping-pong buffers se mantiene la regla:

> Un banco nunca se modifica mientras está siendo consumido.

Conceptualmente:

``` text
CURRENT → consumidor
NEXT    ← productor
```

Cuando llega la frontera apropiada y `NEXT` está listo:

``` text
CURRENT ↔ NEXT
```

Las fronteras no son iguales para todos:

-   tile line buffer: línea lógica;
-   sprite line buffer: línea lógica;
-   RGB line buffer: después de consumir dos líneas físicas
    correspondientes a una línea lógica.

Esto es independiente de `FRAME_COMMIT`, que opera una vez por frame
sobre el estado arquitectónico de escena.

------------------------------------------------------------------------

# 26. Política de recursos FPGA

No se congela en esta fase el número exacto de EBR físicos consumidos.

Las capacidades lógicas principales son, aproximadamente:

``` text
Tilemap     64 × 64 × 16 bit = 8 KiB
Text RAM    80 × 30 × celda
Font RAM    256 × 16 × 8 bit = 4 KiB
Paleta      256 × 24 bit
Line buffers y estado auxiliar
```

El empaquetado real depende de las configuraciones de EBR inferidas por
síntesis.

Se considera preferible sintetizar el diseño real y medir:

-   número de EBR;
-   LUT/FF;
-   Fmax;
-   routing;
-   utilización por bloque;

antes de introducir optimizaciones prematuras motivadas sólo por el
cálculo lógico de bytes.

------------------------------------------------------------------------

# 27. Decisiones consolidadas

Quedan fijadas las siguientes decisiones:

1. Resolución lógica 320×240, salida 640×480 con escalado 2×.
2. Framebuffer clásico `RGB565` o `INDEX8`, con `FB_FRONT`/`FB_BACK` y `FB_SWAP`.
3. `FB_STRIDE` configurable y shadow/active; `0` selecciona stride automático; se valida en escritura (múltiplo de 16 B) y en `STATE_COMMIT` (línea completa).
4. Se añaden 8 `SURFACE` programables para composición de framebuffers/ventanas.
5. El framebuffer clásico es conceptualmente una surface fullscreen opaca, pero conserva su interfaz MMIO especializada.
6. `CONFIG.SURFACE_ENABLE` selecciona framebuffer clásico o compositor de surfaces como fuente base.
7. Cada surface define `BASE`, `STRIDE`, `X`, `Y`, `WIDTH`, `HEIGHT`, `FORMAT` y `ENABLE`.
8. Las surfaces soportan `RGB565` opaco e `INDEX8` con índice 0 transparente.
9. Existe una única paleta global de 256 colores RGB888, compartida por todas las fuentes INDEX8.
10. No existen paletas por surface ni alpha blending.
11. El compositor y los RGB line buffers mantienen formato interno `RGB888`.
12. No existe un line buffer por surface; se compone secuencialmente sobre `RGB_NEXT`.
13. Los descriptores de surface son shadow/active y se presentan mediante `STATE_COMMIT`.
14. No existe FRONT/BACK por surface; cambiar `BASE` permite single, double o triple buffering gestionado por software.
15. Tiles y sprites siguen siendo motores independientes y convergen en el mismo compositor; la imagen base queda siempre por debajo de tiles y sprites.
16. Tilemap único de 64×64×16 bits; VBlank para actualizaciones directas limpias.
17. Tileset en SDRAM seleccionado mediante `TILESET_BASE` shadow/active.
18. 64 sprites con estado shadow/active.
19. Text RAM 80×30 y fuente 256×8×16 inicializada desde bitstream.
20. HUD sin RAM propia, reutilizando renderer de fuente y paleta de texto.
21. Tile/sprite/RGB line buffers ping-pong.
22. Preparación de la primera línea durante VBlank.
23. El timing de vídeo nunca espera.
24. Tile/sprite underflow deja transparente lo no preparado; underflow RGB final (incluido el de surfaces) produce `0xFF00FF`.
25. `FRAME_COMMIT` unifica framebuffer swap y commit de escena; `FRAME_COMMIT=3` solicita ambos atómicamente.
26. El punto de aplicación es la entrada a VBlank.
27. `CTRL` es inmediato; `CONFIG`, surfaces y demás estado de escena son shadow/active.
28. El límite principal del compositor de surfaces es el ancho de banda SDRAM; debe medirse en RTL real.
29. Las memorias grandes no se borran en reset.
30. El consumo físico exacto de EBR y Fmax se decide a partir de síntesis real.

------------------------------------------------------------------------

# 28. Puntos de integración final

Antes de declarar esta revisión como contrato implementado deberán
trasladarse estas decisiones al documento MMIO maestro y a las
constantes comunes de RTL/software.

En particular deberán quedar en una única fuente:

``` text
offsets VIDEO
semántica y validación de FB_STRIDE
layout y validación de SURFACE[0..7] (propuesto en 21.9)
semántica de SURFACE_ENABLE
bits de CTRL
bits de CONFIG
bits de FRAME_COMMIT
bits de STATUS
valores de FB_FORMAT (compartidos con SURFACE.FORMAT)
formatos exactos de sprite
formato exacto de celda TEXT
formato exacto de entrada TILEMAP
semántica exacta de TILE_STATUS / SPRITE_STATUS / SURFACE_STATUS
```

Los tres formatos de datos anteriores ya fueron objeto del diseño previo
y deben copiarse literalmente de su definición consolidada al documento
MMIO final; no deben reinventarse durante la implementación.

La síntesis del primer RTL completo será el punto adecuado para revisar
el coste real de EBR y Fmax.
