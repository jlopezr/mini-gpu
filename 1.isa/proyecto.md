# MiniCPU → MiniGPU

## 1. Objetivo

El objetivo del proyecto es construir una arquitectura gráfica sencilla desde
cero y comprender cada capa que interviene en su ejecución:

1. definir una ISA escalar pequeña, MiniISA;
2. ejecutar programas de esa ISA en una MiniCPU funcional;
3. convertir la CPU en una implementación temporal y después segmentada;
4. ampliar la microarquitectura con ejecución SIMT hasta obtener una MiniGPU;
5. implementar progresivamente el diseño en VHDL sobre FPGA.

Mandelbrot es el workload conductor. Es pequeño, paralelizable, fácil de
comprobar y exige aritmética, saltos, bucles y escrituras a memoria.

## 2. Principios de diseño

- La ISA describe el comportamiento visible para el programa; el pipeline, las
  latencias, los lanes y el scheduler pertenecen a la microarquitectura.
- MiniCPU y MiniGPU ejecutarán la misma ISA base. La GPU añadirá recursos SIMT
  sin convertir las operaciones escalares en instrucciones vectoriales.
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
código MiniISA → MiniCPU → MiniGPU → VHDL
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

Durante la ejecución, la MiniCPU usa provisionalmente un framebuffer de una
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

### 6.4. MiniCPU temporal y segmentada

La siguiente CPU debe asignar latencias explícitas a las unidades funcionales y
producir el mismo estado arquitectónico que el simulador funcional. Después se
añadirá pipeline, junto con la detección de hazards, stalls y, si resulta útil,
forwarding.

### 6.5. Evolución SIMT

La MiniGPU mantendrá instrucciones escalares y ejecutará una instrucción sobre
varios threads de un warp. Cada thread tendrá su propio estado arquitectónico;
la microarquitectura decidirá cuántos lanes físicos y warps residentes existen.

Los elementos previstos son:

- identificadores de thread, lane y warp;
- registro físico organizado por lanes y warps;
- máscara de threads activos;
- scoreboard para dependencias;
- warp scheduler;
- reconvergencia de control;
- pipelines funcionales compartidos.

Un warp inicial de ocho threads es un buen punto de partida didáctico, pero no
forma parte todavía de la ISA.

### 6.6. VHDL y FPGA

La implementación VHDL debe llegar después de estabilizar el comportamiento en
los simuladores. El orden previsto es CPU simple, CPU segmentada y extensión
SIMT. Las restricciones de la FPGA —RAM, DSP, frecuencia y puertos del register
file— podrán cambiar la microarquitectura sin alterar la ISA.

## 7. Estado actual

- Los modelos float y Q16.16 existen.
- MiniISA v0.1 tiene encoding, ensamblador y programa Mandelbrot.
- Existe una MiniCPU funcional capaz de ejecutar el subconjunto que necesita
  Mandelbrot.
- El framebuffer puede convertirse al formato `.iter` común.
- La temporización, el pipeline, SIMT y VHDL son etapas posteriores.

## 8. Decisiones abiertas

### ISA

- Implementar en el simulador las operaciones lógicas y los shifts ya definidos,
  y decidir la semántica de `MULHI`, `DIVU`, `REM` y `REMU`, que siguen
  reservadas aunque el ensamblador reconoce sus mnemónicos.
- Definir formalmente excepciones, `TRAP` y encodings inválidos.
- Decidir si `R0` seguirá siendo un registro general o será constante cero.
- Cerrar la semántica y el encoding de las extensiones SIMT.

### Microarquitectura

- Latencias, pipeline, forwarding y política de hazards de MiniCPU.
- Anchura de warp, lanes físicos, warps residentes y organización del register
  file de MiniGPU.
- Scoreboard, scheduler, máscaras y reconvergencia.
- Jerarquía y latencias de memoria.

### FPGA

- Placa objetivo, frecuencia y uso de bloques DSP/RAM.
- Salida de vídeo y ubicación final del framebuffer.
- Necesidad de memoria externa.

## 9. Próximo hito

El siguiente hito es convertir la MiniCPU funcional en referencia ejecutable de
toda MiniISA v0.1:

1. completar en el simulador las instrucciones marcadas como definidas;
2. añadir pruebas unitarias por instrucción y por error arquitectónico;
3. ejecutar Mandelbrot;
4. comparar su `.iter` bit a bit con el golden model Q16.16;
5. comenzar el simulador temporal sólo cuando esa comparación sea estable.
