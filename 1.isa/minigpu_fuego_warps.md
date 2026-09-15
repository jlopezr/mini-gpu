# Efecto de fuego para MiniGPU

## 1. Objetivo

El efecto de fuego es un workload especialmente interesante para MiniGPU
porque permite empezar con un algoritmo sencillo que funciona con la ISA
actual y, a partir de él, estudiar de forma cuantitativa qué primitivas
SIMT merece la pena añadir.

La idea no es únicamente conseguir una animación de fuego, sino
utilizarla como un pequeño benchmark gráfico que ejercite:

-   ejecución SIMT;
-   warps y lanes;
-   accesos sub-palabra;
-   tráfico de memoria;
-   sincronización entre warps;
-   divergencia;
-   generación pseudoaleatoria;
-   renderizado a framebuffer;
-   posibles operaciones de intercambio entre lanes;
-   contadores de rendimiento de LSU, fabric y SDRAM.

La estrategia propuesta es implementar primero una versión completamente
válida con MiniISA v0.1 y utilizarla como referencia para posteriores
optimizaciones.

------------------------------------------------------------------------

## 2. Lo que ofrece actualmente MiniGPU

MiniGPU dispone actualmente de **8 warps de 8 lanes**, para un total de
**64 threads residentes**.

`GETTID` devuelve:

``` text
thread_id = warp_id * warp_size + lane_id
```

Por tanto, en la implementación actual:

``` text
GETTID = 0..63
```

Esto sugiere una primera elección muy conveniente: hacer que una fila
del mapa de fuego tenga **64 píxeles**.

``` text
warp 0 : threads  0..7
warp 1 : threads  8..15
warp 2 : threads 16..23
...
warp 7 : threads 56..63

                 ↓

x = 0 1 2 3 ... 62 63
```

Cada thread puede encargarse directamente de una columna.

La ISA dispone además de las instrucciones que necesitamos para una
primera implementación:

-   `GETTID`
-   `LOADUB`
-   `STOREB`
-   operaciones ALU (`ADD`, `SUB`, `XOR`, etc.)
-   shifts inmediatos (`SHLI`, `SHRI`)
-   branches
-   `BAR`
-   `EXIT`

En cambio, MiniISA v0.1 **no tiene todavía operaciones como `SHFL` o
`BALLOT`**.

Eso es interesante: podemos hacer primero el algoritmo sin ellas y
utilizar las mediciones para decidir posteriormente si merece la pena
incorporarlas.

------------------------------------------------------------------------

## 3. Representación del fuego

El fuego puede representarse como un mapa de temperaturas de 8 bits:

``` text
0       = negro / frío
...
128     = rojo/naranja
...
255     = amarillo/blanco / máximo calor
```

Con 8 bits por celda, una imagen de 64×200 necesita solamente:

``` text
64 * 200 = 12.800 bytes
```

Incluso si utilizamos buffers adicionales, el coste es pequeño.

`LOADUB` resulta especialmente apropiado porque carga un byte con
extensión a cero:

``` asm
LOADUB Rd, Ra, offset
```

y `STOREB` permite almacenar de nuevo únicamente los 8 bits bajos:

``` asm
STOREB Rs, Ra, offset
```

------------------------------------------------------------------------

## 4. Algoritmo básico

El fuego clásico se puede construir propagando calor desde abajo hacia
arriba.

Para cada celda podemos calcular algo parecido a:

``` c
new_heat =
    (left + center + center + right) / 4;

new_heat -= decay;
```

Gráficamente:

``` text
fila y:

       L     C     R
       │     │     │
       └──┬──┴──┬──┘
          │
          ▼
      nuevo calor

fila y-1:
          D
```

El doble peso del píxel central evita que el fuego se disperse
horizontalmente demasiado deprisa.

Una primera versión puede utilizar un `decay` constante de 2.

------------------------------------------------------------------------

## 5. Kernel inicial con la ISA actual

Cada thread obtiene su columna:

``` asm
GETTID R3
```

Suponiendo:

``` text
R1 = dirección de la fila fuente
R2 = dirección de la fila destino
R3 = x
```

la dirección del píxel central es:

``` asm
ADD R4, R1, R3
```

