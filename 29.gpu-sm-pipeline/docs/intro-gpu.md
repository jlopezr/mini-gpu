# De un cubo 3D a píxeles
## Una introducción a la GPU desde MiniGPU

### 1. Introducción

Una GPU puede parecer una máquina especialmente complicada cuando se observa desde fuera. Aparecen términos como *vertex shader*, *fragment shader*, *rasterizer*, *warps*, *SIMD*, *texturas*, *depth buffer* o *framebuffer*, y es fácil perder de vista qué problema está intentando resolver realmente todo ese hardware.

En este documento vamos a tomar el camino contrario.

No comenzaremos estudiando la arquitectura de una GPU comercial moderna. Comenzaremos con una pregunta mucho más sencilla:

> **¿Qué tiene que hacer realmente una máquina para dibujar un cubo 3D en una pantalla?**

La respuesta final será sorprendentemente concreta: tiene que calcular números y realizar escrituras en memoria.

Todo lo demás —transformaciones, proyección, triángulos, rasterización, paralelismo— existe para determinar **qué valores hay que escribir y en qué posiciones de memoria**.

Utilizaremos como hilo conductor las distintas versiones del ejemplo `cube_solid` de MiniGPU. Estas versiones son especialmente interesantes porque no presentan de golpe una arquitectura gráfica terminada. Por el contrario, van introduciendo progresivamente diferentes formas de organizar el mismo problema.

La evolución que estudiaremos será:

**v3 → rasterización paralela sencilla**

**v4 → rasterización por triángulos, bounding boxes y edge functions incrementales**

**v5 → cálculo de la geometría dentro de la propia GPU**

**v6 → transformación SIMD de los vértices**

**v7 → paralelización del procesamiento de las caras**

**v8 → optimización del borrado del framebuffer**

La v3 parte de triángulos ya preparados y hace que los 64 threads participen directamente en la generación de los píxeles.

La v4 reorganiza completamente ese trabajo: procesa un triángulo cada vez, limita el rasterizado a su bounding box y actualiza las funciones de borde mediante sumas incrementales. También organiza las lanes para producir accesos consecutivos a memoria.

Más adelante, la v5 elimina incluso la geometría precalculada: la propia MiniGPU rota y proyecta los vértices y construye los descriptores de los triángulos que posteriormente rasterizará.

Es decir, los ejemplos nos permitirán construir progresivamente buena parte de un pequeño pipeline gráfico.

Pero antes de llegar allí necesitamos empezar mucho más abajo.

---

# Parte I — ¿Qué significa dibujar?

## 2. Al final de todo hay una memoria

Supongamos una pantalla de 320 × 240 píxeles.

Podemos imaginarla inicialmente como una cuadrícula:

```text
              x
       0  1  2  3  4  5  ...             319
     +--+--+--+--+--+--+-------------------+
 y 0 |  |  |  |  |  |  |                   |
     +--+--+--+--+--+--+-------------------+
   1 |  |  |  |  |  |  |                   |
     +--+--+--+--+--+--+-------------------+
   2 |  |  |  |  |  |  |                   |
     +--+--+--+--+--+--+-------------------+
     |                                         |
     |                                         |
 239 |                                         |
     +-----------------------------------------+
```

Cada casilla representa un píxel.

Un píxel no sabe nada de cubos, triángulos, cámaras ni mundos tridimensionales. Solo necesita contener un color.

Por tanto, si queremos una pantalla de 320 × 240:

\[
320 \times 240 = 76800
\]

Tenemos que determinar el color de **76 800 píxeles**.

Esta es nuestra primera simplificación fundamental:

> Dibujar una imagen significa producir el color de cada píxel que queremos mostrar.

¿Dónde guardamos esos colores?

En memoria.

La región de memoria que contiene la imagen que posteriormente será enviada a la pantalla se denomina **framebuffer**.

Conceptualmente podemos imaginar:

```text
FRAMEBUFFER

dirección baja
    |
    v

+---------------------+
| píxel (0,0)         |
| píxel (1,0)         |
| píxel (2,0)         |
| ...                 |
| píxel (319,0)       |
+---------------------+
| píxel (0,1)         |
| píxel (1,1)         |
| ...                 |
+---------------------+
|                     |
|        ...          |
|                     |
+---------------------+
| píxel (319,239)     |
+---------------------+

    ^
    |
dirección alta
```

Por ahora podemos pensar que cada píxel ocupa una posición de memoria. Más adelante veremos que MiniGPU hace algo ligeramente más interesante.

---

## 3. Del color a los bits: RGB565

Una pantalla normalmente genera sus colores combinando intensidades de rojo, verde y azul:

\[
Color=(R,G,B)
\]

Una representación muy habitual en sistemas pequeños y FPGA es **RGB565**.

El nombre indica directamente cómo se distribuyen los bits:

```text
15            11 10             5 4             0
+---------------+----------------+---------------+
|   RRRRR       |    GGGGGG      |    BBBBB      |
+---------------+----------------+---------------+
     5 bits           6 bits          5 bits
```

En total:

\[
5+6+5=16\ bits
\]

Por tanto, cada píxel ocupa **16 bits**, es decir, dos bytes.

¿Por qué el verde tiene seis bits y rojo y azul solamente cinco? Es una decisión habitual en este formato relacionada con la sensibilidad visual humana, pero para nuestra arquitectura lo importante es otra cosa:

> **un color completo cabe en 16 bits.**

Por ejemplo, conceptualmente:

```text
rojo puro   = 11111 000000 00000
verde puro  = 00000 111111 00000
azul puro   = 00000 000000 11111
```

Cuando el rasterizador determine que cierto píxel debe ser rojo, el resultado final de todo el proceso gráfico será escribir el valor RGB565 correspondiente en la memoria.

Toda la sofisticación que construiremos después desemboca en una operación de este tipo.

---

## 4. Dos píxeles por palabra

La máquina de nuestros ejemplos trabaja cómodamente con palabras de 32 bits, mientras que un píxel RGB565 necesita solamente 16.

Eso permite empaquetar **dos píxeles en cada palabra de 32 bits**:

```text
31                         16 15                         0
+----------------------------+----------------------------+
|          píxel B           |          píxel A           |
|          RGB565            |          RGB565            |
+----------------------------+----------------------------+
             16 bits                     16 bits
```

Así, una línea de 320 píxeles contiene:

\[
320/2=160
\]

palabras de 32 bits.

Y el framebuffer completo contiene:

\[
160\times240=38400
\]

palabras de 32 bits.

En bytes:

\[
38400\times4=153600\ bytes
\]

Esta organización aparece continuamente en el rasterizador de MiniGPU. De hecho, el comentario inicial de la v3 dice explícitamente que cada palabra contiene dos píxeles y que las lanes escriben palabras consecutivas.

Esto tendrá consecuencias importantes.

Supongamos que estamos trabajando con la palabra:

```text
+----------------+----------------+
| pixel x+1      | pixel x        |
+----------------+----------------+
```

Puede ocurrir que un triángulo cubra `pixel x` pero no `pixel x+1`.

Entonces no podemos sustituir alegremente los 32 bits completos por el color del triángulo.

Necesitaremos conservar una mitad:

```text
ANTES

+----------------+----------------+
| fondo          | fondo          |
+----------------+----------------+

TRIÁNGULO SOLO CUBRE EL IZQUIERDO LÓGICO

+----------------+----------------+
| fondo          | color          |
+----------------+----------------+
```

Esta aparentemente pequeña decisión de representación tendrá consecuencias en el código del rasterizador: veremos operaciones `LOAD`, modificación de una mitad de la palabra y posterior `STORE`.

Este es un buen ejemplo de algo que aparecerá muchas veces a lo largo del documento:

> Las decisiones sobre el formato de memoria afectan directamente al algoritmo y a la arquitectura de la GPU.

---

# Parte II — El problema 3D

## 5. Pero nuestro cubo no está hecho de píxeles

Hasta ahora no hemos hablado de 3D.

Una imagen ya terminada es sencilla:

```text
píxel → color
```

Pero nosotros no queremos almacenar previamente todas las imágenes posibles de un cubo girando.

Queremos describir un cubo y hacer que la máquina calcule la imagen correspondiente.

Un cubo puede representarse mediante sus ocho vértices:

```text
             7---------6
            /|        /|
           / |       / |
          4---------5  |
          |  |      |  |
          |  3------|--2
          | /       | /
          |/        |/
          0---------1
```

Cada vértice tiene tres coordenadas:

\[
P=(x,y,z)
\]

Por ejemplo, si el cubo está centrado en el origen, podemos construir sus vértices combinando valores positivos y negativos:

\[
(-s,-s,-s)
\]

\[
(+s,-s,-s)
\]

\[
...
\]

\[
(+s,+s,+s)
\]

En la v5 del ejemplo esto aparece de una forma particularmente bonita: el código genera los ocho vértices a partir de los bits del índice del vértice, seleccionando `+256` o `-256` para cada coordenada. Es decir, el propio número de vértice codifica qué esquina del cubo estamos construyendo.

Pero aquí aparece nuestro primer gran problema.

La pantalla es 2D:

\[
(x_{screen},y_{screen})
\]

y nuestro cubo es 3D:

\[
(x,y,z)
\]

Necesitamos transformar una cosa en la otra.

---

# Parte III — De 3D a 2D

## 6. El pipeline conceptual

Antes de entrar en matemáticas, conviene ver el proceso completo.

Para dibujar nuestro cubo haremos conceptualmente esto:

```text
        CUBO 3D
           |
           v
   +----------------+
   | 8 vértices 3D  |
   +----------------+
           |
           | rotación
           v
   +----------------+
   | vértices       |
   | transformados  |
   +----------------+
           |
           | proyección
           v
   +----------------+
   | 8 puntos 2D    |
   +----------------+
           |
           | construir caras
           v
   +----------------+
   | triángulos 2D  |
   +----------------+
           |
           | rasterización
           v
   +----------------+
   | píxeles        |
   +----------------+
           |
           | RGB565
           v
   +----------------+
   | framebuffer    |
   +----------------+
           |
           | scanout
           v
        PANTALLA
```

Este esquema contiene una distinción extremadamente importante.

Hay una primera parte que trabaja fundamentalmente con **vértices**:

```text
3D → transformar → proyectar → 2D
```

y una segunda que trabaja fundamentalmente con **triángulos y píxeles**:

```text
triángulos → determinar píxeles → framebuffer
```

En términos generales llamaremos a la primera parte **procesamiento de geometría** y a la segunda **rasterización**.

Esta división nos será muy útil para comprender por qué las versiones del programa evolucionan como lo hacen.

---

## 7. Girar el cubo

Si almacenásemos siempre las mismas coordenadas, el cubo permanecería inmóvil.

Para animarlo necesitamos transformar sus vértices.

Una rotación 2D ya nos da una idea de lo que ocurre. Si rotamos un punto `(x,y)` un ángulo θ:

\[
x'=x\cos\theta-y\sin\theta
\]

\[
y'=x\sin\theta+y\cos\theta
\]

En tres dimensiones podemos aplicar rotaciones sobre diferentes ejes.

No es necesario que el lector memorice ahora todas las matrices de rotación. Lo importante arquitectónicamente es observar qué tipo de trabajo aparece:

```text
multiplicaciones
sumas
restas
seno
coseno
```

Y hay algo todavía más importante:

> Cada vértice puede transformarse independientemente de los demás.

Si tenemos:

```text
V0
V1
V2
V3
V4
V5
V6
V7
```

podemos calcular:

```text
rotate(V0)
rotate(V1)
rotate(V2)
...
rotate(V7)
```

El resultado de `rotate(V0)` no depende del resultado de `rotate(V5)`.

Esto es una señal enorme para una arquitectura paralela.

Pero los primeros ejemplos no explotan todavía esta posibilidad. Llegaremos a ella cuando comparemos v5 y v6.

---

## 8. Seno y coseno sin una FPU sofisticada

La v5 utiliza una tabla `cube_sine_q14` para obtener valores de seno.

Esto merece detenerse un momento porque muestra perfectamente el tipo de decisiones que aparecen en una GPU pequeña implementada sobre FPGA.

En una CPU/GPU comercial podríamos pensar inmediatamente en coma flotante. Pero no necesitamos obligatoriamente representar:

```text
sin(θ) = 0.707106...
```

como un número IEEE-754.

Podemos utilizar **punto fijo**.

La tabla de la v5 utiliza Q14. Simplificando, podemos interpretar que reservamos 14 bits fraccionarios y escalamos el número real por:

\[
2^{14}=16384
\]

Así:

\[
1.0 \rightarrow 16384
\]

\[
0.5 \rightarrow 8192
\]

\[
-1.0 \rightarrow -16384
\]

Después de multiplicar dos valores tendremos que corregir la escala.

En el código aparecen precisamente desplazamientos aritméticos de 14 bits después de las multiplicaciones usadas en las rotaciones.

Esto nos permite hacer geometría utilizando esencialmente:

```text
MUL
ADD
SUB
SAR
```

sin necesitar que todo el pipeline gráfico se base en coma flotante.

Este detalle será importante más adelante cuando hablemos de qué significa realmente que una arquitectura sea una “GPU”. No es la presencia de una FPU concreta lo que convierte mágicamente una máquina en GPU.

---

# Parte IV — La cámara y la proyección

## 9. ¿Cómo convertimos `(x,y,z)` en `(x,y)`?

Después de rotar el cubo seguimos teniendo puntos tridimensionales.

Necesitamos proyectarlos sobre una superficie bidimensional.

Podemos imaginar una cámara mirando hacia el cubo:

```text
                         pantalla
                           |
                           |
              objeto       | 
             +------+      |
            /      /|      |
           +------+ |      |
           |      | +      |
           |      |/       |
           +------+         |
                           |
 camera *------------------+
```

La idea de una proyección con perspectiva es sencilla:

> cuanto más lejos está un objeto, más pequeño parece.

Una forma simplificada de expresarlo es:

\[
x_{screen}=c_x+\frac{x f}{z}
\]

\[
y_{screen}=c_y+\frac{y f}{z}
\]

donde:

- `x,y,z` son las coordenadas del punto respecto a la cámara,
- `f` controla la escala o distancia focal,
- `(c_x,c_y)` representa el centro de la pantalla.

Nuestros ejemplos hacen precisamente una proyección de este estilo.

En la v5 se añade un desplazamiento de profundidad de `768` y se utiliza un factor de proyección de `140`. Después se desplaza el resultado al centro de la pantalla, `(160,120)`.

Es decir, de forma conceptual:

```text
z_camera = z_rotado + 768

screen_x = 160 + x_rotado * 140 / z_camera
screen_y = 120 + y_rotado * 140 / z_camera
```

Ahora podemos empezar a ver una imagen.

Un vértice:

```text
P = (x,y,z)
```

termina convertido en:

```text
Pscreen = (sx,sy)
```

Los ocho vértices del cubo 3D terminan siendo ocho puntos sobre nuestra pantalla de 320 × 240.

---

## 10. Una observación arquitectónica: aparece la división

La proyección introduce una operación particularmente interesante:

\[
\frac{x f}{z}
\]

Tenemos multiplicación y **división**.

La división suele ser bastante más costosa que una suma y puede ser también considerablemente más costosa que una multiplicación, especialmente en una arquitectura pequeña.

Y tenemos que hacerla para cada vértice.

Aquí comienza a aparecer una de las razones por las que estudiar gráficos resulta tan interesante desde Arquitectura de Computadores.

Un algoritmo que matemáticamente podemos escribir en una línea:

\[
x'=x f/z
\]

puede tener implicaciones arquitectónicas importantes:

- ¿cuántos ciclos tarda `DIV`?
- ¿la unidad de división está compartida?
- ¿puede comenzar otra operación mientras termina una división?
- ¿podemos ejecutar la transformación de otro vértice mientras esperamos?
- ¿cuántas unidades aritméticas queremos gastar en FPGA?

Las matemáticas nos dicen **qué hay que calcular**.

La arquitectura determina **cómo conseguimos calcularlo eficientemente**.

---

# Parte V — ¿Por qué triángulos?

## 11. De ocho puntos a una superficie

Después de proyectar los vértices tendremos algo parecido a esto:

```text
          o--------o
         /        /|
        /        / |
       o--------o  |
       |        |  o
       |        | /
       |        |/
       o--------o
```

Pero seguimos teniendo un problema.

Un conjunto de puntos no es una superficie.

Necesitamos indicar qué vértices están conectados y qué regiones tienen que rellenarse.

Nuestro cubo tiene seis caras cuadradas.

Podríamos diseñar un rasterizador que supiera dibujar cuadriláteros, pero existe una primitiva mucho más conveniente:

> **el triángulo.**

Cada cara cuadrada puede dividirse en dos triángulos:

```text
A-------------B
|           / |
|         /   |
|       /     |
|     /       |
|   /         |
| /           |
D-------------C
```

Por ejemplo:

```text
T0 = A,B,C
T1 = A,C,D
```

Así:

\[
6\ caras\times2=12\ triángulos
\]

Y esto coincide con la representación del cubo utilizada por nuestros ejemplos. La tabla `cube_tris` de v5 contiene doce triángulos, cada uno definido mediante tres índices de vértices.

---

## 12. ¿Por qué gustan tanto los triángulos?

El triángulo tiene varias propiedades extremadamente convenientes.

Tres puntos no colineales determinan un plano.

Además, un triángulo siempre es convexo.

Eso significa que si tenemos:

```text
        A
       / \
      /   \
     /     \
    B-------C
```

podemos decidir si un punto está dentro del triángulo comprobando en qué lado de sus tres bordes se encuentra.

No necesitamos resolver polígonos arbitrariamente complejos.

Esta propiedad nos conducirá directamente a las **edge functions**, que son el corazón del rasterizador de nuestros ejemplos.

Pero antes necesitamos eliminar trabajo que ni siquiera deberíamos dibujar.

---

# Parte VI — Caras visibles y back-face culling

## 13. No vemos las seis caras del cubo

Observemos un cubo normal:

```text
             +--------+
            /        /|
           /        / |
          +--------+  |
          |        |  |
          |        |  +
          |        | /
          |        |/
          +--------+
```

Aunque tiene seis caras, desde una cámara exterior solamente podemos ver algunas.

Las caras que apuntan en dirección contraria a la cámara no necesitan rasterizarse.

Eliminar esas caras se denomina **back-face culling**.

Esto es importante porque nos permite descartar primitivas completas antes de empezar a trabajar píxel por píxel.

Supongamos que un triángulo proyectado tiene vértices:

\[
P_0=(x_0,y_0)
\]

\[
P_1=(x_1,y_1)
\]

\[
P_2=(x_2,y_2)
\]

Podemos calcular una cantidad proporcional al área orientada:

\[
area =
(x_1-x_0)(y_2-y_0)
-
(y_1-y_0)(x_2-x_0)
\]

El signo nos dice la orientación de los vértices sobre la pantalla.

Visualmente:

```text
A → B → C     frente

A → C → B     orientación contraria
```

Dependiendo de la convención elegida, una orientación corresponderá a una cara frontal y la otra a una cara trasera.

En la v5 se calcula precisamente esta área proyectada para decidir si un triángulo debe descartarse.

Este es nuestro primer ejemplo de una optimización gráfica extremadamente potente:

> **No optimices el dibujo de algo que puedes decidir no dibujar.**

Y veremos esta idea muchas veces.

---

# Parte VII — Hemos llegado al verdadero problema

## 14. Tenemos un triángulo. ¿Ahora qué?

Supongamos que después de toda la geometría tenemos este triángulo proyectado:

```text
             A (130,40)
              *
             / \
            /   \
           /     \
          /       \
         /         \
        *-----------*
 B (80,170)       C (220,170)
```

Ahora tenemos que responder una pregunta aparentemente sencilla:

> ¿Qué píxeles de la pantalla están dentro del triángulo?

Esta operación es la **rasterización**.

La entrada es una primitiva geométrica continua:

```text
tres vértices
```

La salida es un conjunto discreto:

```text
píxel (104,71)
píxel (105,71)
píxel (106,71)
...
```

Esta transición:

\[
geometría\ continua \rightarrow muestras\ discretas
\]

es una de las operaciones fundamentales de una GPU gráfica.

---

## 15. La solución ingenua

Tenemos una pantalla de 320 × 240.

Una primera solución perfectamente válida sería:

```text
for y = 0 .. 239:
    for x = 0 .. 319:
        if pixel(x,y) está dentro del triángulo:
            framebuffer[x,y] = color
```

Esto funcionaría.

Pero para **cada triángulo** comprobaríamos:

\[
320\times240=76800
\]

píxeles.

Para 6 triángulos visibles:

\[
76800\times6=460800
\]

tests.

Y eso para un único frame.

A 60 frames por segundo:

\[
460800\times60=27\,648\,000
\]

tests por segundo.

No todos esos tests son necesariamente caros, pero estamos haciendo algo evidentemente absurdo: comprobar píxeles de la esquina superior izquierda para un triángulo minúsculo situado en la esquina inferior derecha.

Podemos hacerlo mejor.

---

# Parte VIII — Bounding box

## 16. La caja que contiene al triángulo

Para tres vértices:

```text
(x0,y0)
(x1,y1)
(x2,y2)
```

podemos calcular:

\[
minX=\min(x_0,x_1,x_2)
\]

\[
maxX=\max(x_0,x_1,x_2)
\]

\[
minY=\min(y_0,y_1,y_2)
\]

\[
maxY=\max(y_0,y_1,y_2)
\]

Esto produce el rectángulo más pequeño alineado con los ejes que contiene al triángulo:

```text
        minX                       maxX
          |                          |
          v                          v

          +--------------------------+  <- minY
          |            A             |
          |           / \            |
          |          /   \           |
          |         /     \          |
          |        /       \         |
          |       /         \        |
          |      B-----------C       |
          +--------------------------+  <- maxY
```

Fuera de esta caja sabemos con certeza que ningún píxel pertenece al triángulo.

Así que podemos hacer:

```text
for y = minY .. maxY:
    for x = minX .. maxX:
        if inside_triangle(x,y):
            framebuffer[x,y] = color
```

Parece una optimización obvia, pero es muy importante.

Y precisamente el uso de la bounding box es una de las diferencias fundamentales entre la organización de v3 y la de v4. La v4 carga para cada triángulo los límites horizontal y vertical de la región que necesita recorrer.

Pero todavía nos falta resolver:

```text
inside_triangle(x,y)
```

Aquí entran las edge functions.

---

# Parte IX — Edge functions

## 17. ¿A qué lado de una línea está un punto?

Tomemos un borde orientado desde:

\[
A=(x_a,y_a)
\]

hasta:

\[
B=(x_b,y_b)
\]

Podemos construir una función de la forma:

\[
E(x,y)=Ax+By+C
\]

tal que:

- `E(x,y) > 0` significa que el punto está a un lado del borde,
- `E(x,y) < 0` significa que está al otro,
- `E(x,y) = 0` significa que está sobre la línea.

Los coeficientes pueden obtenerse a partir de los dos extremos del borde.

Una formulación habitual es:

\[
A=y_a-y_b
\]

\[
B=x_b-x_a
\]

\[
C=x_a y_b-x_b y_a
\]

Por tanto:

\[
E(x,y)=(y_a-y_b)x+(x_b-x_a)y+x_a y_b-x_b y_a
\]

No es necesario memorizar esta expresión.

Lo importante es entender qué hemos conseguido.

Hemos convertido:

> “¿está este punto al lado correcto de esta línea?”

en:

> “calcula unas multiplicaciones y sumas y mira el signo del resultado”.

Eso es extraordinariamente conveniente para hardware.

---

## 18. Tres bordes, tres tests

Un triángulo tiene tres bordes.

Por tanto construiremos:

\[
E_0(x,y)
\]

\[
E_1(x,y)
\]

\[
E_2(x,y)
\]

Si hemos elegido consistentemente la orientación de los vértices, un punto estará dentro cuando las tres funciones tengan el signo apropiado.

Por ejemplo:

\[
E_0(x,y)\ge0
\]

\[
E_1(x,y)\ge0
\]

\[
E_2(x,y)\ge0
\]

Visualmente:

```text
                 E0
                 /
                /
               /   zona válida
              /        ↓
             A---------+
              \       /
               \  P  /
                \ * /
                 \ /
                  B
```

Cada borde define un semiplano.

La intersección de los tres semiplanos es exactamente el triángulo:

```text
semiplano 0
     ∩
semiplano 1
     ∩
semiplano 2
     =
triángulo
```

Por tanto, el rasterizador puede recorrer la bounding box y, para cada píxel, hacer tres tests.

Conceptualmente:

```text
e0 = A0*x + B0*y + C0
e1 = A1*x + B1*y + C1
e2 = A2*x + B2*y + C2

if e0 >= 0 and e1 >= 0 and e2 >= 0:
    dibujar_pixel()
```

Esto es prácticamente el corazón matemático del rasterizador utilizado por nuestros ejemplos.

En v5, cuando la propia GPU genera los descriptores de los triángulos, calcula precisamente los coeficientes `A`, `B` y `C` de los tres bordes.

Y esto nos permite entender por fin qué es uno de esos **descriptores de triángulo** que aparecen continuamente en el ensamblador.

---

# Parte X — El descriptor de un triángulo

## 19. Convertir geometría en datos fáciles de rasterizar

El rasterizador no necesita recibir necesariamente:

```text
V0 = (x0,y0)
V1 = (x1,y1)
V2 = (x2,y2)
```

y repetir todos los cálculos geométricos.

Podemos preparar previamente la información que realmente necesita.

En la v4, cada descriptor ocupa 14 palabras e incluye las tres edge functions, el color y los límites del bounding box.

Conceptualmente podemos representarlo así:

```text
TRIANGLE DESCRIPTOR
+-----------------------+
| A0                    |
| B0                    |
| C0                    |
+-----------------------+
| A1                    |
| B1                    |
| C1                    |
+-----------------------+
| A2                    |
| B2                    |
| C2                    |
+-----------------------+
| color RGB565          |
+-----------------------+
| min X                 |
| max X                 |
| min Y                 |
| max Y                 |
+-----------------------+
```

Ahora la rasterización ya no necesita “entender” un cubo.

Ni siquiera necesita saber qué es una cara.

Recibe algo equivalente a:

> Hay un triángulo de este color. Solo tienes que recorrer esta región y comprobar estas tres ecuaciones.

Esta separación es conceptualmente importantísima.

Podemos pensar en dos mundos:

```text
          GEOMETRÍA
              |
              | genera
              v
    +--------------------+
    | descriptor         |
    | del triángulo      |
    +--------------------+
              |
              | consume
              v
       RASTERIZADOR
              |
              v
           PÍXELES
```

La geometría produce primitivas preparadas.

El rasterizador consume primitivas y produce cobertura de píxeles.

En una arquitectura mucho más sofisticada la frontera puede ser diferente y existirán muchas etapas adicionales, pero esta pequeña separación ya nos permite comprender buena parte de la lógica que hay detrás de un pipeline gráfico.

---

# Parte XI — Una optimización fundamental

## 20. No recalcules `Ax + By + C` para cada píxel

Supongamos:

\[
E(x,y)=Ax+By+C
\]

Estamos en el píxel `(x,y)` y ya hemos calculado:

\[
E(x,y)
\]

¿Qué ocurre en el siguiente píxel horizontal?

\[
E(x+1,y)
\]

Sustituimos:

\[
E(x+1,y)=A(x+1)+By+C
\]

Desarrollando:

\[
E(x+1,y)=Ax+A+By+C
\]

Pero:

\[
Ax+By+C=E(x,y)
\]

Por tanto:

\[
\boxed{E(x+1,y)=E(x,y)+A}
\]

Esto es extremadamente importante.

Para pasar al siguiente píxel **no necesitamos volver a multiplicar**.

Solo necesitamos sumar `A`.

Lo mismo verticalmente:

\[
E(x,y+1)=Ax+B(y+1)+C
\]

por tanto:

\[
\boxed{E(x,y+1)=E(x,y)+B}
\]

Acabamos de transformar buena parte del rasterizador.

En vez de:

```text
para cada píxel:
    MUL
    MUL
    ADD
    ADD
```

podemos calcular el valor completo una vez y después avanzar mediante:

```text
ADD
```

Esta es la idea de la evaluación **incremental** de las edge functions.

Y es exactamente una de las grandes optimizaciones introducidas por la v4: el propio comentario del programa destaca que las funciones de borde se actualizan incrementalmente mediante sumas.

---

## 21. Un ejemplo numérico

Supongamos una edge function ficticia:

\[
E(x,y)=3x+2y-20
\]

Queremos recorrer horizontalmente la fila `y=5`.

Para `x=4`:

\[
E(4,5)=3(4)+2(5)-20
\]

\[
=12+10-20=2
\]

Ahora queremos `x=5`.

Podríamos volver a calcular:

\[
E(5,5)=15+10-20=5
\]

Pero sabemos que:

\[
A=3
\]

por tanto:

\[
E(5,5)=E(4,5)+3
\]

\[
=2+3=5
\]

Siguiente:

\[
E(6,5)=5+3=8
\]

Siguiente:

\[
E(7,5)=8+3=11
\]

Es decir:

```text
x     E

4      2
5      5
6      8
7     11
8     14
9     17
```

Después del primer cálculo solamente hacemos sumas.

Ahora imaginemos esto repetido para millones de píxeles.

Ya podemos intuir por qué una reorganización matemática aparentemente pequeña puede producir una diferencia grande en rendimiento.

---

# Parte XII — De un rasterizador a una GPU

## 22. Hasta ahora no necesitábamos una GPU

Todo lo explicado hasta este momento podría ejecutarse perfectamente en una CPU.

Podríamos escribir:

```text
transformar_vertices()

for cada triangulo:
    if visible:
        calcular_descriptor()

        for y dentro del bounding box:
            for x dentro del bounding box:
                calcular edge functions

                if pixel dentro:
                    framebuffer[x,y] = color
```

