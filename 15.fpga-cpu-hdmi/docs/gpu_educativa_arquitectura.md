# GPU educativa — Arquitectura, modos de vídeo, ISA y pipeline gráfico

## 1. Objetivo general

La GPU está pensada como una arquitectura educativa y programable, con énfasis en:

- ejecución **SIMT**;
- una ISA pequeña y general;
- salida de vídeo HDMI estable;
- varios formatos de framebuffer;
- uso eficiente de SDRAM;
- programación mediante kernels;
- aceleración hardware selectiva para operaciones que realmente lo justifican;
- posibilidad de evolucionar hacia gráficos 3D.

La arquitectura base considerada es:

- **8 warps**
- **8 lanes por warp**
- **64 lanes en total**
- **32 MiB de SDRAM**
- framebuffer almacenado en SDRAM
- salida HDMI con timing fijo
- line buffer/FIFO entre SDRAM y scanout
- doble buffering
- overlay de texto
- posible capa hardware de sprites

---

# 2. Arquitectura general

```text
                         CPU
                          │
                 comandos / dispatch
                          │
                          ▼
                 ┌───────────────────┐
                 │       GPU         │
                 │                   │
                 │  8 warps × 8 lanes
                 │     = 64 lanes    │
                 │                   │
                 │   ISA SIMT        │
                 └─────────┬─────────┘
                           │
                           ▼
                        SDRAM
                         32 MiB
                           │
              ┌────────────┼────────────┐
              │            │            │
              │            │            │
        framebuffer     sprites      otros datos
              │
              ▼
        line buffer/FIFO
              │
              ▼
          scanout HDMI
              │
       ┌──────┴───────┐
       │              │
   text overlay   sprite overlay
       │              │
       └──────┬───────┘
              ▼
             HDMI
```

La idea importante es separar tres conceptos:

1. **GPU programable**  
   Ejecuta kernels mediante warps y lanes.

2. **Memoria de vídeo**  
   Vive en SDRAM compartida.

3. **Scanout**  
   Lee el framebuffer, aplica overlays y genera HDMI.

---

# 3. Modos de vídeo propuestos

## 3.1 Tabla de modos

| Modo | Resolución | Formato | Framebuffer | Lectura aprox. a 60 Hz |
|---|---:|---:|---:|---:|
| TEXT | 80×30 caracteres | carácter + atributos | pocos KiB | muy baja |
| RGB565 | 320×240 | 16 bpp | 150 KiB | ~9,2 MB/s |
| INDEX8 | 320×240 | 8 bpp + paleta | 75 KiB | ~4,6 MB/s |
| XRGB8888 | 320×240 | 32 bpp | 300 KiB | ~18,4 MB/s |
| INDEX8_HI | 640×480 | 8 bpp + paleta | 300 KiB | ~18,4 MB/s |
| RGB565_HI | 640×480 | 16 bpp | 600 KiB | ~36,9 MB/s |
| MONO | 640×480 | 1 bpp | 37,5 KiB | ~2,3 MB/s |

> RGB888 puro ocupa 225 KiB a 320×240, pero XRGB8888 puede ser más cómodo para una GPU SIMT porque cada lane puede trabajar con una palabra de 32 bits alineada.

---

# 4. Salida HDMI fija

Una decisión recomendable es mantener un único timing de salida HDMI, por ejemplo:

```text
640 × 480 @ 60 Hz
```

Los modos 320×240 se escalan 2× en hardware:

```text
Framebuffer 320×240
        │
        ▼
duplicación 2× horizontal
        │
duplicación 2× vertical
        │
        ▼
   640×480 scanout
        │
        ▼
       HDMI
```

Esto simplifica mucho:

- timing HDMI;
- sincronización;
- scanout;
- cambio de modo;
- depuración.

---

# 5. SDRAM y ancho de banda

La capacidad de SDRAM no es el principal problema: con 32 MiB sobra espacio para varios framebuffers y recursos.

