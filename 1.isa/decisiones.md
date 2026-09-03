# MiniCPU → MiniGPU: decisiones de diseño

## 1. Objetivo del proyecto

El objetivo no es construir una GPU potente, sino **entender cómo una
CPU sencilla puede evolucionar progresivamente hacia una arquitectura
GPU/SIMT**.

El caso de uso principal será el cálculo del conjunto de Mandelbrot,
porque:

-   cada píxel puede calcularse de forma independiente;
-   tiene bastante cálculo aritmético por dato;
-   requiere poca memoria externa durante el bucle principal;
-   introduce divergencia de control de forma natural, ya que distintos
    píxeles necesitan distinto número de iteraciones;
-   permite verificar fácilmente el resultado mediante una imagen.

La secuencia prevista es:

``` text
Mandelbrot Python float
        ↓
Mandelbrot Python fixed-point
        ↓
MiniISA
        ↓
MiniCPU escalar sencilla
        ↓
MiniCPU con pipeline
        ↓
ejecución SIMD
        ↓
ejecución SIMT / warps
        ↓
MiniGPU con múltiples warps
        ↓
scoreboard + scheduler + pipelines
        ↓
implementación VHDL
        ↓
FPGA
```

------------------------------------------------------------------------

## 2. Separación entre cálculo y visualización

El cálculo de Mandelbrot **no genera directamente una imagen**.

Todos los motores de cálculo producirán un archivo `.iter` que contiene
el número de iteraciones de cada píxel.

Esto permite que:

``` text
Python float ──────┐
Python fixed ──────┤
MiniCPU ───────────┤
MiniGPU ───────────┤──► .iter ──► visor ──► PNG
VHDL ──────────────┘
```

El visor es independiente de la arquitectura.

### Formato `.iter` actual

``` text
4 bytes    magic = "ITER"
4 bytes    width             uint32 little-endian
4 bytes    height            uint32 little-endian
4 bytes    max_iterations    uint32 little-endian
-----------------------------------------------
width × height × 2 bytes
           iteraciones       uint16 little-endian
```

El archivo no almacena colores, sino únicamente el número de
iteraciones.

------------------------------------------------------------------------

## 3. Golden models

Se mantendrán dos implementaciones Python de referencia.

### 3.1. Mandelbrot float

Es la referencia matemática/visual.

Usa aritmética de coma flotante de Python.

No se espera que coincida exactamente con la implementación fixed-point.

### 3.2. Mandelbrot fixed-point

Será el **golden model exacto de la futura ISA y del hardware**.

La intención es que:

``` text
Python fixed
MiniCPU
MiniGPU
VHDL
```

produzcan exactamente el mismo `.iter`, píxel por píxel.

Si cualquiera de estas implementaciones difiere del Python fixed-point,
se considerará un bug hasta demostrar lo contrario.

------------------------------------------------------------------------

## 4. Fixed-point

### Decisión actual

Usar inicialmente valores de **32 bits signed** y formato **Q16.16**.

``` text
31             16 15              0
┌────────────────┬─────────────────┐
│ parte entera   │ parte fraccional│
└────────────────┴─────────────────┘
       16 bits          16 bits
```

Interpretación:

``` text
valor_real = entero_signed / 2^16
```

Ejemplos:

``` text
0.0   = 0x00000000
0.5   = 0x00008000
1.0   = 0x00010000
2.0   = 0x00020000
-1.0  = 0xFFFF0000
```

Resolución:

``` text
2^-16 ≈ 0.0000152588
```

### Multiplicación

Dos Q16.16 producen inicialmente un resultado signed de 64 bits.

La operación de referencia es:

``` text
tmp = signed64(a) × signed64(b)
result = signed32(tmp >> 16)
```

El desplazamiento de valores negativos debe ser **aritmético**.

Python debe forzar explícitamente el resultado a 32 bits para reproducir
el comportamiento del hardware.

### Overflow

El comportamiento previsto es wrap-around a 32 bits, equivalente a
conservar los 32 bits bajos del resultado correspondiente después de la
operación definida.

