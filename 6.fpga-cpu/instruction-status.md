# Estado de implementación de MiniISA

Este documento resume el estado real de MiniISA v0.1 en septiembre de 2026.
La especificación de referencia es `../1.isa/isa.md`; si una implementación se
comporta de forma diferente, debe corregirse la implementación y no reinterpretar
la ISA a partir de ella.

## Leyenda

- OK Implementada y utilizable.
- PENDIENTE No implementada.
- PARCIAL Existe un comportamiento parcial o provisional.
- RESERVADO Opcode reservado; no forma parte de las instrucciones exigidas actualmente.

La columna «Ensamblador» indica si `miniisa_asm.py` puede generar el encoding.
No significa que el simulador o la FPGA puedan ejecutarlo todavía.

## Instrucciones definidas

| Opcode | Instrucción | Ensamblador | Simulador |   FPGA    | Observaciones                                                                    |
|-------:|-------------|:-----------:|:---------:|:---------:|----------------------------------------------------------------------------------|
| `0x00` | `NOP`       |     OK      |    OK     |    OK     | Retira una instrucción sin modificar estado salvo el PC.                         |
| `0x01` | `ADD`       |     OK      |    OK     |    OK     | Suma de 32 bits con wrap.                                                        |
| `0x02` | `SUB`       |     OK      |    OK     |    OK     | Resta de 32 bits con wrap.                                                       |
| `0x03` | `MULFX`     |     OK      |    OK     | PENDIENTE | Multiplicación signed Q16.16.                                                    |
| `0x04` | `AND`       |     OK      |    OK     |    OK     | AND bit a bit.                                                                   |
| `0x05` | `OR`        |     OK      |    OK     |    OK     | OR bit a bit.                                                                    |
| `0x06` | `XOR`       |     OK      |    OK     |    OK     | XOR bit a bit.                                                                   |
| `0x07` | `SHL`       |     OK      |    OK     |    OK     | Usa los cinco bits bajos de `Rb`.                                                |
| `0x08` | `SHR`       |     OK      |    OK     |    OK     | Desplazamiento lógico; usa `Rb[4:0]`.                                            |
| `0x09` | `SAR`       |     OK      |    OK     |    OK     | Desplazamiento aritmético; usa `Rb[4:0]`.                                        |
| `0x0A` | `MUL`       |     OK      |    OK     | PENDIENTE | Conserva los 32 bits bajos del producto.                                         |
| `0x0C` | `DIV`       |     OK      |    OK     | PENDIENTE | Signed y hacia cero; división por cero debe provocar trap.                       |
| `0x10` | `MOVI`      |     OK      |    OK     |    OK     | Extensión de signo de `imm16`.                                                   |
| `0x11` | `ADDI`      |     OK      |    OK     |    OK     | Inmediato con extensión de signo.                                                |
| `0x12` | `ANDI`      |     OK      |    OK     |    OK     | Inmediato con extensión de ceros.                                                |
| `0x13` | `ORI`       |     OK      |    OK     |    OK     | Inmediato con extensión de ceros.                                                |
| `0x14` | `XORI`      |     OK      |    OK     |    OK     | Inmediato con extensión de ceros.                                                |
| `0x15` | `LOAD`      |     OK      |    OK     |    OK     | Palabra de 32 bits alineada.                                                     |
| `0x16` | `STORE`     |     OK      |    OK     |    OK     | Palabra de 32 bits alineada.                                                     |
| `0x17` | `MOVHI`     |     OK      |    OK     |    OK     | Escribe `imm16 << 16`.                                                           |
| `0x20` | `BEQ`       |     OK      |    OK     |    OK     | Branch relativo a la instrucción siguiente.                                      |
| `0x21` | `BNE`       |     OK      |    OK     |    OK     | Branch relativo a la instrucción siguiente.                                      |
| `0x22` | `BLT`       |     OK      |    OK     |    OK     | Comparación signed.                                                              |
| `0x23` | `BGE`       |     OK      |    OK     |    OK     | Comparación signed.                                                              |
| `0x24` | `BLTU`      |     OK      |    OK     |    OK     | Comparación unsigned.                                                            |
| `0x25` | `BGEU`      |     OK      |    OK     |    OK     | Comparación unsigned.                                                            |
| `0x2F` | `BRA`       |     OK      |    OK     |    OK     | Offset signed de 26 bits, expresado en palabras.                                 |
| `0x30` | `GETTID`    |     OK      |    OK     |    OK     | En MiniCPU escribe cero; en MiniGPU será el ID del thread.                       |
| `0x3E` | `TRAP`      |     OK      |    OK     |    OK     | Detiene la CPU con error explícito y conserva su PC.                             |
| `0x3F` | `HALT`      |     OK      |    OK     |    OK     | Detiene la ejecución después de retirar la instrucción.                          |