El punto crítico es el **ancho de banda sostenido**.

Aproximadamente:

```text
BW = ancho × alto × bytes_por_pixel × FPS
```

Ejemplos:

```text
320×240 RGB565
320 × 240 × 2 × 60
≈ 9,2 MB/s

640×480 RGB565
640 × 480 × 2 × 60
≈ 36,9 MB/s
```

El scanout no debería leer un píxel suelto de SDRAM cada ciclo.

Se recomienda:

```text
SDRAM
  │
  │ lecturas en burst
  ▼
Line Buffer / FIFO
  │
  ▼
Scanout
  │
  ▼
HDMI
```

Esto desacopla:

- latencia SDRAM;
- refresh;
- apertura de filas;
- arbitraje;
- pixel clock.

---

# 6. Filosofía de ISA

La GPU no se plantea como un blitter tradicional con instrucciones como:

```text
FILL_RECT
DRAW_LINE
BLIT
```

Esas operaciones se implementan como **kernels**.

La ISA física debe mantenerse pequeña y útil para cómputo general SIMT.

---

# 7. ISA base propuesta

## 7.1 Operaciones de memoria

```asm
LD8   Rd, [Ra]
LD16  Rd, [Ra]
LD32  Rd, [Ra]

ST8   [Ra], Rs
ST16  [Ra], Rs
ST32  [Ra], Rs
```

Son especialmente importantes porque cada formato gráfico trabaja de forma natural con tamaños distintos.

---

# 8. Instrucciones específicas de formato

## 8.1 PACK565

```asm
PACK565 Rd, Ra
```

Entrada:

```text
Ra = 0x00RRGGBB
```

Salida:

```text
Rd = 0x0000RRRRRGGGGGGBBBBB
```

La operación conceptual es:

```text
R5 = R >> 3
G6 = G >> 2
B5 = B >> 3
```

y luego:

```text
RGB565 = (R5 << 11) | (G6 << 5) | B5
```

---

## 8.2 UNPACK565

```asm
UNPACK565 Rd, Ra
```

Convierte aproximadamente:

```text
RGB565 -> 0x00RRGGBB
```

Es útil para:

- leer un píxel;
- modificar color;
- blending;
- postprocesado;
- conversiones de formato.

---

# 9. Coalescing de memoria

Con 8 lanes por warp, RGB565 encaja especialmente bien.

Cada lane escribe 16 bits:

```text
lane 0: 16 bits
lane 1: 16 bits
lane 2: 16 bits
lane 3: 16 bits
lane 4: 16 bits
lane 5: 16 bits
lane 6: 16 bits
lane 7: 16 bits
```

Total:

```text
8 × 16 = 128 bits
```

Puede convertirse en una operación de memoria agrupada:

```text
8 lanes
   │
   ▼
coalescer
   │
   ▼
128-bit write / burst
   │
   ▼
SDRAM
```

Para INDEX8:

```text
8 lanes × 8 bits = 64 bits
```

Para XRGB8888:

```text
8 lanes × 32 bits = 256 bits
```

Esto hace que XRGB8888 sea arquitectónicamente más natural que RGB888 de 24 bits.

---

# 10. INDEX8

El framebuffer almacena únicamente índices:

```text
0..255
```

El scanout consulta una paleta:

```text
Framebuffer INDEX8
       │
       ▼
     index
       │
       ▼
 palette[256]
       │
       ▼
   RGB888
       │
       ▼
      HDMI
```

La GPU no necesita leer la paleta durante un kernel que simplemente genere índices.

Ejemplo conceptual:

```asm
; iteraciones de Mandelbrot
AND  rColor, rIter, 255
ST8  [rAddr], rColor
```

La paleta puede modificarse sin tocar framebuffer.

Esto permite:

- animaciones de color;
- ciclos de paleta;
- efectos de fuego;
- agua;
- fractales;
- demos retro.

---

# 11. MONO 1 bpp y BALLOT

