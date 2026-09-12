Sí. Yo lo montaría como una escalera de hitos donde **cada fase deja algo visible por HDMI**, y donde cada bloque nuevo tenga una prueba muy pequeña que demuestre que funciona antes de pasar al siguiente.

Me parece buena idea que la **fase 0 sea la LSU**, porque si la memoria y el arbitraje quedan razonablemente limpios, todo lo demás se apoya sobre una base mucho más estable.

1. **Fase 0 — Optimizar LSU y dejar memoria fiable**
   Objetivo: arreglar el `pick`, registrar arbitraje si hace falta, validar loads/stores de las 8 lanes y coalescing básico. Aún no necesitas HDMI para la prueba principal, pero si ya está disponible puedes usarlo como “osciloscopio visual”.
   
   Prueba: CPU rellena un framebuffer con un patrón simple en SDRAM y la GPU hace copias o modificaciones sencillas sobre bloques. Por ejemplo, invertir colores de una región o copiar una franja. Resultado visible: una pantalla con bloques que cambian correctamente, sin píxeles corruptos.

   Éxito de la fase: `LD/ST` fiables, arbitraje de memoria estable y comportamiento conocido cuando varios warps quieren memoria.

2. **Fase 1 — HDMI + framebuffer mínimo**
   Objetivo: que el subsistema de vídeo funcione sin depender aún de la GPU. Yo haría primero `RGB565 320×240 → scaler 2× → HDMI 640×480`.

   Hardware mínimo:
   framebuffer base address, DMA/scanout de SDRAM a line buffer y salida HDMI. Sin shaders, sprites, texto ni 3D.

   Prueba: la CPU escribe directamente una imagen en SDRAM: barras de color, checkerboard, gradiente RGB565, etc.

   Resultado visible: imagen estable. Esta fase valida SDRAM → scanout → scaler → HDMI.

3. **Fase 2 — Front/back framebuffer + VBlank swap**
   Esta sería una de las primeras extensiones de vídeo, porque luego absolutamente todos los demos pueden beneficiarse de ella.

   Registros mínimos:

   ```text
   FB_FRONT
   FB_BACK
   SWAP_REQUEST
   VBLANK
   ```

   La CPU dibuja alternativamente dos imágenes y solicita swap.

   Prueba: animación muy simple, como un cuadrado que se mueve horizontalmente. Sin VBlank swap deberías poder provocar tearing; con swap sincronizado debería desaparecer.

   Esta prueba es especialmente buena porque valida visualmente que el mecanismo funciona.

## Fase 2.5 — Soporte Burst y accesos sub-word en el controlador SDRAM

### Objetivo

Extender el controlador SDRAM para soportar transferencias **burst**, permitiendo leer o escribir varias palabras consecutivas mediante una única petición lógica.

Además, la interfaz de memoria deberá diseñarse desde esta fase teniendo en cuenta que los futuros clientes, especialmente la GPU, necesitarán accesos de:

- 8 bits
- 16 bits
- 32 bits

El objetivo no es que el protocolo físico SDRAM tenga operaciones específicas `LD8`, `LD16` o `LD32`, sino proporcionar una interfaz suficientemente general para soportarlas posteriormente sin tener que rediseñar el subsistema de memoria.

Esta fase se realiza después de disponer de HDMI, framebuffer y double buffering funcionales. El sistema de vídeo existente servirá como banco de pruebas para verificar el nuevo comportamiento del controlador.

El soporte burst será utilizado posteriormente por:

- Scanout HDMI.
- LSU de la GPU.
- Accesos coalesced de las lanes.
- Framebuffer.
- Z-buffer.
- Lecturas de texturas.
- Cargas de vértices.
- Operaciones de copia y blit.

---

### Ancho natural del controlador

El controlador trabajará internamente con un **ancho natural de transferencia**, por ejemplo 32 bits.

Conceptualmente:

```text
              32 bits
        ┌─────────────────┐
addr →  │ SDRAM controller│
        └─────────────────┘
              │
              ▼
        [31........0]
```

Las transferencias burst estarán expresadas principalmente como secuencias de estas palabras naturales.

Por ejemplo:

```text
READ BURST
address = 0x00100000
length  = 4 words
```

produce:

```text
0x00100000 → word 0
0x00100004 → word 1
0x00100008 → word 2
0x0010000C → word 3
```

El ancho exacto utilizado dependerá del ancho interno definitivo del controlador, pero los clientes no deberán depender directamente de los detalles del protocolo físico SDRAM.