No hay nada intrínsecamente “GPU” aquí.

Una CPU podría dibujar nuestro cubo.

Entonces, ¿por qué aparecen las GPU?

Porque al observar el trabajo encontramos una enorme cantidad de **paralelismo de datos**.

Consideremos una fila del triángulo:

```text
x=100
  |
  v

+--+--+--+--+--+--+--+--+--+--+--+--+
|  |  |  |  |  |  |  |  |  |  |  |  |
+--+--+--+--+--+--+--+--+--+--+--+--+
```

El test del píxel 100 es prácticamente el mismo trabajo que el del 101, 102, 103...

Y consideremos los vértices:

```text
V0 → transformar
V1 → transformar
V2 → transformar
V3 → transformar
...
```

Otra vez aparece el mismo programa aplicado a muchos datos diferentes.

Esto es terreno ideal para una arquitectura que pueda ejecutar operaciones similares sobre múltiples elementos.

Y aquí es donde nuestra historia cambia.

Hasta ahora hemos estudiado fundamentalmente:

> **cómo se dibuja un triángulo.**

A partir de ahora podremos estudiar:

> **cómo organizar una máquina para dibujar muchos píxeles eficientemente.**

---

# Parte XIII — Primera aproximación al paralelismo

## 23. Imaginemos 64 trabajadores

Supongamos que nuestra máquina dispone de 64 threads.

En vez de hacer que un único thread recorra todo:

```text
thread 0:

pixel 0
pixel 1
pixel 2
pixel 3
...
```

podemos repartir el trabajo:

```text
thread 0  → una parte
thread 1  → otra parte
thread 2  → otra parte
...
thread 63 → otra parte
```

La pregunta importante ya no es simplemente:

> ¿podemos paralelizar?

Claramente podemos.

La pregunta interesante es:

> **¿cómo repartimos el trabajo?**

Podríamos asignar píxeles consecutivos:

```text
T0 T1 T2 T3 T4 T5 T6 T7 ...
```

o filas:

```text
T0  ----------------
T1  ----------------
T2  ----------------
...
```

o bloques:

```text
+----+----+----+----+
| T0 | T1 | T2 | T3 |
+----+----+----+----+
| T4 | T5 | T6 | T7 |
+----+----+----+----+
```

Todas son paralelas.

Pero **no todas son igual de buenas**.

¿Por qué?

Porque la GPU no contiene solamente ALUs.

También tiene memoria.

Y el modo en que repartamos el trabajo determinará qué direcciones intenta acceder cada thread al mismo tiempo.

Aquí aparecerá uno de los temas centrales de MiniGPU:

> **organizar el trabajo computacional para que también produzca buenos accesos a memoria.**

---

# Parte XIV — Antes de v3: el rasterizador conceptual

## 24. Nuestro primer programa imaginario

Antes de mirar la v3, construyamos mentalmente una versión todavía más sencilla.

Tenemos seis triángulos visibles ya preparados:

```text
triangle[0]
triangle[1]
triangle[2]
triangle[3]
triangle[4]
triangle[5]
```

Cada uno contiene:

```text
A0 B0 C0
A1 B1 C1
A2 B2 C2
color
```

Queremos producir el framebuffer.

Una posibilidad sería recorrer cada píxel de una región y preguntar a qué triángulo pertenece:

```text
for cada pixel:
    color = background

    for cada triangle:
        if inside(pixel, triangle):
            color = triangle.color

    framebuffer[pixel] = color
```

Obsérvese la organización:

```text
PIXEL
  |
  +--> triangle 0?
  |
  +--> triangle 1?
  |
  +--> triangle 2?
  |
  +--> triangle 3?
  |
  +--> triangle 4?
  |
  +--> triangle 5?
  |
  v
COLOR FINAL
```

Esta estrategia tiene una propiedad atractiva:

> cada posición del framebuffer se escribe una sola vez.

Si ningún triángulo cubre el píxel, escribimos fondo.

Por tanto, al mismo tiempo que dibujamos estamos borrando la imagen anterior.

No necesitamos una pasada de `clear` independiente.

Esta es precisamente una de las ideas fundamentales de la **v3**.

El comentario inicial explica que cada thread tiene asignadas sus palabras RGB565 y que siempre escribe una palabra, incluso cuando ningún triángulo la cubre, de modo que no hace falta una pasada separada de borrado.

Ya tenemos suficiente base para empezar a estudiar código real.

---

# Antes de la GPU: dibujar el cubo con una CPU

Hasta ahora hemos hablado del framebuffer, de los píxeles y de cómo se representa el color. Sabemos, por tanto, cuál es el destino final de nuestro trabajo: una región de memoria que el sistema de vídeo recorrerá posteriormente para producir la imagen.

Pero todavía queda una pregunta mucho más importante:

**¿cómo pasamos de un cubo definido mediante coordenadas tridimensionales a esos píxeles del framebuffer?**

Antes de introducir threads, warps, lanes o ejecución SIMT, resulta muy útil responder a esta pregunta utilizando únicamente una CPU.

De hecho, una de las versiones anteriores del ejemplo del cubo hace exactamente eso. Todo el proceso se ejecuta secuencialmente: la CPU transforma los vértices, los proyecta sobre la pantalla, determina qué caras son visibles, divide esas caras en triángulos y finalmente recorre los píxeles de cada triángulo.

Esto nos permitirá separar dos problemas que conviene no confundir:

1. **Cómo se dibuja un objeto 3D.**
2. **Cómo una GPU permite ejecutar ese trabajo de forma paralela.**

La GPU no cambia las matemáticas fundamentales del rasterizado. Lo que cambia, sobre todo, es **cómo organizamos y distribuimos el trabajo**.

---

## 1. El pipeline completo ya existe en la CPU

La versión CPU del cubo implementa aproximadamente este pipeline:

```text
         MODELO 3D
             │
             ▼
       8 vértices (x,y,z)
             │
             ▼
          rotación
             │
             ▼
   vértices transformados
             │
             ▼
     proyección perspectiva
             │
             ▼
       8 puntos (x,y)
             │
             ▼
       recorrer 6 caras
             │
             ▼
     back-face culling
             │
             ▼
  dividir cara en 2 triángulos
             │
             ▼
       bounding box
             │
             ▼
       edge functions
             │
             ▼
        rasterización
             │
             ▼
          putpixel
             │
             ▼
        framebuffer
             │
             ▼
           scanout
```

Este diagrama es importante porque, conceptualmente, **ya estamos haciendo gráficos 3D completos**.

Todavía no hay una GPU involucrada.

Eso nos enseña una primera idea fundamental:

> Una GPU no es necesaria para definir las matemáticas de los gráficos 3D. La GPU aparece cuando queremos ejecutar esas matemáticas y procesar grandes cantidades de datos de forma eficiente.

---

# 2. El cubo comienza siendo solamente ocho puntos

El cubo se almacena mediante ocho vértices tridimensionales.

En el programa CPU aparecen como:

```asm
vertices:
    .word -65536, -65536, -65536
    .word  65536, -65536, -65536
    .word -65536,  65536, -65536
    .word  65536,  65536, -65536
    .word -65536, -65536,  65536
    .word  65536, -65536,  65536
    .word -65536,  65536,  65536
    .word  65536,  65536,  65536
```

Los valores están expresados en formato de punto fijo. Conceptualmente podemos imaginar simplemente:

```text
(-1,-1,-1)
(+1,-1,-1)
(-1,+1,-1)
(+1,+1,-1)

(-1,-1,+1)
(+1,-1,+1)
(-1,+1,+1)
(+1,+1,+1)
```

Todavía no existen caras ni píxeles.

Solo tenemos ocho posiciones en un espacio tridimensional.

Podemos visualizarlo así:

```text
        6────────7
       /│       /│
      / │      / │
     2────────3  │
     │  │     │  │
     │  4─────│──5
     │ /      │ /
     │/       │/
     0────────1
```

Las caras del cubo se describen posteriormente indicando qué cuatro vértices forman cada una.

---

# 3. Rotar el objeto

Si dibujásemos siempre los mismos vértices, el cubo permanecería inmóvil.

Para animarlo modificamos sus coordenadas aplicando una rotación.

La versión CPU realiza este trabajo recorriendo secuencialmente los ocho vértices:

```text
vértice 0
    ↓
rotar
    ↓
proyectar

vértice 1
    ↓
rotar
    ↓
proyectar

...

vértice 7
    ↓
rotar
    ↓
proyectar
```

En ensamblador esto aparece como un bucle:

```asm
MOVI  R19, 8

vertex_loop:
    ...
    ; transformar vértice
    ...
    ADDI  R19, R19, -1
    BNE   R19, R0, vertex_loop
```

La CPU procesa un vértice después de otro.

Esta observación será muy importante más adelante.

Los ocho cálculos son prácticamente independientes:

```text
V0 ──► transform(V0)
V1 ──► transform(V1)
V2 ──► transform(V2)
V3 ──► transform(V3)
V4 ──► transform(V4)
V5 ──► transform(V5)
V6 ──► transform(V6)
V7 ──► transform(V7)
```

La CPU los ejecuta secuencialmente porque ese es el modelo de ejecución que estamos utilizando.

Pero el algoritmo ya nos está mostrando **paralelismo natural**.

Más adelante veremos que esta correspondencia resulta especialmente atractiva para MiniGPU:

```text
8 vértices
     ↕
8 lanes
```

Por ahora, sin embargo, continuaremos pensando como una CPU.

---

# 4. Del espacio 3D a la pantalla 2D

Después de rotar un vértice tenemos unas coordenadas tridimensionales:

```text
(x, y, z)
```

Pero el framebuffer es bidimensional.

Necesitamos convertir:

```text
(x, y, z)
```

en:

```text
(screen_x, screen_y)
```

Para ello utilizamos una proyección perspectiva.

De forma simplificada:

$$
screen_x = center_x + \frac{x \cdot focal}{z}
$$

$$
screen_y = center_y + \frac{y \cdot focal}{z}
$$

En nuestro ejemplo:

```text
center_x = 160
center_y = 120
focal    = 140
```

porque la pantalla es de 320×240 píxeles.

El código refleja directamente esta operación:

```asm
MUL   R11, R9, R13
DIV   R11, R11, R10
ADDI  R11, R11, 160

MUL   R12, R7, R13
DIV   R12, R12, R10
ADDI  R12, R12, 120
```

Por tanto, después de transformar los ocho vértices ya no necesitamos trabajar con el cubo exclusivamente como objeto tridimensional.

Tenemos ocho posiciones proyectadas:

```text
P0 = (x0,y0)
P1 = (x1,y1)
...
P7 = (x7,y7)
```

que viven en el espacio de la pantalla.

Esta frontera es conceptualmente importante:

```text
             GEOMETRÍA 3D

(x,y,z) ──► rotación ──► perspectiva
                              │
                              ▼

             RASTERIZACIÓN 2D

                         (screen_x,
                          screen_y)
```

El rasterizador que veremos a continuación no necesita saber que esos puntos pertenecían originalmente a un cubo tridimensional.

Para él son simplemente puntos 2D.

---

# 5. Construir las caras

Un conjunto de ocho puntos todavía no describe qué superficies forman el cubo.

Por eso existe una tabla de caras.

Cada cara contiene cuatro vértices:

```text
v0 ─────── v1
│           │
│           │
│           │
v3 ─────── v2
```

Pero nuestro rasterizador trabaja con triángulos.

Dividimos entonces el cuadrilátero en dos:

```text
v0 ─────── v1
│ \         │
│   \       │
│     \     │
v3 ─────── v2
```

obteniendo:

```text
T0 = (v0,v1,v2)
T1 = (v0,v2,v3)
```

Por tanto:

```text
6 caras × 2 triángulos/cara = 12 triángulos
```

como máximo.

¿Por qué triángulos?

Porque un triángulo tiene propiedades especialmente convenientes para el hardware y para el software:

- siempre es plano;
- siempre es convexo;
- queda completamente definido por tres vértices;
- podemos determinar fácilmente si un punto está dentro;
- sus atributos pueden interpolarse de forma sencilla.

Por eso el triángulo sigue siendo la primitiva fundamental de los rasterizadores modernos.

---

# 6. Antes de dibujar: back-face culling

Un cubo es un objeto cerrado.

Cuando lo observamos desde una determinada posición, aproximadamente la mitad de sus caras apuntan en dirección contraria a la cámara.

No tiene sentido rasterizarlas.

Podemos detectar esas caras utilizando el área orientada del triángulo proyectado.

Para tres puntos:

```text
P0 = (x0,y0)
P1 = (x1,y1)
P2 = (x2,y2)
```

calculamos:

$$
area =
(x_1-x_0)(y_2-y_0)
-
(y_1-y_0)(x_2-x_0)
$$

El signo nos indica la orientación del triángulo en pantalla.

En el programa aparece literalmente:

```asm
SUB   R15, R11, R9
SUB   R16, R14, R10
MUL   R17, R15, R16

SUB   R15, R12, R10
SUB   R16, R13, R9
MUL   R18, R15, R16

SUB   R17, R17, R18
```

y después:

```asm
BGE   R0, R17, face_done
```

Si el área tiene la orientación que hemos definido como trasera, descartamos la cara completa.

Esta operación recibe el nombre de:

**back-face culling**.

El pipeline se ha convertido entonces en:

```text
12 triángulos potenciales
          │
          ▼
   orientación/área
          │
     ┌────┴────┐
     │         │
 trasero     visible
     │         │
 descartar     ▼
           rasterizar
```

El convenio exacto del signo depende del orden de los vértices y del sentido de los ejes de pantalla. En este ejemplo, la tabla de caras está construida teniendo en cuenta que el eje Y de pantalla crece hacia abajo.

---

# 7. Hemos llegado al verdadero problema del rasterizador

Supongamos que después de proyectar obtenemos un triángulo:

```text
             P1
             /\
            /  \
           /    \
          /      \
         /        \
        /          \
       P0──────────P2
```

Tenemos las coordenadas de sus tres vértices.

Pero el framebuffer no entiende triángulos.

El framebuffer entiende píxeles.

Necesitamos transformar:

```text
tres vértices
```

en algo parecido a:

```text
píxel (104,72)  → rojo
píxel (105,72)  → rojo
píxel (106,72)  → rojo
píxel (103,73)  → rojo
...
```

Ese proceso es la **rasterización**.

Y aquí aparece una pregunta fundamental:

> Dado un píxel `(x,y)`, ¿cómo sabemos si está dentro del triángulo?

---

# 8. Las funciones de borde

Cada una de las tres aristas de un triángulo divide el plano en dos semiplanos.

Podemos construir una función matemática que nos indique en cuál de ellos se encuentra un punto.

Para una arista podemos escribir:

$$
E(x,y)=Ax+By+C
$$

donde los coeficientes dependen de sus dos vértices.

Para una arista que va de:

```text
Pa = (xa,ya)
```

a:

```text
Pb = (xb,yb)
```

una forma habitual es:

$$
A = y_a-y_b
$$

$$
B = x_b-x_a
$$

$$
C = x_a y_b-x_b y_a
$$

y por tanto:

$$
E(x,y)=Ax+By+C
$$

Dependiendo del orden de los vértices, un punto situado en el lado interior de la arista producirá un valor positivo o negativo.

Si hemos elegido consistentemente el orden de los vértices, podemos comprobar un triángulo mediante:

```text
E0(x,y) >= 0
        AND
E1(x,y) >= 0
        AND
E2(x,y) >= 0
```

Gráficamente:

```text
                   E1
                  /
                 /
             +--/----+
             | /     |
         E0  |/      |   zona que satisface
             /\      |   las tres condiciones
            /  \     |
           /    \    |
          +------+---+
              E2
```

La intersección de los tres semiplanos es precisamente el triángulo.

Esta es una idea extraordinariamente potente.

Hemos convertido la pregunta:

```text
¿está este píxel dentro de una figura?
```

en tres operaciones aritméticas y tres comparaciones.

---

# 9. No queremos comprobar toda la pantalla

Una posibilidad extremadamente sencilla sería:

```text
for y = 0 .. 239:
    for x = 0 .. 319:
        comprobar E0
        comprobar E1
        comprobar E2
```

Funcionaría.

Pero para un triángulo pequeño estaríamos comprobando decenas de miles de píxeles que evidentemente están muy lejos de él.

Por eso calculamos primero su **bounding box**:

```text
minX = min(x0,x1,x2)
maxX = max(x0,x1,x2)

minY = min(y0,y1,y2)
maxY = max(y0,y1,y2)
```

Obtenemos un rectángulo:

```text
        minX                 maxX
          │                    │
          ▼                    ▼

minY  ─── +--------------------+
          |         /\         |
          |        /  \        |
          |       /    \       |
          |      /      \      |
          |     /________\     |
maxY  ─── +--------------------+
```

Ahora solo examinamos los píxeles contenidos en ese rectángulo.

El código CPU comienza precisamente `fill_triangle` calculando esos cuatro límites.

---

# 10. El rasterizador secuencial más sencillo

Llegados a este punto podríamos implementar:

```text
for y = minY .. maxY:
    for x = minX .. maxX:

        E0 = edge0(x,y)
        E1 = edge1(x,y)
        E2 = edge2(x,y)

        if E0 >= 0 and
           E1 >= 0 and
           E2 >= 0:

            putpixel(x,y,color)
```

Esto ya sería un rasterizador correcto.

Pero tendría un problema.

Calcular cada función:

$$
E(x,y)=Ax+By+C
$$

desde cero para cada píxel implica multiplicaciones repetidas.

Y resulta que no hacen falta.

---

# 11. La propiedad incremental de las edge functions

Partimos de:

$$
E(x,y)=Ax+By+C
$$

¿Qué ocurre al movernos un píxel hacia la derecha?

$$
E(x+1,y)=A(x+1)+By+C
$$

Desarrollando:

$$
E(x+1,y)=Ax+By+C+A
$$

por tanto:

$$
E(x+1,y)=E(x,y)+A
$$

Lo mismo sucede verticalmente:

$$
E(x,y+1)=E(x,y)+B
$$

Esta propiedad cambia completamente el coste del rasterizador.

Solo necesitamos calcular la función completa al comienzo.

Después podemos recorrer los píxeles mediante sumas.

```text
          x → x+1 → x+2 → x+3

E0        +A    +A    +A
E1        +A1   +A1   +A1
E2        +A2   +A2   +A2

y
│
▼         +B
y+1
```

La versión CPU utiliza una formulación equivalente basada en `dx` y `dy`.

Al avanzar horizontalmente:

```asm
SUB   R12, R12, R21
SUB   R13, R13, R23
SUB   R14, R14, R28
```

Es decir:

```text
E += -dy
```

Y al avanzar verticalmente:

```asm
ADD   R9,  R9,  R20
ADD   R10, R10, R22
ADD   R11, R11, R25
```

es decir:

```text
E_row += dx
```

Las multiplicaciones se utilizan para calcular los valores iniciales de las tres funciones de borde.

Después, el recorrido del triángulo es fundamentalmente:

**sumas, comparaciones y saltos.**

Esta característica será importantísima cuando llevemos el algoritmo a MiniGPU.

---

# 12. El corazón de `fill_triangle`

Una vez inicializadas las tres funciones de borde, la estructura real del rasterizador CPU es muy sencilla.

Conceptualmente:

```text
for y = minY .. maxY:

    E0 = E0_row
    E1 = E1_row
    E2 = E2_row

    for x = minX .. maxX:

        if E0 >= 0 &&
           E1 >= 0 &&
           E2 >= 0:

            putpixel(x,y,color)

        E0 += stepX0
        E1 += stepX1
        E2 += stepX2

    E0_row += stepY0
    E1_row += stepY1
    E2_row += stepY2
```

Y esto es prácticamente una traducción directa del ensamblador:

```asm
@tri_pixel:
    BLT   R12, R0, @tri_skip
    BLT   R13, R0, @tri_skip
    BLT   R14, R0, @tri_skip

    JAL   R30, putpixel

@tri_skip:
    SUB   R12, R12, R21
    SUB   R13, R13, R23
    SUB   R14, R14, R28

    ADDI  R4, R4, 1
    BGE   R16, R4, @tri_pixel
```

Lo más importante aquí no es memorizar los registros.

Es reconocer el algoritmo:

```text
              ┌─────────────────┐
              │ ¿E0,E1,E2 >= 0? │
              └────────┬────────┘
                       │
              ┌────────┴────────┐
             sí                 no
              │                  │
              ▼                  │
          putpixel               │
              │                  │
              └────────┬─────────┘
                       ▼
                 avanzar E
                       │
                       ▼
                  siguiente x
```

Este pequeño bucle contiene el núcleo del rasterizador que posteriormente paralelizaremos.

---

# 13. De un píxel al framebuffer

Cuando las tres funciones de borde indican que el punto está dentro del triángulo, el programa llama a:

```asm
putpixel
```

Conceptualmente:

```text
putpixel(x,y,color)
```

termina convirtiéndose en una dirección de memoria del framebuffer.

Si ignoramos por un momento el empaquetado de RGB565, la idea es:

$$
address =
framebuffer +
y \cdot stride +
x \cdot bytesPerPixel
$$

Para nuestra pantalla:

```text
320 píxeles/fila
2 bytes/píxel
```

por tanto:

$$
stride=320\times2=640\text{ bytes}
$$

que es precisamente el valor que conserva el programa:

```asm
MOVI R24, 640
```

Por tanto hemos completado toda la transformación:

```text
                 (x,y,z)
                    │
                    ▼
                 rotación
                    │
                    ▼
                perspectiva
                    │
                    ▼
             (screen_x,screen_y)
                    │
                    ▼
                 triángulo
                    │
                    ▼
              edge functions
                    │
                    ▼
             píxel interior
                    │
                    ▼
                putpixel
                    │
                    ▼
       dirección del framebuffer
                    │
                    ▼
                  STORE
```

Ya podemos dibujar un cubo sólido.

Y seguimos sin necesitar una GPU.

---

# 14. Limpiar el frame anterior

Hay otro detalle que será importante más adelante.

El framebuffer contiene memoria persistente.

Si en el frame anterior el cubo ocupaba:

```text
       ███████
       ███████
       ███████
```

y en el nuevo frame se ha desplazado o rotado:

```text
             ███████
             ███████
             ███████
```

dibujar únicamente el nuevo cubo no elimina automáticamente los píxeles antiguos.

Hay que limpiar la región anterior.

La versión CPU limpia inicialmente los dos buffers completos y después, en cada frame, limpia una caja fija alrededor de la región donde puede aparecer el cubo.

Conceptualmente:

```text
frame:

    obtener back buffer

    limpiar región
          │
          ▼
    transformar vértices
          │
          ▼
    rasterizar caras
          │
          ▼
        swap
```

Esta operación parece secundaria, pero más adelante veremos que el borrado puede representar una cantidad significativa de tráfico de memoria.

De hecho, una de las optimizaciones que aparecerá mucho más tarde, en v8, consistirá precisamente en reducir esa región de borrado.

---

# 15. Double buffering

La CPU no dibuja directamente sobre el framebuffer que está siendo mostrado.

Trabaja sobre el **back buffer**.

Podemos imaginar:

```text
         SCANOUT
            │
            ▼
     ┌──────────────┐
     │ FRONT BUFFER │
     │              │
     │ frame N      │
     └──────────────┘


           CPU
            │
            ▼
     ┌──────────────┐
     │ BACK BUFFER  │
     │              │
     │ frame N+1    │
     └──────────────┘
```

Cuando termina de renderizar:

```text
              SWAP
                │
                ▼

 FRONT <────────────────> BACK
```

El frame recién terminado pasa a ser mostrado y el buffer anterior queda disponible para construir un nuevo frame.

Esto separa dos actividades diferentes:

```text
renderizado → escribe framebuffer

scanout     → lee framebuffer
```

y evita modificar arbitrariamente la imagen mientras el sistema de vídeo la está recorriendo.

Esta arquitectura seguirá siendo exactamente igual cuando sustituyamos la CPU por MiniGPU.

---

# 16. ¿Dónde está el problema?

Nuestro rasterizador CPU funciona.

Entonces, ¿para qué queremos una GPU?

Observemos dónde está el trabajo.

Primero tenemos ocho vértices:

```text
V0 V1 V2 V3 V4 V5 V6 V7
```

y hacemos:

```text
transform(V0)
transform(V1)
transform(V2)
...
transform(V7)
```

Pero estas transformaciones son independientes.

Después tenemos muchos píxeles:

```text
P0 P1 P2 P3 P4 P5 ... Pn
```

y para cada uno hacemos esencialmente:

```text
inside(P0)?
inside(P1)?
inside(P2)?
...
inside(Pn)?
```

También son, en gran medida, cálculos independientes.

El algoritmo contiene por tanto una enorme cantidad de **paralelismo de datos**.

La CPU que acabamos de utilizar lo expresa como:

```text
hacer A
después B
después C
después D
...
```

Pero matemáticamente muchas de esas operaciones podrían realizarse simultáneamente:

```text
       ┌──► A
       ├──► B
───────┼──► C
       ├──► D
       └──► ...
```

Y aquí aparece por fin la GPU.

---

# 17. El primer impulso: repartir los píxeles

Una vez entendido el rasterizador secuencial, podemos formular una idea muy sencilla:

> Si tenemos muchos elementos de ejecución, ¿por qué no hacemos que distintos threads procesen distintos píxeles?

La CPU hacía:

```text
CPU

pixel 0
   ↓
pixel 1
   ↓
pixel 2
   ↓
pixel 3
   ↓
...
```

Con múltiples threads podríamos intentar:

```text
thread 0 ──► píxeles ...
thread 1 ──► píxeles ...
thread 2 ──► píxeles ...
thread 3 ──► píxeles ...
...
thread 63 ─► píxeles ...
```

Esta idea es el punto de partida de nuestra primera versión verdaderamente GPU del rasterizador.

Pero pronto descubriremos que simplemente decir:

**“tengo 64 threads, reparto el trabajo entre 64”**

no es suficiente.

También tendremos que preguntarnos:

- ¿qué píxeles procesa cada thread?
- ¿qué threads ejecutan juntos?
- ¿cómo se agrupan en warps?
- ¿qué representa una lane?
- ¿qué ocurre si unas lanes entran en un `if` y otras no?
- ¿qué direcciones de memoria genera cada lane?
- ¿puede el LSU combinar varios accesos?
- ¿cómo hacemos que las escrituras sean coalescentes?
- ¿qué datos conviene calcular una sola vez?
- ¿cómo sincronizamos distintas fases del frame?

Es decir, pasaremos de estudiar únicamente un **algoritmo gráfico** a estudiar también su **mapeo sobre una arquitectura paralela**.

---

# 18. La transición fundamental

Conviene detenerse aquí porque hemos alcanzado una frontera conceptual importante.

Hasta este punto nuestra pregunta era:

> **¿Cómo se dibuja un triángulo?**

La respuesta ha sido:

```text
vértices
   ↓
proyección
   ↓
triángulos
   ↓
bounding box
   ↓
edge functions
   ↓
recorrer píxeles
   ↓
putpixel
```

A partir de ahora la pregunta será diferente:

> **¿Cómo reorganizamos ese trabajo para ejecutarlo eficientemente sobre MiniGPU?**

No vamos a cambiar las matemáticas fundamentales.

Seguiremos teniendo:

```text
E0
E1
E2
```

seguiremos preguntando:

```text
E0 >= 0 &&
E1 >= 0 &&
E2 >= 0
```

y seguiremos terminando escribiendo RGB565 en el framebuffer.

Lo que cambiará será la organización del trabajo.

Por ejemplo, el rasterizador CPU avanza naturalmente:

```text
x
x+1
x+2
x+3
x+4
...
```

Pero MiniGPU tiene ocho lanes y el framebuffer almacena dos píxeles RGB565 dentro de cada palabra de 32 bits.

Eso hará que más adelante nos interese pensar en bloques como:

```text
lane 0 → píxeles  0, 1
lane 1 → píxeles  2, 3
lane 2 → píxeles  4, 5
lane 3 → píxeles  6, 7
lane 4 → píxeles  8, 9
lane 5 → píxeles 10,11
lane 6 → píxeles 12,13
lane 7 → píxeles 14,15
```

De repente, una propiedad matemática que en la CPU decía:

$$
E(x+1,y)=E(x,y)+A
$$

acabará produciendo relaciones como:

$$
E(x+16,y)=E(x,y)+16A
$$

No porque la geometría haya cambiado.

No porque el triángulo sea diferente.

Sino porque **hemos adaptado el recorrido del mismo algoritmo a la organización de nuestra máquina**.

Esta distinción será una de las ideas centrales de todo lo que sigue.

---

# 19. Lo que debemos conservar de la versión CPU

Antes de pasar a v3, podemos reducir todo el programa anterior a unas pocas ideas fundamentales.

El pipeline gráfico es:

```text
modelo 3D
    │
    ▼
transformación
    │
    ▼
proyección
    │
    ▼
triángulos 2D
    │
    ▼
culling
    │
    ▼
triangle setup
    │
    ▼
rasterización
    │
    ▼
píxeles RGB565
    │
    ▼
framebuffer
    │
    ▼
scanout
```

El núcleo matemático del rasterizador es:

$$
E_i(x,y)=A_i x+B_i y+C_i
$$

para las tres aristas, y un píxel pertenece al triángulo cuando satisface las tres condiciones de cobertura.

La optimización matemática fundamental es:

$$
E(x+1,y)=E(x,y)+A
$$

$$
E(x,y+1)=E(x,y)+B
$$

Y el problema arquitectónico que tenemos delante es:

```text
                ALGORITMO SECUENCIAL

                     for y
                       │
                       ▼
                     for x
                       │
                       ▼
                 edge tests
                       │
                       ▼
                   putpixel


                       │
                       │
                       ▼


             ¿CÓMO LO PARALELIZAMOS?


                       │
                       ▼

                MINIGPU / SIMT
```