Un framebuffer de 1 bit presenta una oportunidad interesante.

Cada warp procesa 8 píxeles:

```text
lane 0 -> bit 0
lane 1 -> bit 1
...
lane 7 -> bit 7
```

Una instrucción SIMT muy útil sería:

```asm
BALLOT Rd, predicate
```

Ejemplo:

```text
lane   predicado
 0       1
 1       0
 2       1
 3       1
 4       0
 5       0
 6       1
 7       0
```

Resultado:

```text
Rd = 01001101
```

Después una lane puede escribir el byte completo:

```asm
CMP    p0, rValue, 0
BALLOT rMask, p0

; solo una lane realiza la escritura
ST8 [addr], rMask
```

`BALLOT` es preferible a una instrucción específica `PACK1BPP`, porque también resulta útil en algoritmos generales SIMT.

---

# 12. Operaciones entre lanes

Además de `BALLOT`, se consideran interesantes:

```asm
SHUFFLE   Rd, Rs, lane
BROADCAST Rd, Rs, lane
ANY       predicate
ALL       predicate
```

Estas primitivas permiten:

- intercambio de datos dentro del warp;
- reducciones;
- comunicación sin SDRAM;
- algoritmos paralelos;
- packing;
- búsqueda;
- máscaras;
- operaciones cooperativas.

---

# 13. Kernels 2D

Las operaciones gráficas de alto nivel viven como software.

## Kernels base

```text
clear
fill_rect
draw_rect
draw_line
draw_circle
draw_triangle_2d
copy_rect

blit
blit_colorkey
blit_alpha
blit_scale_nearest
blit_flip

draw_tile
draw_tilemap

rgb888_to_rgb565
rgb565_to_rgb888

memcpy_gpu
memset_gpu
```

---

# 14. Kernels de demos y cómputo

También son buenos candidatos:

```text
mandelbrot
julia
noise
plasma
palette_effect
image_convolve_3x3

particle_update
particle_render

sprite_transform
```

Estos kernels son interesantes porque muestran usos distintos de SIMT.

---

# 15. Ejemplo: clear como kernel

No existe una instrucción física `CLEAR`.

Se lanza un kernel sobre todos los píxeles.

Ejemplo simplificado:

```asm
; Ra = 0x00RRGGBB

PACK565 rColor, Ra

; calcular dirección del pixel asignado a este thread
...

ST16 [rAddr], rColor
```

Con 64 lanes trabajando concurrentemente.

---

# 16. Texto como overlay

El modo texto no tiene por qué sustituir al modo gráfico.

Puede funcionar como una capa hardware independiente.

```text
Framebuffer gráfico ───────┐
                           │
Text RAM + Font ROM ───────┼── Compositor ── HDMI
                           │
Sprites ───────────────────┘
```

Así se puede mostrar texto encima de:

- RGB565;
- INDEX8;
- XRGB8888;
- MONO.

Aplicaciones:

- consola;
- depuración;
- FPS;
- estadísticas;
- registros;
- HUD;
- mensajes de error.

---

# 17. Memoria de texto

Con fuente 8×16 y salida 640×480:

```text
80 columnas × 30 filas
```

Si cada celda usa:

```text
1 byte carácter
1 byte atributos
```

la memoria sería:

```text
80 × 30 × 2 = 4800 bytes
```

≈ 4,7 KiB.

La ROM de fuente también es muy pequeña.

---

# 18. Atributos de texto

Una opción sencilla sería:

```text
FG[3:0]
BG[3:0]
```

para:

```text
16 colores foreground
16 colores background
```

También se pueden reservar bits para:

```text
transparent background
blink
invert
enable
```

Estas extensiones son opcionales.

---

# 19. Capa hardware de sprites

Los sprites no deberían ser un modo de vídeo exclusivo.

Encajan mejor como **overlay hardware**.

```text
Framebuffer
    │
Sprites
    │
Texto
    │
    ▼
Compositor
    │
    ▼
HDMI
```

