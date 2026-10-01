<!-- trace:artifact DES-MINIGPU-FIRE
type: design
kind: exploration
subjects:
  - minigpu
status: draft
-->

# Efecto de fuego como benchmark para MiniGPU

## 1. Propósito

El efecto de fuego se plantea como un workload de estudio para MiniGPU. Permite comenzar con un algoritmo sencillo que funciona con la arquitectura disponible y utilizar después medidas reales para estudiar posibles mejoras de la ejecución SIMT.

El objetivo no es únicamente producir una animación, sino disponer de un benchmark gráfico pequeño que ejercite:

- ejecución SIMT;
- warps y lanes;
- accesos sub-palabra;
- tráfico de memoria;
- sincronización entre warps;
- divergencia y reconvergencia;
- generación pseudoaleatoria;
- renderizado a framebuffer;
- comunicación potencial entre lanes;
- contadores de rendimiento de GPU, LSU, fabric y SDRAM.

La estrategia es deliberadamente incremental:

```text
hacerlo funcionar con la arquitectura disponible
        ↓
medir
        ↓
identificar el cuello de botella
        ↓
estudiar una mejora arquitectónica
        ↓
volver a medir
        ↓
comparar
```

La primera implementación debe ser completamente válida con MiniISA v0.1 y servir como baseline para cualquier optimización posterior.

---

## 2. Baseline de referencia

### 2.1 Configuración MiniGPU

El análisis parte de la implementación MiniGPU de referencia, que dispone de:

```text
8 warps
×
8 lanes por warp
=
64 threads residentes
```

`GETTID` proporciona un identificador según:

```text
thread_id = warp_id * warp_size + lane_id
```

Con esta configuración:

```text
GETTID = 0..63
```

Esto permite escoger inicialmente un ancho de **64 píxeles**, de modo que cada thread se encargue directamente de una columna:

```text
warp 0 : threads  0..7
warp 1 : threads  8..15
warp 2 : threads 16..23
...
warp 7 : threads 56..63

                 ↓

x = 0 1 2 3 ... 62 63
```

El ancho de 64 píxeles es, por tanto, una elección conveniente para este experimento y no una propiedad general del algoritmo.

### 2.2 MiniISA utilizada

La primera versión utiliza únicamente operaciones disponibles en MiniISA v0.1, entre ellas:

- `GETTID`;
- `LOADUB`;
- `STOREB`;
- operaciones ALU como `ADD`, `SUB` y `XOR`;
- shifts inmediatos como `SHLI` y `SHRI`;
- branches;
- `BAR`;
- `EXIT`.

La definición de estas instrucciones pertenece a [`isa.md`](isa.md). Este documento únicamente estudia su utilización dentro del workload.

MiniISA v0.1 no dispone de operaciones de intercambio entre lanes como `SHFL`, ni de operaciones de voto como `BALLOT`. Esta ausencia resulta útil experimentalmente: permite medir primero una implementación sin ellas antes de estudiar si una extensión de ese tipo estaría justificada.

---

## 3. Diseño del workload

### 3.1 Representación del fuego

El fuego se representa mediante un mapa de temperaturas de 8 bits:

```text
0       = negro / frío
...
128     = rojo/naranja
...
255     = amarillo/blanco / máximo calor
```

Con un byte por celda, una imagen inicial de 64×200 necesita:

```text
64 × 200 = 12.800 bytes
```

Incluso utilizando buffers auxiliares, el coste de almacenamiento sigue siendo pequeño.

`LOADUB` permite leer una temperatura extendiendo a cero:

```asm
LOADUB Rd, Ra, offset
```

y `STOREB` permite escribir únicamente los ocho bits bajos:

```asm
STOREB Rs, Ra, offset
```

### 3.2 Propagación básica

El fuego se propaga desde la parte inferior hacia arriba.

Para una celda puede utilizarse inicialmente:

```c
new_heat =
    (left + center + center + right) / 4;

new_heat -= decay;
```

Gráficamente:

```text
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

El doble peso del píxel central reduce la dispersión horizontal.

Una primera implementación puede utilizar:

```text
decay = 2
```

### 3.3 Cálculo de una celda

Cada thread obtiene su columna:

```asm
GETTID R3
```

Con la convención:

```text
R1 = dirección de la fila fuente
R2 = dirección de la fila destino
R3 = x
```

la dirección del píxel central es:

```asm
ADD R4, R1, R3
```

Los tres valores de entrada se cargan mediante:

```asm
LOADUB R10, R4, -1     ; izquierda
LOADUB R11, R4,  0     ; centro
LOADUB R12, R4,  1     ; derecha
```

y se combinan:

```asm
ADD  R13, R10, R11
ADD  R13, R13, R11
ADD  R13, R13, R12