---

### Interfaz de petición

Una posible interfaz será:

```text
req_valid
req_ready

req_write
req_addr
req_len

req_wdata
req_wmask
```

y para las respuestas de lectura:

```text
rsp_valid
rsp_data
rsp_last
```

`req_len` indica la cantidad de palabras naturales que forman la transferencia.

Por ejemplo:

```text
req_valid = 1
req_write = 0
req_addr  = 0x00100000
req_len   = 8
```

solicita ocho palabras consecutivas.

El controlador responderá aproximadamente:

```text
rsp_valid   rsp_data     rsp_last
    1        word 0         0
    1        word 1         0
    1        word 2         0
    ...
    1        word 7         1
```

Idealmente, una vez iniciada la transferencia, las palabras podrán entregarse consecutivamente siempre que el funcionamiento de la SDRAM lo permita.

---

### Petición lógica frente a burst físico

El tamaño solicitado por un cliente no tiene por qué corresponder exactamente con un único burst físico de SDRAM.

Por ejemplo, un cliente podría solicitar:

```text
READ 128 bytes
```

y el controlador podría resolverlo internamente mediante:

```text
burst 0
burst 1
burst 2
burst 3
```

El controlador será responsable de dividir las transferencias cuando sea necesario por:

- Tamaño máximo de burst.
- Límites de fila.
- Cambios de banco.
- Alineamiento.
- Restricciones propias de la SDRAM.

De esta forma, los clientes solicitan **bloques de memoria consecutiva**, mientras que el controlador decide cómo ejecutar eficientemente esas transferencias sobre la SDRAM física.

---

## Accesos de 8, 16 y 32 bits

Aunque el controlador trabaje internamente con palabras completas, la arquitectura deberá soportar accesos sub-word.

La GPU podrá disponer posteriormente de instrucciones:

```text
LD8
LD16
LD32

ST8
ST16
ST32
```

sin necesidad de modificar el protocolo físico SDRAM.

La adaptación entre estos accesos y las palabras naturales del controlador se realizará mediante selección de bytes y máscaras de escritura.

---

### Lecturas sub-word

Para las lecturas, el controlador puede obtener una palabra natural completa.

Por ejemplo:

```text
          31                        0
         ┌──────┬──────┬──────┬──────┐
word  →  │  B3  │  B2  │  B1  │  B0  │
         └──────┴──────┴──────┴──────┘
```

La LSU o el cliente correspondiente seleccionará posteriormente el byte o halfword solicitado.

Por ejemplo:

```text
LD8 addr+0  → B0
LD8 addr+1  → B1
LD8 addr+2  → B2
LD8 addr+3  → B3

LD16 addr+0 → B1:B0
LD16 addr+2 → B3:B2

LD32 addr+0 → B3:B2:B1:B0
```

Por tanto, no es necesario disponer de un tipo especial de burst de 8 o 16 bits.

El controlador puede seguir realizando transferencias eficientes utilizando su ancho natural.

---

### Escrituras sub-word

Las escrituras necesitan adicionalmente una máscara por byte para evitar modificar los bytes vecinos.

Por ejemplo, para un bus natural de 32 bits:

```text
wdata[31:0]
wmask[3:0]
```

Cada bit de `wmask` indica qué byte de la palabra debe escribirse.

Ejemplos:

```text
ST8 addr+0  → wmask = 0001
ST8 addr+1  → wmask = 0010
ST8 addr+2  → wmask = 0100
ST8 addr+3  → wmask = 1000

ST16 addr+0 → wmask = 0011
ST16 addr+2 → wmask = 1100

ST32 addr+0 → wmask = 1111
```

Esto permitirá implementar posteriormente `ST8`, `ST16` y `ST32` sin realizar innecesariamente operaciones read-modify-write.

La máscara deberá trasladarse a los byte enables o señales de máscara proporcionadas por la SDRAM cuando sea posible.

---

### Accesos no alineados

En una primera versión se recomienda exigir alineamiento natural:

```text
LD8/ST8   → cualquier dirección

LD16/ST16 → dirección múltiplo de 2

LD32/ST32 → dirección múltiplo de 4
```

Esto simplifica considerablemente la LSU, el coalescer y el controlador.

Un acceso de 16 o 32 bits que cruce el límite de una palabra natural requeriría dos accesos de memoria y lógica adicional para combinar los resultados.