Cada sprite podría tener una entrada de descriptor.

Ejemplo conceptual:

```text
x
y
width
height
base_addr
format
palette
flags
```

Flags posibles:

```text
enable
flip_x
flip_y
priority
transparent_color
```

Una propuesta razonable sería soportar un número limitado de sprites hardware, por ejemplo 32 o 64, aunque esta cifra debe considerarse una decisión de diseño y no un requisito cerrado.

---

# 20. Kernels relacionados con sprites

Aunque exista una capa hardware opcional de sprites, también son útiles kernels software:

```text
sprite_transform
sprite_blit
sprite_blit_colorkey
sprite_scale
sprite_flip
```

Esto permite comparar:

- sprites hardware;
- sprites renderizados a framebuffer.

---

# 21. Doble buffering

Sí: debe formar parte del diseño desde el principio.

Hay dos framebuffers:

```text
Front Buffer
Back Buffer
```

Durante un frame:

```text
HDMI -> lee Front Buffer
GPU  -> escribe Back Buffer
```

Al llegar VBlank:

```text
Front <-> Back
```

En el siguiente frame:

```text
HDMI -> lee antiguo Back
GPU  -> escribe antiguo Front
```

---

# 22. Swap seguro en VBlank

Se pueden exponer registros:

```text
FB_FRONT
FB_BACK
SWAP_REQUEST
```

El software solicita:

```text
SWAP_REQUEST = 1
```

pero el hardware espera a VBlank para intercambiar.

Así se evita tearing.

```text
frame N

HDMI: buffer A
GPU : buffer B

          VBLANK
             │
             ▼

frame N+1

HDMI: buffer B
GPU : buffer A
```

---

# 23. Triple buffering

No es imprescindible, pero con 32 MiB de SDRAM sería posible.

Ventajas:

- GPU no tiene que esperar al scanout;
- puede haber un buffer mostrado, uno terminado y otro en construcción.

Desventaja:

- mayor complejidad;
- menos valor educativo inicialmente.

Para la primera versión se recomienda doble buffering.

---

# 24. Pipeline 3D propuesto

La idea es mantener el máximo posible programable, pero acelerar en hardware las etapas donde el coste o la complejidad lo justifican.

Pipeline:

```text
Vértices
   │
   ▼
SIMT Vertex Kernel
   │
   ▼
Triangle Setup / Rasterizer HW
   │
   ▼
Fragment Warps
   │
   ├── arithmetic
   ├── texture fetch
   ├── PACK565
   │
   ▼
Depth Test / Write
   │
   ▼
Back Buffer
```

---

# 25. Vertex kernel

El vertex shader vive como kernel SIMT.

Operaciones típicas:

```text
transformación de posición
transformación de normales
lighting sencillo
cálculo de UV
perspectiva
```

Kernels:

```text
vertex_transform
normal_transform
vertex_lighting
```

No se propone inicialmente una unidad fija de matrices.

---

# 26. Rasterizador hardware

Esta sí es una unidad que merece la pena implementar físicamente.

Entrada:

```text
(x0, y0, z0)
(x1, y1, z1)
(x2, y2, z2)
```

Salida:

```text
fragmentos cubiertos por el triángulo
```

Puede generar:

```text
x
y
z interpolado
u
v
otros atributos
```

El rasterizador evita usar lanes para:

- edge walking;
- cobertura;
- setup de triángulo;
- generación de fragmentos.

---

# 27. Triangle setup

Puede calcular:

- bounding box;
- ecuaciones de borde;
- deltas;
- interpolantes;
- orientación del triángulo.

Es una buena candidata a hardware porque se ejecuta para cada triángulo y alimenta directamente al rasterizador.

---

# 28. Fragment kernel

Los fragmentos generados por el rasterizador se envían a warps.

Cada lane puede procesar un fragmento.

Ejemplo:

```text
lane 0 -> fragmento 0
lane 1 -> fragmento 1
...
lane 7 -> fragmento 7
```

El kernel puede realizar:

```text
texturing
lighting
fog
color
procedural effects
alpha
PACK565
```

---

# 29. Texture fetch

Puede existir una operación o unidad simple de textura.

Ejemplo conceptual:

```asm
TEX Rd, Ru, Rv
```

Versión inicial:

```text
nearest neighbour
```

Se dejarían para versiones futuras:

```text
bilinear
trilinear
mipmapping
anisotropic filtering
```

---

# 30. Z-buffer / depth buffer

Se recomienda hardware de depth test.

Operación conceptual:

```text
if new_z < old_z:
    depth[x,y] = new_z
    framebuffer[x,y] = color
```

La unidad de depth puede:

- leer Z;
- comparar;
- actualizar;
- permitir o bloquear escritura de color.

Esto evita repetir mucho trabajo trivial en los shaders.

---

# 31. Kernels 3D

Lista inicial:

```text
vertex_transform
vertex_lighting
normal_transform

triangle_setup
triangle_raster

fragment_shader
texture_sample

depth_clear
depth_test_write
```

En una arquitectura donde raster y depth sean hardware, algunos de estos nombres representarían servicios del pipeline y no kernels puros.

---

# 32. Qué pondría en hardware físico para 3D

## Sí

```text
Triangle setup
Triangle rasterizer
Depth test/write
Texture fetch básico
```

Opcionalmente:

```text
interpoladores
perspective-correct interpolation
```

---

# 33. Qué dejaría inicialmente en software

```text
vertex transform
lighting
normal transform
materiales
fog
procedural shading
conversiones de color
sprites framebuffer
tile rendering
postprocesado
```

---

# 34. Qué NO implementaría al principio

Para mantener el proyecto educativo y manejable:

```text
clipping complejo totalmente hardware
fixed-function lighting
unidad de matrices dedicada
bilinear/trilinear
mipmapping
anisotropic filtering
MSAA
blending complejo
geometry shaders
tessellation
```

Todas estas funciones pueden estudiarse más adelante.

---

# 35. Interacción entre GPU y scanout

La GPU escribe en SDRAM.

El scanout lee una región de SDRAM independientemente.

```text
                  SDRAM
                    │
       ┌────────────┴────────────┐
       │                         │
       ▼                         ▼
GPU writes                  scanout reads
Back Buffer                 Front Buffer
       │                         │
       └────────────┬────────────┘
                    │
                  VBlank
                    │
                    ▼
                   swap
```

GPU y HDMI pueden funcionar en paralelo.

---

# 36. Arbitraje SDRAM

La SDRAM debe atender, como mínimo:

```text
scanout
GPU loads
GPU stores
CPU
texture reads
depth reads/writes
sprite fetches
```

Conviene dar al scanout prioridad suficiente para evitar underflow.

Una política conceptual sería:

```text
1. scanout urgente
2. refresh SDRAM
3. GPU burst
4. CPU
5. prefetch opcional
```

La implementación concreta dependerá del controlador de memoria.

---

# 37. Importancia del acceso secuencial

Los kernels deben intentar producir accesos contiguos.

Bueno:

```text
lane 0 -> pixel N
lane 1 -> pixel N+1
lane 2 -> pixel N+2
...
lane 7 -> pixel N+7
```

Malo:

```text
lane 0 -> dirección aleatoria
lane 1 -> dirección aleatoria
...
```

La unidad de memoria debe intentar coalescer accesos.

---

# 38. Ejemplo de kernel RGB565

Pseudocódigo:

```c
x = global_thread_x;
y = global_thread_y;

r = x;
g = y;
b = x ^ y;

rgb888 = (r << 16) | (g << 8) | b;

rgb565 = PACK565(rgb888);

addr = framebuffer + (y * pitch) + x * 2;

store16(addr, rgb565);
```

---

# 39. Ejemplo de kernel INDEX8