Esta es precisamente la pregunta que intentarán responder las siguientes versiones.

La primera respuesta no será perfecta.

Tampoco queremos que lo sea.

Comenzaremos con una distribución relativamente sencilla del rasterizado entre los threads de MiniGPU. Después iremos descubriendo sus problemas y, versión a versión, reorganizaremos el algoritmo para aprovechar mejor los warps, las lanes, el LSU y la memoria.

Ese recorrido —más que el cubo en sí— es lo que nos permitirá entender **por qué una GPU acaba teniendo la arquitectura que tiene**.# Antes de la GPU: dibujar el cubo con una CPU

Hasta ahora hemos hablado del framebuffer, de los píxeles y de cómo se representa el color. Sabemos, por tanto, cuál es el destino final de nuestro trabajo: una región de memoria que el sistema de vídeo recorrerá posteriormente para producir la imagen.

Pero todavía queda una pregunta mucho más importante:

**¿cómo pasamos de un cubo definido mediante coordenadas tridimensionales a esos píxeles del framebuffer?**

Antes de introducir threads, warps, lanes o ejecución SIMT, resulta muy útil responder a esta pregunta utilizando únicamente una CPU.

De hecho, una de las versiones anteriores del ejemplo del cubo hace exactamente eso. Todo el proceso se ejecuta secuencialmente: la CPU transforma los vértices, los proyecta sobre la pantalla, determina qué caras son visibles, divide esas caras en triángulos y finalmente recorre los píxeles de cada triángulo.

Esto nos permitirá separar dos problemas que conviene no confundir:

1. **Cómo se dibuja un objeto 3D.**
2. **Cómo una GPU permite ejecutar ese trabajo de forma paralela.**

La GPU no cambia las matemáticas fundamentales del rasterizado. Lo que cambia, sobre todo, es **cómo organizamos y distribuimos el trabajo**.

---

## 1. El pipeline completo ya existe en la CPU

La versión CPU del cubo implementa aproximadamente este pipeline:

```text
         MODELO 3D
             │
             ▼
       8 vértices (x,y,z)
             │
             ▼
          rotación
             │
             ▼
   vértices transformados
             │
             ▼
     proyección perspectiva
             │
             ▼
       8 puntos (x,y)
             │
             ▼
       recorrer 6 caras
             │
             ▼
     back-face culling
             │
             ▼
  dividir cara en 2 triángulos
             │
             ▼
       bounding box
             │
             ▼
       edge functions
             │
             ▼
        rasterización
             │
             ▼
          putpixel
             │
             ▼
        framebuffer
             │
             ▼
           scanout
```

Este diagrama es importante porque, conceptualmente, **ya estamos haciendo gráficos 3D completos**.

Todavía no hay una GPU involucrada.

Eso nos enseña una primera idea fundamental:

> Una GPU no es necesaria para definir las matemáticas de los gráficos 3D. La GPU aparece cuando queremos ejecutar esas matemáticas y procesar grandes cantidades de datos de forma eficiente.

---

# 2. El cubo comienza siendo solamente ocho puntos

El cubo se almacena mediante ocho vértices tridimensionales.

En el programa CPU aparecen como:

```asm
vertices:
    .word -65536, -65536, -65536
    .word  65536, -65536, -65536
    .word -65536,  65536, -65536
    .word  65536,  65536, -65536
    .word -65536, -65536,  65536
    .word  65536, -65536,  65536
    .word -65536,  65536,  65536
    .word  65536,  65536,  65536
```

Los valores están expresados en formato de punto fijo. Conceptualmente podemos imaginar simplemente:

```text
(-1,-1,-1)
(+1,-1,-1)
(-1,+1,-1)
(+1,+1,-1)

(-1,-1,+1)
(+1,-1,+1)
(-1,+1,+1)
(+1,+1,+1)
```

Todavía no existen caras ni píxeles.

Solo tenemos ocho posiciones en un espacio tridimensional.

Podemos visualizarlo así:

```text
        6────────7
       /│       /│
      / │      / │
     2────────3  │
     │  │     │  │
     │  4─────│──5
     │ /      │ /
     │/       │/
     0────────1
```

Las caras del cubo se describen posteriormente indicando qué cuatro vértices forman cada una.

---

# 3. Rotar el objeto

Si dibujásemos siempre los mismos vértices, el cubo permanecería inmóvil.

Para animarlo modificamos sus coordenadas aplicando una rotación.

La versión CPU realiza este trabajo recorriendo secuencialmente los ocho vértices:

```text
vértice 0
    ↓
rotar
    ↓
proyectar

vértice 1
    ↓
rotar
    ↓
proyectar

...

vértice 7
    ↓
rotar
    ↓
proyectar
```

En ensamblador esto aparece como un bucle:

```asm
MOVI  R19, 8

vertex_loop:
    ...
    ; transformar vértice
    ...
    ADDI  R19, R19, -1
    BNE   R19, R0, vertex_loop
```

La CPU procesa un vértice después de otro.

Esta observación será muy importante más adelante.

Los ocho cálculos son prácticamente independientes:

```text
V0 ──► transform(V0)
V1 ──► transform(V1)
V2 ──► transform(V2)
V3 ──► transform(V3)
V4 ──► transform(V4)
V5 ──► transform(V5)
V6 ──► transform(V6)
V7 ──► transform(V7)
```

La CPU los ejecuta secuencialmente porque ese es el modelo de ejecución que estamos utilizando.

Pero el algoritmo ya nos está mostrando **paralelismo natural**.

Más adelante veremos que esta correspondencia resulta especialmente atractiva para MiniGPU:

```text
8 vértices
     ↕
8 lanes
```

Por ahora, sin embargo, continuaremos pensando como una CPU.

---

# 4. Del espacio 3D a la pantalla 2D

Después de rotar un vértice tenemos unas coordenadas tridimensionales:

```text
(x, y, z)
```

Pero el framebuffer es bidimensional.

Necesitamos convertir:

```text
(x, y, z)
```

en:

```text
(screen_x, screen_y)
```

Para ello utilizamos una proyección perspectiva.

De forma simplificada:

$$
screen_x = center_x + \frac{x \cdot focal}{z}
$$

$$
screen_y = center_y + \frac{y \cdot focal}{z}
$$

En nuestro ejemplo:

```text
center_x = 160
center_y = 120
focal    = 140
```

porque la pantalla es de 320×240 píxeles.

El código refleja directamente esta operación:

```asm
MUL   R11, R9, R13
DIV   R11, R11, R10
ADDI  R11, R11, 160

MUL   R12, R7, R13
DIV   R12, R12, R10
ADDI  R12, R12, 120
```

Por tanto, después de transformar los ocho vértices ya no necesitamos trabajar con el cubo exclusivamente como objeto tridimensional.

Tenemos ocho posiciones proyectadas:

```text
P0 = (x0,y0)
P1 = (x1,y1)
...
P7 = (x7,y7)
```

que viven en el espacio de la pantalla.

Esta frontera es conceptualmente importante:

```text
             GEOMETRÍA 3D

(x,y,z) ──► rotación ──► perspectiva
                              │
                              ▼

             RASTERIZACIÓN 2D

                         (screen_x,
                          screen_y)
```

El rasterizador que veremos a continuación no necesita saber que esos puntos pertenecían originalmente a un cubo tridimensional.

Para él son simplemente puntos 2D.

---

# 5. Construir las caras

Un conjunto de ocho puntos todavía no describe qué superficies forman el cubo.

Por eso existe una tabla de caras.

Cada cara contiene cuatro vértices:

```text
v0 ─────── v1
│           │
│           │
│           │
v3 ─────── v2
```

Pero nuestro rasterizador trabaja con triángulos.

Dividimos entonces el cuadrilátero en dos:

```text
v0 ─────── v1
│ \         │
│   \       │
│     \     │
v3 ─────── v2
```

obteniendo:

```text
T0 = (v0,v1,v2)
T1 = (v0,v2,v3)
```

Por tanto:

```text
6 caras × 2 triángulos/cara = 12 triángulos
```

como máximo.

¿Por qué triángulos?

Porque un triángulo tiene propiedades especialmente convenientes para el hardware y para el software:

- siempre es plano;
- siempre es convexo;
- queda completamente definido por tres vértices;
- podemos determinar fácilmente si un punto está dentro;
- sus atributos pueden interpolarse de forma sencilla.

Por eso el triángulo sigue siendo la primitiva fundamental de los rasterizadores modernos.

---

# 6. Antes de dibujar: back-face culling

Un cubo es un objeto cerrado.

Cuando lo observamos desde una determinada posición, aproximadamente la mitad de sus caras apuntan en dirección contraria a la cámara.

No tiene sentido rasterizarlas.

Podemos detectar esas caras utilizando el área orientada del triángulo proyectado.

Para tres puntos:

```text
P0 = (x0,y0)
P1 = (x1,y1)
P2 = (x2,y2)
```

calculamos:

$$
area =
(x_1-x_0)(y_2-y_0)
-
(y_1-y_0)(x_2-x_0)
$$

El signo nos indica la orientación del triángulo en pantalla.

En el programa aparece literalmente:

```asm
SUB   R15, R11, R9
SUB   R16, R14, R10
MUL   R17, R15, R16

SUB   R15, R12, R10
SUB   R16, R13, R9
MUL   R18, R15, R16

SUB   R17, R17, R18
```

y después:

```asm
BGE   R0, R17, face_done
```

Si el área tiene la orientación que hemos definido como trasera, descartamos la cara completa.

Esta operación recibe el nombre de:

**back-face culling**.

El pipeline se ha convertido entonces en:

```text
12 triángulos potenciales
          │
          ▼
   orientación/área
          │
     ┌────┴────┐
     │         │
 trasero     visible
     │         │
 descartar     ▼
           rasterizar
```

El convenio exacto del signo depende del orden de los vértices y del sentido de los ejes de pantalla. En este ejemplo, la tabla de caras está construida teniendo en cuenta que el eje Y de pantalla crece hacia abajo.

---

# 7. Hemos llegado al verdadero problema del rasterizador

Supongamos que después de proyectar obtenemos un triángulo:

```text
             P1
             /\
            /  \
           /    \
          /      \
         /        \
        /          \
       P0──────────P2
```

Tenemos las coordenadas de sus tres vértices.

Pero el framebuffer no entiende triángulos.

El framebuffer entiende píxeles.

Necesitamos transformar:

```text
tres vértices
```

en algo parecido a:

```text
píxel (104,72)  → rojo
píxel (105,72)  → rojo
píxel (106,72)  → rojo
píxel (103,73)  → rojo
...
```

Ese proceso es la **rasterización**.

Y aquí aparece una pregunta fundamental:

> Dado un píxel `(x,y)`, ¿cómo sabemos si está dentro del triángulo?

---

# 8. Las funciones de borde

Cada una de las tres aristas de un triángulo divide el plano en dos semiplanos.

Podemos construir una función matemática que nos indique en cuál de ellos se encuentra un punto.

Para una arista podemos escribir:

$$
E(x,y)=Ax+By+C
$$

donde los coeficientes dependen de sus dos vértices.

Para una arista que va de:

```text
Pa = (xa,ya)
```

a:

```text
Pb = (xb,yb)
```

una forma habitual es:

$$
A = y_a-y_b
$$

$$
B = x_b-x_a
$$

$$
C = x_a y_b-x_b y_a
$$

y por tanto:

$$
E(x,y)=Ax+By+C
$$

Dependiendo del orden de los vértices, un punto situado en el lado interior de la arista producirá un valor positivo o negativo.

Si hemos elegido consistentemente el orden de los vértices, podemos comprobar un triángulo mediante:

```text
E0(x,y) >= 0
        AND
E1(x,y) >= 0
        AND
E2(x,y) >= 0
```

Gráficamente:

```text
                   E1
                  /
                 /
             +--/----+
             | /     |
         E0  |/      |   zona que satisface
             /\      |   las tres condiciones
            /  \     |
           /    \    |
          +------+---+
              E2
```

La intersección de los tres semiplanos es precisamente el triángulo.

Esta es una idea extraordinariamente potente.

Hemos convertido la pregunta:

```text
¿está este píxel dentro de una figura?
```

en tres operaciones aritméticas y tres comparaciones.

---

# 9. No queremos comprobar toda la pantalla

Una posibilidad extremadamente sencilla sería:

```text
for y = 0 .. 239:
    for x = 0 .. 319:
        comprobar E0
        comprobar E1
        comprobar E2
```

Funcionaría.

Pero para un triángulo pequeño estaríamos comprobando decenas de miles de píxeles que evidentemente están muy lejos de él.

Por eso calculamos primero su **bounding box**:

```text
minX = min(x0,x1,x2)
maxX = max(x0,x1,x2)

minY = min(y0,y1,y2)
maxY = max(y0,y1,y2)
```

Obtenemos un rectángulo:

```text
        minX                 maxX
          │                    │
          ▼                    ▼

minY  ─── +--------------------+
          |         /\         |
          |        /  \        |
          |       /    \       |
          |      /      \      |
          |     /________\     |
maxY  ─── +--------------------+
```

Ahora solo examinamos los píxeles contenidos en ese rectángulo.

El código CPU comienza precisamente `fill_triangle` calculando esos cuatro límites.

---

# 10. El rasterizador secuencial más sencillo

Llegados a este punto podríamos implementar:

```text
for y = minY .. maxY:
    for x = minX .. maxX:

        E0 = edge0(x,y)
        E1 = edge1(x,y)
        E2 = edge2(x,y)

        if E0 >= 0 and
           E1 >= 0 and
           E2 >= 0:

            putpixel(x,y,color)
```

Esto ya sería un rasterizador correcto.

Pero tendría un problema.

Calcular cada función:

$$
E(x,y)=Ax+By+C
$$

desde cero para cada píxel implica multiplicaciones repetidas.

Y resulta que no hacen falta.

---

# 11. La propiedad incremental de las edge functions

Partimos de:

$$
E(x,y)=Ax+By+C
$$

¿Qué ocurre al movernos un píxel hacia la derecha?

$$
E(x+1,y)=A(x+1)+By+C
$$

Desarrollando:

$$
E(x+1,y)=Ax+By+C+A
$$

por tanto:

$$
E(x+1,y)=E(x,y)+A
$$

Lo mismo sucede verticalmente:

$$
E(x,y+1)=E(x,y)+B
$$

Esta propiedad cambia completamente el coste del rasterizador.

Solo necesitamos calcular la función completa al comienzo.

Después podemos recorrer los píxeles mediante sumas.

```text
          x → x+1 → x+2 → x+3

E0        +A    +A    +A
E1        +A1   +A1   +A1
E2        +A2   +A2   +A2

y
│
▼         +B
y+1
```

La versión CPU utiliza una formulación equivalente basada en `dx` y `dy`.

Al avanzar horizontalmente:

```asm
SUB   R12, R12, R21
SUB   R13, R13, R23
SUB   R14, R14, R28
```

Es decir:

```text
E += -dy
```

Y al avanzar verticalmente:

```asm
ADD   R9,  R9,  R20
ADD   R10, R10, R22
ADD   R11, R11, R25
```

es decir:

```text
E_row += dx
```

Las multiplicaciones se utilizan para calcular los valores iniciales de las tres funciones de borde.

Después, el recorrido del triángulo es fundamentalmente:

**sumas, comparaciones y saltos.**

Esta característica será importantísima cuando llevemos el algoritmo a MiniGPU.

---

# 12. El corazón de `fill_triangle`

Una vez inicializadas las tres funciones de borde, la estructura real del rasterizador CPU es muy sencilla.

Conceptualmente:

```text
for y = minY .. maxY:

    E0 = E0_row
    E1 = E1_row
    E2 = E2_row

    for x = minX .. maxX:

        if E0 >= 0 &&
           E1 >= 0 &&
           E2 >= 0:

            putpixel(x,y,color)

        E0 += stepX0
        E1 += stepX1
        E2 += stepX2

    E0_row += stepY0
    E1_row += stepY1
    E2_row += stepY2
```

Y esto es prácticamente una traducción directa del ensamblador:

```asm
@tri_pixel:
    BLT   R12, R0, @tri_skip
    BLT   R13, R0, @tri_skip
    BLT   R14, R0, @tri_skip

    JAL   R30, putpixel

@tri_skip:
    SUB   R12, R12, R21
    SUB   R13, R13, R23
    SUB   R14, R14, R28

    ADDI  R4, R4, 1
    BGE   R16, R4, @tri_pixel
```

Lo más importante aquí no es memorizar los registros.

Es reconocer el algoritmo:

```text
              ┌─────────────────┐
              │ ¿E0,E1,E2 >= 0? │
              └────────┬────────┘
                       │
              ┌────────┴────────┐
             sí                 no
              │                  │
              ▼                  │
          putpixel               │
              │                  │
              └────────┬─────────┘
                       ▼
                 avanzar E
                       │
                       ▼
                  siguiente x
```

Este pequeño bucle contiene el núcleo del rasterizador que posteriormente paralelizaremos.

---

# 13. De un píxel al framebuffer

Cuando las tres funciones de borde indican que el punto está dentro del triángulo, el programa llama a:

```asm
putpixel
```

Conceptualmente:

```text
putpixel(x,y,color)
```

termina convirtiéndose en una dirección de memoria del framebuffer.

Si ignoramos por un momento el empaquetado de RGB565, la idea es:

$$
address =
framebuffer +
y \cdot stride +
x \cdot bytesPerPixel
$$

Para nuestra pantalla:

```text
320 píxeles/fila
2 bytes/píxel
```

por tanto:

$$
stride=320\times2=640\text{ bytes}
$$

que es precisamente el valor que conserva el programa:

```asm
MOVI R24, 640
```

Por tanto hemos completado toda la transformación:

```text
                 (x,y,z)
                    │
                    ▼
                 rotación
                    │
                    ▼
                perspectiva
                    │
                    ▼
             (screen_x,screen_y)
                    │
                    ▼
                 triángulo
                    │
                    ▼
              edge functions
                    │
                    ▼
             píxel interior
                    │
                    ▼
                putpixel
                    │
                    ▼
       dirección del framebuffer
                    │
                    ▼
                  STORE
```

Ya podemos dibujar un cubo sólido.

Y seguimos sin necesitar una GPU.

---

# 14. Limpiar el frame anterior

Hay otro detalle que será importante más adelante.

El framebuffer contiene memoria persistente.

Si en el frame anterior el cubo ocupaba:

```text
       ███████
       ███████
       ███████
```

y en el nuevo frame se ha desplazado o rotado:

```text
             ███████
             ███████
             ███████
```

dibujar únicamente el nuevo cubo no elimina automáticamente los píxeles antiguos.

Hay que limpiar la región anterior.

La versión CPU limpia inicialmente los dos buffers completos y después, en cada frame, limpia una caja fija alrededor de la región donde puede aparecer el cubo.

Conceptualmente:

```text
frame:

    obtener back buffer

    limpiar región
          │
          ▼
    transformar vértices
          │
          ▼
    rasterizar caras
          │
          ▼
        swap
```

Esta operación parece secundaria, pero más adelante veremos que el borrado puede representar una cantidad significativa de tráfico de memoria.

De hecho, una de las optimizaciones que aparecerá mucho más tarde, en v8, consistirá precisamente en reducir esa región de borrado.

---

# 15. Double buffering

La CPU no dibuja directamente sobre el framebuffer que está siendo mostrado.

Trabaja sobre el **back buffer**.

Podemos imaginar:

```text
         SCANOUT
            │
            ▼
     ┌──────────────┐
     │ FRONT BUFFER │
     │              │
     │ frame N      │
     └──────────────┘


           CPU
            │
            ▼
     ┌──────────────┐
     │ BACK BUFFER  │
     │              │
     │ frame N+1    │
     └──────────────┘
```

Cuando termina de renderizar:

```text
              SWAP
                │
                ▼

 FRONT <────────────────> BACK
```

El frame recién terminado pasa a ser mostrado y el buffer anterior queda disponible para construir un nuevo frame.

Esto separa dos actividades diferentes:

```text
renderizado → escribe framebuffer

scanout     → lee framebuffer
```

y evita modificar arbitrariamente la imagen mientras el sistema de vídeo la está recorriendo.

Esta arquitectura seguirá siendo exactamente igual cuando sustituyamos la CPU por MiniGPU.

---

# 16. ¿Dónde está el problema?

Nuestro rasterizador CPU funciona.

Entonces, ¿para qué queremos una GPU?

Observemos dónde está el trabajo.

Primero tenemos ocho vértices:

```text
V0 V1 V2 V3 V4 V5 V6 V7
```

y hacemos:

```text
transform(V0)
transform(V1)
transform(V2)
...
transform(V7)
```

Pero estas transformaciones son independientes.

Después tenemos muchos píxeles:

```text
P0 P1 P2 P3 P4 P5 ... Pn
```

y para cada uno hacemos esencialmente:

```text
inside(P0)?
inside(P1)?
inside(P2)?
...
inside(Pn)?
```

También son, en gran medida, cálculos independientes.

El algoritmo contiene por tanto una enorme cantidad de **paralelismo de datos**.

La CPU que acabamos de utilizar lo expresa como:

```text
hacer A
después B
después C
después D
...
```

Pero matemáticamente muchas de esas operaciones podrían realizarse simultáneamente:

```text
       ┌──► A
       ├──► B
───────┼──► C
       ├──► D
       └──► ...
```

Y aquí aparece por fin la GPU.

---

# 17. El primer impulso: repartir los píxeles

Una vez entendido el rasterizador secuencial, podemos formular una idea muy sencilla:

> Si tenemos muchos elementos de ejecución, ¿por qué no hacemos que distintos threads procesen distintos píxeles?

La CPU hacía:

```text
CPU

pixel 0
   ↓
pixel 1
   ↓
pixel 2
   ↓
pixel 3
   ↓
...
```

Con múltiples threads podríamos intentar:

```text
thread 0 ──► píxeles ...
thread 1 ──► píxeles ...
thread 2 ──► píxeles ...
thread 3 ──► píxeles ...
...
thread 63 ─► píxeles ...
```

Esta idea es el punto de partida de nuestra primera versión verdaderamente GPU del rasterizador.

Pero pronto descubriremos que simplemente decir:

**“tengo 64 threads, reparto el trabajo entre 64”**

no es suficiente.

También tendremos que preguntarnos:

- ¿qué píxeles procesa cada thread?
- ¿qué threads ejecutan juntos?
- ¿cómo se agrupan en warps?
- ¿qué representa una lane?
- ¿qué ocurre si unas lanes entran en un `if` y otras no?
- ¿qué direcciones de memoria genera cada lane?
- ¿puede el LSU combinar varios accesos?
- ¿cómo hacemos que las escrituras sean coalescentes?
- ¿qué datos conviene calcular una sola vez?
- ¿cómo sincronizamos distintas fases del frame?

Es decir, pasaremos de estudiar únicamente un **algoritmo gráfico** a estudiar también su **mapeo sobre una arquitectura paralela**.

---

# 18. La transición fundamental

Conviene detenerse aquí porque hemos alcanzado una frontera conceptual importante.

Hasta este punto nuestra pregunta era:

> **¿Cómo se dibuja un triángulo?**

La respuesta ha sido:

```text
vértices
   ↓
proyección
   ↓
triángulos
   ↓
bounding box
   ↓
edge functions
   ↓
recorrer píxeles
   ↓
putpixel
```

A partir de ahora la pregunta será diferente:

> **¿Cómo reorganizamos ese trabajo para ejecutarlo eficientemente sobre MiniGPU?**

No vamos a cambiar las matemáticas fundamentales.

Seguiremos teniendo:

```text
E0
E1
E2
```

seguiremos preguntando:

```text
E0 >= 0 &&
E1 >= 0 &&
E2 >= 0
```

y seguiremos terminando escribiendo RGB565 en el framebuffer.

Lo que cambiará será la organización del trabajo.

Por ejemplo, el rasterizador CPU avanza naturalmente:

```text
x
x+1
x+2
x+3
x+4
...
```

Pero MiniGPU tiene ocho lanes y el framebuffer almacena dos píxeles RGB565 dentro de cada palabra de 32 bits.

Eso hará que más adelante nos interese pensar en bloques como:

```text
lane 0 → píxeles  0, 1
lane 1 → píxeles  2, 3
lane 2 → píxeles  4, 5
lane 3 → píxeles  6, 7
lane 4 → píxeles  8, 9
lane 5 → píxeles 10,11
lane 6 → píxeles 12,13
lane 7 → píxeles 14,15
```

De repente, una propiedad matemática que en la CPU decía:

$$
E(x+1,y)=E(x,y)+A
$$

acabará produciendo relaciones como:

$$
E(x+16,y)=E(x,y)+16A
$$

No porque la geometría haya cambiado.

No porque el triángulo sea diferente.

Sino porque **hemos adaptado el recorrido del mismo algoritmo a la organización de nuestra máquina**.

Esta distinción será una de las ideas centrales de todo lo que sigue.

---

# 19. Lo que debemos conservar de la versión CPU

Antes de pasar a v3, podemos reducir todo el programa anterior a unas pocas ideas fundamentales.

El pipeline gráfico es:

```text
modelo 3D
    │
    ▼
transformación
    │
    ▼
proyección
    │
    ▼
triángulos 2D
    │
    ▼
culling
    │
    ▼
triangle setup
    │
    ▼
rasterización
    │
    ▼
píxeles RGB565
    │
    ▼
framebuffer
    │
    ▼
scanout
```

El núcleo matemático del rasterizador es:

$$
E_i(x,y)=A_i x+B_i y+C_i
$$

para las tres aristas, y un píxel pertenece al triángulo cuando satisface las tres condiciones de cobertura.

La optimización matemática fundamental es:

$$
E(x+1,y)=E(x,y)+A
$$

$$
E(x,y+1)=E(x,y)+B
$$

Y el problema arquitectónico que tenemos delante es:

```text
                ALGORITMO SECUENCIAL

                     for y
                       │
                       ▼
                     for x
                       │
                       ▼
                 edge tests
                       │
                       ▼
                   putpixel


                       │
                       │
                       ▼


             ¿CÓMO LO PARALELIZAMOS?


                       │
                       ▼

                MINIGPU / SIMT
```

Esta es precisamente la pregunta que intentarán responder las siguientes versiones.

La primera respuesta no será perfecta.

Tampoco queremos que lo sea.

Comenzaremos con una distribución relativamente sencilla del rasterizado entre los threads de MiniGPU. Después iremos descubriendo sus problemas y, versión a versión, reorganizaremos el algoritmo para aprovechar mejor los warps, las lanes, el LSU y la memoria.

Ese recorrido —más que el cubo en sí— es lo que nos permitirá entender **por qué una GPU acaba teniendo la arquitectura que tiene**.

---

# Parte XV — v3: nuestro primer rasterizador paralelo

## 25. La filosofía de v3

La v3 representa un punto de partida muy interesante porque la geometría ya está preparada.

No le pedimos todavía a la MiniGPU que piense:

> “¿dónde queda este vértice después de rotar el cubo?”

Los frames contienen descriptores precalculados.

Eso nos permite aislar el problema del **rasterizado**.

La estructura general es aproximadamente:

```text
frame precomputado
        |
        v
6 descriptores de triángulo
        |
        v
64 threads
        |
        v
tests de cobertura
        |
        v
RGB565
        |
        v
framebuffer
```

Cada thread procesa sus propias palabras del framebuffer.

Esta es una decisión pedagógicamente muy buena: antes de complicarnos con matrices, rotaciones y proyección, podemos estudiar cómo una GPU convierte triángulos 2D ya preparados en píxeles.

---

## 26. Dos píxeles de una vez

Recordemos nuestra palabra de 32 bits:

```text
+----------------+----------------+
| pixel impar    | pixel par      |
+----------------+----------------+
```

La v3 trabaja por palabras, no por píxeles individuales.

Para cada palabra debe comprobar los dos píxeles.

Conceptualmente:

```text
color0 = background
color1 = background

for triangle in triangles:

    if pixel0 inside triangle:
        color0 = triangle.color

    if pixel1 inside triangle:
        color1 = triangle.color

word = color1 << 16 | color0

STORE word
```

Esto explica por qué el código evalúa las edge functions para dos posiciones horizontales relacionadas.

La unidad natural de almacenamiento es una palabra de 32 bits, aunque la unidad visual siga siendo el píxel.

---

## 27. El gran coste oculto de v3

La estrategia tiene una ventaja:

```text
una palabra → un STORE final
```

y no necesita borrar previamente.

Pero observemos el trabajo:

```text
WORD 0
    triangle 0
    triangle 1
    triangle 2
    triangle 3
    triangle 4
    triangle 5

WORD 1
    triangle 0
    triangle 1
    triangle 2
    triangle 3
    triangle 4
    triangle 5

WORD 2
    triangle 0
    ...
```

Para cada palabra volvemos a recorrer los seis triángulos.

Y eso implica volver a obtener la información necesaria para evaluarlos.

La v3 recorre una región fija de 448 palabras por thread y, para cada palabra, entra en el bucle de los seis triángulos.

Aquí encontramos un patrón que será fundamental durante todo el desarrollo:

> Una primera implementación puede tener muchísimo paralelismo y seguir haciendo demasiado trabajo.

**Paralelizar trabajo innecesario no hace que deje de ser innecesario.**

---

# Parte XVI — v4: cambiar el orden de los bucles

## 28. La gran idea de v4

La v4 realiza un cambio conceptual enorme.

En vez de:

```text
for cada palabra:
    for cada triángulo:
        test
```

hace:

```text
for cada triángulo:
    for las palabras de su bounding box:
        test
```

Parece simplemente intercambiar dos bucles.

Pero las consecuencias son profundas.

Ahora podemos:

1. cargar el descriptor del triángulo una vez;
2. utilizar su bounding box;
3. ignorar enormes regiones donde sabemos que el triángulo no existe;
4. aprovechar las edge functions incrementales;
5. organizar los threads para realizar accesos consecutivos a memoria.

El propio encabezado de v4 resume exactamente esta transformación: se procesa un triángulo completo antes de pasar al siguiente, el descriptor se carga una sola vez, solo se recorre su bounding box y las funciones de borde se actualizan mediante sumas.

Esta será nuestra primera gran lección de arquitectura GPU:

> **La forma de expresar y ordenar el algoritmo importa tanto como la cantidad de unidades de ejecución disponibles.**

---

## 29. Pero hemos perdido algo

En v3 cada palabra terminaba con un color definitivo.

Por eso podíamos escribir fondo cuando ningún triángulo la cubría.

En v4 hacemos algo diferente:

```text
triangle 0 → modifica algunos píxeles
triangle 1 → modifica otros
triangle 2 → modifica otros
...
```

¿Qué ocurre con los píxeles que no cubre ningún triángulo?

Nadie los toca.

Si el framebuffer contiene la imagen anterior, seguiríamos viendo restos del frame anterior.

Por tanto, v4 necesita primero:

```text
CLEAR
```

y después:

```text
RASTER
```

Conceptualmente:

```text
FRAME N

+-------------------+
| imagen antigua    |
+-------------------+
          |
          | clear
          v
+-------------------+
| fondo             |
+-------------------+
          |
          | triángulo 0
          | triángulo 1
          | ...
          v
+-------------------+
| imagen nueva      |
+-------------------+
```

La v4 realiza precisamente una pasada de borrado antes de rasterizar los triángulos.

Así aparece un trade-off.

v3:

```text
+ no necesita clear
- prueba todos los triángulos para cada palabra
```

v4:

```text
+ rasteriza solamente bounding boxes
+ descriptor cargado una vez
+ edge functions incrementales
- necesita clear
```

Este tipo de intercambio es exactamente lo que estudiaremos durante todo el documento.

No existe una optimización aislada de la arquitectura.

Reducir trabajo en un lugar puede crear trabajo en otro.

---

# Parte XVII — La primera imagen de una GPU

## 30. Lo que hemos construido hasta ahora

Sin haber hablado todavía en detalle de warps, lanes o scheduling, ya podemos dibujar una arquitectura conceptual:

```text
                 GEOMETRÍA
                    |
                    v
             +-------------+
             | vértices 3D |
             +-------------+
                    |
             rotar/proyectar
                    |
                    v
             +-------------+
             | vértices 2D |
             +-------------+
                    |
          culling + setup
                    |
                    v
        +-----------------------+
        | triangle descriptors  |
        +-----------------------+
                    |
                    v
            +---------------+
            | rasterizador  |
            +---------------+
                    |
          edge tests / color
                    |
                    v
            +---------------+
            | framebuffer   |
            +---------------+
                    |
                    v
               SCANOUT
                    |
                    v
                PANTALLA
```

Y ya podemos identificar dos formas diferentes de paralelismo.

En geometría:

```text
V0 V1 V2 V3 V4 V5 V6 V7
 |  |  |  |  |  |  |  |
 v  v  v  v  v  v  v  v
misma transformación
```

En rasterización:

```text
P0 P1 P2 P3 P4 P5 P6 P7 ...
 |  |  |  |  |  |  |  |
 v  v  v  v  v  v  v  v
mismos edge tests
```

Este patrón repetido de:

> **misma operación, muchos datos**

es una de las claves que explican la arquitectura de las GPU.

Pero todavía falta una pregunta fundamental:

**¿Cómo representa MiniGPU esos 64 trabajos paralelos físicamente?**

Para responderla tendremos que introducir threads, lanes, warps, ejecución SIMT y coalescing de memoria.

Y ahí podremos volver a v4 y entender por qué esta aparentemente extraña distribución:

```text
lane 0 → word 0
lane 1 → word 1
lane 2 → word 2
...
lane 7 → word 7
```

no es accidental, sino una decisión central para el rendimiento del rasterizador.

---

# 31. Lo aprendido hasta aquí

Antes de continuar conviene comprobar que la cadena conceptual está completa.

Nuestro cubo empieza como **ocho vértices tridimensionales**.

Esos vértices se transforman para producir la rotación.

Después se proyectan sobre la pantalla, convirtiendo coordenadas 3D en coordenadas 2D.

Los vértices forman caras y las caras se dividen en triángulos.

Las caras orientadas en dirección contraria pueden descartarse mediante back-face culling.

Para cada triángulo visible podemos calcular un descriptor que contiene sus tres edge functions, color y bounding box.

El rasterizador recorre esa bounding box.

Las tres edge functions permiten decidir si cada píxel está dentro o fuera del triángulo.

Como las funciones tienen la forma:

\[
E(x,y)=Ax+By+C
\]

podemos desplazarnos horizontal y verticalmente actualizándolas mediante simples sumas.

Los píxeles resultantes se codifican en RGB565.

MiniGPU empaqueta dos píxeles RGB565 en cada palabra de 32 bits.

Esas palabras se escriben en el framebuffer.

Y el contenido del framebuffer es finalmente lo que terminará siendo mostrado.

Podemos condensar todo el proceso en una sola línea:

\[
\boxed{
\text{vértices 3D}
\rightarrow
\text{vértices 2D}
\rightarrow
\text{triángulos}
\rightarrow
\text{cobertura}
\rightarrow
\text{RGB565}
\rightarrow
\text{memoria}
\rightarrow
\text{pantalla}
}
\]

La GPU no “ve” un cubo.

No existe en su interior ningún concepto mágico de “cubo”.

En diferentes momentos solo existen números:

```text
(x,y,z)

(sx,sy)

A,B,C

minX,maxX,minY,maxY

RGB565

dirección de memoria
```

El cubo aparece porque hemos diseñado una secuencia de cálculos que transforma una descripción geométrica en los valores correctos del framebuffer.

Ese es el punto de partida para entender una GPU gráfica.

En la siguiente parte dejaremos de mirar únicamente el algoritmo y empezaremos a mirar **la máquina que lo ejecuta**.

Veremos cómo los 64 threads de MiniGPU se organizan en warps y lanes, por qué SIMT permite explotar el paralelismo del rasterizado, qué ocurre cuando las lanes toman caminos diferentes, por qué las direcciones de memoria consecutivas son tan importantes y cómo v4 organiza deliberadamente el framebuffer para obtener accesos BL8 coalesced.

Después utilizaremos esa arquitectura para desmontar el rasterizador v4 prácticamente paso a paso, desde `GETTID` hasta el `STORE` de ocho palabras consecutivas.

# Parte XVIII — De un algoritmo paralelo a una GPU

## 32. Tenemos trabajo paralelo. Ahora necesitamos organizarlo

Al terminar la primera parte habíamos llegado a una conclusión importante.

Tanto el procesamiento de vértices como el rasterizado contienen muchas operaciones independientes:

```text
V0 → transformar
V1 → transformar
V2 → transformar
...

P0 → comprobar
P1 → comprobar
P2 → comprobar
...
```

Una CPU convencional podría realizar todas estas operaciones secuencialmente.

Una primera idea para acelerarlas sería simplemente disponer de muchos procesadores independientes:

```text
CPU0 → P0
CPU1 → P1
CPU2 → P2
CPU3 → P3
...
```

Pero esto sería caro.

Cada procesador necesitaría buena parte de la lógica necesaria para buscar, decodificar y ejecutar sus propias instrucciones.

Y además estaríamos desperdiciando una información muy valiosa:

> En gráficos, muchas veces queremos ejecutar **la misma instrucción sobre datos diferentes**.

Por ejemplo, ocho píxeles pueden necesitar simultáneamente:

```text
E0 += step
```

pero cada uno tiene un valor distinto de `E0`.

No necesitamos necesariamente ocho máquinas independientes ejecutando ocho programas diferentes.

Podemos compartir parte del control.

Esta idea nos lleva primero a SIMD y después al modelo SIMT utilizado por MiniGPU.

---

# 33. SIMD: una instrucción, varios datos

SIMD significa:

**Single Instruction, Multiple Data**

Podemos imaginar una instrucción:

```text
ADD R3, R1, R2
```

que conceptualmente actúa sobre varios elementos simultáneamente:

```text
lane 0: R3[0] = R1[0] + R2[0]
lane 1: R3[1] = R1[1] + R2[1]
lane 2: R3[2] = R1[2] + R2[2]
lane 3: R3[3] = R1[3] + R2[3]
...
```

Todas las lanes ejecutan el mismo `ADD`.

Pero los datos son diferentes.

Podemos representarlo así:

```text
                    ADD R3,R1,R2
                          |
          +-------+-------+-------+-------+
          |       |       |       |       |
          v       v       v       v       v

lane      0       1       2      ...      7

R1       12      25      -3              91
R2        4       7      10               2
          |       |       |               |
          v       v       v               v
R3       16      32       7              93
```

Una única instrucción describe mucho trabajo.

Esto resulta extremadamente atractivo para gráficos.

---

# 34. Una lane no es un thread

Aquí conviene separar dos conceptos que inicialmente pueden confundirse.

Una **lane** representa una posición dentro de la ejecución paralela de una instrucción.

Un **thread** representa conceptualmente una instancia del programa.

MiniGPU permite que pensemos en threads:

```text
thread 0
thread 1
thread 2
...
```

Cada uno posee su propio estado arquitectónico relevante, por ejemplo sus registros.

Así podemos escribir conceptualmente:

```text
GETTID R1
```

y cada thread obtiene un resultado diferente:

```text
thread 0 → R1 = 0
thread 1 → R1 = 1
thread 2 → R1 = 2
...
```

Pero esos threads no tienen por qué ejecutarse mediante CPUs completamente independientes.

Podemos agruparlos.

---

# 35. Warp: un grupo de threads que avanza conjuntamente

En nuestros ejemplos de MiniGPU aparecen 64 threads organizados en grupos de 8.

A cada grupo lo llamaremos **warp**.

Por tanto:

\[
64\ threads / 8\ lanes = 8\ warps
\]

Conceptualmente:

```text
WARP 0
+----+----+----+----+----+----+----+----+
| T0 | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
+----+----+----+----+----+----+----+----+
  L0   L1   L2   L3   L4   L5   L6   L7


WARP 1
+-----+-----+-----+-----+-----+-----+-----+-----+
| T8  | T9  | T10 | T11 | T12 | T13 | T14 | T15 |
+-----+-----+-----+-----+-----+-----+-----+-----+
  L0    L1    L2    L3    L4    L5    L6    L7


...


WARP 7
+-----+-----+-----+-----+-----+-----+-----+-----+
| T56 | T57 | T58 | T59 | T60 | T61 | T62 | T63 |
+-----+-----+-----+-----+-----+-----+-----+-----+
```

Por tanto existen dos identificadores que nos interesarán mucho:

```text
lane_id = thread_id & 7
warp_id = thread_id >> 3
```

Esto es exactamente lo que hace el rasterizador de v4.

Así:

```text
tid   warp   lane

 0      0      0
 1      0      1
 2      0      2
 ...
 7      0      7

 8      1      0
 9      1      1
 ...
15      1      7

...

63      7      7
```

Esta pequeña descomposición será la clave para entender cómo v4 reparte la pantalla.

---

# 36. SIMT: programar threads, ejecutar grupos

Aquí aparece una idea especialmente importante.

Desde el punto de vista del programador podemos razonar como si cada thread ejecutase el programa:

```text
thread 0:
    instrucciones...

thread 1:
    instrucciones...

thread 2:
    instrucciones...
```

Pero el hardware agrupa threads y ejecuta sus instrucciones conjuntamente.

A este modelo se le suele llamar **SIMT**:

**Single Instruction, Multiple Threads.**

Para nuestro propósito podemos verlo como una forma cómoda de programar una máquina con ejecución SIMD.

En lugar de escribir explícitamente:

```text
ADD vectorR3, vectorR1, vectorR2
```

escribimos un programa aparentemente escalar:

```text
ADD R3, R1, R2
```

y cada lane lo ejecuta sobre los registros correspondientes a su thread.

Conceptualmente:

```text
                 instrucción ADD
                       |
      +----------------+----------------+
      |       |        |       |        |
      v       v        v       v        v

    thread0 thread1  thread2  ...     thread7
       |       |        |               |
       v       v        v               v
     datos0  datos1   datos2          datos7
```

Esto tiene una ventaja enorme para nuestro rasterizador.

Podemos escribir **un solo programa** que diga:

> calcula las edge functions del píxel que te corresponde.

Y hacer que cada lane tenga coordenadas diferentes.

---

# 37. El problema que queremos resolver con v4

Recordemos el rasterizador de v4.

Tenemos un triángulo y su bounding box:

```text
+--------------------------------+
|                                |
|             /\                 |
|            /  \                |
|           /    \               |
|          /      \              |
|         /        \             |
|        /__________\            |
|                                |
+--------------------------------+
```

Queremos recorrer las palabras de 32 bits de esa caja.

Cada palabra contiene dos píxeles:

```text
word 0       word 1       word 2       word 3
+--+--+      +--+--+      +--+--+      +--+--+
|P0|P1|      |P2|P3|      |P4|P5|      |P6|P7|
+--+--+      +--+--+      +--+--+      +--+--+
```

Ahora tenemos ocho lanes.

Una distribución natural sería:

```text
lane 0 → word 0
lane 1 → word 1
lane 2 → word 2
lane 3 → word 3
lane 4 → word 4
lane 5 → word 5
lane 6 → word 6
lane 7 → word 7
```

Esto significa que un warp procesa simultáneamente:

\[
8\ palabras\times2\ píxeles=16\ píxeles
\]

horizontalmente.

Y aquí aparece algo muy bonito: esta distribución no solo proporciona paralelismo aritmético.

También produce **direcciones consecutivas de memoria**.

---

# Parte XIX — La memoria también determina la arquitectura

## 38. Ocho lanes haciendo STORE

Supongamos que una palabra ocupa 4 bytes.

Si `lane 0` escribe en la dirección:

```text
0x1000
```

podemos hacer que las siguientes lanes escriban:

```text
lane 0 → 0x1000
lane 1 → 0x1004
lane 2 → 0x1008
lane 3 → 0x100C
lane 4 → 0x1010
lane 5 → 0x1014
lane 6 → 0x1018
lane 7 → 0x101C
```

Tenemos ocho accesos de 32 bits perfectamente consecutivos.

En vez de considerar esto como ocho operaciones de memoria completamente independientes, el LSU puede reconocer el patrón y tratarlo como una transferencia agrupada.

En los comentarios de v4 se describe precisamente esta intención: las ocho lanes escriben ocho palabras consecutivas para que el LSU pueda utilizar el acceso coalesced `BL8`.

Esta operación se denomina normalmente **coalescing**.

---

# 39. Qué significa coalescer accesos

Supongamos que tenemos estas peticiones:

```text
L0 → A
L1 → A+4
L2 → A+8
L3 → A+12
L4 → A+16
L5 → A+20
L6 → A+24
L7 → A+28
```

Podemos reconocer que forman una región continua:

```text
A                                             A+31
|                                                |
v                                                v

+----+----+----+----+----+----+----+----+
| L0 | L1 | L2 | L3 | L4 | L5 | L6 | L7 |
+----+----+----+----+----+----+----+----+
       8 × 32 bits = 32 bytes
```

Eso es mucho más conveniente para el subsistema de memoria que un patrón como:

```text
L0 → 0x1000
L1 → 0x5328
L2 → 0x2014
L3 → 0xA004
...
```

La lección es importante:

> En una GPU no basta con repartir correctamente los cálculos. También interesa repartirlos de manera que los threads vecinos accedan a memoria de forma favorable.

Esta es una diferencia conceptual importante respecto a pensar únicamente en “muchos procesadores”.

---

# 40. La pantalla y el warp encajan horizontalmente

Recordemos que tenemos 320 píxeles por fila.

Como cada palabra contiene dos:

\[
320/2=160\ palabras
\]

Un warp procesa ocho palabras consecutivas:

\[
8\times2=16\ píxeles
\]

Así podemos imaginar una fila:

```text
píxeles:

 0                                      15
 |                                       |
 v                                       v
+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+
|  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+--+

 \___/ \___/ \___/ \___/ \___/ \___/ \___/ \___/
  L0    L1    L2    L3    L4    L5    L6    L7

             UN WARP
```

Cada lane procesa dos píxeles porque controla una palabra RGB565 de 32 bits.

Esta organización aparecerá una y otra vez en el ensamblador de v4.

---

# Parte XX — ¿Y qué hacen los ocho warps?

## 41. Repartir también la dimensión vertical

Tenemos ocho warps.

Podríamos hacer:

```text
warp 0 → fila y
warp 1 → fila y+1
warp 2 → fila y+2
...
warp 7 → fila y+7
```

Entonces los 64 threads cubren conceptualmente una región de:

\[
16\ píxeles \times 8\ filas
\]

aunque el recorrido horizontal de cada warp continuará posteriormente.

Podemos dibujarlo:

```text
             16 píxeles procesados por warp

         <---------------------------->

warp 0   L0 L1 L2 L3 L4 L5 L6 L7     y
warp 1   L0 L1 L2 L3 L4 L5 L6 L7     y+1
warp 2   L0 L1 L2 L3 L4 L5 L6 L7     y+2
warp 3   L0 L1 L2 L3 L4 L5 L6 L7     y+3
warp 4   L0 L1 L2 L3 L4 L5 L6 L7     y+4
warp 5   L0 L1 L2 L3 L4 L5 L6 L7     y+5
warp 6   L0 L1 L2 L3 L4 L5 L6 L7     y+6
warp 7   L0 L1 L2 L3 L4 L5 L6 L7     y+7
```

Cuando un warp termina su fila, no toma la siguiente, porque esa pertenece al siguiente warp.

Toma:

```text
y + 8
```

Por ejemplo:

```text
warp 0 → y=10,18,26,34,...
warp 1 → y=11,19,27,35,...
warp 2 → y=12,20,28,36,...
...
warp 7 → y=17,25,33,41,...
```

Esta es exactamente la distribución utilizada en v4: el valor inicial de `y` se obtiene sumando `warp_id` a `minY`, y posteriormente cada warp avanza ocho filas.

---

# 42. La imagen completa del reparto

Ahora podemos visualizar la bounding box como una rejilla de trabajo:

```text
                         X

          bloque 0             bloque 1
       <------------>       <------------>

       L0 L1 L2 L3 L4 L5 L6 L7   L0 L1 L2 ...

W0  -> [] [] [] [] [] [] [] []   [] [] [] ...
W1  -> [] [] [] [] [] [] [] []   [] [] [] ...
W2  -> [] [] [] [] [] [] [] []   [] [] [] ...
W3  -> [] [] [] [] [] [] [] []   [] [] [] ...
W4  -> [] [] [] [] [] [] [] []   [] [] [] ...
W5  -> [] [] [] [] [] [] [] []   [] [] [] ...
W6  -> [] [] [] [] [] [] [] []   [] [] [] ...
W7  -> [] [] [] [] [] [] [] []   [] [] [] ...

       cada [] = una palabra = dos píxeles
```

Horizontalmente:

- las lanes separan palabras;

verticalmente:

- los warps separan filas.

Esto es un excelente ejemplo de cómo un algoritmo gráfico se transforma en un **mapping del espacio de datos sobre la arquitectura**.

---

# Parte XXI — Por qué la bounding box se alinea

## 43. Una pequeña rareza del descriptor

En el setup aparecen operaciones para ajustar los límites horizontales del bounding box.

En lugar de conservar siempre una caja exactamente ajustada al triángulo, el rasterizador trabaja convenientemente con límites compatibles con grupos de ocho palabras.

¿Por qué aceptar trabajo adicional?

Porque queremos bloques completos:

```text
L0 L1 L2 L3 L4 L5 L6 L7
```

Supongamos que el triángulo empieza en mitad de un bloque:

```text
                 TRIÁNGULO
                    /\
                   /  \
                  /    \

bloque:   L0 L1 L2 L3 L4 L5 L6 L7
                    ^
                    |
                 empieza aquí
```

Podríamos intentar comenzar solamente con:

```text
L3 L4 L5 L6 L7
```

pero entonces el mapping y los accesos de memoria se vuelven más complicados.

Otra posibilidad es ampliar la bounding box:

```text
L0 L1 L2 L3 L4 L5 L6 L7
```

y dejar que las edge functions rechacen las posiciones que realmente quedan fuera.

Hacemos algunos tests adicionales, pero conservamos una estructura regular.

Esta es otra lección recurrente en GPU:

> A veces merece la pena hacer un poco de trabajo aritmético inútil para mantener una ejecución y unos accesos a memoria mucho más regulares.

---

# Parte XXII — Las edge functions en paralelo

## 44. Cada lane necesita un punto inicial diferente

Recordemos:

\[
E(x,y)=Ax+By+C
\]

Cada warp tiene una fila diferente.

Cada lane tiene una posición horizontal diferente.

Por tanto, aunque todas ejecuten:

```text
E = A*x + B*y + C
```

los valores `x` e `y` no son iguales.

Por ejemplo:

```text
warp 2:

lane 0 → (x,   y+2)
lane 1 → (x+2, y+2)
lane 2 → (x+4, y+2)
lane 3 → (x+6, y+2)
...
```

¿Por qué `x+2`?

Porque cada lane procesa **una palabra**, y cada palabra representa dos píxeles.

Así que las posiciones de los primeros píxeles son:

```text
x
x+2
x+4
x+6
...
x+14
```

Cada lane calcula inicialmente sus tres edge functions para su propio punto.

Esta inicialización todavía necesita multiplicaciones.

La v4 calcula inicialmente los valores de los tres bordes utilizando `MUL` para la posición correspondiente al thread.

Pero esto ocurre una vez al comenzar el recorrido correspondiente.

Después podemos aprovechar la incrementalidad.

---

# 45. Avanzar una palabra

Antes vimos:

\[
E(x+1,y)=E(x,y)+A
\]

Pero una lane no avanza un píxel cuando pasa a la palabra siguiente.

Una palabra contiene dos píxeles.

Por tanto:

\[
x \rightarrow x+2
\]

y:

\[
E(x+2,y)=E(x,y)+2A
\]

Sin embargo, hay otro detalle.

Las ocho lanes están procesando conjuntamente ocho palabras:

```text
L0 L1 L2 L3 L4 L5 L6 L7
```

Cuando terminan ese bloque, cada lane salta al siguiente bloque manteniendo su posición relativa:

```text
bloque 0:

L0 → word 0
L1 → word 1
...
L7 → word 7


bloque 1:

L0 → word 8
L1 → word 9
...
L7 → word 15
```

Para una misma lane:

\[
8\ palabras\times2\ píxeles=16\ píxeles
\]

Así que:

\[
x \rightarrow x+16
\]

y por tanto:

\[
\boxed{E_{next}=E+16A}
\]

Ahora podemos entender perfectamente unas operaciones que, vistas directamente en ensamblador, podrían parecer bastante arbitrarias.

La v4 calcula:

```text
A0 * 16
A1 * 16
A2 * 16
```

como incrementos horizontales.

No es una constante mágica.

El `16` sale directamente de la arquitectura del rasterizador:

\[
8\ lanes
\times
2\ píxeles/palabra
=
16\ píxeles
\]

Esta conexión entre matemáticas, formato de píxel y ancho SIMD es uno de los detalles más bonitos del ejemplo.

---

# 46. Y el segundo píxel de la palabra

Supongamos que una lane está procesando:

```text
+-------------------+-------------------+
| pixel x+1         | pixel x           |
+-------------------+-------------------+
```

Si ya tenemos:

\[
E(x,y)
\]

para el primer píxel, no necesitamos calcular desde cero:

\[
E(x+1,y)
\]

Sabemos que:

\[
E(x+1,y)=E(x,y)+A
\]

Por tanto, para cada uno de los tres bordes podemos comprobar:

**primer píxel:**

\[
E_0,\ E_1,\ E_2
\]

**segundo píxel:**

\[
E_0+A_0,\ E_1+A_1,\ E_2+A_2
\]

Esto vuelve a reducir multiplicaciones a sumas.

La geometría de un triángulo está empezando a convertirse casi completamente en comparaciones y sumas.

---

# Parte XXIII — El inner loop del rasterizador

## 47. Qué hace realmente una lane

Ya podemos describir conceptualmente el corazón de v4.

Cada lane tiene:

```text
address      dirección de su palabra
E0           borde 0 para el primer píxel
E1           borde 1 para el primer píxel
E2           borde 2 para el primer píxel
color        color del triángulo
```

Entonces:

```text
word = LOAD(address)

if E0 >= 0 && E1 >= 0 && E2 >= 0:
    sustituir pixel bajo por color

if E0+A0 >= 0 &&
   E1+A1 >= 0 &&
   E2+A2 >= 0:
    sustituir pixel alto por color

STORE(address, word)
```

Después:

```text
E0 += 16*A0
E1 += 16*A1
E2 += 16*A2

address += 8 palabras
```

Como cada palabra tiene 4 bytes:

\[
8\times4=32\ bytes
\]

Así que:

```text
address += 32
```

La v4 hace precisamente ese avance de 32 bytes al pasar al siguiente bloque horizontal.

De nuevo, una constante aparentemente arbitraria:

```text
32
```

sale directamente de:

\[
8\ lanes\times4\ bytes/palabra=32\ bytes
\]

---

# 48. ¿Por qué hacemos LOAD antes del STORE?

Esta pregunta es muy importante.

¿Por qué no escribir directamente el color?

Porque una palabra contiene dos píxeles y puede ocurrir:

```text
pixel 0 → dentro
pixel 1 → fuera
```

También puede ocurrir:

```text
pixel 0 → fuera
pixel 1 → dentro
```

O:

```text
pixel 0 → dentro
pixel 1 → dentro
```

O:

```text
pixel 0 → fuera
pixel 1 → fuera
```

Además, el framebuffer puede contener píxeles dibujados por un triángulo anterior.

Por tanto hacemos:

```text
LOAD palabra existente
```

y modificamos solamente las mitades cubiertas.

Por ejemplo:

```text
ANTES

31                       16 15                        0
+--------------------------+--------------------------+
| color anterior B         | color anterior A         |
+--------------------------+--------------------------+


solo pixel A está dentro


DESPUÉS

+--------------------------+--------------------------+
| color anterior B         | color triángulo          |
+--------------------------+--------------------------+
```

Esto es un clásico **read-modify-write**.

---

# 49. El coste del read-modify-write

Ahora aparece una consideración arquitectónica.

Para cada palabra de la bounding box hacemos potencialmente:

```text
LOAD
tests
modificación
STORE
```

Incluso si solamente queremos cambiar 16 bits.

Esto tiene coste de ancho de banda y latencia.

Podríamos imaginar otras arquitecturas:

- stores de 16 bits;
- stores con máscara de bytes;
- stores predicados;
- una unidad especializada que acepte máscara de cobertura;
- otro formato de framebuffer.

Pero cada alternativa tiene costes.

El ejemplo actual es muy valioso porque hace explícita la operación.

No existe una unidad gráfica mágica que “pinte el píxel”.

La GPU acaba haciendo algo extremadamente reconocible para alguien de Arquitectura de Computadores:

```text
LOAD
AND/OR/SHIFT
STORE
```

La diferencia está en que muchos threads hacen estas operaciones siguiendo un patrón cuidadosamente organizado.

---

# Parte XXIV — Divergencia

## 50. El problema del `if`

Hasta ahora hemos dicho que las ocho lanes ejecutan la misma instrucción.

Pero nuestro rasterizador contiene:

```text
if pixel_inside:
    modificar_pixel()
```

¿Qué ocurre si:

```text
lane 0 → dentro
lane 1 → dentro
lane 2 → fuera
lane 3 → fuera
lane 4 → dentro
lane 5 → fuera
lane 6 → fuera
lane 7 → fuera
```

Las lanes pertenecen al mismo warp.

No podemos hacer que unas ejecuten una instrucción completamente distinta mientras otras ejecutan otra, al menos no si estamos compartiendo el flujo de instrucciones del warp.

Aquí aparece uno de los conceptos centrales de SIMT:

**divergencia de control.**

---

# 51. Máscara de lanes activas

Podemos imaginar que cada warp tiene una máscara:

```text
lane:    7 6 5 4 3 2 1 0
mask:    0 0 0 1 0 0 1 1
```

Las lanes cuyo bit vale `1` ejecutan efectivamente la instrucción.

Las demás permanecen inactivas para esa ruta.

Conceptualmente:

```text
if inside:
    write_color
```

puede convertirse en:

```text
máscara = lanes donde inside == true

ejecutar write_color
solo con esas lanes activas
```

Después todas vuelven a reunirse.

A ese proceso de volver a una ejecución común lo llamamos **reconvergencia**.

---

# 52. Divergencia no significa ejecución independiente

Esto es importante.

Si la mitad de las lanes entra por una rama y la otra mitad por otra:

```text
if condition:
    A
else:
    B
```

no debemos imaginar necesariamente:

```text
4 lanes ejecutando A
al mismo tiempo que
4 lanes ejecutan B
```

En un modelo SIMT sencillo ocurre conceptualmente algo parecido a:

```text
ejecutar A con máscara de lanes correspondiente
ejecutar B con la máscara complementaria
reconverger
```

Así que la divergencia puede reducir la eficiencia.

Si solo una lane está activa:

```text
[1 0 0 0 0 0 0 0]
```

estamos utilizando una fracción pequeña del ancho disponible para esa parte del programa.

---

# 53. ¿Es terrible la divergencia del rasterizador?

No necesariamente.

Cerca de los bordes de un triángulo tendremos situaciones como:

```text
outside outside outside inside inside inside inside inside
```

Pero en regiones interiores grandes podemos tener:

```text
inside inside inside inside inside inside inside inside
```

y fuera:

```text
outside outside outside outside outside outside outside outside
```

