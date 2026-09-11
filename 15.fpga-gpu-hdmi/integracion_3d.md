# Integración 3D de la GPU

Este documento continúa la descripción de la GPU y se centra en cómo integrar un pipeline 3D sobre el núcleo SIMT existente de **8 warps × 8 lanes**, manteniendo la mayor parte del procesamiento programable y añadiendo hardware fijo únicamente donde aporta una ventaja clara.

## 1. Objetivo general

La idea no es construir un pipeline 3D completamente fijo. El núcleo SIMT existente debe ejecutar los shaders y kernels, mientras que hardware especializado se encarga de convertir triángulos en grupos de fragmentos eficientes y de las operaciones muy repetitivas ligadas a memoria.

Pipeline propuesto:

```text
Vertex Queue
    |
    v
Vertex Shader / Kernel (SIMT)
    |
    v
Triangle Setup HW
    |
    v
Rasterizer HW
    |
    v
Fragment Queue (grupos de hasta 8 fragments)
    |
    v
Fragment Shader (SIMT)
    |
    +--> Texture Unit
    +--> Depth / Z
    |
    v
Back Buffer
    |
    v
Compositor (sprites/texto)
    |
    v
Scanout HDMI
```

## 2. Un único núcleo SIMT para varios tipos de trabajo

No es necesario crear ALUs separadas para vertex shaders, fragment shaders y kernels generales. Los tres tipos de trabajo utilizan el mismo núcleo de 8 lanes y esencialmente la misma ISA.

Cada warp residente lleva asociado un tipo de trabajo:

- `VERTEX`: procesa vértices y genera datos para el ensamblado/rasterizado.
- `FRAGMENT`: procesa fragmentos producidos por el rasterizador.
- `COMPUTE`: ejecuta kernels generales, incluyendo operaciones 2D.

El tipo del warp determina principalmente de dónde vienen sus entradas, dónde van sus resultados y qué prioridad puede recibir en el scheduler. No implica una ALU distinta.

Además, para esta arquitectura se considera **fragment shader y pixel shader como el mismo concepto**. Los kernels 2D como `clear`, `fill_rect`, `blit` o `mandelbrot` se consideran trabajo `COMPUTE`, aunque produzcan píxeles.

## 3. Work Queues y warps residentes

El sistema mantiene varias colas de trabajo:

```text
Vertex Queue
Fragment Queue
Compute Queue
      |
      v
 Work Scheduler
      |
      v
8 slots de warp residentes
```

Los 8 slots físicos forman un pool común. No se recomienda reservar permanentemente, por ejemplo, 2 warps para vertex, 4 para fragment y 2 para compute.

Cuando un slot queda libre, el work scheduler selecciona trabajo de alguna cola y crea un nuevo warp residente. Una distribución instantánea podría ser:

```text
W0  FRAGMENT
W1  FRAGMENT
W2  FRAGMENT
W3  FRAGMENT
W4  VERTEX
W5  VERTEX
W6  COMPUTE
W7  FRAGMENT
```

La distribución cambia dinámicamente según termina el trabajo.

En la primera versión, una vez que un warp entra como residente permanece en su slot hasta finalizar. Puede quedar bloqueado esperando memoria, textura o una barrera, pero no se hace preemption ni se guarda/restaura su contexto para sustituirlo por otro warp.

Estados mínimos recomendados:

```text
FREE
READY
RUNNING
WAIT_MEM
WAIT_TEX
WAIT_BARRIER
DONE
```

El contexto de un warp debe conservar al menos PC, registros, máscara de lanes activas, identificadores de threads/workgroup, tipo de trabajo y estado.

## 4. Dos decisiones distintas de scheduling

Conviene separar conceptualmente dos funciones.

### Work scheduler

Actúa cuando existe un slot `FREE`. Decide si el siguiente warp procede de `Vertex Queue`, `Fragment Queue` o `Compute Queue`.

Puede utilizar prioridad con fairness o weighted round-robin. Por ejemplo, el trabajo de fragmentos puede recibir prioridad para terminar el frame, pero compute no debería quedar bloqueado indefinidamente.

### Instruction scheduler

Actúa sobre los warps que ya son residentes. Selecciona un warp `READY` para ejecutar una instrucción.