```c
x = global_thread_x;
y = global_thread_y;

iterations = mandelbrot(x, y);

index = iterations & 255;

addr = framebuffer + y * pitch + x;

store8(addr, index);
```

El scanout convierte posteriormente el índice mediante la paleta.

---

# 40. Ejemplo MONO

Cada warp genera 8 píxeles.

```c
predicate = value > threshold;

byte mask = ballot(predicate);

if (lane_id == 0)
    store8(addr, mask);
```

Esto aprovecha directamente la estructura de 8 lanes.

---

# 41. Organización conceptual final

```text
                         CPU
                          │
                    dispatch kernel
                          │
                          ▼
              ┌─────────────────────┐
              │     GPU SIMT        │
              │                     │
              │  8 warps × 8 lanes │
              │                     │
              │  ALU / LD / ST      │
              │  PACK565            │
              │  BALLOT             │
              │  SHUFFLE            │
              └──────────┬──────────┘
                         │
                         ▼
                  Memory Coalescer
                         │
                         ▼
                       SDRAM
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
   Front Buffer      Back Buffer         Assets
       │                                    │
       │                               Textures
       │                               Sprites
       │                               Fonts
       ▼
  Line Buffer
       │
       ▼
   Pixel Decode
   / Palette
       │
       ▼
 Sprite Overlay
       │
       ▼
  Text Overlay
       │
       ▼
      HDMI
```

Para 3D:

```text
geometry
   │
   ▼
vertex kernel
   │
   ▼
triangle setup HW
   │
   ▼
rasterizer HW
   │
   ▼
fragment warps
   │
   ├── TEX
   ├── ALU
   ├── PACK565
   │
   ▼
depth test HW
   │
   ▼
back buffer
```

---

# 42. Resumen de decisiones recomendadas

## Arquitectura

- 8 warps × 8 lanes.
- ISA SIMT pequeña.
- SDRAM de 32 MiB compartida.
- coalescing de memoria.
- bursts SDRAM.
- line buffer para HDMI.

## Modos

- TEXT 80×30 overlay.
- RGB565 320×240.
- INDEX8 320×240.
- XRGB8888 320×240.
- INDEX8 640×480.
- RGB565 640×480.
- MONO 640×480.

## ISA gráfica específica

Mantenerla pequeña:

```text
PACK565
UNPACK565
BALLOT
SHUFFLE
BROADCAST
ANY
ALL
```

más:

```text
LD8 / LD16 / LD32
ST8 / ST16 / ST32
```

y la ISA aritmética normal.

## Software

Implementar como kernels:

```text
clear
fill_rect
line
circle
blit
blit_colorkey
blit_scale
copy_rect
tilemap
fractales
particles
image processing
```

## Scanout

- framebuffer principal;
- overlay opcional de sprites;
- overlay de texto;
- HDMI fijo;
- scaler para modos 320×240.

## Buffering

- Front Buffer: leído por HDMI.
- Back Buffer: escrito por GPU.
- swap únicamente en VBlank.

## 3D

Hardware recomendado:

```text
triangle setup
rasterizer
depth test/write
texture fetch nearest
```

Software/programable:

```text
vertex shader
fragment shader
lighting
materials
efectos
```

---

# 43. Idea central del diseño

La GPU no intenta ofrecer muchas instrucciones gráficas de alto nivel.

La filosofía es:

```text
hardware pequeño + ISA general + kernels programables
```

Las únicas aceleraciones específicas se reservan para situaciones donde el hardware ofrece una ventaja clara:

```text
PACK565
operaciones entre lanes
rasterización
depth
texture fetch
scanout
sprites/text overlay
```

Esto mantiene la GPU suficientemente simple para ser educativa, pero lo bastante flexible para ejecutar:

- gráficos 2D;
- juegos;
- tilemaps;
- sprites;
- fractales;
- procesamiento de imagen;
- partículas;
- demos SIMT;
- gráficos 3D básicos.