El soporte para accesos no alineados podrá añadirse posteriormente si existe una necesidad real.

---

## Integración con el scanout HDMI

El primer consumidor importante del mecanismo burst será el scanout.

En lugar de solicitar individualmente cada píxel o palabra:

```text
Framebuffer
    ↓
lectura individual
    ↓
espera
    ↓
siguiente lectura
```

el scanout solicitará bloques consecutivos:

```text
Framebuffer SDRAM
        ↓
    burst read
        ↓
┌─────────────────┐
│ Video FIFO /    │
│ Line Buffer     │
└────────┬────────┘
         ↓
      Scanout
         ↓
        HDMI
```

El FIFO desacopla la latencia variable de la SDRAM del ritmo fijo requerido por la salida de vídeo.

Cuando su ocupación caiga por debajo de un determinado umbral, el scanout solicitará otro bloque antes de que el FIFO quede vacío.

Una línea completa de vídeo puede estar formada por múltiples bursts.

Por ejemplo, una línea RGB565 de 320 píxeles ocupa:

```text
320 × 2 bytes = 640 bytes
```

pero esos 640 bytes no tienen por qué corresponder a una única operación física SDRAM.

---

## Preparación para el coalescing de la GPU

Aunque la GPU todavía no participe en la generación del framebuffer durante esta fase, la interfaz deberá permitir que posteriormente la LSU agrupe accesos realizados por las ocho lanes.

La separación será:

```text
GPU lanes
    ↓
LSU
    ↓
Coalescer
    ↓
petición de memoria
    ↓
Controlador SDRAM
    ↓
SDRAM
```

El **coalescer** será responsable de detectar accesos compatibles y agruparlos.

El **controlador SDRAM** será responsable de ejecutar eficientemente las transferencias resultantes.

---

### Ejemplo: INDEX8

En un framebuffer INDEX8, ocho lanes podrían escribir ocho píxeles consecutivos:

```text
lane 0 → addr + 0
lane 1 → addr + 1
lane 2 → addr + 2
lane 3 → addr + 3
lane 4 → addr + 4
lane 5 → addr + 5
lane 6 → addr + 6
lane 7 → addr + 7
```

Cada lane realiza conceptualmente un acceso de 8 bits:

```text
8 lanes × 8 bits = 8 bytes
```

Con un ancho natural de 32 bits, el coalescer puede convertirlo en:

```text
word 0 → pixels 0,1,2,3
word 1 → pixels 4,5,6,7
```

Es decir, solo dos palabras consecutivas de memoria.

Para lectura, los datos pueden repartirse posteriormente:

```text
word 0
 ├─ byte 0 → lane 0
 ├─ byte 1 → lane 1
 ├─ byte 2 → lane 2
 └─ byte 3 → lane 3

word 1
 ├─ byte 0 → lane 4
 ├─ byte 1 → lane 5
 ├─ byte 2 → lane 6
 └─ byte 3 → lane 7
```

---

### Ejemplo: RGB565

Para RGB565:

```text
8 lanes × 16 bits = 128 bits = 16 bytes
```

Ocho píxeles consecutivos pueden convertirse en:

```text
4 × words de 32 bits
```

en lugar de ocho transacciones independientes.

---

### Ejemplo: XRGB8888

Para XRGB8888:

```text
8 lanes × 32 bits = 256 bits = 32 bytes
```

que corresponden naturalmente a:

```text
8 × words de 32 bits
```

con direcciones consecutivas.

Esto demuestra por qué la combinación de:

```text
LD8 / LD16 / LD32
        ↓
LSU + Coalescer
        ↓
transferencias alineadas
        ↓
SDRAM burst
```

será importante para el rendimiento futuro de la GPU.

---

## Prueba de la fase

Se reutilizará inicialmente el mismo demo de double buffering de la fase anterior.

La CPU continuará generando la animación en el back buffer y solicitando el swap durante VBlank.

La diferencia será que el scanout del front buffer utilizará ahora lecturas burst:

```text
CPU
 ↓
BACK BUFFER
 ↓
VBlank swap
 ↓
FRONT BUFFER
 ↓
SDRAM burst reads
 ↓
Video FIFO / Line Buffer
 ↓
HDMI
```

El resultado visual deberá ser **idéntico al obtenido antes de introducir burst**.

---

### Pruebas adicionales de accesos sub-word

Además del test HDMI, se añadirán pruebas específicas de memoria para comprobar las máscaras y selección de bytes.