Un esquema round-robin es suficiente inicialmente. Si un warp hace un `LD` o `TEX` y pasa a `WAIT_MEM`/`WAIT_TEX`, el scheduler puede ejecutar otro warp mientras llega la respuesta.

Así se utiliza el paralelismo entre warps para ocultar latencias.

## 5. Vertex stage

Los vértices pueden contener, según el formato elegido:

```text
position
color
u, v
normal
otros atributos
```

El vertex shader se ejecuta en las lanes SIMT. Entre sus tareas pueden estar:

- transformación Model/View/Projection;
- transformación de normales;
- iluminación por vértice;
- generación/modificación de coordenadas de textura;
- preparación de atributos para interpolación.

Inicialmente no es necesario un multiplicador matricial fijo dedicado. Las operaciones matriciales pueden implementarse con las ALUs/MUL existentes.

La salida de los vertex shaders se coloca en una FIFO o estructura que alimenta el ensamblado de primitivas y el Triangle Setup.

## 6. Triangle Setup en hardware

El Triangle Setup recibe tres vértices ya transformados y prepara la información necesaria para rasterizar el triángulo.

Sus tareas principales son:

1. Conversión/preparación de coordenadas de pantalla.
2. Determinación de orientación y, opcionalmente, back-face culling.
3. Cálculo del bounding box del triángulo.
4. Cálculo de las tres edge equations.
5. Preparación de los incrementos para interpolar atributos.

Una edge equation puede representarse como:

```text
E(x,y) = A*x + B*y + C
```

Se calcula una para cada lado del triángulo. El signo de las tres funciones permite decidir si una muestra está dentro o fuera.

También se preparan gradientes como:

```text
dZ/dx   dZ/dy
dU/dx   dU/dy
dV/dx   dV/dy
```

y los correspondientes a otros atributos que necesite el fragment shader.

El objetivo es hacer los cálculos relativamente costosos una vez por triángulo y permitir que el rasterizador trabaje después principalmente con sumas incrementales.

## 7. Rasterizer alineado con las 8 lanes

El rasterizador recorre el bounding box y evalúa las edge equations.

La propiedad importante es que no hace falta recalcular una multiplicación completa para cada píxel:

```text
E(x+1,y) = E(x,y) + A
E(x,y+1) = E(x,y) + B
```

Por tanto, una vez inicializado el triángulo, el recorrido puede basarse principalmente en sumadores.

La unidad natural de trabajo debe coincidir con el ancho SIMT: **8 píxeles adyacentes**.

Por ejemplo:

```text
lane 0 -> (x+0, y)
lane 1 -> (x+1, y)
lane 2 -> (x+2, y)
...
lane 7 -> (x+7, y)
```

El rasterizador evalúa los ocho candidatos y genera una máscara de cobertura:

```text
coverage_mask = 8'b11101100
```

Los bits activos corresponden a fragments realmente cubiertos por el triángulo.

El paquete enviado a la Fragment Queue puede contener conceptualmente:

```text
x_base, y
coverage_mask
Z[0..7]
U[0..7]
V[0..7]
color/otros interpolantes
primitive information
```

De esta forma, una entrada de la Fragment Queue se transforma de forma natural en un warp de fragment shader de hasta 8 lanes activas.

## 8. Fragment Queue y fragment shader

El rasterizador introduce grupos en la `Fragment Queue`. Cuando el work scheduler asigna uno a un slot libre, crea un warp `FRAGMENT`.

La máscara inicial del warp procede directamente de `coverage_mask`.

Ejemplo:

```text
Rasterizer:
mask = 11101100

        |
        v

Fragment Warp:
lane 0  inactive
lane 1  inactive
lane 2  active
lane 3  active
lane 4  inactive
lane 5  active
lane 6  active
lane 7  active
```

El fragment shader puede realizar operaciones como:

- cálculo de color;
- lectura de textura;
- iluminación;
- fog;
- efectos procedurales;
- combinación de atributos interpolados;
- conversión final a RGB565 u otro formato.

Las lanes inactivas permanecen enmascaradas.

## 9. Texture Unit

Una primera Texture Unit debe mantenerse sencilla.

Interfaz conceptual:

```text
TEX Rd, Ru, Rv
```

La unidad conoce parámetros de la textura, por ejemplo:

```text
base address
width / height
pitch
format
```

Y genera direcciones equivalentes a:

```text
address = base + v*pitch + u*bytes_per_texel
```

Para la primera versión es recomendable soportar únicamente **nearest-neighbor**.

No son necesarios inicialmente:

- bilinear filtering;
- trilinear filtering;
- anisotropic filtering;
- mipmapping complejo.

### Texture cache

Una caché pequeña puede tener un impacto importante. Las 8 lanes suelen acceder a texels próximos, por lo que muchas lecturas presentan localidad espacial.

```text
8 TEX requests
      |
      v
small texture cache
      |
   hit | miss
      v
    SDRAM
```

La Texture Unit también puede coalescer accesos cuando las lanes solicitan direcciones contiguas o cercanas.

## 10. Depth / Z-buffer

El pipeline 3D debe disponer de un depth buffer independiente del color buffer.

Para cada fragmento se compara el nuevo valor Z con el almacenado:

```text
new_Z < old_Z ?
```

Si pasa el test, el fragmento puede actualizar el depth buffer y continuar hacia la escritura de color.

La implementación puede comenzar con un Z de 16 bits para reducir almacenamiento y tráfico de memoria.

### Early-Z

Siempre que sea posible, el test de profundidad debe ejecutarse antes del fragment shader:

```text
Rasterizer
    |
    v
Early Z
    |
    +--- fail ---> descartar fragment
    |
   pass
    v
Fragment Shader
```

Esto evita gastar instrucciones de shader y accesos de textura en fragmentos que finalmente estarán ocultos.

Para la primera versión conviene mantener simples las interacciones con transparencia, `discard` y escrituras especiales de profundidad, ya que complican el uso de Early-Z.

## 11. Interpolación perspective-correct

Interpolar `u` y `v` linealmente en screen-space produce deformación visible en superficies con perspectiva.

Para corregirlo se pueden preparar en los vértices:

```text
u/w
v/w
1/w
```

El rasterizador interpola linealmente esos valores. Después, para cada fragmento:

```text
u = (u/w) / (1/w)
v = (v/w) / (1/w)
```

Esto introduce la necesidad de un recíproco/división.

No es necesario colocar un divisor grande independiente en cada lane desde la primera versión. Puede estudiarse una unidad compartida de reciprocal/división, una aproximación iterativa o una implementación con precisión limitada adecuada para gráficos.

La perspectiva correcta puede introducirse después de tener funcionando el pipeline básico con interpolación lineal.

## 12. Accesos de memoria y coalescing

La organización en grupos de 8 lanes debe aprovecharse en todas las etapas.

Ejemplos de un warp escribiendo píxeles contiguos:

```text
RGB565:     8 lanes × 16 bits = 128 bits
INDEX8:     8 lanes ×  8 bits =  64 bits
XRGB8888:   8 lanes × 32 bits = 256 bits
```

La LSU debería detectar accesos adyacentes y convertirlos en el menor número posible de transacciones/bursts SDRAM.

Esto es especialmente importante para:

- framebuffer writes;
- Z-buffer;
- texture fetch;
- kernels 2D;
- copias de memoria.

## 13. Double buffering

El renderizado 3D se realiza sobre el back buffer mientras HDMI lee el front buffer.

```text
GPU ----------> BACK BUFFER

HDMI <--------- FRONT BUFFER
```

Al terminar el frame, software solicita un swap:

```text
SWAP_REQUEST = 1
```

El hardware cambia `FB_FRONT` y `FB_BACK` únicamente durante VBlank.

```text
frame N:
GPU  -> back B
HDMI -> front A

VBlank -> swap

frame N+1:
GPU  -> back A
HDMI -> front B
```

Esto evita tearing y desacopla el tiempo de renderizado del scanout.

## 14. Integración con sprites y texto

El resultado 3D es simplemente otra imagen almacenada en el framebuffer. Los overlays no necesitan formar parte del rasterizador 3D.

Una composición posible es:

```text
Framebuffer 2D/3D
       |
       v
Sprite overlay
       |
       v
Text overlay
       |
       v
HDMI
```