SHRI R13, R13, 2
```

Esto implementa:

```text
(left + 2*center + right) / 4
```

Después se aplica el enfriamiento:

```asm
ADDI R13, R13, -2
```

Para impedir que el underflow convierta un valor pequeño en un entero grande:

```asm
BGE  R13, R0, heat_ok
MOVI R13, 0

heat_ok:
```

Finalmente se escribe el resultado:

```asm
ADD    R5, R2, R3
STOREB R13, R5, 0
```

### 3.4 Padding lateral

Los threads correspondientes a los extremos presentan un caso especial:

```text
thread 0:
    left = x - 1

thread 63:
    right = x + 1
```

Tratar estos extremos mediante branches introduciría divergencia.

Para la implementación inicial se propone añadir un byte de padding a cada lado de la fila:

```text
+------+--------------------------------+------+
|  0   | p0 p1 p2 ... p61 p62 p63      |  0   |
+------+--------------------------------+------+
```

La fila física pasa a ocupar:

```text
64 + 2 = 66 bytes
```

El puntero `src` apunta a `p0`, no al byte de padding.

Así:

```asm
LOADUB R10, R4, -1
LOADUB R11, R4,  0
LOADUB R12, R4,  1
```

es válido para todos los threads sin introducir tratamiento divergente de los extremos de la imagen.

### 3.5 Propagación vertical

No es necesario disponer simultáneamente de un thread por cada píxel de la imagen.

Los 64 threads residentes procesan una fila completa y después se reutilizan para la siguiente:

```text
64 threads
    │
    ▼
fila 198

64 threads
    │
    ▼
fila 197

...
```

Cada iteración vertical utiliza los 64 threads.

El kernel puede, por tanto, contener un bucle vertical:

```asm
MOVI R20, NUM_ROWS

row_loop:

    ; cada thread calcula su píxel
    ...
    STOREB R13, R5, 0

    BAR

    ADDI R1, R1, -66
    ADDI R2, R2, -66

    ADDI R20, R20, -1
    BNE  R20, R0, row_loop

    EXIT
```

### 3.6 Sincronización entre filas

Los 64 threads se distribuyen entre ocho warps.

Antes de que un warp utilice una fila como entrada de la siguiente iteración, todos los warps participantes deben haber terminado de escribirla:

```text
generar fila N
      │
      ▼
todos deben haber terminado
      │
      ▼
usar fila N para generar N-1
```

Según MiniISA v0.1, `BAR` sincroniza los warps participantes del mismo workgroup y garantiza que las operaciones de memoria anteriores hayan finalizado antes de continuar.

El patrón del workload es:

```asm
STOREB ...
BAR
```

Después de `BAR`, los warps pueden utilizar con seguridad la fila recién generada como entrada de la siguiente iteración.

Este es uno de los aspectos arquitectónicamente interesantes del ejemplo: los ocho warps no realizan simplemente cálculos independientes, sino que cooperan en la construcción de una estructura común fila a fila.

---

## 4. Fuente de calor y generación pseudoaleatoria

### 4.1 Fuente inicial

La fila inferior actúa como fuente de energía.

Una fuente completamente fija:

```text
255 255 255 255 255 ...
```

produce un fuego muy estable.

Puede introducirse variación mediante valores como:

```text
255 255 128 255 0 255 192 255 ...
```

La CPU podría actualizar esta fila en cada frame, pero resulta más interesante para el benchmark que la propia GPU pueda generarla.

### 4.2 RNG por thread

Cada thread puede conservar un estado pseudoaleatorio en un registro.

`xorshift32` encaja con las operaciones disponibles porque utiliza únicamente XOR y shifts:

```c
x ^= x << 13;
x ^= x >> 17;
x ^= x << 5;
```

Una traducción directa es:

```asm
SHLI R22, R21, 13
XOR  R21, R21, R22

SHRI R22, R21, 17
XOR  R21, R21, R22

SHLI R22, R21, 5
XOR  R21, R21, R22
```

Puede obtenerse una temperatura de 8 bits mediante:

```asm
ANDI R22, R21, 0xFF
```

Cada thread genera así el valor correspondiente a su propia columna.

Las semillas deben diferir entre threads. Una opción es derivarlas de `GETTID` y de una semilla global proporcionada por la CPU.

---

## 5. Kernel de referencia

Una organización conceptual del programa sería:

```text
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