## Opcodes reservados

Estos opcodes tienen nombre o espacio asignado, pero no poseen todavía una
semántica exigible en MiniISA v0.1.

|      Opcode | Nombre o rango | Ensamblador | Situación                                                                                      |
|------------:|----------------|:-----------:|------------------------------------------------------------------------------------------------|
|      `0x0B` | `MULHI`        |     OK      | Reservada. El ensamblador permite emitirla, pero ninguna CPU debe asumir todavía su semántica. |
|      `0x0D` | `DIVU`         |     OK      | Reservada.                                                                                     |
|      `0x0E` | `REM`          |     OK      | Reservada.                                                                                     |
|      `0x0F` | `REMU`         |     OK      | Reservada.                                                                                     |
| `0x18–0x1F` | RESERVADO      |  PENDIENTE  | Reservadas para inmediatos o memoria.                                                          |
| `0x26–0x2E` | RESERVADO      |  PENDIENTE  | Reservadas para control de flujo.                                                              |
|      `0x31` | `GETLANE`      |  PENDIENTE  | Reservada para GPU.                                                                            |
|      `0x32` | `GETWARP`      |  PENDIENTE  | Reservada para GPU.                                                                            |
|      `0x33` | `BAR`          |  PENDIENTE  | Reservada para GPU.                                                                            |
| `0x34–0x3D` | RESERVADO      |  PENDIENTE  | Reservadas para GPU.                                                                           |

Que el ensamblador acepte `MULHI`, `DIVU`, `REM` y `REMU` antes de que su
semántica esté definida es una decisión provisional. Sería más seguro
rechazarlas por defecto o exigir una opción explícita para opcodes
experimentales.

## Resumen numérico

Contando las 30 instrucciones con nombre y semántica definida o parcialmente
asignada en la tabla principal:

| Implementación      | Completas |  Parciales | Pendientes |
|---------------------|----------:|-----------:|-----------:|
| Ensamblador         |        30 |          0 |          0 |
| Simulador funcional |        30 |          0 |          0 |
| CPU FPGA            |        27 |          0 |          3 |

Los errores detienen la CPU y conservan el código y PC de la instrucción que
los produjo. No existen vector, handler ni reanudación.

## Temas pendientes

### 1. Mantener cerrado el simulador funcional

El simulador implementa todas las instrucciones definidas y su estado de error.
Debe conservarse como referencia ejecutable y ampliar sus pruebas cada vez que
cambie la especificación.

### 2. Ampliar la CPU FPGA por grupos

Orden recomendado:

1. `MUL` y `MULFX`, comprobando el uso de los multiplicadores `MULT18X18D`.
2. `DIV` mediante una unidad iterativa multiciclo.

Después de cada grupo hay que repetir `apio build` y comprobar explícitamente
el margen sobre 120 MHz.

### 3. Formalizar los traps

El simulador y la FPGA distinguen:

