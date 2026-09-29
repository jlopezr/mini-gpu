<!-- trace:artifact DES-MINIGPU-2D-V03
type: design
kind: proposal
-->

# MiniGPU 2D --- propuesta consolidada v0.3

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
    primero el píxel final y realiza una única consulta de paleta.
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
Framebuffer ───────────────┐
                           │
Tile renderer ─► TILE LB ──┤
                           ├─► compositor ─► RGB line buffer ─► scaler 2× ─► HDMI
Sprite renderer ► SPR LB ──┤
                           │
Text/HUD ──────────────────┘
```

El framebuffer, tiles y sprites forman la escena gráfica. Texto y HUD se
aplican como overlays posteriores.

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

## 3.2. Stride fijo

No existe `FB_STRIDE` configurable.

``` text
RGB565:
    stride = 320 × 2 = 640 bytes
    tamaño = 320 × 240 × 2 = 153600 bytes

INDEX8:
    stride = 320 bytes
    tamaño = 320 × 240 = 76800 bytes
```

Ambos strides son múltiplos de 16 bytes, por lo que cada línea queda
naturalmente alineada con las transacciones de 128 bits del fabric si la
base también lo está.

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

# 10. Composición

El compositor combina las fuentes gráficas de acuerdo con sus enables y
prioridades.

Tiles y sprites producen índices. En `INDEX8`, el framebuffer también
produce un índice.

El diseño debe resolver primero cuál es el píxel indexado ganador y
efectuar **una única consulta de paleta por píxel**.

En `RGB565`, el framebuffer se convierte a RGB para entrar en la
composición final.

Texto/HUD se aplican como overlay utilizando su propia selección rápida
de `PALETTE[1..15]`.

------------------------------------------------------------------------

# 11. RGB line buffers y escalado

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

# 12. Preparación de la primera línea

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

Durante la zona visible:

``` text
mostrar Y=0   mientras se prepara Y=1
mostrar Y=1   mientras se prepara Y=2
...
mostrar Y=239
```

No se prepara una Y=240.

------------------------------------------------------------------------

# 13. Underflow y política temporal

Regla fundamental:

> **El timing de vídeo nunca se detiene esperando datos.**

## 13.1. Tile underflow

Si llega la frontera de línea y `TILE_NEXT` no está completo:

-   se continúa;
-   lo no preparado queda transparente;
-   se registra el underflow correspondiente.

## 13.2. Sprite underflow

Misma política:

-   se continúa;
-   lo no preparado queda transparente;
-   se registra el underflow correspondiente.

## 13.3. Underflow final de vídeo

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

------------------------------------------------------------------------

# 14. FRAME_COMMIT

El antiguo `SWAP` se generaliza a:

``` text
VIDEO.FRAME_COMMIT  (+0x000C)
```

## 14.1. Escritura

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

## 14.2. Lectura

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

## 14.3. Momento de aplicación

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

## 14.4. Finalización

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

## 14.5. Errores

La escritura es atómica.

Si cualquiera de los bits solicitados corresponde a una operación que ya
está pendiente:

-   la escritura completa genera error;
-   no se acepta parcialmente ningún bit nuevo.

Bits reservados distintos de cero también generan error.

------------------------------------------------------------------------

# 15. Estado shadow/active

El estado de escena sincronizado incluye al menos:

``` text
CONFIG
SCROLL_X
SCROLL_Y
TILESET_BASE
SPRITES
```

Los registros pequeños se transfieren a ACTIVE al procesar
`STATE_COMMIT`.

Los sprites se copian durante VBlank.

Mientras `STATE_COMMIT` está pendiente, las escrituras al estado shadow
protegido deben seguir la política MMIO acordada para evitar modificar
una operación ya comprometida.

------------------------------------------------------------------------

# 16. VBLANK

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

# 17. VIDEO.STATUS

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

# 18. CTRL y CONFIG

## 18.1. CTRL

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

## 18.2. CONFIG

`CONFIG` pertenece al estado shadow/active.

``` text
bit 0       TILE_ENABLE
bit 1       SPRITE_ENABLE
bit 2       TEXT_ENABLE
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

# 19. Diagnóstico 2D

Se separan los diagnósticos por motor.

Bloque propuesto:

``` text
+0x0060  TILE_STATUS
+0x0064  TILE_UNDERFLOW_COUNT
+0x0068  SPRITE_STATUS
+0x006C  SPRITE_UNDERFLOW_COUNT
```

Los underflows de tile y sprite son independientes del `HDMI_UNDERFLOW`.

No se espera un underflow equivalente de texto porque Text RAM y Font
RAM están en EBR y no dependen de SDRAM para el scanout normal.

Los contadores permiten observar cuántas líneas han resultado afectadas.

La semántica exacta de W1C/reset de los bits de `TILE_STATUS` y
`SPRITE_STATUS` debe mantenerse coherente con la política general de
diagnósticos MMIO.

------------------------------------------------------------------------

# 20. Mapa MMIO VIDEO consolidado

``` text
VIDEO_BASE = 0x80200000
```