La bounding box ayuda precisamente a no ejecutar sobre zonas arbitrariamente lejanas.

El comportamiento dependerá de la forma y tamaño del triángulo.

Esta es una idea importante:

> La eficiencia SIMT depende no solo del número de threads, sino también de cuánto coinciden sus decisiones de control.

---

# Parte XXV — SSY y reconvergencia

## 54. ¿Dónde vuelven a encontrarse los caminos?

Cuando un warp diverge, el hardware necesita saber dónde debe volver a reunirse la ejecución.

En MiniGPU aparece `SSY`, que permite establecer un punto de reconvergencia para este tipo de control SIMT.

No necesitamos aquí reconstruir toda la microarquitectura de `SSY`; basta con entender el problema que resuelve.

Supongamos:

```text
        condición
        /       \
       /         \
    dentro       fuera
      |            |
 modificar        nada
      |            |
       \          /
        \        /
       siguiente código
```

El punto inferior es la reconvergencia.

Todas las lanes deben volver a compartir el mismo flujo antes de continuar con la parte común.

Esta maquinaria es una de las diferencias entre simplemente construir una ALU vectorial y proporcionar un modelo SIMT cómodo para ejecutar programas con control de flujo.

---

# Parte XXVI — Terminar una fila

## 55. El salto vertical

Cuando una lane termina todos sus bloques horizontales de una fila, su warp debe pasar a la siguiente fila que le corresponde.

Recordemos:

```text
warp 0 → y, y+8, y+16...
warp 1 → y+1, y+9, y+17...
...
```

Así que el incremento vertical es:

\[
\Delta y=8
\]

Para una edge function:

\[
E(x,y+8)=E(x,y)+8B
\]

Pero hay un detalle.

Durante el recorrido horizontal ya hemos ido incrementando `E`.

Al terminar la fila tenemos que conseguir el valor correspondiente al inicio de la siguiente fila del mismo warp.

La v4 prepara precisamente deltas de fila que combinan el avance vertical con la compensación por todo lo avanzado horizontalmente.

Conceptualmente queremos:

```text
valor al inicio de fila actual
        |
        | recorrido horizontal
        v
valor al final
        |
        | corrección
        v
valor al inicio de fila y+8
```

De nuevo, se hace el cálculo más costoso al preparar el recorrido y después se intenta mantener el inner loop basado fundamentalmente en sumas.

---

# Parte XXVII — ¿Por qué un BAR después de cada triángulo?

## 56. Parece que los threads podrían continuar solos

Después de terminar un triángulo, v4 ejecuta una barrera antes de pasar al siguiente.

A primera vista podría parecer innecesario.

Cada warp sabe recorrer el triángulo.

¿Por qué no permitir que:

```text
warp 0 → triangle 1
```

mientras:

```text
warp 7 → todavía triangle 0
```

?

La respuesta está en el framebuffer y en el read-modify-write.

---

# 57. Una carrera entre triángulos

Imaginemos que dos triángulos pueden tocar la misma palabra del framebuffer.

El warp A está terminando el triángulo 0:

```text
LOAD word
```

Mientras tanto otro warp, más adelantado, empieza el triángulo 1:

```text
LOAD same_word
```

Ahora ambos tienen una copia antigua de la palabra.

Después:

```text
warp A modifica pixel izquierdo
warp B modifica pixel derecho
```

y escriben:

```text
warp A → STORE
warp B → STORE
```

El segundo `STORE` podría destruir la modificación del primero.

Es la típica carrera de un read-modify-write:

```text
memoria = X

A: LOAD X
B: LOAD X

A: modifica → XA
B: modifica → XB

A: STORE XA
B: STORE XB

resultado = XB
```

La modificación de A desaparece.

---

# 58. La barrera impone fases

Con `BAR` hacemos:

```text
TODOS LOS WARPS
      |
      v
rasterizan triangle 0
      |
      v
     BAR
      |
      v
rasterizan triangle 1
      |
      v
     BAR
      |
      v
rasterizan triangle 2
```

Así ningún warp empieza el triángulo siguiente hasta que todos han terminado el actual.

Esto no convierte los `LOAD/STORE` en operaciones atómicas.

Lo que hace es evitar que diferentes fases de rasterización se solapen de una forma peligrosa.

Esta distinción es importante:

> **Una barrera sincroniza participantes; no convierte por sí misma un read-modify-write en una operación atómica.**

El algoritmo está organizado para que dentro de una misma fase cada thread tenga una región de trabajo que no entre en conflicto con los demás, y la barrera separa las fases que podrían reutilizar las mismas posiciones.

---

# Parte XXVIII — El clear también necesita sincronización

## 59. Borrar antes de dibujar

La v4 comienza cada frame borrando la región de trabajo.

Imaginemos que algunos warps terminan el clear muy pronto:

```text
warp 0 → clear terminado → empieza raster
```

mientras otro sigue:

```text
warp 7 → todavía borrando
```

Podría ocurrir:

```text
warp 0 dibuja un píxel
warp 7 lo borra posteriormente
```

Otra carrera.

Por tanto necesitamos conceptualmente:

```text
CLEAR
  |
 BAR
  |
RASTER
```

La barrera establece una frontera entre fases.

Este patrón aparecerá continuamente en computación paralela:

```text
fase A
  |
sincronización
  |
fase B
```

---

# Parte XXIX — Ya tenemos un pequeño pipeline gráfico paralelo

## 60. El frame según v4

Podemos resumir ahora un frame de v4:

```text
        FRAME N
           |
           v
   +---------------+
   | CLEAR         |
   | 64 threads    |
   +---------------+
           |
          BAR
           |
           v
   +---------------+
   | TRIANGLE 0    |
   | raster        |
   +---------------+
           |
          BAR
           |
           v
   +---------------+
   | TRIANGLE 1    |
   +---------------+
           |
          BAR
           |
          ...
           |
   +---------------+
   | TRIANGLE 5    |
   +---------------+
           |
          BAR
           |
           v
       FRAME LISTO
```

Cada triángulo se rasteriza en paralelo.

Dentro de cada warp:

```text
8 lanes
→ 8 palabras
→ 16 píxeles
```

Los warps se distribuyen verticalmente.

Las edge functions se actualizan incrementalmente.

Los accesos horizontales están organizados para favorecer BL8.

Ya estamos bastante lejos del doble bucle ingenuo de una CPU.

Pero todavía falta algo esencial.

Mientras estamos dibujando el siguiente frame, la pantalla necesita seguir mostrando algo.

---

# Parte XXX — Scanout: la pantalla no espera a la GPU

## 61. El framebuffer no es la pantalla

Hasta ahora hemos utilizado frases como:

> “escribimos el framebuffer y aparece la imagen”.

Pero físicamente falta una etapa.

La pantalla necesita recibir continuamente píxeles siguiendo una temporización determinada.

Existe por tanto una lógica de **scanout** que lee el framebuffer y genera la señal de vídeo.

Conceptualmente:

```text
GPU
 |
 | STORE
 v
+----------------+
| framebuffer    |
+----------------+
        |
        | LOAD continuo
        v
+----------------+
| scanout        |
+----------------+
        |
        v
     HDMI/VÍDEO
        |
        v
     pantalla
```

La GPU escribe.

El scanout lee.

Son dos consumidores/productores diferentes de la misma memoria de imagen.

---

# 62. ¿Qué pasa si dibujamos mientras se está mostrando?

Supongamos que tenemos un solo framebuffer.

La pantalla está recorriendo:

```text
fila 0
fila 1
fila 2
...
```

Mientras tanto la GPU empieza a generar la imagen siguiente.

Puede ocurrir:

```text
parte superior → frame nuevo
parte inferior → frame antiguo
```

porque el scanout ha leído unas zonas antes de que la GPU las actualizase y otras después.

Visualmente podríamos terminar mostrando una mezcla:

```text
+-----------------------+
|       FRAME N+1       |
|                       |
+-----------------------+
|       FRAME N         |
|                       |
+-----------------------+
```

Este tipo de artefacto está relacionado con lo que normalmente se conoce como **tearing**.

Necesitamos separar la imagen que se está mostrando de la que estamos construyendo.

---

# Parte XXXI — Double buffering

## 63. Dos framebuffers

La solución clásica consiste en disponer de dos buffers:

```text
FRONT BUFFER
→ lo está leyendo scanout

BACK BUFFER
→ lo está dibujando GPU
```

Por ejemplo, en nuestros ejemplos aparecen dos direcciones de framebuffer:

```text
0x00100000
0x00140000
```

El programa configura inicialmente ambas y activa el scanout. En v4 puede verse esa inicialización antes de comenzar el bucle de frames.

Conceptualmente:

```text
                  +------------------+
scanout <---------| FRONT            |
                  | frame N          |
                  +------------------+

GPU ------------->+------------------+
                  | BACK             |
                  | construyendo N+1 |
                  +------------------+
```

Mientras la pantalla muestra N, la GPU puede trabajar tranquilamente en N+1.

---

# 64. Swap

Cuando la GPU termina:

```text
BACK = frame N+1 completo
```

solicita un **swap**.

Los papeles cambian:

```text
ANTES

FRONT → N
BACK  → N+1


DESPUÉS

FRONT → N+1
BACK  → antiguo N
```

Podemos representarlo:

```text
FRAME N

scanout <--- FB A
GPU -------> FB B


       SWAP


FRAME N+1

scanout <--- FB B
GPU -------> FB A
```

Esto es double buffering.

El programa de v4 solicita el swap mediante MMIO y espera a que la petición se complete antes de continuar.

---

# 65. El swap no significa copiar el framebuffer

Este detalle es muy importante.

No hacemos:

```text
copiar 153600 bytes
```

de un buffer a otro.

Simplemente cambiamos cuál de las dos direcciones considera scanout como framebuffer frontal.

Conceptualmente:

```text
front_pointer = back_pointer
back_pointer  = old_front_pointer
```

Es decir, intercambiamos roles, no imágenes.

Esto hace que el swap sea muchísimo más barato que copiar una pantalla completa.

---

# Parte XXXII — Una consecuencia sutil del double buffering

## 66. El back buffer no está vacío

Supongamos:

```text
frame 0:
front = A
back  = B
```

Dibujamos frame 1 en B.

Swap:

```text
front = B   → frame 1
back  = A
```

Pero A contiene todavía la imagen antigua.

Cuando vayamos a dibujar el siguiente frame en A, no podemos asumir que está vacío.

Por eso el clear sigue siendo necesario.

Y hay una consecuencia todavía más interesante si en el futuro queremos hacer **dirty rectangles** o borrar únicamente la zona ocupada por el objeto.

El back buffer no contiene necesariamente el frame inmediatamente anterior.

Con double buffering puede contener el contenido de **dos iteraciones atrás**.

Esto significa que una optimización futura del borrado tendrá que recordar qué región quedó dibujada en **cada framebuffer**, no simplemente la región del frame anterior.

Es un detalle fácil de pasar por alto y muy importante si queremos continuar optimizando v8.

---

# Parte XXXIII — Ya podemos interpretar v3 y v4 arquitectónicamente

## 67. v3: propiedad del framebuffer

En v3 la idea fundamental era:

> cada thread es responsable de determinadas palabras y siempre produce su valor final.

Eso elimina la pasada de clear.

Podemos pensar:

```text
thread
  |
  v
word
  |
  +→ triangle 0?
  +→ triangle 1?
  +→ ...
  +→ triangle 5?
  |
  v
STORE final
```

La ventaja arquitectónica es que la propiedad de la memoria es muy clara.

La desventaja es que hacemos muchísimo trabajo de test y carga de descriptores.

---

# 68. v4: propiedad por fase

v4 cambia la organización:

```text
triangle 0
  |
  +→ threads rasterizan su bbox
  |
 BAR

triangle 1
  |
  +→ threads rasterizan su bbox
  |
 BAR
```

Ahora un mismo píxel puede ser visitado durante varias fases.

Por eso aparecen:

```text
LOAD
modify
STORE
```

y barreras entre triángulos.

Pero a cambio:

- el descriptor se reutiliza;
- el bounding box reduce muchísimo la región;
- las edge functions se hacen incrementales;
- el mapping favorece accesos BL8.

Esto ilustra algo mucho más general:

> **La estructura del algoritmo determina las necesidades de sincronización y memoria.**

No podemos estudiar por separado “el algoritmo” y “la GPU”. Se influyen mutuamente.

---

# Parte XXXIV — El siguiente cuello de botella

## 69. ¿De dónde salen los triángulos?

Hasta ahora hemos hecho una pequeña trampa.

Hemos hablado de:

```text
rotación
proyección
culling
setup
```

pero v3 y v4 pueden trabajar con información preparada previamente.

Eso significa que la GPU está resolviendo fundamentalmente:

```text
triángulos 2D preparados
        ↓
      píxeles
```

Pero si queremos una GPU capaz de generar por sí misma la animación del cubo necesitamos que también haga:

```text
cubo 3D
   ↓
rotación
   ↓
proyección
   ↓
culling
   ↓
descriptores
   ↓
raster
```

Ese es el salto de **v5**.

---

# Parte XXXV — v5: la geometría entra en MiniGPU

## 70. El cambio conceptual de v5

El encabezado de v5 lo explica claramente: la propia MiniGPU calcula la geometría. El thread global 0 rota y proyecta los ocho vértices, realiza back-face culling y genera seis descriptores de triángulo en RAM; después los 64 threads reutilizan el rasterizador de v4.

Ahora el pipeline completo está dentro de nuestra máquina:

```text
             MiniGPU
+----------------------------------+
|                                  |
|  vértices del cubo               |
|          |                       |
|          v                       |
|  rotación                        |
|          |                       |
|          v                       |
|  proyección                      |
|          |                       |
|          v                       |
|  back-face culling               |
|          |                       |
|          v                       |
|  triangle setup                  |
|          |                       |
|          v                       |
|  descriptors                    |
|          |                       |
|          v                       |
|  rasterizador paralelo           |
|          |                       |
|          v                       |
|  framebuffer                     |
|                                  |
+----------------------------------+
```

Esto es un momento importante de nuestra evolución.

Ya no tenemos simplemente un “acelerador de triángulos preparados”.

Tenemos una pequeña máquina capaz de partir de una descripción 3D del cubo y generar la imagen.

---

# 71. Pero v5 hace algo deliberadamente poco GPU

Hay una decisión muy interesante.

La geometría de v5 la calcula:

```text
tid == 0
```

Es decir, un único thread.

Los otros 63 no participan en esa fase.

Podemos imaginar:

```text
GEOMETRÍA

T0  █████████████████████████████
T1
T2
T3
...
T63


RASTER

T0  █████████████████████████████
T1  █████████████████████████████
T2  █████████████████████████████
...
T63 █████████████████████████████
```

Desde el punto de vista de utilización del hardware parece terrible.

¿Por qué hacerlo?

Porque es una excelente etapa intermedia.

Primero trasladamos la geometría a la GPU **sin cambiar todavía su estructura algorítmica**.

Comprobamos que funciona.

Después podemos preguntarnos:

> ¿Qué partes de esta geometría pueden paralelizarse?

Este enfoque incremental es muy útil al diseñar hardware: cambiar una dimensión del problema cada vez permite entender mejor qué produce cada mejora.

---

# Parte XXXVI — Qué hace thread 0 en v5

## 72. Generar los ocho vértices

La primera tarea es obtener los ocho vértices del cubo.

La v5 utiliza coordenadas `±256`.

Conceptualmente:

```text
V0 = (-256,-256,-256)
V1 = (+256,-256,-256)
V2 = (-256,+256,-256)
...
```

El código aprovecha los bits del índice del vértice para seleccionar el signo de cada coordenada.

Esto evita incluso tener que almacenar una tabla completa con las coordenadas originales.

---

# 73. Rotar

Después aplica las rotaciones utilizando seno y coseno en Q14.

Podemos visualizar:

```text
          V original
              |
              v
       rotación eje 1
              |
              v
        V intermedio
              |
              v
       rotación eje 2
              |
              v
         V rotado
```

En el código aparecen multiplicaciones seguidas de desplazamientos aritméticos de 14 bits para volver a la escala correcta del punto fijo.

Esta fase tiene una característica que ya habíamos anticipado:

```text
transform(V0)
transform(V1)
transform(V2)
...
transform(V7)
```

Cada vértice es independiente.

Pero v5 todavía los calcula secuencialmente.

---

# 74. Proyectar

Después se añade la distancia de cámara y se realiza la proyección perspectiva.

La v5 utiliza un desplazamiento en Z de 768, un factor 140 y centro de pantalla `(160,120)`.

Conceptualmente:

\[
z_c=z+768
\]

\[
s_x=160+\frac{140x}{z_c}
\]

\[
s_y=120+\frac{140y}{z_c}
\]

Así cada vértice 3D termina convertido en un par 2D.

El resultado se almacena en `cube_points`.

Podemos imaginar la memoria:

```text
cube_points:

V0 → sx0, sy0
V1 → sx1, sy1
V2 → sx2, sy2
...
V7 → sx7, sy7
```

Esta memoria se convierte en la frontera entre:

```text
TRANSFORMACIÓN DE VÉRTICES
```

y:

```text
SETUP DE TRIÁNGULOS
```

---

# Parte XXXVII — De vértices proyectados a descriptores

## 75. Recorrer los doce triángulos

El cubo tiene doce triángulos geométricos.

La tabla `cube_tris` indica qué tres vértices forman cada uno.

Conceptualmente:

```text
triangle 0 → V0,V1,V2
triangle 1 → V0,V2,V3
...
```

Para cada triángulo, thread 0:

1. carga los tres puntos proyectados;
2. calcula su orientación;
3. descarta el triángulo si está de espaldas;
4. calcula las tres edge functions;
5. calcula la bounding box;
6. prepara el color;
7. escribe un descriptor.

Esta fase suele denominarse **triangle setup**.

---

# 76. El setup como transformación de representación

Esto merece una interpretación más profunda.

Antes del setup tenemos una representación adecuada para pensar geométricamente:

```text
P0
P1
P2
```

Después tenemos una representación adecuada para rasterizar:

```text
A0 B0 C0
A1 B1 C1
A2 B2 C2
bbox
color
```

Es el mismo triángulo.

Pero hemos cambiado su representación para adaptarla a la siguiente etapa.

Podemos pensar:

```text
representación para geometría
        |
        | triangle setup
        v
representación para rasterización
```

Este patrón es muy común en arquitectura:

> Una etapa precalcula información para que la siguiente pueda hacer un trabajo mucho más simple y repetitivo.

---

# Parte XXXVIII — Solo seis triángulos visibles

## 77. Compactar después del culling

Aunque el cubo tiene doce triángulos, desde una cámara exterior aproximadamente la mitad corresponden a caras posteriores.

v5 genera hasta seis descriptores visibles.

En vez de dejar:

```text
slot 0 → visible
slot 1 → invisible
slot 2 → invisible
slot 3 → visible
...
```

el setup compacto puede producir:

```text
descriptor 0 → visible
descriptor 1 → visible
descriptor 2 → visible
...
descriptor 5 → visible
```

Esto es importante para el rasterizador.

Después no tiene que recorrer doce entradas preguntándose cuáles sirven.

Tiene directamente una lista compacta.

Pero compactar tiene un coste: alguien debe decidir dónde escribir el siguiente descriptor.

En v5 esto es fácil porque solamente existe un productor:

```text
thread 0
```

Mantiene un contador/puntero y va añadiendo los triángulos visibles.

No hay conflicto.

---

# Parte XXXIX — La pregunta que conduce a v6

## 78. ¿Por qué transformar ocho vértices secuencialmente?

Observemos la primera mitad de la geometría:

```text
V0 → rotate → project → store
V1 → rotate → project → store
V2 → rotate → project → store
...
V7 → rotate → project → store
```

Las operaciones son prácticamente idénticas.

Los datos cambian.

Tenemos exactamente ocho vértices.

Y casualmente:

> un warp de MiniGPU tiene ocho lanes.

La correspondencia es demasiado buena para ignorarla.

Podemos hacer:

```text
lane 0 → V0
lane 1 → V1
lane 2 → V2
lane 3 → V3
lane 4 → V4
lane 5 → V5
lane 6 → V6
lane 7 → V7
```

Una instrucción de rotación se aplica a ocho vértices diferentes.

Una instrucción de proyección se aplica a ocho vértices diferentes.

Una instrucción de almacenamiento guarda ocho resultados diferentes.

Eso es exactamente el tipo de trabajo para el que hemos construido una arquitectura SIMT.

Y esa es la idea central de **v6**.

---

# Parte XL — v6: una lane por vértice

## 79. El primer uso muy natural del SIMD en geometría

La v6 transforma los ocho vértices en paralelo utilizando las lanes 0–7. Después, una vez preparados todos los puntos, vuelve al setup compacto realizado por lane/thread 0.

Ahora la fase inicial se parece a:

```text
             MISMA INSTRUCCIÓN

lane 0 → V0 ─┐
lane 1 → V1  │
lane 2 → V2  │
lane 3 → V3  ├→ rotar/proyectar
lane 4 → V4  │
lane 5 → V5  │
lane 6 → V6  │
lane 7 → V7 ─┘
```

Desde el punto de vista conceptual es casi el caso perfecto para SIMD/SIMT.

No estamos forzando el algoritmo a ser paralelo.

El paralelismo ya estaba en el problema.

---

# 80. Una instrucción, ocho vértices

Consideremos una operación simplificada:

\[
x'=x\cos\theta-z\sin\theta
\]

En v5 podemos imaginar:

```text
calcular x' de V0
calcular x' de V1
calcular x' de V2
...
calcular x' de V7
```

En v6:

```text
MUL ...
```

puede conceptualmente estar haciendo:

```text
lane 0 → x0 * cos
lane 1 → x1 * cos
lane 2 → x2 * cos
...
lane 7 → x7 * cos
```

Después otra operación:

```text
lane 0 → z0 * sin
lane 1 → z1 * sin
...
```

Y así sucesivamente.

Esto ilustra por qué las transformaciones de vértices han sido históricamente un candidato tan natural para ejecución paralela.

---

# Parte XLI — Pero hay que volver a sincronizar

## 81. El setup necesita todos los vértices

Aquí aparece otra dependencia.

La transformación de cada vértice es independiente.

Pero para procesar un triángulo necesitamos tres vértices ya proyectados.

Por ejemplo:

```text
triangle 0 = V0,V3,V5
```

No podemos comenzar correctamente el setup hasta estar seguros de que:

```text
V0 listo
V3 listo
V5 listo
```

Como todos los vértices se almacenan en `cube_points`, necesitamos una frontera:

```text
TRANSFORMAR VÉRTICES
        |
        v
       BAR
        |
        v
TRIANGLE SETUP
```

La v6 contiene precisamente una barrera `vertices_ready` después de almacenar los vértices y antes del setup serial.

Esta barrera tiene un significado diferente de las barreras del rasterizador, pero el principio general es el mismo:

> La siguiente fase consume resultados producidos paralelamente por la anterior; antes de consumirlos necesitamos saber que todos están listos.

---

# Parte XLII — Productores y consumidores

## 82. Una forma útil de pensar el pipeline

Podemos interpretar cada etapa en términos de producción y consumo de datos:

```text
VERTEX TRANSFORM
    |
    | produce
    v
cube_points
    |
    | consume
    v
TRIANGLE SETUP
    |
    | produce
    v
cube_descriptors
    |
    | consume
    v
RASTERIZER
    |
    | produce
    v
framebuffer
    |
    | consume
    v
SCANOUT
```

Esta visión es muy útil arquitectónicamente.

Cada frontera plantea preguntas:

- ¿dónde se almacenan los resultados?
- ¿cuándo están listos?
- ¿quién puede leerlos?
- ¿hace falta una barrera?
- ¿pueden productor y consumidor solaparse?
- ¿qué ancho de banda necesitan?

Una GPU moderna responde estas preguntas con una arquitectura muchísimo más sofisticada, pero los problemas fundamentales ya están presentes en nuestra pequeña MiniGPU.

---

# Parte XLIII — ¿Hemos multiplicado por ocho el rendimiento?

## 83. No necesariamente

Sería tentador decir:

> v5 transforma ocho vértices secuencialmente y v6 los hace en ocho lanes, por tanto la geometría es ocho veces más rápida.

Pero eso no puede afirmarse solamente observando el código.

¿Por qué?

Porque necesitamos conocer la microarquitectura.

Por ejemplo:

- ¿cuántos multiplicadores físicos existen?
- ¿cómo se ejecuta `DIV`?
- ¿hay una única unidad compartida?
- ¿pueden las ocho lanes realizar una división simultáneamente?
- ¿qué latencia tiene `LOAD`?
- ¿cómo se planifican los warps?

El programa expresa ocho operaciones paralelas.

El rendimiento real depende de cómo el hardware las implemente.

Esta distinción será importante durante todo el proyecto:

> **Paralelismo expresado por el programa no implica automáticamente paralelismo físico de igual anchura.**

Aun así, v6 es arquitectónicamente mucho más adecuada para explotar cualquier paralelismo disponible en la transformación de vértices.

---

# Parte XLIV — Todavía queda una parte serial

## 84. El triangle setup sigue en thread 0

Después de transformar los ocho vértices:

```text
BAR
```

y v6 vuelve esencialmente al esquema compacto de v5.

Un único thread recorre los doce triángulos y genera los descriptores visibles.

Podemos visualizar la utilización:

```text
VERTICES

lane 0 █████████
lane 1 █████████
lane 2 █████████
lane 3 █████████
lane 4 █████████
lane 5 █████████
lane 6 █████████
lane 7 █████████


SETUP

lane 0 █████████████████████████████
lane 1
lane 2
lane 3
lane 4
lane 5
lane 6
lane 7
```

Esto parece sugerir inmediatamente la siguiente optimización:

> paralelicemos también el setup.

Y eso nos lleva a v7.

Pero aquí aparece una de las lecciones más interesantes de toda la serie:

> **Una fase que puede paralelizarse no tiene por qué mejorar el programa cuando la paralelizamos.**

Para entender por qué, necesitamos estudiar cuidadosamente qué hace v7 con las caras y, sobre todo, qué efecto tiene esa decisión sobre la fase posterior de rasterización.

---

# 85. Situación del pipeline al llegar a v6

Antes de pasar a v7 conviene detenernos y mirar cuánto hemos construido.

Nuestro frame ya puede describirse así:

```text
                    FRAME N
                       |
                       v

              +----------------+
              | angle          |
              +----------------+
                       |
                       v
        +-----------------------------+
        | VERTEX TRANSFORM            |
        | 8 vértices                  |
        | 8 lanes                     |
        +-----------------------------+
                       |
                      BAR
                       |
                       v
        +-----------------------------+
        | TRIANGLE SETUP              |
        | thread 0                    |
        | culling + edges + bbox      |
        +-----------------------------+
                       |
                       v
        +-----------------------------+
        | 6 DESCRIPTORES COMPACTOS    |
        +-----------------------------+
                       |
                       v
        +-----------------------------+
        | CLEAR                       |
        | 64 threads                  |
        +-----------------------------+
                       |
                      BAR
                       |
                       v
        +-----------------------------+
        | RASTER TRIANGLE 0           |
        | 64 threads                  |
        +-----------------------------+
                       |
                      BAR
                       |
                      ...
                       |
        +-----------------------------+
        | RASTER TRIANGLE 5           |
        +-----------------------------+
                       |
                       v
                    SWAP
                       |
                       v
                   SCANOUT
```

Esto ya se parece mucho más a un pipeline gráfico reconocible.

Pero es importante no proyectar todavía sobre MiniGPU unidades hardware que nuestros ejemplos no demuestran.

Aquí estamos hablando principalmente de **fases del programa** ejecutadas sobre MiniGPU.

No debemos imaginar necesariamente que existe físicamente:

```text
Vertex Unit → Triangle Unit → Raster Unit
```

como bloques hardware independientes.

En estos ejemplos, muchas de esas funciones son **software ejecutándose sobre la misma arquitectura programable**.

Esta distinción es fundamental.

---

# Parte XLV — Lo que hemos aprendido de arquitectura GPU

## 86. La GPU no es simplemente “muchas ALUs”

Hasta este punto ya podemos corregir una definición demasiado simplista:

> “Una GPU es una CPU con muchas ALUs.”

Eso no captura lo importante.

Nuestro pequeño ejemplo ya muestra que una arquitectura adecuada para gráficos necesita pensar conjuntamente en:

**Paralelismo de datos**

Muchos vértices y muchos píxeles admiten operaciones semejantes.

**Organización de threads**

Agrupar threads en warps permite compartir el flujo de instrucciones.

**Lanes**

Permiten aplicar una instrucción a diferentes datos.

**Divergencia**

Los threads de un warp pueden necesitar decisiones diferentes, por ejemplo en los bordes del triángulo.

**Reconvergencia**

Después de esas decisiones necesitamos recuperar un flujo común.

**Memoria**

La disposición de los datos determina si los accesos pueden agruparse eficientemente.

**Coalescing**

Ocho lanes accediendo a ocho palabras consecutivas es mucho más interesante que ocho direcciones arbitrarias.

**Sincronización**

Las fases paralelas necesitan fronteras cuando unas consumen los resultados de otras o cuando existe riesgo de carreras.

**Representación de datos**

RGB565, dos píxeles por palabra, descriptores de triángulo y `cube_points` condicionan directamente los algoritmos.

**Reorganización algorítmica**

v4 demuestra que cambiar el orden de los bucles puede ser más importante que añadir hardware.

Y todavía no hemos hablado de caches, texturas, profundidad, interpolación de atributos o shaders.

No hacen falta para comprender la idea esencial.

---

# 87. Una comparación muy útil: CPU frente a nuestra MiniGPU

Podemos imaginar una CPU escalar ejecutando:

```text
for each vertex:
    transform(vertex)

for each triangle:
    setup(triangle)

for each pixel:
    raster(pixel)
```