| Código | Error actual                |
|-------:|-----------------------------|
| `0x01` | Opcode no implementado.     |
| `0x02` | Acceso de memoria inválido. |
| `0x03` | Instrucción `TRAP` explícita. |
| `0x04` | División por cero; reservado hasta implementar `DIV` en FPGA. |
| `0x05` | Opcode conocido con campos reservados inválidos. |

Ante un error, el PC vuelve a señalar la instrucción que lo produjo. `HALT`
continúa siendo una parada normal con `error = 0`. Un fetch o acceso de datos
inválido usa `0x02`. No hay vector de excepciones: el monitor inspecciona código
y PC después de la parada.

### 4. Mantener documentada la diferencia de memoria

El simulador, la CPU y el monitor usan el mismo mapa global. La FPGA EBR
respalda `0x00000000–0x00003fff` y `0x00100000–0x00103fff`; cualquier otra
dirección produce error. La FPGA SDRAM implementa 32 MiB continuos. Los tests
comunes usan solamente las dos ventanas presentes en ambas implementaciones y
el backend no traduce direcciones.

### 5. Crear tests diferenciales

El mismo binario debe ejecutarse en el simulador y en un testbench RTL. Al
terminar se deberían comparar:

- los 32 registros;
- PC final;
- memoria de datos modificada;
- número de instrucciones retiradas;
- estado y código de error.

Conviene usar pequeños programas ensamblados en lugar de escribir manualmente
las palabras hexadecimales en cada testbench.

### 6. Mejorar el control desde el monitor

El monitor ya permite `RUN`, `HALT`, `STEP`, `GET_STATUS`, `READ_REGISTER` y
`RESET_CPU`,
pero quedan decisiones importantes:

- comprobar `RESET_CPU` dentro del futuro runner de regresión hardware;
- comando para escribir el PC o elegir el punto de entrada;
- posible escritura de registros para depuración;
- hacer que `HALT` responda al solicitar la parada o solo cuando la CPU ya esté
  detenida;
- contador de instrucciones retiradas;
- exponer el PC de trap, además del PC siguiente.

### 7. Limpieza de la estructura de pruebas

`cpu_program_system.v` es un fixture de una etapa intermedia y no forma parte
del `top`. Se debe elegir entre:

- moverlo junto con `cpu_program_system_tb.v` a una carpeta de tests; o
- eliminar ambos si `cpu_tb.v` y `cpu_memory_map_tb.v` proporcionan ya toda la
  cobertura necesaria.

También conviene separar claramente RTL sintetizable, testbenches, programas
ASM y herramientas host cuando se confirme cómo incluir subdirectorios con
Apio.

### 8. Memoria necesaria para Mandelbrot

Una imagen de 320 × 240 ocupa 76 800 bytes usando un byte por píxel, muy por
encima de los 16 KiB actuales de RAM de datos. Antes del Mandelbrot completo hay
que decidir entre:

- renderizado por bloques o líneas y descarga progresiva;
- framebuffer externo en SDRAM;
- salida directa hacia vídeo o streaming;
- una representación más compacta si solo se necesitan pocos niveles.

### 9. Evolución posterior hacia MiniGPU

Una vez estable y comprobada la MiniCPU escalar quedarán fuera de esta etapa:

- definición de `GETLANE`, `GETWARP` y `BAR`;
- lanes y warps;
- banco de registros vectorial;
- scheduler y máscaras de ejecución;
- semántica de finalización de threads;
- pipeline, únicamente después de medir la CPU multiciclo completa.

## Criterio de finalización de la MiniCPU escalar

La etapa escalar puede considerarse completa cuando:

1. todas las instrucciones definidas pasan tests en el simulador;
2. la FPGA produce los mismos resultados mediante tests diferenciales;
3. traps y encodings inválidos tienen una semántica documentada;
4. el monitor puede reiniciar, cargar, ejecutar y diagnosticar la CPU;
5. el diseño integrado cumple timing a 120 MHz;
6. un programa con bucles, memoria y aritmética RESERVADOprevio a MandelbrotRESERVADO funciona
   tanto en simulación como en la placa.
