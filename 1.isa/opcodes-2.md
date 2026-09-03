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

- decoder sencillo;
- direccionamiento de instrucciones sencillo;
- adecuado para VHDL;
- permite una ISA tipo RISC;
- evita inicialmente instrucciones de longitud variable.

### Registros

**32 registros arquitectónicos por thread:**

```text
R0 ... R31
```

Cada registro tiene:

```text
32 bits
```

Por tanto, cada identificador de registro necesita **5 bits**.

### Direcciones

Espacio de direcciones previsto:

```text
32 bits
```

### Opcode

La ISA utilizará un opcode de:

```text
6 bits
```

Esto permite un máximo de:

```text
64 opcodes
```

Organización general acordada:

| Rango | Prefijo | Uso |
|---|---|---|
| `0x00–0x0F` | `00xxxx` | ALU / aritmética / lógica |
| `0x10–0x1F` | `01xxxx` | Inmediatos / memoria |
| `0x20–0x2F` | `10xxxx` | Control de flujo |
| `0x30–0x3F` | `11xxxx` | Sistema / SIMT / GPU |

La zona `0x30–0x3F` queda deliberadamente reservada para permitir la evolución de MiniCPU hacia MiniGPU sin romper el encoding.

---

## 7. Formatos de instrucción

La MiniISA v0.1 utilizará tres formatos físicos principales.

### R-Type

Operaciones entre registros:

```text
31          26 25    21 20    16 15    11 10                0
┌─────────────┬────────┬────────┬────────┬────────────────────┐
│   opcode    │   Rd   │   Ra   │   Rb   │       extra        │
└─────────────┴────────┴────────┴────────┴────────────────────┘
      6           5         5         5            11
```

Uso inicial:

- operaciones ALU;
- multiplicación;
- división;
- shifts;
- futuras extensiones que necesiten tres registros.

Los 11 bits `extra` quedan reservados inicialmente.

### I-Type

Operaciones con inmediatos, memoria y branches condicionales:

```text
31          26 25    21 20    16 15                         0
┌─────────────┬────────┬────────┬─────────────────────────────┐
│   opcode    │    X   │    Y   │          imm16              │
└─────────────┴────────┴────────┴─────────────────────────────┘
      6           5         5               16
```

El significado de `X`, `Y` e `imm16` depende del opcode.

Ejemplos:

```asm
ADDI  R3, R2, 10
LOAD  R3, [R2 + 12]
STORE [R2 + 12], R3
BLT   R3, R7, loop
```

Para branches condicionales:

```text
X     = Ra
Y     = Rb
imm16 = offset relativo
```

### B-Type

Reservado inicialmente para `BRA`:

```text
31          26 25                                          0
┌─────────────┬─────────────────────────────────────────────┐
│   opcode    │               signed offset26               │
└─────────────┴─────────────────────────────────────────────┘
      6                         26
```

### Modelo de branches

La arquitectura **no tendrá FLAGS arquitectónicos ni instrucciones `CMP`/`CMPI`**.

Los saltos condicionales comparan directamente dos registros.

Por ejemplo:

```asm
BLT R3, R7, loop
```

equivale conceptualmente a:

```text
if signed(R3) < signed(R7):
    PC = target
else:
    PC = PC + 4
```

Convención preliminar:

```text
branch condicional:
target = PC + 4 + sign_extend(offset16) × 4

BRA:
target = PC + 4 + sign_extend(offset26) × 4
```

Los offsets se expresan en **instrucciones de 32 bits**, no en bytes.

---

## 8. MiniISA v0.1 — mapa de opcodes

### ALU / aritmética / lógica

| Opcode | Binario | Instrucción | Formato | Estado |
|---|---|---|---|---|
| `0x00` | `000000` | `NOP` | R | Definida |
| `0x01` | `000001` | `ADD` | R | Definida |
| `0x02` | `000010` | `SUB` | R | Definida |
| `0x03` | `000011` | `MULFX` | R | Definida |
| `0x04` | `000100` | `AND` | R | Definida |
| `0x05` | `000101` | `OR` | R | Definida |
| `0x06` | `000110` | `XOR` | R | Definida |
| `0x07` | `000111` | `SHL` | R | Definida |
| `0x08` | `001000` | `SHR` | R | Definida |
| `0x09` | `001001` | `SAR` | R | Definida |
| `0x0A` | `001010` | `MUL` | R | Reservada |
| `0x0B` | `001011` | `MULHI` | R | Reservada |
| `0x0C` | `001100` | `DIV` | R | Definida |
| `0x0D` | `001101` | `DIVU` | R | Reservada |
| `0x0E` | `001110` | `REM` | R | Reservada |
| `0x0F` | `001111` | `REMU` | R | Reservada |

Para MiniISA v0.1 se implementará como mínimo `DIV` signed. `DIVU`, `REM` y `REMU` quedan reservadas para una ampliación posterior.

### Inmediatos / memoria

| Opcode | Binario | Instrucción | Formato | Estado |
|---|---|---|---|---|
| `0x10` | `010000` | `MOVI` | I | Definida |
| `0x11` | `010001` | `ADDI` | I | Definida |
| `0x12` | `010010` | `ANDI` | I | Definida |
| `0x13` | `010011` | `ORI` | I | Definida |
| `0x14` | `010100` | `XORI` | I | Definida |
| `0x15` | `010101` | `LOAD` | I | Definida |
| `0x16` | `010110` | `STORE` | I | Definida |
| `0x17` | `010111` | `MOVHI` | I | Definida |
| `0x18–0x1F` | — | — | — | Reservadas |

### Control de flujo

| Opcode | Binario | Instrucción | Formato | Estado |
|---|---|---|---|---|
| `0x20` | `100000` | `BEQ` | I | Definida |
| `0x21` | `100001` | `BNE` | I | Definida |
| `0x22` | `100010` | `BLT` | I | Definida |
| `0x23` | `100011` | `BGE` | I | Definida |
| `0x24` | `100100` | `BLTU` | I | Definida |
| `0x25` | `100101` | `BGEU` | I | Definida |
| `0x26–0x2E` | — | — | — | Reservadas |
| `0x2F` | `101111` | `BRA` | B | Definida |

### Sistema / SIMT / GPU

| Opcode | Binario | Instrucción | Formato | Estado |
|---|---|---|---|---|
| `0x30` | `110000` | `GETTID` | I/especial | Propuesta fuerte |
| `0x31` | `110001` | `GETLANE` | especial | Reservada GPU |
| `0x32` | `110010` | `GETWARP` | especial | Reservada GPU |
| `0x33` | `110011` | `BAR` | especial | Reservada GPU |
| `0x34–0x3D` | — | — | — | Reservadas GPU |
| `0x3E` | `111110` | `TRAP` | especial | Propuesta |
| `0x3F` | `111111` | `HALT` | especial | Definida |

### Inmediatos y constantes

Semántica preliminar:

```asm
MOVI Rd, imm16
```

```text
Rd = sign_extend(imm16)
```

Para constantes grandes:

```asm
MOVHI R3, 0x1234
ORI   R3, R3, 0x5678
```

resultado:

```text
R3 = 0x12345678
```

`ORI`, `ANDI` y `XORI` utilizarán previsiblemente el inmediato con **zero-extension**.

`ADDI` utilizará un inmediato signed con **sign-extension**.

La semántica exacta debe quedar congelada antes de escribir el assembler.

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