Podemos cargar los tres valores:

``` asm
LOADUB R10, R4, -1     ; izquierda
LOADUB R11, R4,  0     ; centro
LOADUB R12, R4,  1     ; derecha
```

y calcular:

``` asm
ADD  R13, R10, R11
ADD  R13, R13, R11
ADD  R13, R13, R12

SHRI R13, R13, 2
```

Esto implementa:

``` text
(left + 2*center + right) / 4
```

Después aplicamos el enfriamiento:

``` asm
ADDI R13, R13, -2
```

y evitamos que un valor pequeño se convierta, por underflow, en un
entero enorme:

``` asm
BGE  R13, R0, positive
MOVI R13, 0

positive:
```

Finalmente:

``` asm
ADD    R5, R2, R3
STOREB R13, R5, 0
```

------------------------------------------------------------------------

## 6. Evitar branches en los bordes

Los threads 0 y 63 presentan un problema:

``` text
thread 0:
    left = x - 1

thread 63:
    right = x + 1
```

Podríamos introducir branches para tratarlos especialmente, pero eso
genera divergencia SIMT.

Una solución mucho más limpia para esta primera versión es almacenar
cada fila con **padding lateral**:

``` text
+------+--------------------------------+------+
|  0   | p0 p1 p2 ... p61 p62 p63      |  0   |
+------+--------------------------------+------+
```

La fila física ocupa entonces:

``` text
64 + 2 = 66 bytes
```

El puntero `src` apunta a `p0`, no al byte de padding.

Así:

``` asm
LOADUB R10, R4, -1
LOADUB R11, R4,  0
LOADUB R12, R4,  1
```

es válido para **todos los threads**.

Esto elimina completamente la divergencia asociada a los extremos.

------------------------------------------------------------------------

## 7. Propagación vertical

No necesitamos disponer de un thread para cada píxel de toda la imagen
simultáneamente.

Los 64 threads residentes pueden procesar una fila completa:

``` text
64 threads
    │
    ▼
fila 198
```

y después reutilizarse para la siguiente:

``` text
64 threads
    │
    ▼
fila 197
```

etc.

El programa GPU puede contener un bucle vertical.

Conceptualmente:

``` asm
MOVI R20, NUM_ROWS

row_loop:

    ; cada thread calcula su píxel
    ...
    STOREB R13, R5, 0

    BAR

    ; avanzar una fila hacia arriba
    ADDI R1, R1, -66
    ADDI R2, R2, -66

    ADDI R20, R20, -1
    BNE  R20, R0, row_loop

    EXIT
```

------------------------------------------------------------------------

## 8. Por qué `BAR` es importante

Aquí aparece una característica SIMT realmente interesante.

Los 64 threads están distribuidos entre ocho warps diferentes. No
podemos permitir que un warp empiece a calcular la siguiente fila
mientras otro todavía no ha terminado de escribir la actual.

Tenemos una dependencia:

``` text
generar fila N
      │
      ▼
todos deben haber terminado
      │
      ▼
usar fila N para generar N-1
```

Para esto MiniGPU ya dispone de:

``` asm
BAR
```

`BAR` sincroniza los warps participantes del mismo workgroup y garantiza
que las operaciones de memoria anteriores hayan finalizado antes de
continuar.

Por tanto, el fuego proporciona inmediatamente un uso real y natural
para la barrera:

``` asm
STOREB ...
BAR
```

Después de `BAR`, todos los warps pueden utilizar con seguridad la fila
recién generada.

Esto hace que el programa sea algo más interesante que simplemente
ejecutar 64 cálculos independientes: **los ocho warps están cooperando
para construir una estructura común fila a fila**.

------------------------------------------------------------------------

## 9. Fuente del fuego

La fila inferior actúa como fuente de energía.

La versión más sencilla sería escribir valores como:

``` text
255 255 255 255 255 ...
```

pero produciría un fuego demasiado estable.

Una alternativa sería:

``` text
255 255 128 255 0 255 192 255 ...
```

La CPU podría modificar esa fila cada frame, pero es más interesante
hacer que la propia GPU genere la fuente.

------------------------------------------------------------------------

## 10. RNG por thread