Nuestra evolución está descubriendo otra forma:

```text
8 vertices
    ↓
ejecución SIMT

triangles
    ↓
preparación especializada

bounding boxes
    ↓
64 threads

8 lanes por warp
    ↓
palabras consecutivas

coalesced memory
```

No hemos cambiado las matemáticas del cubo.

Hemos cambiado **cómo mapeamos esas matemáticas sobre la máquina**.

Y esa frase resume buena parte de lo que significa programar una GPU.

---

# Parte XLVI — Preparando v7

## 88. ¿Podemos procesar las seis caras en paralelo?

Tenemos seis caras.

Tenemos ocho lanes.

Parece natural:

```text
lane 0 → face 0
lane 1 → face 1
lane 2 → face 2
lane 3 → face 3
lane 4 → face 4
lane 5 → face 5
lane 6 → inactiva
lane 7 → inactiva
```

Cada cara contiene dos triángulos.

Cada lane podría:

1. cargar los vértices de su cara;
2. determinar si es visible;
3. generar sus dos descriptores.

Eso es exactamente el experimento que plantea v7. El encabezado indica que las lanes 0–7 transforman los vértices y después las lanes 0–5 procesan cada una una cara del cubo, escribiendo dos slots fijos de descriptor. El rasterizador pasa entonces a recorrer doce slots.

Sobre el papel suena mejor:

```text
v6:
1 lane procesa setup

v7:
6 lanes procesan setup
```

Pero hemos cambiado una propiedad muy importante.

En v6 el thread 0 podía **compactar** los triángulos visibles.

En v7 cada lane necesita poder escribir independientemente sin pelearse por un contador compartido.

La solución elegida es asignar posiciones fijas.

Y esa decisión tendrá consecuencias en la siguiente fase.

Aquí aparece el tema central de la próxima parte:

> **Optimizar una etapa localmente puede empeorar el pipeline global.**

v7 será nuestro mejor ejemplo de ello.

# Parte XLVII — v7: paralelizar no siempre significa acelerar

## 89. El siguiente paso parece evidente

Al terminar v6 habíamos conseguido una correspondencia casi perfecta entre los ocho vértices del cubo y las ocho lanes de un warp:

```text
lane 0 → vértice 0
lane 1 → vértice 1
lane 2 → vértice 2
lane 3 → vértice 3
lane 4 → vértice 4
lane 5 → vértice 5
lane 6 → vértice 6
lane 7 → vértice 7
```

Pero el *triangle setup* seguía siendo serial.

Una única lane recorría los triángulos, hacía culling, calculaba las edge functions, obtenía la bounding box y construía los descriptores.

Parece natural preguntarse:

> Si hemos paralelizado los vértices, ¿por qué no hacemos lo mismo con las caras?

El cubo tiene seis caras.

Tenemos ocho lanes.

La correspondencia parece incluso más cómoda:

```text
lane 0 → cara 0
lane 1 → cara 1
lane 2 → cara 2
lane 3 → cara 3
lane 4 → cara 4
lane 5 → cara 5
lane 6 → sin trabajo
lane 7 → sin trabajo
```

Eso es precisamente lo que experimenta v7: las ocho lanes siguen transformando los ocho vértices, y después las lanes 0–5 procesan cada una una cara completa. Cada cara dispone de dos slots fijos de descriptor, porque cada cara del cubo contiene dos triángulos.

A primera vista hemos convertido otra fase serial en una fase paralela.

Pero aparece un problema nuevo.

---

# 90. El problema de generar una lista compacta en paralelo

En v6 el setup lo realiza un único thread.

Supongamos que examinamos los doce triángulos originales:

```text
T0  visible
T1  visible
T2  oculto
T3  oculto
T4  visible
T5  visible
...
```

Como solo existe un productor, podemos mantener un puntero:

```text
next_descriptor = 0
```

Cuando encontramos un triángulo visible:

```text
descriptors[next_descriptor] = triangle
next_descriptor++
```

Así obtenemos:

```text
slot 0 → visible
slot 1 → visible
slot 2 → visible
slot 3 → visible
slot 4 → visible
slot 5 → visible
```

Es decir, una lista **compacta**.

No hay huecos.

Pero intentemos hacer esto con seis lanes simultáneamente.

Supongamos:

```text
lane 0 → cara visible
lane 1 → cara oculta
lane 2 → cara visible
lane 3 → cara visible
lane 4 → cara oculta
lane 5 → cara oculta
```

Las lanes 0, 2 y 3 necesitan reservar espacio en la lista.

¿Quién obtiene qué posición?

Necesitaríamos algún mecanismo para transformar:

```text
visible = [1,0,1,1,0,0]
```

en posiciones:

```text
lane 0 → descriptor 0
lane 2 → descriptor 1
lane 3 → descriptor 2
```

Esto es una operación de **compactación paralela**.

---

# 91. La compactación paralela no es gratuita

En arquitecturas paralelas existen técnicas para hacerla.

Por ejemplo, conceptualmente podríamos calcular un *prefix sum*:

```text
visible:

lane       0  1  2  3  4  5
           1  0  1  1  0  0

prefix:

           0  1  1  2  3  3
```

Así cada lane visible podría descubrir su índice de salida.

Pero eso necesita comunicación y operaciones adicionales.

Otra posibilidad sería disponer de una operación atómica:

```text
my_slot = atomic_increment(next_descriptor)
```

pero eso introduce serialización sobre un contador compartido y requiere soporte hardware apropiado.

Para seis caras de un cubo, cualquiera de estas soluciones puede ser más sofisticada que el problema que estamos intentando resolver.

v7 elige una solución mucho más sencilla:

> **cada cara tiene posiciones fijas.**

---

# 92. Dos slots por cara

Cada cara produce dos triángulos.

Así podemos reservar:

```text
cara 0 → slots 0,1
cara 1 → slots 2,3
cara 2 → slots 4,5
cara 3 → slots 6,7
cara 4 → slots 8,9
cara 5 → slots 10,11
```

Ahora no existe ninguna disputa.

`lane 3` sabe que sus resultados pertenecen siempre a:

```text
slot 6
slot 7
```

No necesita preguntar a las demás lanes.

Podemos dibujarlo:

```text
          DESCRIPTORES

lane 0 ──> [ T0 ][ T1 ]
lane 1 ──> [ T2 ][ T3 ]
lane 2 ──> [ T4 ][ T5 ]
lane 3 ──> [ T6 ][ T7 ]
lane 4 ──> [ T8 ][ T9 ]
lane 5 ──> [T10 ][T11 ]
```

v7 utiliza precisamente bloques fijos de descriptor por cara.

La escritura paralela se vuelve sencilla.

Pero hemos trasladado el problema.

---

# 93. ¿Qué escribimos para una cara invisible?

Supongamos que `lane 2` descubre mediante back-face culling que su cara no debe dibujarse.

Sus dos slots siguen existiendo:

```text
slot 4
slot 5
```

No podemos simplemente eliminarlos porque entonces volveríamos a necesitar compactación.

Así que conceptualmente quedan como descriptores inactivos.

La estructura pasa a ser algo parecido a:

```text
slot 0  → TRIÁNGULO
slot 1  → TRIÁNGULO

slot 2  → INACTIVO
slot 3  → INACTIVO

slot 4  → TRIÁNGULO
slot 5  → TRIÁNGULO

slot 6  → TRIÁNGULO
slot 7  → TRIÁNGULO

slot 8  → INACTIVO
slot 9  → INACTIVO

slot 10 → INACTIVO
slot 11 → INACTIVO
```

Ahora el setup es fácil de paralelizar.

Pero el consumidor recibe una lista más grande.

---

# 94. El rasterizador ya no consume seis entradas

En v6 teníamos esencialmente:

```text
setup serial
      |
      v
6 descriptores compactos
      |
      v
rasterizador
```

En v7:

```text
setup paralelo
      |
      v
12 slots fijos
      |
      v
rasterizador
```

Y el rasterizador de v7 recorre doce slots.

Esta diferencia ilustra un principio arquitectónico fundamental:

> El resultado de optimizar una etapa depende de cómo ese cambio afecta a las etapas siguientes.

No basta con medir:

```text
tiempo(setup)
```

Tenemos que medir:

\[
tiempo(frame)
\]

---

# 95. Optimización local frente a optimización global

Imaginemos números ficticios únicamente para ilustrar el concepto.

Supongamos que v6 tarda:

```text
vertex transform       100 ciclos
triangle setup         300 ciclos
clear                  2000 ciclos
raster                 5000 ciclos
                       -----------
total                  7400 ciclos
```

Ahora paralelizamos el setup:

```text
vertex transform       100
triangle setup          80
clear                  2000
raster                 5500
                       -----------
total                  7680
```

El setup aislado es muchísimo mejor:

\[
300\rightarrow80
\]

y sin embargo el frame completo es peor:

\[
7400\rightarrow7680
\]

Estos números **no son medidas de los ejemplos**; son únicamente una ilustración del fenómeno. Los archivos permiten observar el cambio estructural de 6 descriptores compactos a 12 slots, pero para cuantificar ciclos reales necesitaríamos las latencias y/o medidas de la implementación.

Esta distinción entre lo que demuestra el código y lo que necesitaríamos medir es importante.

---

# 96. Amdahl aparece en nuestro cubo

Aquí podemos introducir una idea clásica de Arquitectura de Computadores: la ley de Amdahl.

Si una fase representa solamente una pequeña fracción del tiempo total, acelerarla enormemente puede producir una mejora global pequeña.

Si el setup representa:

\[
5\%
\]

del frame, aunque mágicamente consiguiéramos hacerlo instantáneo, el máximo beneficio global estaría limitado.

En cambio, si el raster o el clear ocupan gran parte del tiempo, una mejora moderada allí puede resultar mucho más importante.

Esta observación nos conduce directamente a v8.

Pero antes conviene extraer otra lección de v7.

---

# Parte XLVIII — La granularidad del paralelismo

## 97. No todo trabajo pequeño merece repartirse

Transformar ocho vértices es un caso especialmente limpio:

```text
8 elementos
8 lanes
mismo algoritmo
resultados independientes
```

Procesar seis caras es más complicado.

Aunque las caras son independientes en buena medida, la salida que queremos es una **lista compacta compartida**.

Eso introduce una dependencia estructural que no existía en la transformación de vértices.

Podemos resumir:

```text
VERTEX TRANSFORM

entrada:
V0 V1 V2 V3 V4 V5 V6 V7

salida:
P0 P1 P2 P3 P4 P5 P6 P7

correspondencia 1:1
```

frente a:

```text
CULLING / SETUP

entrada:
cara0 cara1 cara2 cara3 cara4 cara5

salida:
número variable de primitivas visibles

correspondencia:
NO necesariamente 1:1 compacta
```

El segundo problema requiere coordinación si queremos compactar.

Por eso paralelizar algoritmos no consiste simplemente en repartir iteraciones de un bucle.

Hay que estudiar también **cómo se producen y organizan los resultados**.

---

# Parte XLIX — v8: volver atrás también puede ser avanzar

## 98. Una decisión arquitectónica interesante

v8 no continúa ciegamente con todas las decisiones de v7.

El comentario inicial de v8 dice explícitamente que conserva la geometría SIMD y el setup compacto de v6.

Es decir:

```text
v6
├─ vértices SIMD
└─ setup compacto serial

v7
├─ vértices SIMD
└─ caras paralelas / 12 slots

v8
├─ vértices SIMD
└─ setup compacto serial
```

Esto es muy saludable desde el punto de vista experimental.

Una versión posterior no tiene por qué conservar una optimización simplemente porque conceptualmente parece más avanzada.

Podemos conservar las ideas que funcionan mejor para el conjunto.

---

# 99. ¿Qué optimiza entonces v8?

Algo aparentemente mucho menos sofisticado:

> **el borrado del framebuffer.**

Recordemos que v4 introdujo una pasada de clear porque el nuevo rasterizador ya no producía necesariamente un valor final para todas las palabras.

Hasta ahora borrábamos una región conservadora.

v8 observa algo sencillo:

> El cubo nunca ocupa toda esa región.

Así que podemos borrar menos memoria.

El encabezado proporciona los números concretos:

```text
antes: 28 672 palabras
ahora: 23 296 palabras
```

lo que representa una reducción del:

\[
18.75\%
\]

en palabras borradas.

---

# Parte L — Analizando el clear de v8

## 100. La nueva región

v8 limpia:

```text
xword = 24 .. 135
y     = 16 .. 223
```

El número de palabras por fila es:

\[
135-24+1=112
\]

El número de filas:

\[
223-16+1=208
\]

Por tanto:

\[
112\times208=23296
\]

palabras.

Cada palabra contiene 4 bytes:

\[
23296\times4=93184\ bytes
\]

Es decir, cada frame se evitan bastantes escrituras simplemente reconociendo dónde puede aparecer el objeto.

---

# 101. El clear también está diseñado para las ocho lanes

112 palabras por fila es un número especialmente cómodo:

\[
112/8=14
\]

Así que cada fila contiene exactamente catorce bloques de ocho palabras.

Podemos visualizar:

```text
fila:

bloque 0     bloque 1                   bloque 13
<------->    <------->                  <------->

L0...L7      L0...L7       ...          L0...L7
```

Cada bloque permite ocho stores consecutivos.

El clear de v8 utiliza precisamente esta organización: cada lane empieza en una palabra diferente de un bloque, avanza 32 bytes entre bloques y los warps se reparten las filas con separación de ocho.

Por tanto, incluso una operación tan simple como:

```text
framebuffer = negro
```

está cuidadosamente mapeada sobre la arquitectura paralela.

---

# 102. Borrar memoria no es gratis

Desde un punto de vista puramente algorítmico, el clear puede parecer irrelevante:

```text
memset(framebuffer, 0)
```

Pero una GPU no ejecuta conceptos.

Ejecuta operaciones.

Para limpiar 23 296 palabras tenemos que generar 23 296 escrituras de 32 bits, aunque puedan agruparse eficientemente.

A 60 frames por segundo:

\[
23296\times60=1\,397\,760
\]

palabras de 32 bits por segundo solo para esa región de clear.

En bytes:

\[
93184\times60=5\,591\,040\ bytes/s
\]

unos 5,6 MB/s de tráfico de escritura asociado únicamente al clear, ignorando cualquier detalle adicional de la implementación.

Para una GPU moderna esto sería minúsculo.

Para una pequeña GPU sobre FPGA con memoria y recursos limitados puede ser mucho más significativo.

El contexto importa.

---

# Parte LI — Una pregunta peligrosa: ¿por qué no eliminar el clear?

## 103. Volver a la idea de v3

v3 tenía una propiedad atractiva:

> siempre escribía el valor final de cada palabra.

Por tanto no necesitaba clear.

¿Podríamos conservar el eficiente rasterizador de v4–v8 y eliminar también el clear?

No inmediatamente.

El rasterizador actual solamente visita las bounding boxes de los triángulos.

Supongamos:

```text
frame N:

      +------+
      | cubo |
      +------+


frame N+1:

             +------+
             | cubo |
             +------+
```

Si dibujamos N+1 sin borrar, la posición anterior seguirá presente:

```text
      +------+       +------+
      | viejo|       | nuevo|
      +------+       +------+
```

Necesitamos borrar al menos las zonas que contienen imagen antigua y no serán sobrescritas.

---

# 104. Dirty rectangles

Una optimización posible sería recordar la región que ocupó el objeto.

Entonces podríamos borrar solamente:

```text
bbox anterior
```

antes de dibujar la nueva.

Pero el double buffering introduce la sutileza que comentamos anteriormente.

Supongamos:

```text
framebuffer A → frame N
framebuffer B → frame N+1
swap
```

Cuando volvemos a A, su contenido no es N+1.

Contiene N.

Por tanto necesitamos saber qué región está sucia **en cada framebuffer**.

Conceptualmente:

```text
FB A:
    dirty_bbox_A

FB B:
    dirty_bbox_B
```

Cuando A se convierte en back:

```text
clear(dirty_bbox_A)
draw_new_frame(A)
dirty_bbox_A = bbox_new
```

Después hacemos lo mismo independientemente con B.

Esto podría reducir todavía más el clear cuando el objeto ocupa una región pequeña.

Pero también añade:

- estado;
- cálculos de bounding box global;
- más lógica de control;
- posibles problemas de alineamiento;
- variabilidad en el trabajo.

v8 elige una región fija y conservadora.

Es menos sofisticada pero muy regular.

---

# Parte LII — Regularidad frente a trabajo mínimo

## 105. Una tensión constante en GPU

Aquí aparece otro principio general.

Podríamos intentar que cada thread hiciera **exactamente** el mínimo trabajo necesario.

Pero eso puede generar:

- ramas;
- tamaños variables;
- accesos no alineados;
- divergencia;
- coordinación adicional.

Otra estrategia es aceptar cierto trabajo extra pero mantener:

```text
bloques regulares
accesos consecutivos
mismos bucles
mismo patrón entre lanes
```

v8 sigue claramente esta filosofía.

La región de clear no coincide píxel por píxel con la silueta del cubo.

Es un rectángulo.

Se borran píxeles que nunca serán usados.

Pero el patrón resultante es extraordinariamente sencillo:

```text
112 palabras/fila
= 14 grupos exactos de 8
```

La GPU suele premiar la regularidad.

---

# Parte LIII — La evolución completa v3–v8

## 106. Ahora podemos leer las versiones como experimentos

Ya no necesitamos verlas simplemente como versiones de un programa.

Podemos interpretarlas como una secuencia de preguntas arquitectónicas.

### v3 — ¿Podemos rasterizar en paralelo?

Sí.

Distribuimos las palabras del framebuffer entre los 64 threads.

Cada palabra determina su color comprobando todos los triángulos.

La ventaja es que cada palabra obtiene un valor final y no necesitamos clear.

El problema es la cantidad de trabajo redundante.

### v4 — ¿Podemos reorganizar el raster para trabajar menos?

Sí.

Invertimos el orden:

```text
por píxel → todos los triángulos
```

se convierte en:

```text
por triángulo → bounding box
```

Añadimos:

- descriptores reutilizables;
- bounding boxes;
- edge functions incrementales;
- reparto por warps y lanes;
- accesos BL8 coalesced.

A cambio aparece el clear y el read-modify-write.

### v5 — ¿Puede la GPU generar su propia geometría?

Sí.

La MiniGPU pasa a calcular:

- vértices;
- rotación;
- proyección;
- culling;
- edge functions;
- bounding boxes;
- descriptores.

Pero lo hace inicialmente en un único thread.

### v6 — ¿Podemos explotar SIMD en la geometría?

Sí.

Los ocho vértices encajan naturalmente en las ocho lanes.

La transformación de vértices pasa a ser paralela.

El setup permanece serial y compacto.

### v7 — ¿Podemos paralelizar también el setup?

Sí, técnicamente.

Seis lanes procesan seis caras.

Pero evitar la compactación requiere doce slots fijos.

La simplificación de una fase cambia el trabajo de la siguiente.

La lección deja de ser simplemente “más paralelismo”.

### v8 — ¿Dónde más estamos gastando trabajo?

En el clear.

Se conserva la geometría SIMD y el setup compacto de v6 y se reduce la región borrada un 18,75 %.

La evolución completa puede verse así:

```text
v3
│
│ raster paralelo
▼
v4
│
│ bbox + incremental + coalescing
▼
v5
│
│ geometría dentro de GPU
▼
v6
│
│ vértices SIMD
├───────────────┐
│               │
▼               │
v7              │
│ setup SIMD    │
│ experimento   │
│               │
└──────┐        │
       │        │
       ▼        ▼
          v8
   setup compacto v6
       +
   clear optimizado
```

Esto no es una línea donde cada versión sustituye necesariamente todas las decisiones de la anterior.

Es un pequeño espacio de diseño.

---

# Parte LIV — ¿Dónde está el “3D” realmente?

## 107. Una observación importante

Después de todo este recorrido podemos hacer una afirmación que inicialmente puede resultar extraña:

> El rasterizador no dibuja 3D.

El rasterizador de v8 recibe triángulos que ya están expresados en coordenadas de pantalla.

Para él existen:

```text
A0,B0,C0
A1,B1,C1
A2,B2,C2
bbox
color
```

No sabe si esos triángulos proceden de:

- un cubo 3D;
- una interfaz 2D;
- un modelo de una nave espacial;
- un programa que los ha generado aleatoriamente.

La parte 3D ocurre antes:

```text
coordenadas 3D
     |
transformación
     |
proyección
     v
coordenadas 2D
```

Después el problema se convierte en determinar cobertura sobre una cuadrícula.

Esta separación es una de las ideas más importantes para entender un pipeline gráfico.

---

# Parte LV — ¿Por qué nuestro cubo no necesita Z-buffer?

## 108. Un problema que todavía hemos evitado

Supongamos que tenemos dos triángulos:

```text
       TRIÁNGULO A
          delante

       TRIÁNGULO B
          detrás
```

Ambos pueden proyectarse sobre el mismo píxel.

¿Cómo sabe el rasterizador cuál es visible?

Nuestro rasterizador básico no conserva profundidad por píxel.

Tiene esencialmente:

```text
framebuffer[x,y] = color
```

no:

```text
depthbuffer[x,y] = z
```

Para un cubo convexo simple, con back-face culling y una organización controlada del dibujo, podemos construir una demostración visual útil sin implementar todavía un subsistema general de profundidad.

Pero para escenas 3D arbitrarias esto deja de ser suficiente.

---

# 109. El problema de la oclusión

Imaginemos dos triángulos que se cruzan en pantalla:

```text
         AAAAA
       AAA   AAA
     AAA   BBB AAA
       BBBBBBB
         BBB
```

La proyección 2D nos dice que ambos cubren ciertos píxeles.

Pero necesitamos saber cuál está más cerca de la cámara en cada punto.

Ordenar simplemente los triángulos no siempre basta.

Podrían incluso intersectarse de forma que:

```text
en una zona A está delante de B
en otra zona B está delante de A
```

Necesitamos una decisión **por muestra/píxel**.

Aquí aparece el **depth buffer** o **Z-buffer**.

---

# Parte LVI — Z-buffer

## 110. Una memoria adicional

Además del color:

```text
color_buffer[x,y]
```

almacenamos una profundidad:

```text
depth_buffer[x,y]
```

Cuando rasterizamos un fragmento calculamos:

```text
new_z
```

y comparamos:

```text
if new_z < depth_buffer[x,y]:
    depth_buffer[x,y] = new_z
    color_buffer[x,y] = color
```

dependiendo de la convención de profundidad utilizada.

Conceptualmente:

```text
TRIÁNGULO
    |
    v
¿cubre píxel?
    |
   sí
    |
    v
¿está más cerca?
   / \
 no   sí
 |     |
desc.  actualizar Z
       actualizar color
```

Ahora el orden de rasterización deja de determinar por sí solo qué superficie permanece visible.

---

# 111. El coste del Z-buffer

La solución es elegante pero arquitectónicamente cara.

Antes teníamos aproximadamente:

```text
LOAD color
STORE color
```

Ahora podemos necesitar además:

```text
LOAD depth
COMPARE
STORE depth
```

y solamente después actualizar color.

Eso significa:

- más memoria;
- más ancho de banda;
- más operaciones;
- más posibilidades de optimización y cache.

Para 320 × 240, si utilizásemos 32 bits de profundidad:

\[
320\times240\times4=307200\ bytes
\]

solo para el depth buffer.

En una FPGA pequeña esta cantidad ya importa.

Esta es una razón excelente para no introducir un Z-buffer hasta que realmente lo necesitamos.

---

# Parte LVII — De píxel a fragmento

## 112. Una precisión terminológica

Hasta ahora hemos hablado informalmente de “píxeles del triángulo”.

En gráficos es útil distinguir entre **fragmento** y **píxel almacenado**.

Cuando un triángulo cubre una posición de pantalla genera conceptualmente un candidato:

```text
fragmento:
    x
    y
    profundidad
    color
    otros atributos
```

Ese fragmento todavía podría ser descartado:

- por depth test;
- por transparencia;
- por stencil;
- por otras pruebas.

Solo si sobrevive termina modificando el framebuffer.

Así:

```text
triángulo
   |
rasterización
   |
   v
fragmentos
   |
tests
   |
   v
framebuffer
```

En nuestro MiniGPU actual esta distinción está muy comprimida porque el rasterizador hace directamente los edge tests y modifica RGB565.

Pero conceptualmente es útil introducirla para entender GPUs más generales.

---

# Parte LVIII — Nuestro cubo tiene colores planos

## 113. Un color por triángulo

Los descriptores utilizados por el rasterizador contienen un color.

Así podemos hacer:

```text
triángulo 0 → rojo
triángulo 1 → rojo
triángulo 2 → verde
...
```

Todo píxel cubierto por ese triángulo recibe esencialmente el mismo RGB565.

Esto se conoce como un tipo de sombreado plano.

Pero una GPU 3D normalmente quiere hacer mucho más.

Por ejemplo, podemos querer que cada vértice tenga un color diferente:

```text
          rojo
           *
          / \
         /   \
        /     \
       /       \
      *---------*
   verde       azul
```

¿Qué color debería tener el centro?

Necesitamos **interpolar atributos**.

---

# Parte LIX — Interpolación

## 114. Coordenadas baricéntricas

Un punto dentro de un triángulo puede expresarse como combinación de sus tres vértices:

\[
P=\alpha P_0+\beta P_1+\gamma P_2
\]

con:

\[
\alpha+\beta+\gamma=1
\]

y, para puntos interiores:

\[
\alpha,\beta,\gamma\ge0
\]

Esos mismos pesos pueden utilizarse para interpolar atributos.

Si los vértices tienen colores:

\[
C_0,C_1,C_2
\]

podemos calcular:

\[
C(P)=\alpha C_0+\beta C_1+\gamma C_2
\]

Y lo mismo para:

- coordenadas de textura;
- profundidad;
- normales;
- valores de iluminación;
- otros atributos.

Las edge functions que ya conocemos están estrechamente relacionadas con esta forma de calcular coordenadas baricéntricas.

Por tanto, nuestro rasterizador ya contiene parte de la matemática que necesitaríamos para evolucionar hacia interpolación.

---

# Parte LX — Texturas

## 115. En vez de un color, una imagen

Supongamos que queremos poner una imagen sobre una cara del cubo.

Cada vértice puede tener coordenadas:

\[
(u,v)
\]

que indican una posición dentro de una textura.

Por ejemplo:

```text
triángulo en pantalla        textura

       A                     (0,0)------(1,0)
      / \                       |          |
     /   \                      | imagen   |
    B-----C                  (0,1)------(1,1)
```

Durante el rasterizado interpolamos `(u,v)` para cada fragmento.

Después hacemos:

```text
texel = texture[u,v]
```

y utilizamos ese valor para producir el color.

Ahora el rasterizador ya no genera únicamente escrituras de memoria.

También genera lecturas de memoria potencialmente complejas.

---

# 116. De repente la memoria vuelve a dominar

Con texturas aparece otro patrón:

```text
lane 0 → texture[address0]
lane 1 → texture[address1]
...
lane 7 → texture[address7]
```

Si las coordenadas están próximas, quizá los accesos tienen buena localidad.

Si no, pueden estar dispersos.

Esto explica por qué las GPU modernas dedican una enorme cantidad de hardware a:

- caches;
- unidades de textura;
- filtrado;
- compresión;
- jerarquías de memoria.

Pero conceptualmente seguimos haciendo lo mismo que aprendimos con BL8:

> observar qué direcciones producen conjuntamente las lanes.

La escala es diferente.

El principio permanece.

---

# Parte LXI — Shaders

## 117. ¿Y si el color no es simplemente una textura?

Podemos querer calcular:

```text
color = función(
    textura,
    normal,
    luz,
    posición,
    material,
    ...
)
```

En vez de construir hardware fijo para cada efecto posible, las GPUs modernas permiten ejecutar pequeños programas.

Estos programas son los **shaders**.

Simplificando mucho:

**Vertex shader**

trabaja sobre vértices.

**Fragment/pixel shader**

trabaja sobre fragmentos.

Nuestro código de v6 ya tiene algo conceptualmente parecido a un programa de vértices:

```text
vértice
  |
rotar
  |
proyectar
  |
posición de pantalla
```

Y nuestro rasterizador tiene algo extremadamente simple parecido al resultado de un fragment shader:

```text
if covered:
    color = triangle_color
```

No estamos implementando una API moderna de shaders, pero la separación conceptual empieza a ser reconocible.

---

# Parte LXII — Mapear MiniGPU a un pipeline gráfico moderno

## 118. El pipeline conceptual moderno

Sin pretender describir una GPU comercial concreta, podemos representar un pipeline gráfico clásico de forma aproximada:

```text
VERTEX DATA
     |
     v
+------------------+
| Vertex Shader    |
+------------------+
     |
     v
+------------------+
| Primitive        |
| Assembly         |
+------------------+
     |
     v
+------------------+
| Clipping/Culling |
+------------------+
     |
     v
+------------------+
| Rasterization    |
+------------------+
     |
     v
+------------------+
| Fragment Shader  |
+------------------+
     |
     v
+------------------+
| Depth / Blend    |
+------------------+
     |
     v
+------------------+
| Framebuffer      |
+------------------+
     |
     v
   DISPLAY
```

Ahora podemos relacionarlo con nuestro cubo.

---

# 119. Vertex processing

En MiniGPU:

```text
cube vertex
     |
rotación Q14
     |
perspectiva
     |
cube_points
```

En una GPU moderna, buena parte de este trabajo podría expresarse mediante un vertex shader.

La gran idea común es:

> ejecutar una transformación similar sobre muchos vértices.

v6 demuestra exactamente por qué esta fase se presta al paralelismo SIMD/SIMT.

---

# 120. Primitive assembly y setup

Nuestros índices:

```text
V0,V1,V2
```

