# Formatos gráficos y extensiones de MiniISA para MiniGPU

## Objetivo

La propuesta busca formatos que encajen con MiniGPU: GPU SIMT, 8 warps
de 8 lanes (64 threads residentes), memoria compartida CPU/GPU, SDRAM
relativamente costosa y una ISA sencilla de 32 bits. La prioridad es que
la decodificación requiera poco estado, accesos secuenciales, pocas
dependencias y pueda dividirse en bloques independientes.

La recomendación general es separar **framebuffer**, **formato gráfico
de trabajo**, **formato comprimido para sprites/imágenes** y **formato
de almacenamiento de assets**. No tienen por qué ser el mismo.

## Framebuffer

El framebuffer debería permanecer sin comprimir. Las dos opciones
naturales son:

-   **RGB565 (16 bpp):** 320×240 ocupa 153.600 bytes. Reduce a la mitad
    el tráfico respecto a RGB32.
-   **XRGB8888/RGB32 (32 bpp):** 320×240 ocupa 307.200 bytes. Un píxel
    coincide con una palabra de 32 bits y simplifica mucho los accesos.

La elección depende de cuánto pese el ancho de banda SDRAM frente a la
simplicidad.

## PAL8 como formato gráfico principal

Para sprites, tiles y fondos usaría normalmente **PAL8**. Cada píxel es
un índice de 8 bits y una paleta de hasta 256 entradas lo convierte al
formato del framebuffer.

Una imagen 320×240 ocupa sólo 76.800 bytes más la paleta (1.024 bytes si
cada color son 32 bits). Además encaja directamente con `LOADUB` y
`STOREB`.

**PAL4** (16 colores, dos píxeles por byte) puede ser útil para assets
muy retro, pero no lo usaría como representación general porque obliga a
extraer nibbles continuamente.

## RLE: primera compresión

La primera compresión que implementaría sería un RLE estilo PackBits,
con bloques de repetición y bloques literales:

``` text
0LLLLLLL -> LITERAL
1LLLLLLL -> RUN
```

Conceptualmente:

``` text
RUN 8,A
RUN 5,B
LITERAL C,D
RUN 8,E
```

Esto necesita básicamente `LOADUB`, `STOREB`, sumas y branches, por lo
que encaja muy bien con MiniISA.

## Sprites: LITERAL, RUN y SKIP

Para sprites añadiría explícitamente transparencia:

``` text
00LLLLLL -> LITERAL
01LLLLLL -> RUN
10LLLLLL -> SKIP
11LLLLLL -> reservado
```

Si la longitud se interpreta como `L+1`, cada comando representa 1..64
píxeles sin necesitar un caso especial para cero.

`SKIP N` simplemente avanza el destino sin escribir:

``` text
dst += N
```

Esto no sólo comprime áreas transparentes: evita stores al framebuffer.

El tipo `11` conviene dejarlo reservado inicialmente. Más adelante
podría servir para longitud extendida, fin de línea u otra necesidad
demostrada por los workloads.

## Compresión por scanline

Una versión inicial puede comprimir cada scanline independientemente y
guardar una tabla:

``` text
offset_line[height]
```

Esto permite acceso directo a una línea, clipping y descompresión
paralela de distintas líneas.

Un único stream RLE global es menos atractivo porque introduce una
dependencia secuencial fuerte.

## Formato tiled

Para explotar mejor MiniGPU dividiría imágenes grandes en tiles
independientes, inicialmente **8×8** o **16×16**.

``` text
┌────┬────┬────┬────┐
│ T0 │ T1 │ T2 │ T3 │
├────┼────┼────┼────┤
│ T4 │ T5 │ T6 │ T7 │
└────┴────┴────┴────┘
```

8×8 es especialmente interesante porque el warp actual tiene 8 lanes.

Cada tile puede escoger independientemente entre:

-   **RAW:** sin comprimir.
-   **RLE:** RUN/LITERAL.
-   **SOLID:** todo el tile tiene un único color/índice.

El conversor de PC puede elegir automáticamente:

``` text
si todos los píxeles son iguales:
    SOLID
si no:
    probar RLE
    si RLE < RAW:
        RLE
    si no:
        RAW
```

Así la GPU no toma decisiones complejas durante el render.

Los tiles independientes permiten repartir trabajo:

``` text
warp 0 -> tile 0
warp 1 -> tile 1
...
warp 7 -> tile 7
```

y facilitan clipping y actualización parcial.

## Propuesta conceptual `.mtx`

Un formato propio de textura podría organizarse como:

``` text
HEADER
PALETTE
TILE TABLE
TILE DATA
```

Una cabecera conceptual tendría:

``` text
magic
version
width
height
pixel_format
tile_width
tile_height
flags
palette_entries
tile_count
palette_offset
tile_table_offset
data_offset
```

Los formatos iniciales podrían ser `PAL8`, `RGB565`, `RGB32` y
opcionalmente `PAL4`.