Cada thread puede conservar un estado pseudoaleatorio en un registro.

Un `xorshift32` encaja especialmente bien con MiniISA porque necesita
únicamente XOR y shifts:

``` c
x ^= x << 13;
x ^= x >> 17;
x ^= x << 5;
```

En MiniISA:

``` asm
SHLI R22, R21, 13
XOR  R21, R21, R22

SHRI R22, R21, 17
XOR  R21, R21, R22

SHLI R22, R21, 5
XOR  R21, R21, R22
```

Para obtener una temperatura:

``` asm
ANDI R22, R21, 0xFF
```

Así cada thread puede generar el valor de su propia columna de la
fuente.

Conviene inicializar las semillas de forma diferente para cada thread.
Por ejemplo, pueden derivarse de `GETTID` y de una semilla global
proporcionada por la CPU.

------------------------------------------------------------------------

## 11. Una posible estructura completa del programa GPU

Conceptualmente:

``` text
                  ┌─────────────────┐
                  │ inicialización  │
                  └────────┬────────┘
                           │
                           ▼
                  generar fuente
                           │
                           ▼
                 ┌──────────────────┐
                 │ calcular fila N  │
                 └────────┬─────────┘
                          │
                       STOREB
                          │
                          ▼
                         BAR
                          │
                          ▼
                    fila N - 1
                          │
                          ├───────────────┐
                          │               │
                          ▼               │
                  calcular fila          │
                          │               │
                         BAR              │
                          │               │
                          └───────────────┘
                          │
                          ▼
                        EXIT
```

Cada iteración vertical utiliza los 64 threads.

------------------------------------------------------------------------

## 12. Kernel aproximado

Una versión esquemática podría parecerse a:

``` asm
; ------------------------------------------------------------
; Convención conceptual
;
; R1  = src
; R2  = dst
; R3  = thread/x
; R4  = dirección src[x]
; R5  = dirección dst[x]
;
; R10 = left
; R11 = center
; R12 = right
; R13 = heat
;
; R20 = filas restantes
; ------------------------------------------------------------

    GETTID R3

row_loop:

    ADD R4, R1, R3

    LOADUB R10, R4, -1
    LOADUB R11, R4,  0
    LOADUB R12, R4,  1

    ADD R13, R10, R11
    ADD R13, R13, R11
    ADD R13, R13, R12

    SHRI R13, R13, 2

    ADDI R13, R13, -2

    BGE R13, R0, heat_ok
    MOVI R13, 0

heat_ok:

    ADD R5, R2, R3
    STOREB R13, R5, 0

    BAR

    ADDI R1, R1, -66
    ADDI R2, R2, -66

    ADDI R20, R20, -1
    BNE R20, R0, row_loop

    EXIT
```

Esto es deliberadamente un esqueleto: la inicialización de los punteros
y el layout definitivo dependerán de cómo la CPU lance actualmente
programas MiniGPU y de dónde se coloque el buffer.

------------------------------------------------------------------------

## 13. Renderizado

El mapa de calor y el framebuffer no tienen por qué ser lo mismo.

Podemos tener:

``` text
heat buffer
    8 bits/pixel
        │
        ▼
    paleta
        │
        ▼
framebuffer RGB
```

La solución más sencilla es utilizar una paleta de 256 entradas:

``` text
palette[0]
palette[1]
...
palette[255]
```

Cada entrada contiene directamente el color de framebuffer
correspondiente.

Conceptualmente:

``` c
heat = heat_buffer[pixel];
color = palette[heat];
framebuffer[pixel] = color;
```

Esto evita una cascada de branches como:

``` c
if (heat > 220)
    white;
else if (heat > 160)
    yellow;
else if (...)
```

que podría provocar divergencia dentro del warp.

También nos da otro workload interesante para la LSU: accesos byte al
mapa de calor, lookup de paleta y stores al framebuffer.

------------------------------------------------------------------------

## 14. Versión naive: coste de memoria

La primera implementación necesita por píxel:

``` text
3 × LOADUB
1 × STOREB
```

Para una imagen de 64×200:

``` text
12.800 píxeles
```

aproximadamente:

``` text
38.400 LOADUB
12.800 STOREB
```

por actualización completa del mapa de calor.

Esto nos proporciona una referencia muy útil.

------------------------------------------------------------------------

## 15. La extensión interesante: operaciones `SHFL`

El algoritmo tiene una característica muy clara: threads vecinos
necesitan datos vecinos.

Actualmente cada lane hace:

``` text
LOAD left
LOAD center
LOAD right
```

pero dentro de un warp ya tenemos ocho lanes procesando ocho píxeles
contiguos:

``` text
lane:    0   1   2   3   4   5   6   7

heat:   H0  H1  H2  H3  H4  H5  H6  H7
```

Si la arquitectura proporcionase intercambio entre lanes, cada thread
sólo necesitaría cargar su propio píxel:

``` asm
LOADUB R10, R4, 0
```

y después:

``` asm
SHFL_UP   R11, R10
SHFL_DOWN R12, R10
```

Conceptualmente:

``` text
lane 3:

left   = valor de lane 2
center = valor de lane 3
right  = valor de lane 4
```

El cálculo posterior sería exactamente el mismo:

``` asm
ADD  R13, R11, R10
ADD  R13, R13, R10
ADD  R13, R13, R12
SHRI R13, R13, 2
```

------------------------------------------------------------------------

## 16. Comparación naive frente a warp-aware

La comparación conceptual sería:

  operación por píxel       naive   con SHFL
  --------------------- --------- ----------
  `LOADUB`                      3          1
  `STOREB`                      1          1
  `SHFL`                        0          2
  ALU                     similar    similar

Idealmente, el tráfico de lectura del mapa de calor bajaría
aproximadamente de:

``` text
3 lecturas/píxel
```

a:

``` text
1 lectura/píxel
```

Es decir, aproximadamente una reducción de 3× en esas lecturas.

Eso no significa automáticamente una aceleración de 3×: dependerá de las
latencias, del scheduler, de la LSU, del fabric, de la SDRAM y del coste
hardware/temporal de `SHFL`.

Precisamente por eso interesa disponer primero de la versión naive y
**medir**.

------------------------------------------------------------------------

## 17. El problema de los límites de warp

`SHFL` no elimina todos los accesos vecinos.

Con warps de ocho lanes:

``` text
warp 0                   warp 1
0 1 2 3 4 5 6 7          8 9 10 11 12 13 14 15
              │          │
              └──────────┘
```

La lane 7 necesita como vecino derecho el píxel procesado por la lane 0
del siguiente warp.

Un shuffle convencional dentro del warp no puede obtenerlo.

Igualmente, lane 0 necesita el vecino izquierdo perteneciente al warp
anterior.

Por tanto, una implementación optimizada necesitaría algún tratamiento
especial para los bordes de warp:

-   hacer un `LOADUB` adicional únicamente en lanes 0 y 7;
-   proporcionar alguna forma de intercambio entre warps;
-   reorganizar los datos;
-   o aceptar cierta redundancia de memoria.

La primera opción probablemente sea la más razonable.

Esto introduce además una oportunidad interesante para estudiar
**divergencia controlada**.

------------------------------------------------------------------------

## 18. ¿Y `BALLOT`?

`BALLOT` puede resultar útil en otros algoritmos y también podría
utilizarse en el fuego, por ejemplo para detectar:

``` text
heat > threshold
```

en todas las lanes y obtener una máscara:

``` text
00111100
```

Esto permitiría:

-   detectar warps completamente fríos;
-   evitar trabajo cuando todas las lanes tienen calor cero;
-   localizar zonas activas;
-   generar efectos adicionales como chispas.

Sin embargo, para este algoritmo concreto, **`SHFL` parece una extensión
mucho más directamente útil que `BALLOT`**, porque ataca el principal
coste del kernel: las lecturas redundantes de vecinos.

Además, MiniGPU ya dispone de una primitiva SIMT muy valiosa para este
workload: `BAR`.

------------------------------------------------------------------------

## 19. Por qué no añadir `SHFL` antes de medir

Es tentador modificar inmediatamente la ISA.

Pero el fuego permite hacer algo mejor:

``` text
1. implementar fire_naive
2. medir
3. identificar el cuello de botella
4. diseñar SHFL
5. implementar fire_warp
6. volver a medir
7. comparar
```

Así la evolución de la ISA se basa en un workload real y no únicamente
en intuiciones.

Si resulta que la GPU está limitada por otra parte del sistema, reducir
las cargas podría no producir el beneficio esperado.

Si, en cambio, los contadores muestran una presión enorme sobre
LSU/fabric/SDRAM, `SHFL` tendrá una justificación cuantitativa muy
fuerte.

------------------------------------------------------------------------

## 20. Contadores de rendimiento útiles

El programa de fuego sería un excelente caso de prueba para los
contadores que se estaban planteando para LSU, fabric y SDRAM.

Sería interesante medir al menos:

``` text
GPU
    ciclos totales
    instrucciones ejecutadas
    warps activos
    ciclos esperando BAR
    branches/divergencia

LSU
    número de loads
    número de stores
    bytes leídos
    bytes escritos
    ciclos stalled

Fabric
    requests CPU
    requests GPU
    ciclos de espera
    conflictos/arbitraje

SDRAM
    reads
    writes
    bursts
    ciclos busy
    ciclos idle
```

Entonces podríamos comparar:

``` text
fire_naive
vs
fire_shuffle
```

y responder objetivamente preguntas como:

``` text
¿hemos reducido realmente tráfico SDRAM?
¿ha bajado el tiempo esperando la LSU?
¿la GPU pasa ahora a estar limitada por ALU?
¿cuánto cuesta SHFL?
¿cuánto rendimiento obtenemos por el hardware añadido?
```

------------------------------------------------------------------------

## 21. Divergencia como experimento

El renderizado permite además construir deliberadamente dos versiones.

### Versión con branches

``` c
if (heat > 220)
    color = white;
else if (heat > 160)
    color = yellow;
else if (heat > 80)
    color = red;
else
    color = black;
```

Los threads de un mismo warp probablemente tomarán caminos distintos.

Eso ejercita la lógica SIMT de divergencia/reconvergencia (`SSY` y
branches).

### Versión mediante paleta

``` c
color = palette[heat];
```

No hay branches dependientes del píxel.

Comparar ambas versiones permitiría estudiar el coste real de
divergencia en MiniGPU.

------------------------------------------------------------------------

## 22. Posible evolución del tamaño

El ancho inicial de 64 píxeles no tiene por qué ser una limitación
definitiva.

Se elige porque encaja perfectamente con los 64 threads residentes:

``` text
64 threads -> 64 columnas
```

y simplifica muchísimo el primer programa.

Posteriormente cada thread podría procesar varias columnas:

``` text
thread 0:
    x=0
    x=64
    x=128
    x=192

thread 1:
    x=1
    x=65
    x=129
    x=193
```

Así podríamos llegar fácilmente a resoluciones como:

``` text
256×192
320×200
320×240
```

sin necesidad de cambiar el número de threads físicos.

Eso también permitiría estudiar cuánto trabajo conviene asignar a cada
thread antes de cambiar de warp.

------------------------------------------------------------------------

## 23. Doble buffer

Hay dos estrategias posibles.

### Propagación in-place por filas

Si calculamos estrictamente desde abajo hacia arriba:

``` text
fila N -> fila N-1
BAR
fila N-1 -> fila N-2
```

podemos reutilizar el mismo mapa porque una fila se consume antes de ser
sobrescrita de forma problemática.

Es muy eficiente en memoria.

### Ping-pong

Otra posibilidad es mantener:

``` text
heat_A
heat_B
```

y hacer:

``` text
A -> B
B -> A
```

Esto simplifica algoritmos más generales donde todas las celdas de un
frame deben calcularse a partir exclusivamente del estado del frame
anterior.

Para el fuego vertical sencillo, el esquema por filas puede ser más
atractivo; para evolucionar hacia una simulación 2D más general, el
doble buffer resulta más limpio.

------------------------------------------------------------------------

## 24. Papel de `SSY`

La ISA actual ya tiene soporte explícito para regiones divergentes
mediante:

``` asm
SSY label
```

El fuego básico puede diseñarse casi completamente sin divergencia
gracias al padding y a una paleta de colores.