Una versión esquemática del núcleo de propagación sería:

```asm
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

Este código es deliberadamente un esqueleto. La inicialización de los punteros y la ubicación definitiva de los buffers dependen del mecanismo de lanzamiento de MiniGPU y del mapa de memoria utilizado por la plataforma.

---

## 6. Renderizado

El mapa de calor y el framebuffer no tienen por qué compartir representación.

Puede utilizarse:

```text
heat buffer
    8 bits/pixel
        │
        ▼
    paleta
        │
        ▼
framebuffer RGB
```

Una paleta de 256 entradas permite asociar directamente cada temperatura con un color:

```text
palette[0]
palette[1]
...
palette[255]
```

Conceptualmente:

```c
heat = heat_buffer[pixel];
color = palette[heat];
framebuffer[pixel] = color;
```

Este esquema evita una cascada de branches dependientes del valor:

```c
if (heat > 220)
    white;
else if (heat > 160)
    yellow;
else if (...)
```

que podría producir divergencia dentro de un warp.

El renderizado mediante paleta añade además otro patrón útil para estudiar la LSU:

```text
LOADUB del mapa de calor
        ↓
lookup de paleta
        ↓
STORE al framebuffer
```

---

## 7. Baseline y métricas

### 7.1 Coste de memoria de la versión inicial

La propagación inicial necesita, por píxel:

```text
3 × LOADUB
1 × STOREB
```

Para una imagen de 64×200:

```text
12.800 píxeles
```

esto supone aproximadamente:

```text
38.400 LOADUB
12.800 STOREB
```

por actualización completa del mapa de calor.

Estos valores forman un baseline sencillo contra el que comparar posibles optimizaciones.

### 7.2 Métricas de interés

Para estudiar el comportamiento del workload interesa medir, al menos:

```text
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

La disponibilidad y representación concreta de estos contadores pertenece al sistema de instrumentación correspondiente; aquí se enumeran como métricas de interés para el experimento.

El baseline debe permitir responder preguntas como:

```text
¿dónde está el cuello de botella?
¿qué parte del tiempo se consume esperando la LSU?
¿cuánto tráfico llega realmente a SDRAM?
¿cuánto tiempo se consume en BAR?
¿qué coste tiene la divergencia?
```

---

## 8. Exploración de comunicación entre lanes

### 8.1 Motivación

El algoritmo presenta un patrón especialmente interesante: cada thread necesita valores procesados por sus vecinos.

En la versión inicial cada lane carga:

```text
left
center
right
```

Aunque dentro de un warp las ocho lanes están procesando píxeles contiguos:

```text
lane:    0   1   2   3   4   5   6   7

heat:   H0  H1  H2  H3  H4  H5  H6  H7
```

La misma temperatura puede, por tanto, ser cargada varias veces desde memoria por lanes distintas.

Una primitiva de comunicación entre lanes podría permitir que cada lane cargase solamente su propio píxel:

```asm
LOADUB R10, R4, 0
```

y obtuviese los vecinos mediante intercambio dentro del warp.

### 8.2 Posible forma de shuffle

Una posible interfaz a estudiar sería conceptualmente equivalente a:

```asm
SHFL_UP   R11, R10
SHFL_DOWN R12, R10
```

De este modo, para una lane interior:

```text
lane 3:

left   = valor de lane 2
center = valor de lane 3
right  = valor de lane 4
```

El cálculo posterior no cambia:

```asm
ADD  R13, R11, R10
ADD  R13, R13, R10
ADD  R13, R13, R12
SHRI R13, R13, 2
```

`SHFL_UP` y `SHFL_DOWN` se utilizan aquí como forma conceptual de expresar el experimento. Este documento no fija su encoding ni exige que una futura extensión adopte exactamente esos mnemónicos o esa interfaz.

### 8.3 Comparación conceptual

Por píxel:

| Operación | baseline | con shuffle |
|---|---:|---:|
| `LOADUB` | 3 | 1 |
| `STOREB` | 1 | 1 |
| shuffle | 0 | 2 |
| ALU | similar | similar |

El tráfico principal de lectura del mapa de calor podría pasar aproximadamente de:

```text
3 lecturas/píxel
```

a:

```text
1 lectura/píxel
```

para las lanes que pueden obtener ambos vecinos dentro del warp.