Por ejemplo, partiendo de:

```text
word = 0x11223344
```

realizar diferentes escrituras de byte y halfword y comprobar que los bytes no seleccionados permanecen intactos.

También deberán comprobarse:

```text
LD8
LD16
LD32

ST8
ST16
ST32
```

sobre diferentes posiciones válidas dentro de las palabras.

Estas pruebas pueden realizarse inicialmente desde CPU o mediante un testbench, antes de que la LSU de la GPU utilice esta funcionalidad.

---

### Contadores de diagnóstico

Opcionalmente se pueden añadir contadores hardware:

```text
memory_requests
burst_requests
words_transferred

read_requests
write_requests

video_fifo_underflows
stall_cycles
```

Posteriormente podrán añadirse contadores específicos de GPU:

```text
coalesced_requests
uncoalesced_requests
bytes_read
bytes_written
```

Estos contadores facilitarán la evaluación del comportamiento real del subsistema de memoria.

---

## Criterio de finalización

La fase se considera completada cuando el sistema puede mantener de forma estable:

```text
CPU → escritura BACK framebuffer
             +
SDRAM → burst read FRONT framebuffer → HDMI
```

mientras realiza swaps sincronizados con VBlank, sin corrupción ni underflows.

Además:

- Las transferencias burst funcionan correctamente.
- Las lecturas y escrituras de palabras completas funcionan.
- Los accesos de 8 y 16 bits pueden representarse correctamente mediante selección y máscaras.
- Las escrituras parciales no modifican bytes vecinos.
- El controlador puede atender transferencias consecutivas sin depender del formato gráfico.
- La interfaz queda preparada para recibir posteriormente peticiones coalesced de la GPU.

A partir de este punto, el subsistema de memoria queda preparado para la integración CPU → GPU y, posteriormente, para framebuffer, Z-buffer, texturas y otros accesos de alto ancho de banda.

4. **Fase 3 — CPU → GPU: command/dispatch mínimo**
   Antes de scheduler complejo, definiría la integración básica CPU/GPU.

   Algo conceptualmente así:

   ```text
   CPU
    |
    | kernel_id
    | grid size
    | argumentos
    v
   GPU dispatch registers / command FIFO
   ```

   Al principio incluso puedes tener **un único kernel en ejecución**.

   La CPU escribe:

   ```text
   KERNEL_ADDR
   ARG0
   ARG1
   WORK_COUNT
   START
   ```

   y espera `DONE`.

   Prueba HDMI: kernel `clear`.

   La CPU solicita:

   ```text
   clear(backbuffer, BLUE)
   swap()
   clear(backbuffer, RED)
   swap()
   ...
   ```

   Aquí tienes el primer programa donde **la GPU realmente genera la imagen**.

5. **Fase 4 — Scheduler mínimo de warps**
   Aquí metería el scheduler que ya estamos discutiendo.

   En V1 no necesitas todavía las tres work queues. Puedes tener una sola `Compute Queue` y los 8 slots de warp.

   Estados:

   ```text
   FREE
   READY
   WAIT_MEM
   DONE
   ```

   Round-robin entre warps `READY`.

   Prueba: Mandelbrot o plasma.

   Para mí, **Mandelbrot sería un demo excelente en esta fase**, porque:

   - usa bastante ALU;
   - cada píxel es independiente;
   - usa los 8 lanes de forma natural;
   - apenas requiere infraestructura gráfica;
   - el resultado es visualmente obvio.

   Ya tendrías algo que empieza a parecer una GPU de verdad.

6. **Fase 5 — Kernel library 2D básica**
   Antes de entrar en 3D haría unas pocas operaciones por software:

   ```text
   clear
   fill_rect
   draw_line
   blit
   copy_rect
   ```

   No como instrucciones ISA, sino como kernels.

   Prueba HDMI: una escena 2D animada con varios rectángulos, líneas y bitmaps.

   Esto valida dispatch, memoria, scheduler, kernels y framebuffer a la vez.

7. **Fase 6 — Text overlay hardware**
   Este bloque es bastante independiente y relativamente barato.

   Pipeline:

   ```text
   framebuffer
        |
        +---- text overlay
        |
       HDMI
   ```

   Char RAM + attribute RAM + font ROM.

   Prueba: dejar Mandelbrot o una animación ejecutándose y superponer:

   ```text
   GPU DEMO
   FPS: 53
   WARPS: 8
   FRAME: 1234
   ```

   Esta fase es extremadamente útil después para **debug** del resto de la GPU.

   Yo probablemente implementaría texto antes que sprites precisamente por eso.

