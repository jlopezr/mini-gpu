# MiniCPU → MiniGPU

## 1. Objetivo

El objetivo del proyecto es construir una arquitectura gráfica sencilla desde
cero y comprender cada capa que interviene en su ejecución:

1. definir una ISA escalar pequeña, MiniISA;
2. ejecutar programas de esa ISA en una MiniCPU funcional;
3. convertir la CPU en una implementación temporal y después segmentada;
4. ampliar la microarquitectura con ejecución SIMT hasta obtener una MiniGPU;
5. implementar progresivamente el diseño en HDL sobre FPGA.

Mandelbrot es el workload conductor. Es pequeño, paralelizable, fácil de
comprobar y exige aritmética, saltos, bucles y escrituras a memoria.

## 2. Principios de diseño

- La ISA describe el comportamiento visible para el programa; el pipeline, las
  latencias, los lanes y el scheduler pertenecen a la microarquitectura.
- MiniCPU y MiniGPU comparten la misma ISA base. La GPU añade recursos SIMT
  sin convertir las operaciones escalares en instrucciones vectoriales.
- `R0` está cableado a cero en todas las implementaciones: las lecturas devuelven
  cero y las escrituras se descartan. `R1`–`R31` son registros generales.
- Primero se valida el resultado funcional y después se modelan los ciclos y el
  rendimiento.
- Cada etapa debe poder compararse con un modelo de referencia anterior.
- El diseño favorece la claridad y la trazabilidad sobre la optimización
  prematura.

## 3. Flujo de referencia

```text
Mandelbrot float ────── referencia matemática y visual
                             │
Mandelbrot Q16.16 ───── golden model exacto
                             │
código MiniISA → MiniCPU → MiniGPU → RTL / FPGA
                             │
                             ▼
                           .iter → visor → PNG
```

El modelo de coma flotante permite juzgar la imagen ideal. El modelo fixed-point
define el resultado esperado de las implementaciones de MiniISA. Una diferencia
con el modelo float puede ser una consecuencia legítima de la cuantización; una
diferencia con el golden model fixed-point indica un error.

## 4. Aritmética fixed-point

La representación inicial es Q16.16 sobre palabras de 32 bits con signo:

```text
valor_real = entero_signed / 65536
```

La multiplicación específica `MULFX` calcula:

```text
producto = signed64(Ra) * signed64(Rb)
Rd       = low32(producto >> 16)
```

Las operaciones de 32 bits conservan los 32 bits bajos. Por tanto, el overflow
produce wrap módulo 2^32. El desplazamiento de `MULFX` es aritmético y trunca
hacia menos infinito para productos negativos, igual que el golden model Python
actual.

El formato Q16.16 permite representar el dominio de Mandelbrot y simplifica la
primera implementación. El número de bits fraccionales debería mantenerse como
parámetro interno cuando se experimente con precisión.

## 5. Resultados y formato `.iter`

Los motores de cálculo producen recuentos de iteraciones, no colores. El visor
transforma después esos valores en una imagen. Esto permite comparar resultados
píxel a píxel sin mezclar el cálculo con la paleta.

Formato binario `.iter`, en little-endian:

| Offset |                     Tamaño | Campo                           |
|-------:|---------------------------:|---------------------------------|
|      0 |                    4 bytes | magic ASCII `ITER`              |
|      4 |                    4 bytes | anchura, `uint32`               |
|      8 |                    4 bytes | altura, `uint32`                |
|     12 |                    4 bytes | máximo de iteraciones, `uint32` |
|     16 | `width × height × 2` bytes | iteraciones, `uint16` por píxel |

Los píxeles están almacenados por filas, de izquierda a derecha y de arriba
abajo.

En el flujo inicial de Mandelbrot, la MiniCPU usa un framebuffer de una
palabra de 32 bits por píxel en `0x00100000`. Tras la simulación,
`raw_to_iter.py` reduce cada valor a `uint16` y añade la cabecera `.iter`.

## 6. Etapas del proyecto

### 6.1. Modelos de referencia

- `0.mandelbrot/mandelbrot_float.py`: referencia matemática y visual.
- `0.mandelbrot/mandelbrot_fixed.py`: golden model Q16.16.
- `0.mandelbrot/view_iterations.py`: lector de `.iter` y generador de PNG.
- `0.mandelbrot/compare_iterations.py`: comparación de resultados.

### 6.2. MiniISA y herramientas

La especificación está en `1.isa/isa.md`. En la misma carpeta se encuentran el
ensamblador, programas de prueba y Mandelbrot ensamblado.

El ensamblador genera una palabra little-endian de 32 bits por instrucción y,
opcionalmente, un fichero hexadecimal textual.

### 6.3. MiniCPU funcional

`2.cpu-sim-func/minicpu_sim.py` implementa fetch, decode y execute sin modelar
tiempos internos. Su misión es validar la ISA y ejecutar Mandelbrot antes de
introducir complejidad temporal.

La memoria actual es byte-addressed y unificada para programa y datos. `LOAD` y
`STORE` transfieren palabras de 32 bits alineadas a cuatro bytes.

### 6.4. MiniCPU RTL y temporización