Esto representa una reducción aproximada de 3× en esas lecturas, pero **no implica una aceleración de 3× del programa**.

El resultado depende también de:

- latencia de la operación de shuffle;
- scheduler;
- LSU;
- fabric;
- SDRAM;
- stalls;
- coste de hardware;
- frecuencia alcanzable;
- otros cuellos de botella del sistema.

Por eso el baseline debe medirse antes de justificar la extensión.

### 8.4 Límites entre warps

El intercambio dentro de un warp no resuelve todos los vecinos.

Con warps de ocho lanes:

```text
warp 0                   warp 1
0 1 2 3 4 5 6 7          8 9 10 11 12 13 14 15
              │          │
              └──────────┘
```

La lane 7 del primer warp necesita el píxel procesado por la lane 0 del siguiente.

Del mismo modo, la lane 0 necesita como vecino izquierdo un píxel del warp anterior.

Un shuffle restringido al warp no puede obtener esos valores.

Las alternativas incluyen:

- realizar un `LOADUB` adicional únicamente para las lanes de borde;
- proporcionar intercambio entre warps;
- reorganizar los datos;
- aceptar cierta redundancia de memoria.

Para este workload, el acceso adicional en los bordes parece la alternativa más sencilla para estudiar inicialmente.

Este caso también permite experimentar con divergencia controlada.

### 8.5 Posible utilidad de `BALLOT`

Una operación de voto como `BALLOT` podría ser útil para consultas del tipo:

```text
heat > threshold
```

produciendo una máscara de lanes:

```text
00111100
```

Esto permitiría estudiar optimizaciones como:

- detectar warps completamente fríos;
- evitar trabajo cuando todas las lanes contienen calor cero;
- localizar zonas activas;
- introducir efectos adicionales, como chispas.

Para el kernel de propagación descrito aquí, la comunicación de valores entre lanes ataca de forma más directa las lecturas redundantes de vecinos. `BALLOT` se considera, por tanto, una línea experimental distinta y no un requisito de la primera optimización.

---

## 9. Experimentos SIMT

### 9.1 Divergencia en el renderizado

El renderizado permite construir dos variantes equivalentes desde el punto de vista visual.

Una versión basada en branches:

```c
if (heat > 220)
    color = white;
else if (heat > 160)
    color = yellow;
else if (heat > 80)
    color = red;
else
    color = black;
```

puede hacer que lanes del mismo warp recorran caminos diferentes.

Una versión basada en paleta:

```c
color = palette[heat];
```

no introduce branches dependientes del píxel.

Comparar ambas permite estudiar el coste real de divergencia y reconvergencia.

### 9.2 Papel de `SSY`

MiniISA v0.1 proporciona:

```asm
SSY label
```

para marcar el punto de reconvergencia de una región divergente.

La versión básica del fuego puede diseñarse casi completamente sin divergencia gracias al padding y al renderizado mediante paleta.

Esto proporciona un baseline sencillo.

Posteriormente pueden introducirse variantes deliberadamente divergentes para ejercitar:

- comportamiento de la pila REGION;
- comportamiento de PATH;
- reconvergencia;
- branches distintos entre lanes;
- coste temporal de la divergencia.

Así, el mismo workload puede utilizarse también para verificar y caracterizar la implementación SIMT.

---

## 10. Evoluciones del workload

### 10.1 Más columnas por thread

El ancho inicial de 64 píxeles se escoge porque coincide con los 64 threads residentes del baseline:

```text
64 threads → 64 columnas
```

No es una limitación fundamental.

Cada thread puede procesar varias columnas:

```text
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

Esto permite estudiar resoluciones mayores como:

```text
256×192
320×200
320×240
```

sin modificar el número de threads físicos.

También permite estudiar cuánto trabajo conviene asignar a cada thread antes de cambiar de warp.

### 10.2 Propagación in-place

Si las filas se calculan estrictamente de abajo hacia arriba:

```text
fila N -> fila N-1
BAR
fila N-1 -> fila N-2
```

puede reutilizarse un mismo mapa de calor, ya que cada fila se consume antes de ser sobrescrita de forma problemática.

Esta opción minimiza el uso de memoria.

### 10.3 Doble buffer

Una alternativa es mantener:

```text
heat_A
heat_B
```

y alternar:

```text
A -> B
B -> A
```

Este esquema es más general cuando todas las celdas de un frame deben calcularse exclusivamente a partir del estado del frame anterior.

Para la propagación vertical sencilla, el procesamiento por filas resulta atractivo. Para una futura simulación 2D más general, el esquema ping-pong proporciona una separación de estados más clara.

---

## 11. Cobertura arquitectónica del benchmark

Aunque el resultado visual sea sencillo, el workload recorre una parte considerable de MiniGPU:

```text
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