8. **Fase 7 — Sprite overlay**
   Añades descriptors simples:

   ```text
   X
   Y
   WIDTH
   HEIGHT
   BASE_ADDR
   FORMAT
   TRANSPARENT_COLOR
   ENABLE
   ```

   Y haces composición:

   ```text
   framebuffer
        ↓
     sprites
        ↓
      text
        ↓
      HDMI
   ```

   Prueba: mover 8–16 sprites por encima del Mandelbrot o de un fondo generado por la GPU.

   Esto valida composición y lecturas de imagen independientes del framebuffer.

9. **Fase 8 — Work queues reales: Compute + Vertex + Fragment**
   Aquí haría el salto arquitectónico importante.

   Antes de meter el rasterizador, puedes implementar ya:

   ```text
   Compute Queue
   Vertex Queue
   Fragment Queue
   ```

   aunque inicialmente Vertex y Fragment tengan pruebas sintéticas.

   El work scheduler asigna slots libres dinámicamente.

   Prueba: lanzar simultáneamente un kernel compute y pequeños jobs marcados como vertex/fragment ficticios.

   Visualmente podrías seguir renderizando Mandelbrot mientras otro conjunto de warps actualiza una segunda región del framebuffer.

   La prueba importante aquí no es tanto la imagen sino verificar:

   ```text
   W0 Compute
   W1 Compute
   W2 Vertex
   W3 Fragment
   ...
   ```

   y que ninguno monopolice todos los slots.

   El text overlay puede mostrar esta información, lo cual sería genial para debug.

10. **Fase 9 — Vertex shader pipeline mínimo**
    Todavía sin triángulos rasterizados.

    La CPU envía vértices:

    ```text
    x y z
    ```

    y el vertex shader aplica una transformación MVP.

    El resultado se escribe temporalmente en memoria o en una FIFO inspeccionable.

    Prueba HDMI: visualizador de vértices.

    Tomas los vértices transformados y dibujas simplemente un punto o pequeño cuadrado en cada `(x,y)`.

    Por ejemplo, un cubo de 8 puntos girando:

    ```text
      *------*
     /|     /|
    *------* |
    | *----|-*
    |/     |/
    *------*
    ```

    Aún no hay triángulos. Solo validas transformación 3D → pantalla.

11. **Fase 10 — Triangle Setup HW**
    Ahora añades:

    ```text
    3 vértices
        ↓
    bounding box
    edge equations
    winding/culling
    attribute gradients
    ```

    Pero todavía puedes evitar el rasterizador completo.

    Prueba: mandar un triángulo y visualizar su **bounding box**.

    Eso es muy útil porque algo como:

    ```text
        /\
       /  \
      /____\
    +------+
    | bbox |
    +------+
    ```

    permite detectar enseguida errores de coordenadas, clipping o transformación.

    Otra prueba es dibujar los tres edges obtenidos por Triangle Setup.

12. **Fase 11 — Rasterizer sin fragment shader**
    Este es el primer gran momento 3D.

    El rasterizador evalúa las edge equations y genera:

    ```text
    x
    y
    coverage_mask[7:0]
    ```

    en grupos de 8 píxeles.

    Pero todavía no uses fragment shader.

    Haz que el rasterizador escriba directamente un color constante:

    ```text
    triangle -> RED
    ```

    Prueba: triángulos sólidos girando.

    Esta separación es importante: si el triángulo sale mal, sabes que el problema está en setup/raster, no en el shader.

13. **Fase 12 — Fragment Queue + Fragment Shader**
    Ahora conectas:

    ```text
    rasterizer
        ↓
    Fragment Queue
        ↓
    warp
        ↓
    fragment shader
        ↓
    framebuffer
    ```

    El rasterizador genera un grupo de hasta 8 fragmentos y su `active_mask`.

    El shader más sencillo puede ser:

    ```text
    color = interpolated_vertex_color
    ```

    Prueba: triángulo RGB con Gouraud shading.

    Cada vértice:

    ```text
    V0 = rojo
    V1 = verde
    V2 = azul
    ```

    y debes ver el gradiente interpolado.

    Este demo valida a la vez:

    - rasterización;
    - interpolación;
    - fragment queue;
    - máscaras SIMT;
    - fragment shader.