indican qué vértices forman un triángulo.

Después hacemos:

- orientación;
- culling;
- edge equations;
- bounding box.

Eso corresponde conceptualmente a trabajo de ensamblado y setup de primitivas.

En nuestro caso es software.

En otras arquitecturas algunas de estas tareas pueden estar implementadas mediante hardware especializado.

---

# 121. Rasterización

Aquí la correspondencia es directa.

Nuestro rasterizador toma:

```text
triángulo
```

y determina:

```text
qué muestras/píxeles cubre
```

utilizando edge functions.

Una GPU moderna dispone normalmente de hardware altamente especializado para esta fase.

Pero la matemática fundamental que hemos estudiado sigue siendo relevante.

---

# 122. Fragment processing

Nuestro fragment processing es casi trivial:

```text
color = color_del_triangulo
```

No hay iluminación compleja ni texturas.

Una GPU programable moderna podría ejecutar un fragment shader para cada grupo de fragmentos.

De nuevo encontramos:

```text
muchos fragmentos
+
programa semejante
=
SIMD/SIMT
```

---

# 123. Depth, blending y salida

Nuestro ejemplo escribe RGB565 directamente.

Un pipeline más general puede realizar:

```text
depth test
stencil
blending
multisampling
...
```

antes de actualizar el framebuffer.

Estas operaciones suelen estar muy cerca de memoria y necesitan un ancho de banda considerable.

La simplicidad de MiniGPU permite ver qué funcionalidad todavía no existe en lugar de esconderla detrás de una API.

---

# Parte LXIII — Hardware fijo frente a software programable

## 124. ¿Por qué no hacerlo todo con instrucciones?

Nuestro ejemplo hace muchísimo trabajo mediante software.

Podríamos continuar:

```text
depth test → software
interpolación → software
texturas → software
```

¿Por qué una GPU real incluye unidades especializadas?

Porque algunas operaciones:

- aparecen constantemente;
- tienen patrones muy regulares;
- consumen mucho rendimiento o ancho de banda;
- pueden implementarse mucho más eficientemente en hardware dedicado.

Por ejemplo, un rasterizador hardware puede evaluar cobertura de muchos píxeles sin ejecutar una larga secuencia explícita de instrucciones por cada uno.

Pero el hardware fijo tiene un coste:

- área;
- complejidad;
- menor flexibilidad.

El diseño de una GPU consiste en buena medida en decidir:

> **¿qué debe ser programable y qué merece convertirse en hardware especializado?**

MiniGPU es un laboratorio excelente para explorar precisamente esa frontera.

---

# Parte LXIV — Un ejemplo: ¿hardware para edge functions?

## 125. Lo que hoy hacemos en software

Nuestro inner loop necesita repetidamente:

```text
test E0
test E1
test E2

E0 += step0
E1 += step1
E2 += step2
```

Podríamos imaginar una unidad especializada que recibiera:

```text
A0,B0,C0
A1,B1,C1
A2,B2,C2
bbox
```

y produjera máscaras de cobertura:

```text
11011100
```

para ocho lanes/píxeles.

Eso reduciría muchas instrucciones.

Pero gastaríamos LUTs, registros y rutas adicionales en FPGA.

¿Merece la pena?

Solo podemos responder estudiando:

- cuántos ciclos consume hoy;
- qué porcentaje del frame representa;
- cuánto hardware costaría;
- qué Fmax perderíamos o ganaríamos;
- si esa lógica podría reutilizarse.

Este es exactamente el tipo de pregunta que convierte el ejemplo del cubo en un proyecto de Arquitectura de Computadores y no simplemente en una demo gráfica.

---

# Parte LXV — Fmax también forma parte del rendimiento

## 126. Más hardware puede hacer una GPU más lenta

Supongamos dos diseños.

Diseño A:

```text
100 ciclos por bloque
100 MHz
```

Diseño B añade muchísimo hardware paralelo:

```text
70 ciclos por bloque
60 MHz
```

El segundo utiliza menos ciclos, pero eso no garantiza menor tiempo.

A:

\[
100/100\,MHz=1\ \mu s
\]

B:

\[
70/60\,MHz\approx1.17\ \mu s
\]

El diseño con menos ciclos es más lento.

En FPGA esto es especialmente importante.

Añadir:

- multiplexores;
- bypass;
- unidades funcionales;
- rutas de forwarding;
- lógica de arbitraje;

puede aumentar el camino crítico y reducir Fmax.

Por eso las optimizaciones de MiniGPU deben evaluarse al menos en dos dimensiones:

```text
ciclos
×
periodo del reloj
```

y además considerar:

```text
LUT
FF
BRAM
DSP
```

---

# Parte LXVI — Cómo medir nuestro rasterizador

## 127. Qué métricas nos interesan

Ahora que entendemos el pipeline, podemos definir métricas mucho más útiles que simplemente “se ve fluido”.

Por frame podríamos contar:

```text
frames generados
swaps
```

Por fase:

```text
ciclos vertex transform
ciclos triangle setup
ciclos clear
ciclos raster
ciclos esperando swap
```

Por rasterización:

```text
triángulos procesados
palabras visitadas
píxeles testeados
píxeles cubiertos
LOADs
STOREs
bloques BL8
```

Por ejecución SIMT:

```text
lanes activas
divergencia
warps esperando ALU
warps esperando LSU
warps esperando BAR
```

Por vídeo:

```text
scanout underflow
swaps por segundo
frames presentados
```

Estas métricas permitirían responder empíricamente preguntas como:

> ¿v7 gana realmente algo?

> ¿qué porcentaje del frame consume el clear?

> ¿cuánto aporta v8?

> ¿el raster está limitado por ALU o por memoria?

> ¿los `MUL` del setup importan?

> ¿estamos ocultando correctamente las latencias entre warps?

Una vez que tenemos instrumentación, dejamos de optimizar por intuición.

---

# Parte LXVII — FPS, frames y swaps

## 128. Qué significa realmente FPS en este sistema

Si el scanout funciona a 60 Hz, existen 60 oportunidades de presentación por segundo.

Pero eso no significa automáticamente que la GPU esté generando 60 frames distintos.

Si contamos swaps completados durante un segundo obtenemos una medida muy útil de la tasa de frames presentados por la GPU:

\[
FPS \approx swaps/segundo
\]

si cada frame generado produce exactamente un swap.

Por ejemplo:

```text
scanout = 60 Hz
swaps   = 60/s
```

la GPU mantiene el ritmo.

Si:

```text
scanout = 60 Hz
swaps   = 42/s
```

algunas imágenes tendrán que permanecer visibles durante más de un refresco.

Esto distingue:

```text
frecuencia de refresco
```

de:

```text
frecuencia de generación/presentación de frames nuevos
```

Una distinción que en gráficos es fundamental.

---

# Parte LXVIII — El coste real de una instrucción GPU

## 129. “Una instrucción” no significa necesariamente “un ciclo”

Supongamos:

```text
MUL R3,R1,R2
```

El ISA presenta una única instrucción.

Pero internamente podría:

- tardar varios ciclos;
- bloquear el warp;
- utilizar una unidad compartida;
- permitir que otro warp avance mientras tanto.

Lo mismo ocurre con:

```text
DIV
LOAD
STORE
```

Por eso una GPU suele utilizar múltiples warps no solamente para hacer más trabajo, sino también para **ocultar latencias**.

---

# 130. Latency hiding

Imaginemos:

```text
warp 0 → LOAD → esperando memoria
```

Si la máquina simplemente se detiene, perdemos ciclos.

Pero quizá podemos ejecutar:

```text
warp 1 → ADD
warp 2 → MUL
warp 3 → edge tests
```

mientras llega el resultado.

Conceptualmente:

```text
ciclo

1   W0 LOAD
2   W1 ADD
3   W2 ADD
4   W3 MUL
5   W1 ...
6   W0 resultado listo
```

Esta es otra razón para disponer de múltiples warps residentes.

No todo el paralelismo tiene que ejecutarse físicamente a la vez.

También podemos **intercalar** trabajo para mantener ocupadas las unidades funcionales.

Esto enlaza directamente con decisiones de microarquitectura de MiniGPU: qué hace el scheduler cuando un warp está en `WAIT_ALU`, `WAIT_LSU` o esperando una barrera.

---

# Parte LXIX — Throughput frente a latencia

## 131. Una GPU puede aceptar latencias largas

Una CPU orientada a un único thread suele preocuparse enormemente por la latencia de una operación individual.

Una GPU está a menudo más interesada en **throughput**:

> cuántos elementos terminamos por unidad de tiempo.

Si una multiplicación tarda varios ciclos pero podemos mantener otras operaciones en vuelo, quizá sea aceptable.

Por ejemplo:

```text
latencia MUL = 4 ciclos
```

no implica necesariamente:

```text
una MUL cada 4 ciclos
```

Una unidad pipelined podría tener:

```text
latencia = 4
throughput = 1 por ciclo
```

O una unidad iterativa podría tener:

```text
latencia = 4
throughput = 1 cada 4 ciclos
```

Son arquitecturas muy diferentes.

Para comprender el rendimiento de MiniGPU necesitaremos distinguir siempre:

```text
latencia
```

de:

```text
throughput
```

---

# Parte LXX — Por qué este cubo es un buen benchmark

## 132. Es pequeño, pero toca casi todo

El cubo parece una demo gráfica elemental.

Sin embargo ejercita:

- instrucciones aritméticas;
- multiplicación;
- división;
- shifts;
- punto fijo;
- tablas en memoria;
- loads;
- stores;
- ramas;
- divergencia;
- reconvergencia;
- warps;
- lanes;
- barriers;
- acceso coalesced;
- framebuffer;
- MMIO;
- double buffering;
- scanout;
- sincronización CPU/GPU/vídeo conceptual;
- geometría;
- rasterización.

Y además produce un resultado visual.

Eso es extremadamente útil.

Un error en una unidad aritmética puede deformar el cubo.

Un error en rasterización puede generar agujeros.

Un problema de sincronización puede producir artefactos.

Un problema de framebuffer puede alterar colores o posiciones.

Un problema de swap puede verse como tearing o frames incorrectos.

El programa funciona simultáneamente como demostración y como carga arquitectónica.

---

# Parte LXXI — Lo que MiniGPU todavía no es

## 133. Evitar una comparación injusta

Después de relacionar nuestro diseño con GPUs modernas podría parecer que MiniGPU es simplemente una versión pequeña de una GPU comercial.

No exactamente.

Los ejemplos que hemos estudiado demuestran un conjunto concreto de capacidades y técnicas.

No debemos atribuirle automáticamente:

- caches gráficas sofisticadas;
- texture units;
- hardware de clipping;
- raster units dedicadas;
- Z compression;
- hierarchical Z;
- blending hardware;
- tile-based rendering;
- shaders compatibles con APIs comerciales;
- scheduling comparable a arquitecturas comerciales.

Nada de eso se deduce de estos ejemplos.

Lo valioso es que MiniGPU nos permite estudiar **los problemas que motivan muchas de esas soluciones**.

Y eso es pedagógicamente incluso más interesante.

---

# Parte LXXII — Construir una GPU desde abajo

## 134. Lo que hemos hecho realmente

Empezamos con:

```text
memoria
```

Después:

```text
memoria
→ framebuffer
→ RGB565
→ dos píxeles/palabra
```

Después:

```text
triángulos
→ edge functions
→ píxeles
```

Después:

```text
bounding boxes
→ incrementalidad
```

Después:

```text
threads
→ warps
→ lanes
→ SIMT
```

Después:

```text
coalescing
→ barriers
→ double buffering
```

Después:

```text
vértices 3D
→ rotación
→ perspectiva
→ culling
→ setup
```

Y finalmente:

```text
paralelismo de geometría
→ trade-offs del pipeline
→ optimización de memoria
```

Es decir, no hemos aprendido una lista de bloques que “tiene una GPU”.

Hemos descubierto **por qué empiezan a aparecer esos bloques y conceptos**.

---

# Parte LXXIII — El recorrido de un único vértice

## 135. Sigamos ahora un dato concreto

Para consolidar todo, imaginemos el vértice 3 del cubo.

Inicialmente:

\[
V_3=(x,y,z)
\]

En v6 una lane lo recibe.

Aplica rotaciones:

\[
(x,y,z)\rightarrow(x_r,y_r,z_r)
\]

Después cámara:

\[
z_c=z_r+768
\]

Proyección:

\[
s_x=160+\frac{140x_r}{z_c}
\]

\[
s_y=120+\frac{140y_r}{z_c}
\]

Finalmente almacena:

```text
cube_points[3] = (sx,sy)
```

En ese momento el vértice deja de ser 3D desde el punto de vista del rasterizador.

---

# Parte LXXIV — El recorrido de un triángulo

## 136. Tres vértices se convierten en ecuaciones

Supongamos:

```text
T = V1,V3,V6
```

El setup carga:

```text
P1 = cube_points[1]
P3 = cube_points[3]
P6 = cube_points[6]
```

Calcula orientación.

Si la cara es trasera:

```text
discard
```

Si es visible:

```text
P1,P3 → edge 0
P3,P6 → edge 1
P6,P1 → edge 2
```

y obtiene:

\[
E_0=A_0x+B_0y+C_0
\]

\[
E_1=A_1x+B_1y+C_1
\]

\[
E_2=A_2x+B_2y+C_2
\]

También obtiene:

```text
minX
maxX
minY
maxY
color
```

El triángulo queda convertido en un descriptor.

---

# Parte LXXV — El recorrido de una palabra del framebuffer

## 137. De geometría a bits

Supongamos que `lane 4` recibe una palabra que representa:

```text
pixel (108,73)
pixel (109,73)
```

La lane ya tiene los valores de las edge functions para `(108,73)`:

```text
E0
E1
E2
```

Comprueba:

```text
E0 >= 0
E1 >= 0
E2 >= 0
```

Si se cumplen, el primer píxel pertenece al triángulo.

Para el segundo utiliza:

```text
E0 + A0
E1 + A1
E2 + A2
```

Después carga la palabra existente:

```text
old_word = LOAD(address)
```

Supongamos:

```text
pixel 108 → dentro
pixel 109 → fuera
```

Conserva los 16 bits correspondientes al segundo y sustituye los del primero por RGB565.

Finalmente:

```text
STORE(address,new_word)
```

Y esa operación de 32 bits es el final físico de una cadena que empezó con un vértice tridimensional.

---

# 138. Toda la GPU en una cadena

Podemos escribir ahora el recorrido completo:

```text
(x,y,z)
   |
   | rotación
   v
(xr,yr,zr)
   |
   | perspectiva
   v
(sx,sy)
   |
   | primitive setup
   v
A,B,C + bbox
   |
   | rasterización
   v
coverage
   |
   | color
   v
RGB565
   |
   | pack
   v
32-bit word
   |
   | STORE
   v
framebuffer
   |
   | scanout
   v
HDMI / pantalla
```

Esta cadena es probablemente la idea más importante de todo el documento.

Una GPU gráfica es una máquina construida para ejecutar eficientemente enormes cantidades de transformaciones de este estilo.

---

# Parte LXXVI — ¿Qué enseñan realmente v3–v8?

## 139. Primera lección: los gráficos son computación

No hay nada misterioso en “dibujar”.

Tenemos:

- álgebra;
- comparaciones;
- transformaciones;
- memoria.

Una imagen termina siendo un conjunto de números almacenados.

---

## 140. Segunda lección: los gráficos contienen paralelismo natural

Los vértices pueden procesarse independientemente.

Los fragmentos pueden procesarse independientemente en gran medida.

Eso permite aplicar la misma secuencia de instrucciones a muchos datos.

De ahí la utilidad de SIMD/SIMT.

---

## 141. Tercera lección: el mapping importa

No basta con tener 64 threads.

Hay que decidir qué hace cada uno.

v4 utiliza:

```text
lane → posición horizontal
warp → posición vertical
```

porque así obtiene simultáneamente:

- reparto de trabajo;
- edge functions incrementales;
- accesos consecutivos;
- BL8.

Es una decisión algorítmica y arquitectónica al mismo tiempo.

---

## 142. Cuarta lección: memoria y cómputo están ligados

Dos píxeles RGB565 por palabra producen read-modify-write.

El ancho del warp determina bloques de ocho palabras.

El coalescing condiciona el reparto horizontal.

El double buffering condiciona el clear.

La representación de datos nunca es un detalle aislado.

---

## 143. Quinta lección: la sincronización nace de dependencias reales

Usamos barreras porque:

```text
vertex transform
→ triangle setup
```

tiene una relación productor-consumidor.

Y porque:

```text
triangle N
→ triangle N+1
```

puede producir carreras de read-modify-write si las fases se solapan.

Una barrera no debería aparecer simplemente porque “esto es código GPU”.

Debe responder a una dependencia.

---

## 144. Sexta lección: más paralelismo no es automáticamente mejor

v7 es el ejemplo perfecto.

Paralelizar el setup modifica la representación de salida y puede trasladar trabajo al rasterizador.

El objetivo no es maximizar:

```text
número de lanes ocupadas
```

sino minimizar el coste global respetando recursos y frecuencia.

---

## 145. Séptima lección: optimizar significa medir

v8 optimiza algo tan poco glamuroso como el clear.

Eso puede ser más útil que añadir una unidad sofisticada si el clear representa una fracción importante del frame.

Sin contadores no sabemos cuánto.

Por eso una GPU experimental necesita observabilidad.

---

# Parte LXXVII — Un posible camino a partir de v8

## 146. ¿Qué podría ser v9?

A partir de aquí ya abandonamos la evolución documentada por los ejemplos y entramos en **posibles experimentos futuros**. Por tanto, lo siguiente no describe código existente en v3–v8.

Un experimento razonable sería medir primero:

```text
Tgeometry
Tsetup
Tclear
Traster
Tswap_wait
```

Antes de tocar nada.

Después elegir la fase dominante.

Por ejemplo, si el clear resulta importante, podríamos experimentar con dirty rectangles por framebuffer.

Si domina raster, podríamos estudiar:

- coste del `LOAD`;
- coste de las ramas;
- utilización de lanes;
- número de palabras procesadas fuera del triángulo;
- coste de los `MUL` de inicialización.

Si domina geometría:

- latencia de `DIV`;
- utilización del multiplicador;
- scheduling entre warps;
- alternativas de perspectiva.

La medición debería decidir la dirección.

---

# 147. Precalcular más información en el descriptor

Otra posibilidad sería trasladar cálculos desde los 64 threads al setup.

Por ejemplo, algunos incrementos de edge functions dependen únicamente del triángulo:

\[
16A_0,\quad16A_1,\quad16A_2
\]

El setup podría almacenarlos en el descriptor.

Entonces el rasterizador evitaría recalcularlos repetidamente.

Pero el descriptor crecería.

Eso significa:

```text
menos MUL
```

a cambio de:

```text
más memoria
más LOAD
descriptor mayor
```

¿Cuál gana?

No podemos decidirlo sin conocer los costes reales de MiniGPU.

Es un magnífico experimento arquitectónico.

---

# 148. Eliminar el LOAD del rasterizador

Otra pregunta interesante:

> ¿Podemos evitar el read-modify-write?

Actualmente:

```text
LOAD word
modificar 0, 1 o 2 píxeles
STORE word
```

Si el ISA o el LSU permitiera stores parciales de 16 bits, podríamos escribir únicamente el píxel cubierto.

Pero eso plantea nuevas preguntas:

- ¿cómo coalescen ocho `STOREH`?
- ¿qué ocurre si ambas mitades están cubiertas?
- ¿aumenta el número de transacciones?
- ¿qué complejidad añade al LSU?
- ¿afecta al banking?
- ¿mejora realmente el rendimiento?

Otra vez, una modificación aparentemente sencilla cruza ISA, LSU, memoria y rasterizador.

---

# 149. Más hardware especializado

También podríamos experimentar con una instrucción gráfica.

Por ejemplo, puramente como idea:

```text
EDGE3
```

que evaluara tres edge functions o generase una máscara.

Pero antes habría que demostrar que:

1. esa operación domina suficiente tiempo;
2. la instrucción reduce suficientes ciclos;
3. el coste de hardware es razonable;
4. no perjudica Fmax;
5. no estamos construyendo hardware excesivamente específico para un único demo.

Esta última pregunta es especialmente importante.

Una GPU programable debe conservar cierta generalidad.

---

# Parte LXXVIII — Conclusión

## 150. De Arquitectura de Computadores a gráficos

Si se conoce Arquitectura de Computadores pero no gráficos, una GPU puede parecer inicialmente un mundo separado.

Después de seguir el cubo de MiniGPU debería resultar mucho menos exótica.

Seguimos encontrando conceptos familiares:

```text
registros
ALUs
MUL/DIV
memoria
LOAD/STORE
latencia
throughput
dependencias
hazards
sincronización
ancho de banda
localidad
paralelismo
```

Lo particular de una GPU está en cómo organiza esos recursos alrededor de cargas con cantidades enormes de paralelismo de datos.

Los gráficos proporcionan exactamente ese tipo de carga.

---

# 151. El cubo visto por una persona

Una persona ve:

```text
          +--------+
         /        /|
        /        / |
       +--------+  |
       |        |  |
       |        |  +
       |        | /
       |        |/
       +--------+
```

Dice:

> “Es un cubo girando.”

---

# 152. El cubo visto por la GPU

La GPU ve primero:

```text
-256
+256
sin
cos
MUL
SAR
DIV
```

Después:

```text
(132,74)
(201,91)
(183,164)
```

Después:

```text
A0 B0 C0
A1 B1 C1
A2 B2 C2
```

Después:

```text
E0 >= 0
E1 >= 0
E2 >= 0
```

Después:

```text
RGB565 = 0x....
```

Después:

```text
STORE [framebuffer + offset], value
```

Y finalmente el scanout lee esa memoria siguiendo el ritmo del vídeo.

El cubo no existe como concepto dentro de la máquina.

Existe como una sucesión de representaciones numéricas.

---

# 153. La idea fundamental

Si hubiera que conservar una sola idea de todo este recorrido sería esta:

> **Una GPU es interesante no porque conozca objetos 3D, sino porque está organizada para aplicar enormes cantidades de cálculo semejante sobre datos diferentes y mover esos datos por memoria de forma eficiente.**

El pipeline gráfico transforma el problema hasta conseguir precisamente esa forma.

Un modelo 3D se descompone en vértices.

Los vértices se transforman independientemente.

Las primitivas se convierten en triángulos.

Los triángulos se convierten en fragmentos.

Los fragmentos pueden procesarse masivamente en paralelo.

Y los resultados terminan convertidos en escrituras al framebuffer.

MiniGPU permite observar esa transformación sin que quede escondida detrás de millones de líneas de driver, shaders, caches y hardware especializado.

---

# 154. La evolución resumida en una imagen

```text
                         CUBO 3D
                            |
                            v
                  +------------------+
                  | 8 VÉRTICES       |
                  +------------------+
                            |
                  v5 serial / v6 SIMD
                            |
                            v
                  +------------------+
                  | ROTACIÓN         |
                  | PROYECCIÓN       |
                  +------------------+
                            |
                            v
                  +------------------+
                  | PUNTOS 2D        |
                  +------------------+
                            |
                  culling + setup
                  v6 serial / v7 SIMD
                            |
                            v
                  +------------------+
                  | DESCRIPTORES     |
                  | A,B,C + bbox     |
                  +------------------+
                            |
                            v
                  +------------------+
                  | RASTERIZACIÓN    |
                  | 64 threads       |
                  +------------------+
                            |
                 +----------+----------+
                 |                     |
              warps                  lanes
              filas             palabras contiguas
                 |                     |
                 +----------+----------+
                            |
                            v
                    EDGE FUNCTIONS
                            |
                            v
                     COVERAGE TEST
                            |
                            v
                       RGB565
                            |
                            v
                   +----------------+
                   | FRAMEBUFFER    |
                   +----------------+
                            |
                          SWAP
                            |
                            v
                   +----------------+
                   | SCANOUT        |
                   +----------------+
                            |
                            v
                        PANTALLA
```

---

# 155. Epílogo: por qué construirlo así merece la pena

Podríamos haber empezado este documento mostrando el diagrama de una GPU moderna y diciendo:

```text
esto es un vertex shader
esto es un rasterizer
esto es un fragment shader
esto es un ROP
```

Habríamos aprendido nombres.

Pero no necesariamente habríamos entendido por qué existen.

La evolución v3–v8 nos permite recorrer el camino contrario.

Primero aparece un problema:

> estamos comprobando demasiados píxeles.

Entonces aparece una bounding box.

Después:

> estamos recalculando demasiado.

Aparecen edge functions incrementales.

Después:

> tenemos muchos píxeles independientes.

Aparecen lanes, warps y SIMT.

Después:

> las lanes acceden a memoria.

Aparece el coalescing.

Después:

> unas lanes toman ramas diferentes.

Aparecen divergencia y reconvergencia.

Después:

> diferentes fases comparten datos.

Aparecen barreras.

Después:

> queremos generar la geometría.

Aparecen transformación y proyección.

Después:

> tenemos ocho vértices independientes.

Aparece el SIMD de v6.

Después:

> queremos paralelizar el setup.

v7 nos enseña que el paralelismo también tiene costes.

Después:

> seguimos escribiendo demasiada memoria.

v8 reduce el clear.

Esta forma de llegar a una GPU es probablemente más útil para alguien interesado en Arquitectura de Computadores que memorizar la organización de una arquitectura comercial concreta.

Porque permite formular la pregunta que realmente importa al diseñar una máquina:

> **¿Qué problema estoy intentando resolver, qué trabajo está haciendo realmente el programa y qué organización del hardware permite hacerlo con menos tiempo, menos tráfico y un coste razonable de recursos?**

Ese es exactamente el tipo de pregunta que convierte a MiniGPU en algo más interesante que un circuito capaz de dibujar un cubo.

# Apéndice A — Rasterizar un triángulo completo a mano

## A.1. Objetivo

Durante el documento hemos utilizado repetidamente las edge functions:

\[
E(x,y)=Ax+By+C
\]

Ahora vamos a realizar el proceso completo con números.

El objetivo es seguir el mismo tipo de cálculo que posteriormente realiza MiniGPU, pero utilizando un triángulo pequeño que podamos comprobar manualmente.

Supongamos el triángulo:

\[
P_0=(2,2)
\]

\[
P_1=(8,2)
\]

\[
P_2=(5,7)
\]

Visualmente:

```text
y

7              P2(5,7)
                  *
                 / \
6               /   \
               /     \
5             /       \
             /         \
4           /           \
           /             \
3         /               \
         /                 \
2     P0*-------------------*P1
       (2,2)              (8,2)

      2  3  4  5  6  7  8       x
```

Queremos responder:

> Para un punto `(x,y)`, ¿está dentro de este triángulo?

---

## A.2. Construcción de una edge function

Para un borde dirigido desde:

\[
P_a=(x_a,y_a)
\]

hasta:

\[
P_b=(x_b,y_b)
\]

utilizaremos:

\[
E(x,y)=Ax+By+C
\]

con:

\[
A=y_a-y_b
\]

\[
B=x_b-x_a
\]

\[
C=x_a y_b-x_b y_a
\]

Construiremos una función para cada borde.

---

## A.3. Primer borde: P0 → P1

Tenemos:

\[
P_0=(2,2)
\]

\[
P_1=(8,2)
\]

Por tanto:

\[
A_0=2-2=0
\]

\[
B_0=8-2=6
\]

\[
C_0=2\cdot2-8\cdot2
\]

\[
C_0=4-16=-12
\]

Así:

\[
E_0(x,y)=0x+6y-12
\]

o simplemente:

\[
\boxed{E_0(x,y)=6y-12}
\]

Tiene sentido geométricamente.

El borde es horizontal:

```text
P0 ---------------- P1
```

por lo que la función no depende de `x`.

Sobre la línea `y=2`:

\[
E_0=6(2)-12=0
\]

Por encima:

\[
y>2\Rightarrow E_0>0
\]

---

## A.4. Segundo borde: P1 → P2

Ahora:

\[
P_1=(8,2)
\]

\[
P_2=(5,7)
\]

Tenemos:

\[
A_1=2-7=-5
\]

\[
B_1=5-8=-3
\]

\[
C_1=8\cdot7-5\cdot2
\]

\[
C_1=56-10=46
\]

Por tanto:

\[
\boxed{E_1(x,y)=-5x-3y+46}
\]

---

## A.5. Tercer borde: P2 → P0

Tenemos:

\[
P_2=(5,7)
\]

\[
P_0=(2,2)
\]

Entonces:

\[
A_2=7-2=5
\]

\[
B_2=2-5=-3
\]

\[
C_2=5\cdot2-2\cdot7
\]

\[
C_2=10-14=-4
\]

Por tanto:

\[
\boxed{E_2(x,y)=5x-3y-4}
\]

Ya tenemos las tres ecuaciones:

\[
E_0=6y-12
\]

\[
E_1=-5x-3y+46
\]

\[
E_2=5x-3y-4
\]

---

# A.6. Probemos un punto interior

Tomemos:

\[
P=(5,4)
\]

Primer borde:

\[
E_0(5,4)=6(4)-12=12
\]

Segundo:

\[
E_1(5,4)=-5(5)-3(4)+46
\]

\[
=-25-12+46=9
\]

Tercero:

\[
E_2(5,4)=5(5)-3(4)-4
\]

\[
=25-12-4=9
\]

Tenemos:

\[
E_0=12
\]

\[
E_1=9
\]

\[
E_2=9
\]

Las tres son positivas.

Por tanto:

\[
\boxed{(5,4)\text{ está dentro}}
\]

---

# A.7. Probemos un punto exterior

Tomemos:

\[
P=(1,4)
\]

Tenemos:

\[
E_0(1,4)=12
\]

\[
E_1(1,4)=-5-12+46=29
\]

pero:

\[
E_2(1,4)=5-12-4=-11
\]

