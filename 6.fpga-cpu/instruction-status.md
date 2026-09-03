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
| `0x3E` | `TRAP`      |     OK      |  PARCIAL  |  PARCIAL  | El encoding existe, pero aún cae en el error genérico de opcode no implementado. |
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
| Simulador funcional |        29 | 1 (`TRAP`) |          0 |
| CPU FPGA            |        26 | 1 (`TRAP`) |          3 |

`TRAP` se considera parcial porque ambas implementaciones se detienen ante su
opcode, pero no existe todavía el estado arquitectónico específico que permita
distinguir un `TRAP` intencionado de un opcode sin implementar.

## Temas pendientes

### 1. Mantener cerrado el simulador funcional

El simulador implementa ya todas las instrucciones definidas salvo la semántica
arquitectónica formal de `TRAP`. Debe conservarse como referencia ejecutable y
ampliar sus pruebas cada vez que cambie la especificación.

### 2. Ampliar la CPU FPGA por grupos

Orden recomendado:

1. `TRAP` formal.
2. `MUL` y `MULFX`, comprobando el uso de los multiplicadores `MULT18X18D`.
3. `DIV` mediante una unidad iterativa multiciclo.

Después de cada grupo hay que repetir `apio build` y comprobar explícitamente
el margen sobre 120 MHz.

### 3. Formalizar los traps

Actualmente la FPGA distingue únicamente:

| Código | Error actual                |
|-------:|-----------------------------|
| `0x01` | Opcode no implementado.     |
| `0x02` | Acceso de memoria inválido. |

Falta definir al menos:

- instrucción `TRAP` explícita;
- encoding inválido, por ejemplo campos reservados distintos de cero;
- división por cero;
- fetch desalineado o fuera de memoria;
- posibilidad de conocer el PC de la instrucción que produjo el error.

También debe decidirse si un trap solo detiene la CPU o si en el futuro salta a
un vector de excepciones.

### 4. Mantener documentada la diferencia de memoria

Existe una diferencia arquitectónica que los tests simples no muestran:

- el simulador usa una memoria unificada de 2 MiB por defecto;
- la FPGA usa Harvard, con 16 KiB de programa y 16 KiB de datos;
- una dirección CPU de datos `0x00000004` aparece ante el monitor como
  `0x00100004`.

No se añadirá un modo Harvard al simulador: ningún programa del proyecto debe
depender de poder solapar código y datos. Los programas destinados al hardware
deben respetar por convención los 16 KiB disponibles en cada espacio.

El futuro runner de regresión usará siempre direcciones locales de datos en sus
casos de prueba. El backend FPGA sumará `0x00100000` únicamente al leer o
inicializar esa memoria mediante el monitor; el backend del simulador utilizará
la dirección local sin traducción.

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