Además ejercita el camino de memoria:

```text
GPU
 ↓
LSU
 ↓
memory fabric
 ↓
SDRAM
```

y puede terminar escribiendo un framebuffer consumido posteriormente por el sistema de vídeo.

Por ello resulta útil como benchmark arquitectónico además de como demostración gráfica.

---

## 12. Plan experimental

### Fase 1 — fuego mínimo

Implementar:

- resolución 64×N;
- mapa de calor de 8 bits;
- padding lateral;
- fuente inicialmente fija;
- 3 × `LOADUB` por píxel;
- 1 × `STOREB` por píxel;
- `BAR` entre filas.

Objetivo:

```text
obtener una implementación funcional de referencia
```

### Fase 2 — fuente dinámica

Añadir un `xorshift32` por thread.

Objetivo:

```text
generar movimiento sin actualización continua desde CPU
```

### Fase 3 — renderizado

Añadir:

```text
heat
  ↓
palette
  ↓
framebuffer
```

Objetivo:

```text
producir la representación gráfica del fuego
```

### Fase 4 — instrumentación

Medir:

- ciclos;
- instrucciones;
- loads y stores;
- stalls;
- tráfico del fabric;
- tráfico SDRAM;
- tiempo en barreras;
- divergencia cuando corresponda.

Objetivo:

```text
identificar el cuello de botella real
```

### Fase 5 — comunicación entre lanes

Solo después de disponer de medidas del baseline, diseñar e implementar experimentalmente una operación de comunicación entre lanes equivalente funcionalmente a:

```asm
SHFL_UP
SHFL_DOWN
```

El objetivo es sustituir lecturas redundantes de vecinos por comunicación dentro del warp.

Esta fase es experimental: no presupone que la extensión definitiva de MiniISA deba utilizar exactamente esos mnemónicos ni esa interfaz.

### Fase 6 — comparación

Comparar:

```text
fire_naive
vs
fire_shuffle
```

Preguntas de interés:

```text
¿se ha reducido realmente el tráfico SDRAM?
¿ha disminuido el tiempo esperando la LSU?
¿la GPU ha pasado a estar limitada por la ALU?
¿cuál es el coste temporal del shuffle?
¿qué rendimiento aporta respecto al hardware añadido?
```

El objetivo es cuantificar el beneficio de la nueva primitiva y obtener datos suficientes para evaluar si la extensión está justificada.

### Fase 7 — experimentos SIMT

Explorar:

- renderizado divergente;
- optimización de warps fríos;
- posibles operaciones de voto como `BALLOT`;
- más píxeles por thread;
- variantes del esquema de buffering.

Objetivo:

```text
convertir el fuego en un benchmark SIMT más completo
```

---

## 13. Conclusiones

El efecto de fuego resulta adecuado como caso de estudio para MiniGPU porque puede comenzar con un kernel muy sencillo y crecer junto con la arquitectura.

La primera versión no requiere nuevas instrucciones. Con:

```text
GETTID
LOADUB
STOREB
ALU
shifts
branches
BAR
EXIT
```

puede construirse un programa paralelo en el que los ocho warps del baseline colaboren fila a fila.

`BAR` tiene un uso natural en el algoritmo: antes de consumir como entrada una fila recién generada, los warps deben completar la fase que la produce.

El patrón de acceso a vecinos proporciona además un caso concreto para estudiar comunicación entre lanes. Una operación de shuffle podría permitir reutilizar temperaturas ya cargadas dentro del warp y reducir las tres lecturas por píxel de la versión baseline hacia aproximadamente una lectura principal por píxel, salvo por el tratamiento necesario en los límites entre warps.

La hipótesis debe comprobarse mediante medidas. Una reducción del número de cargas no garantiza por sí sola una mejora proporcional del tiempo de ejecución.

El proceso de trabajo propuesto es:

```text
implementar baseline
        ↓
medir
        ↓
identificar el cuello de botella
        ↓
formular una mejora
        ↓
implementar variante
        ↓
volver a medir
        ↓
comparar
```

De este modo, el efecto de fuego deja de ser únicamente una demostración gráfica y se convierte en un caso de estudio para evolucionar MiniGPU y MiniISA a partir de comportamiento medido.