14. **Fase 13 — Z-buffer**
    Añades depth interpolation y:

    ```text
    read Z
    compare
    write Z
    write color
    ```

    Al principio incluso puede ser late-Z.

    Prueba: dos triángulos que se cruzan y cambian de orden según rotan.

    Sin Z verás uno encima del otro según orden de dibujo.

    Con Z, la geometría correcta gana píxel a píxel.

    Es una prueba visual espectacularmente buena para detectar bugs de profundidad.

15. **Fase 14 — Early-Z**
    Una vez que el Z básico funciona, mueves el test antes del fragment shader cuando sea posible.

    La imagen no debería cambiar.

    La prueba esta vez es de rendimiento: renderizar muchos triángulos detrás de un objeto grande.

    Debes obtener:

    ```text
    mismo frame
    menos fragment shaders ejecutados
    ```

    Aquí el text overlay puede mostrar:

    ```text
    fragments generated: 150000
    fragments shaded:     62000
    early-z killed:       88000
    ```

16. **Fase 15 — Texture unit nearest-neighbour**
    Añades inicialmente solo:

    ```text
    TEX u,v
    ```

    con:

    ```text
    addr = base + v*pitch + u*bpp
    ```

    Sin bilinear, mipmapping ni nada más.

    Prueba: un único quad formado por dos triángulos con una textura checkerboard.

    Luego un cubo texturizado.

    Este probablemente será el primer demo que visualmente parezca “3D clásico”.

17. **Fase 16 — Perspective-correct interpolation**
    Hasta este punto puedes utilizar temporalmente interpolación affine.

    Luego cambias:

    ```text
    u
    v
    ```

    por:

    ```text
    u/w
    v/w
    1/w
    ```

    y reconstruyes U,V en el fragment.

    Prueba ideal: un quad inclinado con un patrón checkerboard.

    Con affine tendrás deformación evidente.

    Con perspective correct debería verse correctamente.

    Es una prueba A/B perfecta.

18. **Fase 17 — Texture cache pequeña**
    La imagen no cambia.

    Aquí el objetivo es aumentar rendimiento y reducir tráfico SDRAM.

    Prueba: cubo o suelo texturizado ocupando gran parte de pantalla.

    Overlay:

    ```text
    TEX requests
    cache hits
    cache misses
    ```

    Así puedes medir directamente si está funcionando.

19. **Fase 18 — Demo 3D completo**
    En este punto ya puedes juntar todo:

    ```text
    CPU
     ↓
    command/dispatch
     ↓
    Vertex Queue
     ↓
    Vertex Shader
     ↓
    Triangle Setup
     ↓
    Rasterizer
     ↓
    Fragment Queue
     ↓
    Early Z
     ↓
    Fragment Shader + TEX
     ↓
    framebuffer
     ↓
    sprites
     ↓
    text
     ↓
    HDMI
    ```

    Y el demo podría ser un escenario sencillo:

    - cubos texturizados;
    - cámara rotando;
    - Z-buffer;
    - HUD mediante text overlay;
    - sprite como cursor/logo;
    - double buffering.

    Para mí, esa sería la **v1 de la GPU**.

Hay una decisión de orden que sí haría deliberadamente: **texto antes de 3D completo**. No porque sea prioritario gráficamente, sino porque se convierte en tu consola de depuración. Poder tener en HDMI algo como:

```text
FPS 47
VERTEX Q  3
FRAG Q   18
COMP Q    0

W0 FRAG READY
W1 FRAG WAIT_TEX
W2 VERT READY
W3 FREE
...
```

mientras el dibujo ocurre debajo va a ser extremadamente útil.

Y separaría el desarrollo 3D en cuatro hitos visuales muy claros:

```text
puntos 3D
   ↓
bounding boxes / edges
   ↓
triángulos sólidos
   ↓
triángulos interpolados
   ↓
triángulos con Z
   ↓
triángulos texturizados
```

Así nunca tienes la situación de “he añadido vertex shader + triangle setup + rasterizer + fragment shader + Z + texturas y la pantalla está negra, ¿qué está roto?”. Cada etapa produce una imagen comprobable.

De hecho, el **primer demo 3D que intentaría no sería un cubo**, sino exactamente esta secuencia:

```text
1 punto
→ 3 puntos
→ wireframe triangle
→ solid triangle
→ RGB triangle
→ overlapping triangles + Z
→ textured triangle
→ textured quad
→ rotating cube
```

Eso te va aislando los errores casi uno por uno.