La semántica exacta deberá quedar formalizada en la especificación de la
ISA.

### Decisión pendiente

Q16.16 funciona suficientemente bien para avanzar, pero no se considera
necesariamente el formato final óptimo.

Se podrá experimentar posteriormente con:

``` text
Q12.20
Q8.24
Q6.26
...
```

sin cambiar el ancho de registro de 32 bits.

En la prueba inicial Q16.16 frente a float, a 640×480 y 256 iteraciones:

``` text
Total píxeles:       307200
Píxeles iguales:     303415
Píxeles diferentes:    3785
Diferentes:          1.232096 %
```

Esto se considera suficiente para continuar con el diseño de la
arquitectura.

------------------------------------------------------------------------

## 5. Separación ISA / microarquitectura

Una decisión fundamental del proyecto es mantener separadas:

-   **ISA:** qué significa cada instrucción;
-   **microarquitectura:** cómo la máquina ejecuta esas instrucciones.

La misma instrucción:

``` asm
ADD R3, R1, R2
```

puede significar exactamente lo mismo en ambas máquinas.

En MiniCPU:

``` text
R3 ← R1 + R2
```

para un único thread.

En MiniGPU, conceptualmente:

``` text
lane 0: T0.R3 ← T0.R1 + T0.R2
lane 1: T1.R3 ← T1.R1 + T1.R2
...
```

solo para las lanes activas.

La intención es mantener el mismo kernel/binario durante la evolución
CPU → GPU siempre que sea razonable.

------------------------------------------------------------------------

## 6. MiniISA: decisiones preliminares

### Ancho de instrucción

**32 bits fijos.**

Motivos:

-   decoder sencillo;
-   direccionamiento de instrucciones sencillo;
-   adecuado para VHDL;
-   permite una ISA tipo RISC;
-   evita inicialmente instrucciones de longitud variable.

### Registros

**32 registros arquitectónicos por thread:**

``` text
R0 ... R31
```

Cada registro:

``` text
32 bits
```

Se necesitan 5 bits para codificar un registro.

### Direcciones

Espacio de direcciones previsto:

``` text
32 bits
```

El modelo de memoria exacto queda pendiente de concretar.

### Opcode

Propuesta actual:

``` text
6 bits
```

Esto permite:

``` text
64 opcodes
```

No se espera necesitar los 64 inicialmente.

Se reservará explícitamente espacio para futuras extensiones GPU/SIMT.

Una posible organización conceptual, aún no cerrada, sería:

``` text
00xxxx   ALU / operaciones comunes
01xxxx   memoria
10xxxx   control de flujo
11xxxx   extensiones / GPU / sistema
```

Esta distribución concreta todavía no es definitiva.

------------------------------------------------------------------------

## 7. Instrucciones base propuestas

Lista preliminar:

``` asm
MOVI  Rd, imm
LUI   Rd, imm

ADD   Rd, Ra, Rb
ADDI  Rd, Ra, imm
SUB   Rd, Ra, Rb

MULFX Rd, Ra, Rb

LOAD  Rd, [Ra + imm]
STORE [Ra + imm], Rs

CMP   Ra, Rb
CMPI  Ra, imm

BEQ   offset
BNE   offset
BLT   offset
BGE   offset
BRA   offset

HALT
```

La lista no está todavía congelada.

------------------------------------------------------------------------

## 8. Carga de constantes

La ISA necesita inmediatos.

Como mínimo:

``` asm
MOVI Rd, imm
```

y probablemente:

``` asm
ADDI Rd, Ra, imm
```

Para constantes que no quepan en el inmediato se prevé una operación
como:

``` asm
LUI Rd, imm
```

combinada con otra operación sobre los bits inferiores.

El encoding exacto y el tamaño de cada inmediato están todavía
pendientes.

------------------------------------------------------------------------

## 9. MULFX

Para la primera versión se acepta una instrucción específica de
fixed-point:

``` asm
MULFX Rd, Ra, Rb
```