Ya existen implementaciones multiciclo de MiniCPU en FPGA, desde
`6.fpga-cpu` con memoria EBR hasta las variantes con SDRAM, vídeo y extensiones
de instrucciones. Sus latencias y contadores de ciclos permiten estudiar el
rendimiento y contrastar el resultado con el simulador funcional.

La segmentación de instrucciones, la detección de hazards y el forwarding
siguen siendo posibles evoluciones; no son requisitos para disponer de una
CPU RTL funcional ni para implementar SIMT.

### 6.5. Evolución SIMT

La MiniGPU ya ejecuta instrucciones escalares sobre varios threads de un warp.
`11.gpu-sim-func` proporciona el simulador funcional; `12.fpga-gpu` implementa
el SM con memoria EBR y `14.fpga-gpu-ram` y `17.fpga-gpu-ram-v2` lo integran
con SDRAM.

La ejecución SIMT incluye:

- estado de registros por thread y PC por warp;
- máscaras de lanes activas y vivas;
- planificación de warps;
- regiones y caminos pendientes de reconvergencia mediante `SSY`;
- barreras `BAR` y retirada de lanes mediante `EXIT`;
- identificación del thread mediante `GETTID`.

La configuración actual usa ocho warps de ocho lanes, con 64 threads residentes.
Estas cantidades son decisiones microarquitectónicas, no constantes de la ISA.
`GETLANE`, `GETWARP` y `GETWID` siguen siendo propuestas de ampliación.

### 6.6. HDL y FPGA

La implementación hardware ya existe: el RTL del repositorio está escrito en
Verilog y tiene como destino la ULX3S-85F. Hay diseños de CPU y GPU, memoria EBR
y SDRAM externa, monitor UART y variantes de CPU con salida HDMI.

La validación combina simuladores funcionales, testbenches RTL, síntesis,
análisis de timing y pruebas en placa. El estado de validación de cada variante
se documenta en su carpeta; sintetizar un diseño no equivale a haberlo probado
físicamente. Las restricciones de RAM, DSP, frecuencia y puertos del banco de
registros condicionan la microarquitectura.

## 7. Estado actual

- Los modelos float y Q16.16 existen.
- MiniISA tiene especificación, ensamblador y programas de prueba y Mandelbrot.
  La ISA vigente incorpora extensiones posteriores a la v0.1 original.
- Existen simuladores funcionales de MiniCPU y MiniGPU, además de
  implementaciones RTL de ambas arquitecturas.
- SIMT, reconvergencia, barreras y retirada de lanes ya están implementados.
- `R0` vale siempre cero en todas las implementaciones; no es una decisión abierta.
- Las operaciones lógicas, los shifts y la semántica de `MULHI`, `DIVU`, `REM`
  y `REMU` están definidos. La carpeta `21.fpga-cpu-hdmi-alu` incorpora la
  familia ALU completa y los desplazamientos inmediatos en la CPU RTL.
- Hay variantes con accesos de 8 y 16 bits, llamadas, SDRAM, UART y vídeo.
  El repertorio de extensiones disponible depende de la implementación.
- El framebuffer puede convertirse al formato `.iter` común.
- `x.cpu-tests` reúne pruebas comunes para contrastar simuladores y backends FPGA.

## 8. Decisiones abiertas

### ISA

- Decidir qué propuestas de `propuesta-v0.2.md` y `propuesta-v0.3.md` se adoptan
  y distinguirlas del repertorio vigente, incluida su compatibilidad binaria.
- Completar los contratos pendientes de las nuevas extensiones, especialmente
  los saltos indirectos divergentes en SIMT.
- Decidir si se amplía el mecanismo actual de parada con error hacia excepciones
  con vector y recuperación. `TRAP` y los errores de encoding ya están definidos.
- Evaluar identificadores adicionales y operaciones de voto o intercambio entre lanes.

### Microarquitectura

- Evaluar pipeline, forwarding y política de hazards de MiniCPU.
- Medir cambios en la anchura de warp, lanes físicos, warps residentes y banco
  de registros de MiniGPU respecto a la configuración existente.
- Optimizar dependencias, scheduler y unidades funcionales sin alterar la
  semántica SIMT ya implementada.
- Mejorar la jerarquía de memoria y el rendimiento de las transferencias.

### FPGA

- Mejorar frecuencia y uso de DSP/RAM sobre la ULX3S-85F.
- Completar las pruebas en placa pendientes de cada variante.
- Evolucionar la integración de GPU, memoria y vídeo a partir de los bloques existentes.

## 9. Próximo hito

El siguiente hito es consolidar la ISA vigente y su validación entre las
implementaciones existentes:

1. alinear la documentación del estado actual y separar las propuestas futuras;
2. mantener explícitas las capacidades de cada backend y cubrir las nuevas
   instrucciones y errores con pruebas diferenciales;
3. ejecutar Mandelbrot en los backends correspondientes y comparar su `.iter`
   bit a bit con el golden model Q16.16;
4. completar la validación RTL, de timing y en placa que falte en cada variante;
5. medir ciclos y cuellos de botella antes de elegir la siguiente optimización.