## 20.1. Control / frame

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
```

`SWAP_COUNT` continúa contando swaps de framebuffer completados.

## 20.2. Configuración 2D shadow

``` text
+0x0040  CONFIG
+0x0044  SCROLL_X
+0x0048  SCROLL_Y
+0x004C  TILESET_BASE
```

## 20.3. Diagnóstico 2D

``` text
+0x0060  TILE_STATUS
+0x0064  TILE_UNDERFLOW_COUNT
+0x0068  SPRITE_STATUS
+0x006C  SPRITE_UNDERFLOW_COUNT
```

## 20.4. Font loader

``` text
+0x0080  FONT_COUNT
+0x0084  FONT_GLYPH
+0x0088  FONT_DATA0
+0x008C  FONT_DATA1
+0x0090  FONT_DATA2
+0x0094  FONT_DATA3
```

## 20.5. Paleta

``` text
+0x1000 .. +0x13FC  PALETTE[256]
```

Una palabra MMIO por entrada; los bits de color útiles son RGB888.

## 20.6. Sprites shadow

``` text
+0x1800 .. +0x19FC  SPRITES[64]
```

Cada sprite dispone de dos registros de 32 bits.

## 20.7. Tilemap

``` text
+0x2000 .. +0x5FFC  TILEMAP[4096]
```

Una palabra MMIO por entrada lógica de 16 bits.

## 20.8. Text RAM

``` text
+0x6000 .. +0x857C  TEXT[2400]
```

Una palabra MMIO por celda.

Los huecos entre bloques son deliberados y permiten crecimiento sin
renumerar el resto.

------------------------------------------------------------------------

# 21. Reset

Principio:

> **Resetear control, no recorrer memorias grandes para borrarlas.**

Tras reset, el estado de control debe ser seguro y reproducible.

Se propone:

``` text
FB_FRONT = 0
FB_BACK  = 0

FB_SWAP_PENDING    = 0
STATE_COMMIT_PENDING = 0

SCROLL_X = 0
SCROLL_Y = 0
TILESET_BASE = 0

TILE_ENABLE   = 0
SPRITE_ENABLE = 0
TEXT_ENABLE   = 0

HDMI_UNDERFLOW = 0
TILE_UNDERFLOW = 0
SPRITE_UNDERFLOW = 0
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

# 22. Actualización típica de un juego

## 22.1. Framebuffer + escena 2D

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

## 22.2. Sólo sprites/tiles/config

``` text
FRAME_COMMIT = 2
```

## 22.3. Sólo framebuffer

``` text
FRAME_COMMIT = 1
```

------------------------------------------------------------------------

# 23. Cambio de recursos grandes

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

# 24. Line buffers: regla general

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

# 25. Política de recursos FPGA

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

# 26. Decisiones consolidadas

Quedan fijadas las siguientes decisiones:

1.  Resolución lógica 320×240, salida 640×480 con escalado 2×.
2.  Framebuffer `RGB565` o `INDEX8`.
3.  Stride fijo: 640 B para RGB565 y 320 B para INDEX8.
4.  Bases de framebuffer alineadas a 16 B.
5.  FIFO de framebuffer de 128 bits + unpacker.
6.  Paleta global de 256 colores RGB888.
7.  Colores 1..15 replicados en registros para texto/HUD.
8.  Tilemap único de 64×64×16 bits.
9.  Tilemap directo; VBlank para actualizaciones limpias.
10. Tileset en SDRAM seleccionado mediante `TILESET_BASE` shadow/active.
11. 64 sprites con estado shadow/active.
12. Text RAM 80×30.
13. Fuente 256×8×16 inicializada desde el bitstream.
14. Font loader MMIO de cuatro words por glifo.
15. Bit 7 de una fila de glifo es el píxel izquierdo.
16. HUD sin RAM propia, reutilizando renderer de fuente y paleta de
    texto.
17. Tile/sprite/RGB line buffers ping-pong.
18. Preparación de la primera línea durante VBlank.
19. El timing de vídeo nunca espera.
20. Tile/sprite underflow deja transparente lo no preparado.
21. Underflow final de RGB produce magenta `0xFF00FF`.
22. `FRAME_COMMIT` unifica framebuffer swap y commit de escena.
23. `FRAME_COMMIT=3` solicita ambos atómicamente.
24. Los pending se leen tanto en `FRAME_COMMIT` como en `STATUS`.
25. El punto de aplicación es la entrada a VBlank.
26. El loop normal se sincroniza con `FRAME_COMMIT`, no con polling
    explícito de VBlank.
27. VBlank queda disponible para paleta, tilemap, fuente y efectos de
    bajo nivel.
28. `CTRL` es inmediato; `CONFIG` es shadow/active.
29. Las memorias grandes no se borran en reset.
30. El consumo físico exacto de EBR se decide a partir de síntesis real.

------------------------------------------------------------------------

# 27. Puntos de integración final

Antes de declarar esta revisión como contrato implementado deberán
trasladarse estas decisiones al documento MMIO maestro y a las
constantes comunes de RTL/software.

En particular deberán quedar en una única fuente:

``` text
offsets VIDEO
bits de CTRL
bits de CONFIG
bits de FRAME_COMMIT
bits de STATUS
valores de FB_FORMAT
formatos exactos de sprite
formato exacto de celda TEXT
formato exacto de entrada TILEMAP
semántica exacta de TILE_STATUS / SPRITE_STATUS
```

Los tres formatos de datos anteriores ya fueron objeto del diseño previo
y deben copiarse literalmente de su definición consolidada al documento
MMIO final; no deben reinventarse durante la implementación.

La síntesis del primer RTL completo será el punto adecuado para revisar
el coste real de EBR y Fmax.