Semántica provisional para Q16.16:

``` text
tmp = signed64(Ra) × signed64(Rb)
Rd  = signed32(tmp >> 16)
```

Esto simplifica mucho la primera CPU y la posterior implementación VHDL.

Más adelante se podrá estudiar si interesa sustituirla por primitivas
más generales de multiplicación y desplazamiento.

------------------------------------------------------------------------

## 10. GETTID y modelo de work-items

Se propone que `GETTID` forme parte del modelo común CPU/GPU y no sea
exclusivamente una instrucción GPU.

``` asm
GETTID Rd
```

Devuelve el identificador del work-item actual.

### En MiniCPU

El runtime/simulador ejecutaría secuencialmente el kernel:

``` text
tid = 0   → ejecutar kernel
tid = 1   → ejecutar kernel
tid = 2   → ejecutar kernel
...
```

`GETTID` devuelve el ID correspondiente a esa ejecución.

### En MiniGPU

Por ejemplo, con warps de 8 threads:

``` text
warp 0:
  lane 0 → tid 0
  lane 1 → tid 1
  ...
  lane 7 → tid 7

warp 1:
  lane 0 → tid 8
  ...
```

Esto permite que el mismo kernel pueda ejecutarse secuencialmente en CPU
y en paralelo en GPU.

------------------------------------------------------------------------

## 11. Espacio reservado para extensiones GPU

Aunque la primera CPU no necesite estas operaciones, el encoding debe
permitir añadirlas sin rediseñar la ISA.

Posibles extensiones futuras:

``` text
GETLANE
GETWARP

SETMASK
PUSHMASK
POPMASK

BAR
```

No se considera todavía definitiva ni la lista ni la semántica exacta.

Para la primera MiniGPU puede que no sea necesario implementar una pila
general de reconvergencia: Mandelbrot puede manejarse inicialmente
mediante una máscara activa que va perdiendo lanes a medida que los
píxeles terminan.

------------------------------------------------------------------------

## 12. Registros arquitectónicos vs registros físicos

Los 32 registros de la ISA son **registros arquitectónicos por thread**.

No deben confundirse con el tamaño físico del register file.

MiniCPU:

``` text
32 registros × 32 bits
```

MiniGPU con:

``` text
32 registros/thread
8 threads/warp
8 warps residentes
32 bits/registro
```

necesita:

``` text
32 × 8 × 8 × 32 bits
= 65536 bits
= 8192 bytes
= 8 KiB
```

Con 16 warps residentes serían 16 KiB.

Por tanto, una GPU necesita un register file grande principalmente
porque mantiene el estado de **muchos threads residentes**, no porque la
ISA necesite necesariamente cientos de nombres de registros por thread.

### Decisión

Mantener:

``` text
32 registros arquitectónicos/thread
```

y escalar independientemente el número de warps residentes.

------------------------------------------------------------------------

## 13. Register file y ancho de banda interno

La capacidad del register file no es necesariamente el principal
problema.

Con una instrucción:

``` asm
ADD R3, R1, R2
```

y 8 lanes físicas, idealmente habría que obtener:

``` text
8 valores de R1
8 valores de R2
```

y posteriormente escribir:

``` text
8 valores de R3
```

Esto puede requerir mucho más ancho de banda interno del que proporciona
una memoria monolítica sencilla.

Por ello se prevé estudiar:

-   register file bancado;
-   conflictos entre bancos;
-   operand collectors;
-   execution width menor que warp width.

Ejemplo futuro posible:

``` text
warp width      = 8 threads
execution width = 4 lanes
```

Una instrucción del warp se ejecutaría físicamente en dos tandas:

``` text
ciclo N:     threads 0..3
ciclo N+1:   threads 4..7
```

Esta decisión no está tomada todavía; será parte de los experimentos de
microarquitectura y síntesis.

------------------------------------------------------------------------

## 14. MiniCPU inicial

La primera CPU será deliberadamente sencilla y **sin pipeline**.

Objetivo:

1.  ejecutar correctamente la MiniISA;
2.  ejecutar el kernel Mandelbrot;
3.  producir el mismo `.iter` que el golden model fixed-point.

Arquitectura conceptual:

``` text
PC
 ↓
Fetch
 ↓
Decode
 ↓
Register File
 ↓
Execute / ALU
 ↓
Memory
 ↓
Writeback
```

No se pretende inicialmente obtener una instrucción por ciclo.

### Latencias

El simulador podrá asignar latencias abstractas, por ejemplo:

``` text
ADD      1 ciclo
SUB      1 ciclo
CMP      1 ciclo
BRA      1 ciclo
MULFX    3 ciclos
LOAD     2 ciclos
STORE    2 ciclos
```

Estos valores son inicialmente **parámetros del modelo**, no mediciones
físicas.

------------------------------------------------------------------------

## 15. CPU con pipeline

Una vez validada la CPU sencilla se evolucionará hacia una CPU pipeline.

Modelo inicial probable:

``` text
IF → ID → EX → MEM → WB
```

El simulador representará explícitamente el estado de cada etapa y
avanzará mediante `tick()`.

Esto permitirá estudiar:

-   hazards de datos;
-   stalls;
-   forwarding;
-   hazards de control;
-   latencia de multiplicación;
-   CPI;
-   utilización del pipeline.

La CPU pipeline seguirá ejecutando la misma ISA.

------------------------------------------------------------------------

## 16. Simuladores

### Lenguaje

**Python.**

Motivos:

-   facilidad para modificar la arquitectura;
-   legibilidad;
-   facilidad de depuración;
-   facilidad para generar trazas;
-   rendimiento suficiente para una MiniCPU/MiniGPU educativa.

No se pretende simular una GPU comercial completa.

### Modelo temporal

Los simuladores finales serán **cycle-accurate respecto a nuestra
microarquitectura abstracta**.

Una llamada conceptual:

``` python
machine.tick()
```

representará un ciclo.

No se intentará inicialmente simular nanosegundos ni tiempos de
propagación físicos.

------------------------------------------------------------------------

## 17. Latencia, throughput y hardware real

El simulador distinguirá entre:

``` text
latency
```

y:

``` text
initiation rate / throughput
```

Ejemplo:

``` text
MUL:
    latency = 4 ciclos
    puede aceptar 1 operación/ciclo
```

Una unidad pipeline puede tener varias operaciones simultáneamente en
vuelo.

Los valores iniciales serán decisiones del modelo.

Posteriormente:

``` text
Python model
     ↓
VHDL
     ↓
síntesis / timing FPGA
     ↓
latencias y frecuencia reales
     ↓
ajuste del modelo Python
```

La síntesis responderá a preguntas que el simulador abstracto no puede
responder, como la frecuencia máxima y los critical paths.

------------------------------------------------------------------------

## 18. Evolución hacia GPU

La intención no es escribir desde cero un simulador GPU desconectado de
la CPU.

La evolución conceptual será:

``` text
MiniCPU
   ↓
múltiples lanes
   ↓
SIMD
   ↓
threads escalares agrupados
   ↓
SIMT
   ↓
warps
   ↓
múltiples warps residentes
   ↓
warp scheduler
   ↓
scoreboard
   ↓
MiniGPU
```

Esto permite observar qué mecanismos de CPU dejan de ser necesarios y
cuáles aparecen para optimizar throughput.

------------------------------------------------------------------------

## 19. Modelo SIMT previsto

Configuración inicial orientativa:

``` text
1 SM
8 threads/warp
8 warps residentes
8 lanes inicialmente, sujeto a experimentación
```

Cada warp tendrá conceptualmente:

``` text
PC
active_mask
estado
scoreboard
registros de sus threads
```

### Active mask

Con warp de 8 threads:

``` text
active_mask = 11111111
```

Un bit indica si la lane participa en la instrucción actual.

En Mandelbrot, las lanes correspondientes a píxeles que ya han escapado
pueden ir desactivándose.

El bucle termina cuando:

``` text
active_mask == 0
```

o se alcanza el máximo de iteraciones.

------------------------------------------------------------------------

## 20. Scoreboard

El scoreboard servirá para conocer qué operandos están pendientes.

Modelo simple:

``` text
scoreboard[warp][register]
```

Por ejemplo:

``` text
W4.R7 = pending
```

Si la siguiente instrucción de W4 necesita R7, ese warp no será
elegible.

El scheduler podrá seleccionar otro warp ready.

El scoreboard puede seguir el estado a nivel `(warp, registro)` en el
modelo inicial, en lugar de mantener un bit independiente por thread.

------------------------------------------------------------------------

## 21. Warp scheduler

El scheduler trabaja con **warps residentes**, no con todos los threads
lanzados.

En cada oportunidad de issue:

``` text
resident warps
      ↓
scoreboard / estado
      ↓
ready warps
      ↓
scheduler
      ↓
issue
```

Si un warp está esperando una dependencia o memoria, se selecciona otro.

Esta es una diferencia fundamental frente a una CPU orientada a explotar
ILP mediante mecanismos como out-of-order execution.

La GPU explotará principalmente **thread-level parallelism** manteniendo
muchos warps residentes.

------------------------------------------------------------------------

## 22. Pipeline de la MiniGPU

La GPU también tendrá pipelines explícitos en el simulador.

Modelo conceptual futuro:

``` text
Warp Scheduler
      ↓
Issue
      ↓
Operand Collector
      ↓
 ┌────┼──────────┐
 ↓    ↓          ↓
ALU   MUL      Load/Store
pipe  pipe       pipe
```

Podrán existir instrucciones de distintos warps simultáneamente en
diferentes etapas.

El simulador distinguirá:

-   resident;
-   ready;
-   issued;
-   executing/in-flight;
-   stalled;
-   completed.

------------------------------------------------------------------------

## 23. Memoria y Mandelbrot

Mandelbrot es deliberadamente una carga **compute-heavy**.

Durante las iteraciones, valores como:

``` text
zx
zy
cx
cy
iteration
```

pueden mantenerse en registros.

No es necesario acceder continuamente a RAM externa.

Al terminar un píxel se escribe principalmente su número de iteraciones.

Por ejemplo:

``` text
320 × 240 × 1 byte × 60 FPS
≈ 4.6 MB/s
```

Incluso resoluciones educativas superiores siguen teniendo requisitos
modestos.

Por ello la primera FPGA puede evitar DDR externa y utilizar memoria
on-chip para framebuffer y datos.

------------------------------------------------------------------------

## 24. Framebuffer

Para una primera implementación podría utilizarse:

``` text
320 × 240 × 8 bits
= 76800 bytes
≈ 75 KiB
```

Un doble buffer necesitaría aproximadamente:

``` text
150 KiB
```

dependiendo de la FPGA seleccionada.

Arquitectura conceptual:

``` text
MiniGPU
   ↓
Framebuffer BRAM
   ↓
controlador de vídeo
   ↓
VGA / HDMI
```

Esto queda para una fase posterior.

------------------------------------------------------------------------

## 25. VHDL

Después de validar los simuladores Python, se implementará la
arquitectura en VHDL.

La intención es que exista una correspondencia clara entre estado del
simulador y hardware:

``` text
Python                       VHDL

pipeline[0]          ↔       registro de pipeline
warp.pc              ↔       registro PC
warp.active_mask     ↔       registro máscara
scoreboard           ↔       FFs / RAM
register_file        ↔       BRAM / LUTRAM / FF
```

La síntesis FPGA permitirá descubrir limitaciones reales:

-   uso de LUTs;
-   uso de FFs;
-   uso de BRAM;
-   DSPs;
-   routing;
-   frecuencia máxima;
-   critical path;
-   ancho de banda interno.

Estas restricciones podrán obligar a cambiar la microarquitectura.

------------------------------------------------------------------------

## 26. Decisiones acordadas hasta ahora