Eso es positivo para una primera versión.

Después podemos introducir variantes deliberadamente divergentes para
comprobar:

-   comportamiento de la pila REGION;
-   comportamiento de PATH;
-   reconvergencia;
-   coste de branches diferentes entre lanes.

Así el mismo programa puede convertirse también en test de la
implementación SIMT.

------------------------------------------------------------------------

## 25. Qué demuestra este ejemplo de la arquitectura

Aunque visualmente sea sólo un fuego retro, el workload toca una parte
sorprendentemente grande de MiniGPU:

``` text
GETTID
   │
   ▼
distribución de trabajo
   │
   ▼
LOADUB
   │
   ▼
ALU
   │
   ▼
STOREB
   │
   ▼
BAR
   │
   ▼
siguiente fila
```

Además utiliza:

``` text
GPU
 ↓
LSU
 ↓
memory fabric
 ↓
SDRAM
```

y finalmente puede escribir un framebuffer que termina siendo leído por
el sistema de vídeo.

Por eso es una demo mucho más útil arquitectónicamente que un simple
patrón gráfico procedural.

------------------------------------------------------------------------

## 26. Plan de implementación propuesto

La evolución natural sería:

### Fase 1 --- fuego mínimo

-   resolución 64×N;
-   mapa de calor de 8 bits;
-   padding lateral;
-   fuente inicialmente fija;
-   3 × `LOADUB`;
-   1 × `STOREB`;
-   `BAR` entre filas.

Objetivo: **ver fuego funcionando**.

### Fase 2 --- fuente dinámica

Añadir un `xorshift32` por thread.

Objetivo: conseguir movimiento orgánico sin intervención constante de
CPU.

### Fase 3 --- render

Añadir conversión:

``` text
heat -> palette -> framebuffer
```

Objetivo: obtener colores de fuego reales.

### Fase 4 --- instrumentación

Medir:

-   ciclos;
-   loads/stores;
-   stalls;
-   tráfico del fabric;
-   tráfico SDRAM;
-   tiempo en barreras.

Objetivo: determinar el cuello de botella.

### Fase 5 --- extensión warp

Diseñar e implementar algo equivalente a:

``` asm
SHFL_UP
SHFL_DOWN
```

Objetivo: sustituir lecturas redundantes de vecinos por comunicación
entre lanes.

### Fase 6 --- comparación

Comparar:

``` text
fire_naive
fire_shuffle
```

Objetivo: cuantificar el beneficio de la nueva instrucción.

### Fase 7 --- experimentos SIMT

Introducir:

-   render divergente;
-   optimización de warps fríos;
-   posiblemente `BALLOT`;
-   más píxeles por thread.

Objetivo: convertir el fuego en un benchmark SIMT más completo.

------------------------------------------------------------------------

## 27. Conclusión

El efecto de fuego encaja especialmente bien con MiniGPU porque puede
empezar siendo extremadamente sencillo y crecer junto con la
arquitectura.

La primera versión **no necesita nuevas instrucciones**. Con `GETTID`,
`LOADUB`, `STOREB`, ALU, shifts, branches, `BAR` y `EXIT` ya es posible
construir una implementación paralela real en la que los ocho warps
colaboren fila a fila.

La característica más interesante de la versión actual probablemente sea
`BAR`: el algoritmo necesita naturalmente sincronizar los ocho warps
antes de utilizar como entrada la fila que acaban de producir.

Una futura operación `SHFL` tendría también una justificación clara:
permitiría que los ocho threads de un warp compartiesen las temperaturas
que ya han cargado, reduciendo las tres lecturas por píxel de la versión
naive hacia aproximadamente una lectura principal por píxel, salvo el
tratamiento de los límites entre warps.

Por eso conviene no empezar modificando la ISA. El camino más útil es:

``` text
hacerlo funcionar
       ↓
medir
       ↓
identificar el cuello de botella
       ↓
añadir primitivas warp
       ↓
volver a medir
```

De esta manera, el fuego deja de ser únicamente una demo gráfica y se
convierte en un **caso de estudio para evolucionar MiniGPU y MiniISA
basándose en datos reales**.