Así, por ejemplo, una escena 3D puede ocupar el framebuffer mientras el hardware de texto dibuja encima FPS, consola o información de debug sin modificar la imagen renderizada.

Los sprites pueden utilizarse igualmente como una capa independiente sobre la escena 3D.

## 15. Qué implementar en hardware y qué dejar programable

### Hardware fijo recomendado

- Triangle Setup.
- Rasterizer.
- Generación de grupos de 8 fragments y máscaras.
- Depth test/write.
- Early-Z básico.
- Texture fetch básico.
- Pequeña texture cache.
- Coalescing/burst de memoria.
- Interpolación incremental.

### Núcleo SIMT / software

- Vertex shaders.
- Fragment shaders.
- Transformaciones matriciales.
- Iluminación.
- Materiales.
- Fog.
- Efectos procedurales.
- Kernels 2D.
- Postprocesado.

### No prioritario para la primera versión

- Bilinear/trilinear filtering.
- Mipmapping avanzado.
- Anisotropic filtering.
- MSAA.
- Geometry shaders.
- Tessellation.
- Fixed-function lighting complejo.
- Blending avanzado.
- Clipping completamente hardware.

## 16. Orden recomendado de implementación

Para evitar construir demasiadas piezas simultáneamente, la integración 3D puede hacerse por fases.

### Fase 1 — Triángulos planos

```text
vertices
 -> triangle setup
 -> rasterizer
 -> fragment groups
 -> fragment shader muy simple
 -> RGB565 framebuffer
```

Sin textura y, si se desea, inicialmente sin Z. El objetivo es comprobar que los grupos de 8 fragments, máscaras y shaders funcionan correctamente.

### Fase 2 — Z-buffer

Añadir depth interpolation, depth buffer y depth test/write.

Después introducir Early-Z.

### Fase 3 — Vertex shader completo

Conectar el flujo:

```text
Vertex Queue
 -> SIMT vertex shader
 -> primitive assembly
 -> Triangle Setup
```

Añadir matrices MVP y atributos variables.

### Fase 4 — Texturas

Añadir `TEX`, inicialmente nearest-neighbor y sin filtrado.

Después añadir una pequeña texture cache y coalescing de accesos.

### Fase 5 — Perspective-correct

Interpolar `u/w`, `v/w` y `1/w`, e introducir la solución elegida para reciprocal/división.

### Fase 6 — Scheduling mixto

Permitir que Vertex, Fragment y Compute compartan dinámicamente los 8 slots de warp, añadiendo prioridades/fairness según sea necesario.

### Fase 7 — Funciones opcionales

Una vez estable el pipeline básico pueden estudiarse blending, clipping más completo, filtrado de texturas, formatos adicionales y otras extensiones.

## 17. Arquitectura final resumida

```text
                         CPU / Command Processor
                                  |
                 +----------------+----------------+
                 |                |                |
                 v                v                v
            Vertex Queue     Compute Queue    otros comandos
                 |
                 +-------------------+
                                     |
                               Work Scheduler
                                     |
                          +----------+----------+
                          |  8 resident warps  |
                          |    × 8 SIMT lanes   |
                          +----------+----------+
                                     |
                +--------------------+--------------------+
                |                                         |
        vertex shader output                        compute output
                |
                v
          Primitive Assembly
                |
                v
         Triangle Setup HW
                |
                v
           Rasterizer HW
                |
                v
     groups of 8 fragments + mask
                |
                v
          Fragment Queue
                |
                +----------> Work Scheduler
                                  |
                                  v
                         Fragment Warp SIMT
                           /           \
                          v             v
                     Texture Unit    Depth/Z
                          \             /
                           +-----------+
                                |
                                v
                           Back Buffer
                                |
                           VBlank swap
                                |
                                v
                           Front Buffer
                                |
                         Sprite Overlay
                                |
                          Text Overlay
                                |
                                v
                              HDMI
```

La idea central es mantener el núcleo de cálculo **general y programable**, y añadir hardware fijo alrededor de él para transformar triángulos y memoria gráfica en trabajo que encaje naturalmente con los **8 lanes**. El rasterizador no sustituye al núcleo SIMT: su función principal es alimentarlo eficientemente con grupos de fragmentos.