Cada entrada de la tabla de tiles podría contener:

``` text
type
offset
compressed_size
```

o una codificación más compacta. Conviene alinear cabeceras, tablas y
offsets a 4 bytes aunque los streams PAL8 sean byte-oriented.

## LZ4/LZSS simplificado

Para assets grandes almacenados en ROM/flash/SDRAM estudiaría después un
formato inspirado en LZ4/LZSS:

``` text
LITERAL
MATCH(offset,length)
LITERAL
MATCH(offset,length)
...
```

Un match equivale a copiar desde datos ya descomprimidos:

``` c
while (length--)
    *dst++ = *(dst-offset)++;
```

No lo usaría como formato desde el que dibujar directamente. Lo usaría
así:

``` text
asset LZ
   ↓
descompresión
   ↓
PAL8/MTX en RAM
   ↓
render
```

Es decir: **LZ como almacenamiento; PAL8/RLE/tiled como formato
gráfico**.

## PNG y JPEG

No usaría PNG como formato nativo de MiniGPU: DEFLATE, Huffman,
bitstreams, filtros de scanline y checksums complican innecesariamente
el decoder.

JPEG añade Huffman, DCT/IDCT, cuantización, zig-zag y conversión de
color.

Ambos son buenos formatos fuente en PC:

``` text
PNG/JPEG
   ↓
conversor offline
   ↓
MTX
```

La complejidad cara queda fuera de la máquina.

# Instrucciones que podrían ayudar

MiniISA actual ya permite implementar todo lo anterior con accesos
sub-palabra, ALU, shifts, comparaciones, branches y las primitivas SIMT
existentes. Por tanto, **ninguna instrucción nueva es imprescindible**.
La cuestión es cuáles producen una mejora suficientemente grande y
general.

## 1. SHFL: candidata principal

La extensión más interesante es una operación genérica de intercambio
entre lanes:

``` asm
SHFL Rd, Ra, Rlane
```

Semántica conceptual:

``` text
Rd[lane] = Ra[Rlane]
```

Esto permite implementar varias operaciones sin crear instrucciones
diferentes.

### Broadcast para RLE

Una lane decodifica:

``` text
RUN 8, 0x37
```

y todas seleccionan el registro de esa lane:

``` text
lane   0  1  2  3  4  5  6  7
value 37 37 37 37 37 37 37 37
```

Cada lane puede hacer después su store.

### Vecinos para el fuego

La misma `SHFL` permite:

``` text
left  = SHFL(value, lane-1)
right = SHFL(value, lane+1)
```

Por tanto ya tenemos dos workloads distintos ---fuego y descompresión---
que justifican estudiar la misma primitiva. Esto es mucho más atractivo
que una instrucción específica de gráficos.

## 2. BALLOT

Una segunda primitiva SIMT general sería:

``` asm
BALLOT Rd, predicate
```

Por ejemplo:

``` text
lane:      7 6 5 4 3 2 1 0
predicate: 0 0 1 1 1 1 0 0

Rd = 00111100
```

Puede servir para máscaras de transparencia, detectar warps sin trabajo,
compactación, búsqueda y otros algoritmos paralelos. Para RLE es menos
directamente importante que `SHFL`, pero tiene mucha generalidad.

## 3. CLZ y CTZ

``` asm
CLZ Rd, Ra
CTZ Rd, Ra
```

Combinadas con `BALLOT`, permiten localizar rápidamente la
primera/última lane activa. También son útiles fuera de gráficos:
bitsets, allocators, normalización, algoritmos enteros y soporte de
compiladores.

Las consideraría después de `SHFL` y `BALLOT`.

## 4. GETLANE y GETWARP

Actualmente pueden obtenerse a partir de `GETTID` (con warp size 8):

``` asm
GETTID R1
ANDI Rlane, R1, 7
```

y:

``` asm
GETTID R1
SHRI Rwarp, R1, 3
```

Por tanto `GETLANE`/`GETWARP` son cómodas, pero sólo ahorran una
instrucción en estos casos. No las pondría entre las primeras
prioridades.

## 5. BEXT

Para decodificar controles compactos aparece:

``` c
type   = control >> 6;
length = control & 0x3F;
```

Pero ya se expresa eficientemente:

``` asm
SHRI Rtype, Rcontrol, 6
ANDI Rlen, Rcontrol, 0x3F
```

No añadiría `BEXT` únicamente por los formatos gráficos. Se puede
reconsiderar si aparecen más workloads que la necesiten.

## 6. Masked stores

Serían atractivos para transparencia, pero antes conviene comprobar si
el modelo normal de máscaras/divergencia SIMT permite hacer el store
únicamente en las lanes visibles con suficiente eficiencia. No añadiría
una instrucción específica sin medir.

## Instrucciones que evitaría

No añadiría:

``` text
MEMCPY
RLE_DECODE
RUN_STORE
SPRITE_DRAW
```