Una edge function es negativa.

Por tanto:

\[
\boxed{(1,4)\text{ está fuera}}
\]

Esto es exactamente lo que necesita el rasterizador.

No necesita calcular áreas complicadas para cada píxel.

Solo:

```text
if E0 >= 0
and E1 >= 0
and E2 >= 0:
    inside
```

---

# A.8. Bounding box

Nuestro triángulo tiene:

```text
x: 2, 8, 5
y: 2, 2, 7
```

Así:

\[
minX=2
\]

\[
maxX=8
\]

\[
minY=2
\]

\[
maxY=7
\]

Solo necesitamos comprobar:

```text
2 <= x <= 8
2 <= y <= 7
```

Todo lo demás queda descartado sin evaluar las edge functions.

---

# A.9. Rastericemos una fila

Tomemos:

\[
y=4
\]

Empezamos en:

\[
x=2
\]

Las edge functions son:

\[
E_0(2,4)=12
\]

\[
E_1(2,4)=-10-12+46=24
\]

\[
E_2(2,4)=10-12-4=-6
\]

Así:

```text
x=2

E0 = 12
E1 = 24
E2 = -6

FUERA
```

Ahora queremos `x=3`.

No recalculamos todo.

Recordemos:

\[
E(x+1,y)=E(x,y)+A
\]

Los coeficientes A son:

\[
A_0=0
\]

\[
A_1=-5
\]

\[
A_2=5
\]

Por tanto:

```text
x=3

E0 = 12 + 0  = 12
E1 = 24 - 5  = 19
E2 = -6 + 5  = -1

FUERA
```

Siguiente:

```text
x=4

E0 = 12
E1 = 14
E2 = 4

DENTRO
```

Siguiente:

```text
x=5

E0 = 12
E1 = 9
E2 = 9

DENTRO
```

Siguiente:

```text
x=6

E0 = 12
E1 = 4
E2 = 14

DENTRO
```

Siguiente:

```text
x=7

E0 = 12
E1 = -1
E2 = 19

FUERA
```

La fila queda aproximadamente:

```text
x:     2    3    4    5    6    7    8

       .    .    #    #    #    .    .
```

donde `#` representa cobertura.

Obsérvese que después del cálculo inicial no hemos realizado ninguna multiplicación.

Solo:

```text
E0 += 0
E1 += -5
E2 += 5
```

Ese es el fundamento de la rasterización incremental utilizada en v4 y versiones posteriores.

---

# A.10. Ahora pensemos como MiniGPU

MiniGPU no procesa necesariamente un píxel por lane.

Procesa una palabra RGB565:

```text
+----------------+----------------+
| pixel x+1      | pixel x        |
+----------------+----------------+
```

Supongamos que una lane empieza en:

\[
x=4
\]

Para el primer píxel ya tiene:

```text
E0 = 12
E1 = 14
E2 = 4
```

Está dentro.

Para `x+1=5` no recalcula:

\[
Ax+By+C
\]

sino que suma `A`:

```text
E0_right = 12 + 0  = 12
E1_right = 14 - 5  = 9
E2_right = 4  + 5  = 9
```

También está dentro.

Por tanto esa lane puede escribir:

```text
+----------------+----------------+
| color          | color          |
+----------------+----------------+
```

Si solamente uno estuviera dentro, conservaría la otra mitad del `LOAD` original.

---

# A.11. Ahora ocho lanes

Supongamos que las ocho lanes empiezan en palabras consecutivas.

Los primeros píxeles de cada palabra están separados dos píxeles:

```text
lane 0 → x
lane 1 → x+2
lane 2 → x+4
lane 3 → x+6
lane 4 → x+8
lane 5 → x+10
lane 6 → x+12
lane 7 → x+14
```

Un warp cubre:

\[
16\ píxeles
\]

Después del primer bloque:

```text
lane 0 → x+16
lane 1 → x+18
...
lane 7 → x+30
```

Así, para cada lane:

\[
\Delta x=16
\]

y:

\[
E_{next}=E+16A
\]

De ahí salen los incrementos horizontales `A*16` de v4.

Este ejemplo permite conectar directamente:

```text
matemáticas
    ↓
RGB565
    ↓
2 píxeles/palabra
    ↓
8 lanes
    ↓
16 píxeles
    ↓
edge_step = 16*A
```

No hay ninguna constante arbitraria.

---

# Apéndice B — Leer el rasterizador v4 como arquitecto

## B.1. No memorizar el ensamblador

La mejor forma de leer v4 no es intentar comprender cada instrucción aisladamente.

Primero debemos conocer las variables conceptuales que necesita el algoritmo.

Para un triángulo necesitamos:

```text
A0 B0 C0
A1 B1 C1
A2 B2 C2

color

minword
maxword
miny
maxy
```

El descriptor de v4 contiene precisamente esta información.

Después cada thread necesita derivar:

```text
tid
lane
warp
```

y de ellos:

```text
xword inicial
y inicial
dirección de framebuffer
```

Finalmente necesita estado incremental:

```text
E0
E1
E2

stepX0
stepX1
stepX2

rowDelta0
rowDelta1
rowDelta2
```

Con este mapa mental, las instrucciones dejan de parecer una secuencia arbitraria.

---

# B.2. Identidad del thread

La operación conceptual es:

```text
tid = GETTID()
lane = tid & 7
warp = tid >> 3
```

v4 realiza precisamente esta separación.

Podemos comprobar algunos casos:

```text
tid = 0

lane = 0
warp = 0
```

```text
tid = 7

lane = 7
warp = 0
```

```text
tid = 8

lane = 0
warp = 1
```

```text
tid = 37

37 = 0b100101

lane = 37 & 7 = 5
warp = 37 >> 3 = 4
```

Así el thread 37 significa:

```text
warp 4
lane 5
```

---

# B.3. Convertir identidad en coordenadas

Para un descriptor con:

```text
minword
miny
```

podemos construir:

\[
xword=minword+lane
\]

\[
y=miny+warp
\]

Por tanto:

```text
warp 0:
  lane0 → (minword+0, miny+0)
  lane1 → (minword+1, miny+0)
  ...
  lane7 → (minword+7, miny+0)

warp 1:
  lane0 → (minword+0, miny+1)
  ...
```

La identidad del thread se ha convertido en una coordenada del rasterizador.

Este patrón es muy común en programación GPU:

> El identificador del thread no es interesante por sí mismo. Lo utilizamos para calcular qué elemento de los datos pertenece al thread.

---

# B.4. De xword a píxel

Una palabra representa dos píxeles.

Por tanto:

\[
x=2xword
\]

si `xword` se interpreta relativo al comienzo de la fila.

Así:

```text
xword 0 → pixels 0,1
xword 1 → pixels 2,3
xword 2 → pixels 4,5
...
```

Esto explica por qué dos lanes consecutivas no evalúan píxeles consecutivos individuales, sino pares consecutivos.

---

# B.5. De `(x,y)` a dirección

Para una pantalla de 320 píxeles:

\[
160\ palabras/fila
\]

Cada palabra ocupa 4 bytes.

El stride de una fila es:

\[
160\times4=640\ bytes
\]

Por tanto, conceptualmente:

\[
address =
framebuffer +
y\cdot640 +
xword\cdot4
\]

El código puede construir esta expresión de formas adaptadas al ISA disponible, pero esta es la relación que debemos tener en la cabeza.

---

# B.6. Inicializar las edge functions

Cada lane necesita calcular:

\[
E_0=A_0x+B_0y+C_0
\]

\[
E_1=A_1x+B_1y+C_1
\]

\[
E_2=A_2x+B_2y+C_2
\]

para su posición inicial.

Aquí sí aparecen multiplicaciones.

v4 realiza esta inicialización antes de entrar en el recorrido incremental.

Podemos pensar:

```text
MUL A0,x
MUL B0,y
ADD
ADD C0

MUL A1,x
MUL B1,y
...

MUL A2,x
MUL B2,y
...
```

Una vez obtenidos los tres valores, no queremos repetir estas multiplicaciones en cada iteración.

---

# B.7. Preparar los incrementos

Como una misma lane avanza 16 píxeles entre bloques:

\[
stepX_0=16A_0
\]

\[
stepX_1=16A_1
\]

\[
stepX_2=16A_2
\]

v4 prepara esos incrementos.

El inner loop puede entonces hacer:

```text
E0 += stepX0
E1 += stepX1
E2 += stepX2
```

El cálculo general:

```text
Ax + By + C
```

se ha convertido en tres `ADD`.

---

# B.8. Procesar el primer píxel

Conceptualmente:

```text
inside0 =
    E0 >= 0 &&
    E1 >= 0 &&
    E2 >= 0
```

Si `inside0`:

```text
word = (word & preserve_other_half)
     | color
```

dependiendo de qué mitad corresponda al primer píxel.

Aquí puede aparecer divergencia porque no todas las lanes tienen necesariamente el mismo resultado.

---

# B.9. Procesar el segundo píxel

El píxel vecino está en:

\[
x+1
\]

Así:

\[
E_0'=E_0+A_0
\]

\[
E_1'=E_1+A_1
\]

\[
E_2'=E_2+A_2
\]

Entonces:

```text
inside1 =
    E0+A0 >= 0 &&
    E1+A1 >= 0 &&
    E2+A2 >= 0
```

Otra vez solo necesitamos sumas.

---

# B.10. El read-modify-write completo

Podemos resumir una iteración de una lane como:

```text
word = LOAD(address)

if pixel0_inside:
    replace_half0(word,color)

if pixel1_inside:
    replace_half1(word,color)

STORE(address,word)
```

Después:

```text
address += 32

E0 += 16*A0
E1 += 16*A1
E2 += 16*A2
```

¿Por qué `address += 32`?

Porque esa lane salta ocho palabras:

\[
8\times4=32\ bytes
\]

¿Por qué `16*A`?

Porque esas ocho palabras representan:

\[
8\times2=16\ píxeles
\]

Las dos constantes describen exactamente el mismo movimiento visto desde dos espacios distintos:

```text
MEMORIA                    PANTALLA

+32 bytes        <=>       +16 pixels
```

Esta relación es una excelente forma de depurar el rasterizador.

---

# B.11. Terminar el bloque horizontal

Cada lane continúa:

```text
word N
word N+8
word N+16
word N+24
...
```

mientras no haya superado el límite horizontal.

Las ocho lanes juntas cubren:

```text
N..N+7

N+8..N+15

N+16..N+23
...
```

Es decir, entre todas recorren la fila completa sin solaparse.

---

# B.12. Saltar ocho filas

Cuando termina la fila:

```text
warp 0 → siguiente y+8
warp 1 → siguiente y+8
...
```

Así:

```text
W0: 0,8,16,24...
W1: 1,9,17,25...
W2: 2,10,18,26...
...
```

relativo a `minY`.

El resultado es que los ocho warps cubren todas las filas sin que dos warps sean propietarios de la misma fila durante el rasterizado de ese triángulo.

---

# B.13. ¿Por qué BAR?

Cuando todos terminan:

```text
BAR
```

y solo entonces se carga el descriptor siguiente.

La razón no es que una GPU necesite una barrera después de cada triángulo por definición.

La razón específica de este algoritmo es la combinación de:

```text
triángulos sucesivos
+
bounding boxes diferentes
+
read-modify-write
```

Dos triángulos diferentes pueden asignar la misma palabra a threads/warps distintos debido a que sus regiones comienzan en posiciones verticales diferentes.

Permitir que ambas fases se solapen podría crear una carrera.

La barrera convierte:

```text
T0 y T1 simultáneos
```

en:

```text
T0 completo
   ↓
T1 completo
```

---

# B.14. La estructura completa de v4 en pseudocódigo

Una vez entendidos todos los detalles, podemos reducir v4 conceptualmente a algo parecido a:

```text
clear_region_parallel()
BAR

for triangle in triangles:

    load_descriptor()

    lane = tid & 7
    warp = tid >> 3

    y     = minY + warp
    xword = minWord + lane

    initialize_edges(xword,y)

    while y <= maxY:

        while xword <= maxWord:

            word = LOAD(framebuffer[xword,y])

            if left_pixel_inside:
                replace_left(word,color)

            if right_pixel_inside:
                replace_right(word,color)

            STORE(framebuffer[xword,y],word)

            xword += 8

            E0 += 16*A0
            E1 += 16*A1
            E2 += 16*A2

        y += 8

        restore_x()
        update_edges_for_next_row()

    BAR

swap()
```

Naturalmente, el ensamblador real está condicionado por los registros, las instrucciones y el control SIMT de MiniGPU, pero este pseudocódigo es el modelo mental que conviene mantener mientras se lee.

---

# Apéndice C — Seguir un frame completo

## C.1. Estado inicial

Supongamos:

```text
front = framebuffer A
back  = framebuffer B
angle = θ
```

Scanout está leyendo A.

MiniGPU va a construir el siguiente frame en B.

---

## C.2. Transformación de vértices

Las ocho lanes del warp encargado de la geometría reciben:

```text
L0 → V0
L1 → V1
...
L7 → V7
```

Todas utilizan:

```text
sin(θ)
cos(θ)
```

y el segundo ángulo utilizado por la animación.

Calculan:

```text
V3D
 ↓
Vrotated
 ↓
Vprojected
```

y escriben:

```text
cube_points[0..7]
```

---

## C.3. Barrera

Ahora:

```text
BAR
```

garantiza que los puntos proyectados están disponibles antes de que el setup los consuma.

---

## C.4. Triangle setup

El esquema compacto de v6/v8 recorre las primitivas originales.

Para cada una:

```text
indices
  ↓
3 cube_points
  ↓
signed area
  ↓
back-face culling
```

Si no es visible:

```text
skip
```

Si es visible:

```text
3 edge functions
bbox
color
```

y se añade a:

```text
cube_descriptors
```

El resultado es una lista compacta de hasta seis triángulos visibles.

---

## C.5. Clear del back buffer

Antes de dibujar:

```text
clear framebuffer B
```

v8 no limpia toda la pantalla ni siquiera toda la región anterior de v4.

Limpia:

```text
112 words × 208 rows
```

es decir:

\[
23296\ palabras
\]

distribuidas entre los 64 threads.

Después:

```text
BAR
```

---

## C.6. Rasterizar descriptor 0

Los 64 threads cargan conceptualmente la información del primer triángulo.

Cada thread deriva:

```text
lane
warp
```

Las lanes se distribuyen horizontalmente.

Los warps verticalmente.

Se inicializan:

```text
E0
E1
E2
```

y se recorre la bounding box.

Cada lane realiza read-modify-write sobre sus palabras.

---

## C.7. Barrera de triángulo

Al terminar:

```text
BAR
```

Nadie comienza el descriptor 1 hasta que el descriptor 0 ha terminado globalmente.

---

## C.8. Repetir

El proceso continúa:

```text
triangle 0
BAR
triangle 1
BAR
triangle 2
BAR
...
```

hasta terminar la lista compacta.

---

## C.9. Frame terminado

Ahora B contiene la imagen completa.

A sigue siendo el buffer que scanout estaba mostrando.

Solicitamos:

```text
SWAP
```

y esperamos su finalización.

---

## C.10. Cambio de papeles

Después:

```text
front = B
back  = A
```

Scanout comienza a utilizar la nueva imagen según el mecanismo de swap.

MiniGPU puede comenzar a preparar el siguiente frame en A.

Pero A conserva una imagen antigua.

Por eso la siguiente iteración volverá a limpiar la región correspondiente antes de rasterizar.

---

## C.11. Actualizar el ángulo

El ángulo cambia:

\[
\theta\rightarrow\theta+\Delta
\]

y comienza otro frame.

Así obtenemos:

```text
θ0 → imagen 0
θ1 → imagen 1
θ2 → imagen 2
θ3 → imagen 3
...
```

Mostradas suficientemente rápido, producen la percepción de un cubo girando.

---

# Apéndice D — Del código de MiniGPU a una GPU moderna

## D.1. Tabla conceptual

| MiniGPU / ejemplo | Concepto gráfico aproximado |
|---|---|
| generación de los 8 vértices | vertex input |
| rotación y perspectiva | vertex processing |
| `cube_points` | posiciones transformadas |
| tabla de triángulos/caras | primitive connectivity |
| signed area | orientation / back-face culling |
| cálculo A,B,C | triangle setup |
| bounding box | región candidata de rasterización |
| edge functions | coverage test |
| 64 threads | ejecución paralela |
| 8 lanes | ancho de ejecución SIMT/SIMD |
| RGB565 del descriptor | atributo de color plano |
| LOAD-modify-STORE | actualización de framebuffer |
| framebuffer front/back | render targets / presentation buffers |
| swap | presentación |
| scanout | display engine |

Esta tabla es deliberadamente conceptual. No implica que MiniGPU tenga unidades hardware separadas equivalentes a las de una GPU comercial.

---

# D.2. Lo que actualmente hacemos en software

Nuestro programa calcula explícitamente:

```text
edge equations
bounding boxes
coverage
```

Una GPU comercial puede tener hardware especializado para buena parte de estas operaciones.

Por tanto, comparar únicamente “número de instrucciones” entre ambas arquitecturas tendría poco sentido.

MiniGPU está utilizando software para estudiar explícitamente algoritmos que en otras GPUs pueden quedar escondidos tras unidades fixed-function.

---

# D.3. Lo que sería programable en una GPU moderna

La transformación:

```text
(x,y,z)
 ↓
rotación
 ↓
proyección
```

encaja conceptualmente con trabajo realizado por un vertex shader.

Si posteriormente añadimos:

```text
normal
lighting
texture coordinates
```

también podríamos procesarlos durante las etapas programables.

Nuestro color plano:

```text
color = descriptor.color
```

sería el caso más trivial posible de producción de color de fragmento.

---

# D.4. Lo que nos falta para escenas generales

Para evolucionar desde el cubo actual hacia un renderer 3D mucho más general aparecerían, entre otros, los siguientes problemas:

```text
clipping
depth buffer
interpolación de atributos
texturas
perspective-correct interpolation
blending
escenas con muchos objetos
gestión de vértices/índices
```

No todos tienen que implementarse.

Cada uno puede convertirse en un experimento independiente de arquitectura.

---

# Apéndice E — Glosario

## E.1. Framebuffer

Región de memoria que contiene los colores de una imagen.

En nuestros ejemplos los píxeles son RGB565 y se empaquetan dos por palabra de 32 bits.

---

## E.2. Front buffer

Framebuffer que está siendo utilizado para presentación/scanout.

La GPU no debería modificarlo arbitrariamente mientras se muestra si queremos evitar mezclar imágenes.

---

## E.3. Back buffer

Framebuffer sobre el que se construye la siguiente imagen.

Cuando está terminado puede intercambiar su papel con el front buffer.

---

## E.4. Double buffering

Uso de dos framebuffers:

```text
front → mostrar
back  → dibujar
```

Después se intercambian.

Permite desacoplar renderizado y presentación.

---

## E.5. Swap

Operación mediante la cual front y back cambian de papel.

No significa copiar físicamente toda la imagen.

---

## E.6. Scanout

Lógica que lee continuamente el framebuffer y genera la secuencia de píxeles necesaria para la salida de vídeo.

Renderizar y hacer scanout son tareas diferentes.

---

## E.7. RGB565

Formato de color de 16 bits:

```text
RRRRR GGGGGG BBBBB
```

5 bits rojo, 6 verde y 5 azul.

---

## E.8. Vértice

Punto geométrico.

En 3D:

\[
(x,y,z)
\]

Después de la proyección puede quedar representado mediante coordenadas de pantalla:

\[
(x_s,y_s)
\]

además de otros posibles atributos.

---

## E.9. Primitiva

Elemento geométrico básico que procesa el pipeline.

En nuestro renderer la primitiva fundamental es el triángulo.

---

## E.10. Triángulo

Primitiva definida por tres vértices.

Es especialmente útil porque es convexa, planar y permite determinar cobertura mediante tres semiplanos.

---

## E.11. Rasterización

Proceso que transforma una primitiva geométrica en muestras/fragmentos correspondientes a posiciones discretas de pantalla.

Simplificando:

```text
triángulo
   ↓
píxeles cubiertos
```

---

## E.12. Fragmento

Candidato a modificar una posición del framebuffer generado por rasterización.

En un pipeline más completo puede contener:

```text
posición
profundidad
color
coordenadas de textura
otros atributos
```

y todavía puede ser descartado.

---

## E.13. Edge function

Función:

\[
E(x,y)=Ax+By+C
\]

asociada a un borde orientado.

Su signo indica en qué semiplano se encuentra un punto.

Tres edge functions permiten determinar cobertura de un triángulo.

---

## E.14. Bounding box

Rectángulo alineado con los ejes que contiene una primitiva.

Permite limitar los tests de cobertura a una región pequeña.

---

## E.15. Back-face culling

Eliminación de primitivas orientadas en dirección opuesta a la cámara.

En los ejemplos se utiliza el signo del área proyectada para determinar la orientación.

---

## E.16. Triangle setup

Fase que transforma una representación basada en vértices en información cómoda para rasterizar.

En MiniGPU incluye elementos como:

```text
A,B,C de los tres bordes
bounding box
color
```

---

## E.17. Thread

Instancia lógica de ejecución de un programa.

Cada thread dispone conceptualmente de su propio estado arquitectónico relevante.

---

## E.18. Lane

Posición de ejecución dentro de un grupo SIMD/SIMT.

En MiniGPU hay ocho lanes por warp en los ejemplos estudiados.

---

## E.19. Warp

Grupo de threads que ejecutan conjuntamente el flujo de instrucciones.

En nuestros ejemplos:

\[
8\ threads/warp
\]

y:

\[
8\ warps\times8\ threads=64\ threads
\]

---

## E.20. SIMD

**Single Instruction, Multiple Data.**

Una instrucción actúa sobre varios elementos de datos.

---

## E.21. SIMT

**Single Instruction, Multiple Threads.**

Modelo en el que programamos conceptualmente threads independientes pero el hardware agrupa su ejecución.

---

## E.22. Divergencia

Situación en la que diferentes threads de un mismo warp quieren seguir caminos de control diferentes.

Por ejemplo:

```text
if pixel_inside:
    paint()
```

puede ser verdadero para unas lanes y falso para otras.

---

## E.23. Reconvergencia

Punto en el que lanes que habían seguido caminos diferentes vuelven a compartir un mismo flujo de ejecución.

`SSY` está relacionado con este mecanismo en MiniGPU.

---

## E.24. Máscara de ejecución

Conjunto de lanes activas durante una parte del programa.

Por ejemplo:

```text
lane:  7 6 5 4 3 2 1 0
mask:  0 0 1 1 1 1 0 0
```

Solo las lanes activas producen los efectos correspondientes.

---

## E.25. Coalescing

Agrupación de accesos de memoria de varias lanes cuando forman un patrón favorable, normalmente contiguo.

Ejemplo:

```text
L0 → A
L1 → A+4
L2 → A+8
...
L7 → A+28
```

El rasterizador v4 organiza deliberadamente las lanes para favorecer transferencias consecutivas BL8.

---

## E.26. LSU

**Load/Store Unit.**

Unidad responsable de las operaciones de memoria generadas por las lanes.

En una GPU, su capacidad para manejar y agrupar accesos es crítica para el rendimiento.

---

## E.27. Barrier / BAR

Punto de sincronización.

Los participantes que llegan deben esperar hasta que se cumpla la condición de sincronización correspondiente antes de continuar.

En nuestro renderer separa fases con dependencias.

---

## E.28. Read-modify-write

Secuencia:

```text
LOAD
modificar parte
STORE
```

El rasterizador la necesita porque cada palabra contiene dos píxeles y un triángulo puede cubrir solamente uno.

---

## E.29. Race condition

Resultado dependiente del orden temporal de operaciones concurrentes.

Un ejemplo peligroso:

```text
A: LOAD word
B: LOAD word
A: modifica mitad 0
B: modifica mitad 1
A: STORE
B: STORE
```

El último STORE puede perder la modificación del otro.

---

## E.30. Depth buffer / Z-buffer

Memoria que almacena la profundidad asociada a cada posición.

Permite decidir qué fragmento está delante cuando varias primitivas cubren el mismo píxel.

No forma parte del rasterizador básico del cubo estudiado.

---

## E.31. Interpolación

Cálculo de atributos interiores a partir de los atributos de los vértices.

Puede utilizarse para:

```text
color
Z
coordenadas de textura
normales
```

---

## E.32. Coordenadas baricéntricas

Pesos:

\[
\alpha,\beta,\gamma
\]

que permiten expresar un punto del triángulo como:

\[
P=\alpha P_0+\beta P_1+\gamma P_2
\]

con:

\[
\alpha+\beta+\gamma=1
\]

Son especialmente útiles para interpolar atributos.

---

## E.33. Textura

Imagen o conjunto de datos muestreado durante el renderizado.

Normalmente se accede mediante coordenadas `(u,v)` interpoladas sobre el triángulo.

---

## E.34. Shader

Programa ejecutado durante una etapa programable del pipeline gráfico.

Dos categorías habituales son:

```text
vertex shader
fragment/pixel shader
```

Nuestro renderer no implementa una arquitectura de shaders moderna, aunque varias de sus fases permiten entender qué problemas resuelven.

---

## E.35. Latencia

Tiempo desde que comienza una operación hasta que su resultado está disponible.

Por ejemplo, una división puede tener una latencia de varios ciclos.

---

## E.36. Throughput

Cantidad de operaciones que una unidad puede completar o aceptar por unidad de tiempo.

Latencia y throughput no son lo mismo.

Una unidad podría tener:

```text
latencia = 4 ciclos
throughput = 1 operación/ciclo
```

si está correctamente pipelineada.

---

## E.37. Latency hiding

Técnica consistente en ejecutar trabajo de otros warps mientras uno está esperando una operación de larga latencia.

Es una de las razones por las que disponer de múltiples warps puede ser útil incluso cuando no todas las operaciones pueden ejecutarse físicamente a la vez.

---

## E.38. Fmax

Frecuencia máxima a la que puede funcionar correctamente un diseño hardware.

En FPGA una optimización que reduce ciclos pero empeora mucho Fmax puede empeorar el tiempo total.

Por eso:

\[
rendimiento\neq solo\ número\ de\ ciclos
\]

---

# Apéndice F — Hoja mental para leer cualquier renderer

Cuando aparezca un nuevo ejemplo gráfico en MiniGPU, en lugar de empezar directamente por el ensamblador, conviene responder estas preguntas.

### 1. ¿Cuál es la entrada?

```text
vértices
triángulos
imagen
datos precalculados
```

### 2. ¿Cuál es la salida?

Normalmente acabaremos llegando a:

```text
framebuffer
```

pero interesa saber qué etapas existen antes.

### 3. ¿Cuál es la unidad de trabajo?

Puede ser:

```text
un vértice
una cara
un triángulo
una fila
una palabra
un píxel
```

### 4. ¿Cómo se reparte entre threads?

Preguntar:

```text
qué significa tid
qué significa lane
qué significa warp
```

en ese algoritmo concreto.

### 5. ¿Qué datos son privados?

Por ejemplo:

```text
E0,E1,E2 de una lane
```

### 6. ¿Qué datos son compartidos?

Por ejemplo:

```text
cube_points
cube_descriptors
framebuffer
```

### 7. ¿Dónde existen dependencias?

Buscar transiciones:

```text
productor → consumidor
```

y escrituras concurrentes.

Eso explicará la mayoría de los `BAR`.

### 8. ¿Cómo acceden las lanes a memoria?

Esta pregunta es esencial.

No basta con ver:

```text
LOAD
```

Hay que dibujar:

```text
lane0 → ?
lane1 → ?
lane2 → ?
...
```

### 9. ¿Existe divergencia?

Buscar:

```text
if
branch
coverage test
culling
```

y preguntarse si todas las lanes toman normalmente la misma decisión.

### 10. ¿Dónde se repite trabajo?

Buscar cálculos que puedan:

```text
precalcularse
incrementarse
reutilizarse
```

v4 nació esencialmente de esta pregunta.

### 11. ¿Qué fase domina el tiempo?

No asumirlo.

Medir:

```text
geometry
setup
clear
raster
memory wait
swap wait
```

### 12. ¿La optimización mejora el frame completo?

No basta con acelerar una función.

v7 es el recordatorio permanente:

\[
\boxed{\text{optimización local}\neq\text{optimización global}}
\]

---

# Apéndice G — El mapa final de MiniGPU

Después de todo el documento podemos representar el renderer estudiado en tres niveles diferentes.

## Nivel 1 — Lo que ve el usuario

```text
           +-------+
          /       /|
         +-------+ |
         |       | +
         |       |/
         +-------+

       cubo girando
```

## Nivel 2 — Lo que ve el programador gráfico

```text
modelo
  ↓
vértices
  ↓
transformación
  ↓
proyección
  ↓
triángulos
  ↓
culling
  ↓
rasterización
  ↓
fragmentos/píxeles
  ↓
framebuffer
```

## Nivel 3 — Lo que ve el arquitecto

```text
GETTID
AND
SHR
LOAD
MUL
ADD
SUB
SAR
DIV
BRA
SSY
BAR
STORE

       ↓

warps
lanes
máscaras
latencias
LSU
BL8
BRAM/memoria
MMIO
scanout
```

Los tres niveles describen exactamente el mismo sistema.

La clave para diseñar una GPU consiste en ser capaz de desplazarse continuamente entre ellos:

```text
¿Qué quiero dibujar?
        ↕
¿Qué algoritmo lo produce?
        ↕
¿Qué instrucciones ejecuta?
        ↕
¿Qué tráfico de memoria genera?
        ↕
¿Qué hace el hardware cada ciclo?
```

Cuando se puede seguir un píxel desde el vértice original del cubo hasta el `STORE` RGB565 que acaba alimentando el scanout, la GPU deja de ser una caja negra.

Y ese era el objetivo de este documento.