-   Mandelbrot como workload principal.
-   Python para los simuladores.
-   VHDL para la implementación hardware.
-   Separar cálculo `.iter` de visualización.
-   Mantener un Mandelbrot float como referencia visual/matemática.
-   Mantener un Mandelbrot fixed-point como golden model exacto.
-   Datos/registros de 32 bits.
-   Fixed-point inicialmente Q16.16, pero parametrizable.
-   Instrucciones de 32 bits fijas.
-   32 registros arquitectónicos por thread (`R0-R31`).
-   Direcciones de 32 bits como objetivo.
-   Opcode de 6 bits como propuesta base.
-   Reservar espacio de encoding para extensiones GPU.
-   Evitar instrucciones vectoriales explícitas tipo `VADD`
    inicialmente.
-   Mantener operaciones escalares y convertir la microarquitectura a
    SIMT.
-   `GETTID` como candidato fuerte a instrucción común CPU/GPU.
-   CPU inicial sencilla y sin pipeline.
-   Añadir pipeline después de validar funcionalmente la CPU.
-   Simulador final cycle-accurate respecto a la microarquitectura
    modelada.
-   Evolucionar la CPU hacia GPU progresivamente, no construir dos
    diseños inconexos.
-   Warp pequeño inicialmente (probablemente 8 threads) para facilitar
    comprensión y depuración.
-   Mandelbrot permite comenzar sin grandes requisitos de memoria
    externa.

------------------------------------------------------------------------

## 27. Decisiones todavía pendientes

### ISA

-   formatos binarios exactos de instrucción;
-   distribución definitiva de opcodes;
-   tamaño exacto de inmediatos;
-   encoding de branches;
-   semántica exacta de flags;
-   si `CMP` usa flags o predicados;
-   direccionamiento exacto de `LOAD/STORE`;
-   mecanismo definitivo para constantes grandes;
-   semántica final de `MULFX`;
-   comportamiento formal de overflow;
-   instrucciones lógicas y shifts necesarias;
-   encoding y semántica final de extensiones GPU.

### Fixed-point

-   mantener Q16.16 o utilizar más bits fraccionales;
-   política exacta de redondeo/truncado.

### MiniCPU

-   microarquitectura exacta de la CPU multiciclo;
-   latencias iniciales;
-   diseño exacto del pipeline posterior;
-   forwarding y manejo de hazards.

### MiniGPU

-   warp width definitivo;
-   número de warps residentes;
-   número de lanes físicas;
-   relación warp width / execution width;
-   organización física del register file;
-   número y organización de bancos;
-   operand collectors;
-   pipelines funcionales;
-   política exacta del warp scheduler;
-   reconvergencia general;
-   instrucciones de máscaras;
-   shared memory;
-   cachés;
-   latencias de memoria.

### FPGA

-   placa/FPGA objetivo;
-   frecuencia objetivo;
-   uso de DSPs para multiplicación;
-   framebuffer;
-   salida VGA/HDMI;
-   necesidad o no de RAM externa.

------------------------------------------------------------------------

## 28. Próximo paso recomendado

Definir formalmente los **formatos de instrucción de 32 bits** antes de
programar la MiniCPU.

Como mínimo estudiar:

``` text
R-type      registro, registro, registro
I-type      registro, registro, inmediato
M-type      LOAD / STORE
B-type      branches
U-type      constantes grandes
```

y comprobar que permiten representar cómodamente:

-   la ISA base de la CPU;
-   `GETTID`;
-   las futuras extensiones SIMT/GPU;
-   32 registros;
-   inmediatos suficientemente útiles;
-   branches razonables.

Una vez congelada una primera versión de la MiniISA:

``` text
MiniISA v0.1
      ↓
assembler Python
      ↓
programa Mandelbrot
      ↓
MiniCPU funcional
      ↓
comparación bit a bit contra mandelbrot_fixed.iter
```

Ese será el primer punto en el que nuestro Mandelbrot deje de ejecutarse
directamente como código Python y empiece a ejecutarse sobre **una
máquina diseñada por nosotros**.