`MEMCPY` introduce semántica compleja (longitud, solapamiento, faults,
LSU, stalls) y las otras especializan demasiado la ISA.

Es preferible proporcionar primitivas generales y construir los
algoritmos en software.

# Prioridad provisional

  Instrucción            Fuego        RLE      LZ   Generalidad   Prioridad
  ----------------- ---------- ---------- ------- ------------- -----------
  `SHFL`              muy alta       alta   media      muy alta       **1**
  `BALLOT`               media      media    baja      muy alta       **2**
  `CLZ/CTZ`               baja       baja   media      muy alta       **3**
  `GETLANE`              media      media   media         media        baja
  `GETWARP`               baja       baja    baja         media        baja
  `BEXT`                  baja      media   media          alta       medir
  masked store            baja      media    baja         media       medir
  `MEMCPY`                nula       baja    alta          baja          no
  instrucción RLE         nula   muy alta    nula      muy baja          no

Esta prioridad debe validarse con benchmarks.

# Encoding de operaciones warp

MiniISA v0.1 reserva `0x34–0x3D` para GPU. Son diez opcodes, pero
conviene no consumirlos uno a uno sin estudiar antes la familia
completa.

En vez de:

``` text
0x34 SHFL
0x35 BALLOT
0x36 GETLANE
0x37 GETWARP
...
```

merece la pena estudiar algo como:

``` text
0x34 WARP
```

con una subfunción en bits actualmente disponibles:

``` text
subop 0 = SHFL
subop 1 = BALLOT
subop 2 = ...
```

No fijaría aún el encoding. Primero hay que definir conjuntamente la
semántica y operandos de las operaciones. `SHFL` encaja naturalmente con
`Rd, Ra, Rlane`; `BALLOT` tiene necesidades diferentes.

El orden correcto sería:

``` text
definir semántica
      ↓
escribir kernels reales
      ↓
determinar operandos
      ↓
diseñar encoding
```

# Benchmarks para decidir

Los formatos permiten construir una batería muy útil:

1.  **RAW PAL8 → framebuffer:** coste base.
2.  **RLE → framebuffer:** decoder, branches y tráfico.
3.  **Tiled RLE:** reparto entre warps.
4.  **RLE + SHFL:** beneficio de comunicación entre lanes.
5.  **LZ → PAL8 RAM:** cargas dependientes y copias.
6.  **Fuego naive vs fuego con SHFL:** reutilización de vecinos.

Conviene medir ciclos, instrucciones, loads/stores, bytes
leídos/escritos, stalls LSU/fabric, accesos SDRAM, bursts, divergencia y
ocupación de warps.

# Pipeline de assets recomendado

``` text
PNG / JPEG / BMP
        │
        ▼
  conversor en PC
        │
        ├── cuantización/paleta
        ├── división en tiles
        ├── elección RAW/RLE/SOLID
        └── tabla de offsets
        │
        ▼
       MTX
        │
        ▼
 MiniCPU / MiniGPU
        │
        ▼
 framebuffer
```

# Propuesta inicial

``` text
FRAMEBUFFER
    RGB565 o RGB32

TEXTURAS / FONDOS
    PAL8
    tiles 8×8 inicialmente
    RAW / RLE / SOLID

SPRITES
    PAL8
    LITERAL / RUN / SKIP

ASSETS GRANDES
    LZ4-like opcional
       ↓
    descomprimir a RAM
```

## Recomendaciones firmes

1.  Mantener el framebuffer sin comprimir.
2.  Usar PAL8 como principal formato gráfico compacto.
3.  Empezar con RLE RUN/LITERAL.
4.  Añadir SKIP para sprites transparentes.
5.  Dividir imágenes grandes en tiles independientes.
6.  Permitir RAW/RLE/SOLID por tile.
7.  Convertir PNG/JPEG offline en PC.
8.  Usar LZ sólo como posible formato de almacenamiento.
9.  No añadir instrucciones específicas de RLE/JPEG/PNG.
10. Implementar y medir antes de modificar MiniISA.

## Conclusión

La combinación que parece más coherente para MiniGPU es:

``` text
PAL8
  +
tiles 8×8
  +
RAW / RLE / SOLID
  +
SKIP para sprites
```

El análisis refuerza además algo que ya apareció con el efecto de fuego:
**`SHFL` es actualmente la extensión de warp más interesante**, porque
sirve tanto para compartir vecinos como para broadcast y cooperación
durante la descompresión.

La evolución recomendable es:

``` text
formato sencillo
      ↓
decoder con MiniISA actual
      ↓
medir LSU / fabric / SDRAM
      ↓
identificar cuello de botella
      ↓
probar SHFL / BALLOT
      ↓
volver a medir
      ↓
decidir la extensión definitiva
```

Así el formato gráfico y MiniISA evolucionan a partir de workloads
reales, manteniendo la máquina pequeña y comprensible.
