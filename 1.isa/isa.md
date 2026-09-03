# MiniISA v0.1

Este documento es la especificación de la ISA usada por MiniCPU y la futura
MiniGPU. Cuando el código y este texto discrepen, la discrepancia debe tratarse
como un error; no se debe deducir la ISA exclusivamente del simulador.

## 1. Estado arquitectónico

| Elemento         | Definición                          |
|------------------|-------------------------------------|
| Palabra de datos | 32 bits                             |
| Instrucción      | 32 bits, longitud fija              |
| Registros        | 32 registros de 32 bits, `R0`–`R31` |
| PC               | 32 bits                             |
| Direcciones      | 32 bits, byte-addressed             |
| Orden de bytes   | little-endian                       |
| Opcode           | 6 bits                              |

En v0.1 todos los registros, incluido `R0`, son registros generales. Las
escrituras conservan los 32 bits bajos; el overflow hace wrap módulo 2^32. No
existen FLAGS, `CMP` ni delay slots.

## 2. Formatos de instrucción

### R-Type

```text
31          26 25    21 20    16 15    11 10                0
┌─────────────┬────────┬────────┬────────┬────────────────────┐
│   opcode    │   Rd   │   Ra   │   Rb   │       extra        │
└─────────────┴────────┴────────┴────────┴────────────────────┘
      6           5         5         5            11
```

`extra` debe ser cero en v0.1 y queda reservado para extensiones.

### I-Type

```text
31          26 25    21 20    16 15                         0
┌─────────────┬────────┬────────┬─────────────────────────────┐
│   opcode    │    X   │    Y   │           imm16             │
└─────────────┴────────┴────────┴─────────────────────────────┘
      6           5         5               16
```

El significado de `X`, `Y` e `imm16` depende de la instrucción:

| Familia            | X    | Y    | `imm16`                 |
|--------------------|------|------|-------------------------|
| ALU inmediata      | `Rd` | `Ra` | operando inmediato      |
| `LOAD`             | `Rd` | `Ra` | desplazamiento          |
| `STORE`            | `Rs` | `Ra` | desplazamiento          |
| Branch condicional | `Ra` | `Rb` | desplazamiento relativo |
| `GETTID`           | `Rd` | 0    | 0                       |

### B-Type

```text
31          26 25                                          0
┌─────────────┬─────────────────────────────────────────────┐
│   opcode    │               signed offset26               │
└─────────────┴─────────────────────────────────────────────┘
      6                         26
```

En v0.1 sólo `BRA` usa este formato.

## 3. Mapa de opcodes

Los dos bits altos del opcode separan cuatro familias:

| Rango       | Prefijo  | Uso                  |
|-------------|----------|----------------------|
| `0x00–0x0F` | `00xxxx` | ALU y aritmética     |
| `0x10–0x1F` | `01xxxx` | Inmediatos y memoria |
| `0x20–0x2F` | `10xxxx` | Control de flujo     |
| `0x30–0x3F` | `11xxxx` | Sistema y SIMT       |

### ALU y aritmética

| Opcode | Mnemónico | Operandos    | Semántica                         | Simulador |
|-------:|-----------|--------------|-----------------------------------|-----------|
| `0x00` | `NOP`     | —            | Sin efecto                        | Pendiente |
| `0x01` | `ADD`     | `Rd, Ra, Rb` | `Rd = Ra + Rb`                    | Sí        |
| `0x02` | `SUB`     | `Rd, Ra, Rb` | `Rd = Ra - Rb`                    | Sí        |
| `0x03` | `MULFX`   | `Rd, Ra, Rb` | multiplicación signed Q16.16      | Sí        |
| `0x04` | `AND`     | `Rd, Ra, Rb` | AND bit a bit                     | Pendiente |
| `0x05` | `OR`      | `Rd, Ra, Rb` | OR bit a bit                      | Pendiente |
| `0x06` | `XOR`     | `Rd, Ra, Rb` | XOR bit a bit                     | Pendiente |
| `0x07` | `SHL`     | `Rd, Ra, Rb` | desplazamiento lógico izquierdo   | Pendiente |
| `0x08` | `SHR`     | `Rd, Ra, Rb` | desplazamiento lógico derecho     | Pendiente |
| `0x09` | `SAR`     | `Rd, Ra, Rb` | desplazamiento aritmético derecho | Pendiente |
| `0x0A` | `MUL`     | `Rd, Ra, Rb` | 32 bits bajos de `Ra × Rb`        | Sí        |
| `0x0B` | `MULHI`   | `Rd, Ra, Rb` | Reservada                         | No        |
| `0x0C` | `DIV`     | `Rd, Ra, Rb` | división signed, hacia cero       | Sí        |
| `0x0D` | `DIVU`    | `Rd, Ra, Rb` | Reservada                         | No        |
| `0x0E` | `REM`     | `Rd, Ra, Rb` | Reservada                         | No        |
| `0x0F` | `REMU`    | `Rd, Ra, Rb` | Reservada                         | No        |

Para `SHL`, `SHR` y `SAR`, la cantidad de desplazamiento serán los cinco bits
bajos de `Rb`. Esta semántica debe incorporarse al simulador.

`MULFX` interpreta ambos operandos como signed Q16.16, forma un producto signed
de 64 bits, lo desplaza aritméticamente 16 bits a la derecha y escribe los 32
bits bajos. `DIV` interpreta ambos operandos como signed32 y trunca el cociente
hacia cero. La división por cero provoca un trap arquitectónico; hasta que éste
se formalice, el simulador termina con error.

### Inmediatos y memoria

|      Opcode | Mnemónico | Operandos       | Semántica                             | Simulador |
|------------:|-----------|-----------------|---------------------------------------|-----------|
|      `0x10` | `MOVI`    | `Rd, imm16`     | `Rd = sign_extend(imm16)`             | Sí        |
|      `0x11` | `ADDI`    | `Rd, Ra, imm16` | `Rd = Ra + sign_extend(imm16)`        | Sí        |
|      `0x12` | `ANDI`    | `Rd, Ra, imm16` | `Rd = Ra AND zero_extend(imm16)`      | Pendiente |
|      `0x13` | `ORI`     | `Rd, Ra, imm16` | `Rd = Ra OR zero_extend(imm16)`       | Sí        |
|      `0x14` | `XORI`    | `Rd, Ra, imm16` | `Rd = Ra XOR zero_extend(imm16)`      | Pendiente |
|      `0x15` | `LOAD`    | `Rd, Ra, imm16` | `Rd = mem32[Ra + sign_extend(imm16)]` | Sí        |
|      `0x16` | `STORE`   | `Rs, Ra, imm16` | `mem32[Ra + sign_extend(imm16)] = Rs` | Sí        |
|      `0x17` | `MOVHI`   | `Rd, imm16`     | `Rd = imm16 << 16`                    | Sí        |
| `0x18–0x1F` | —         | —               | Reservadas                            | —         |

`LOAD` y `STORE` transfieren exactamente cuatro bytes. La dirección efectiva
hace wrap a 32 bits y debe estar alineada a cuatro bytes. Una dirección no
alineada o fuera de la memoria disponible provoca un trap arquitectónico; por
ahora el simulador termina con error.

Para formar una constante arbitraria de 32 bits:

```asm
MOVHI R1, 0x1234
ORI   R1, R1, 0x5678    ; R1 = 0x12345678
```

### Control de flujo

|      Opcode | Mnemónico | Operandos        | Condición                  | Simulador |
|------------:|-----------|------------------|----------------------------|-----------|
|      `0x20` | `BEQ`     | `Ra, Rb, target` | `Ra == Rb`                 | Sí        |
|      `0x21` | `BNE`     | `Ra, Rb, target` | `Ra != Rb`                 | Sí        |
|      `0x22` | `BLT`     | `Ra, Rb, target` | `signed(Ra) < signed(Rb)`  | Sí        |
|      `0x23` | `BGE`     | `Ra, Rb, target` | `signed(Ra) >= signed(Rb)` | Sí        |
|      `0x24` | `BLTU`    | `Ra, Rb, target` | `Ra < Rb`, unsigned        | Sí        |
|      `0x25` | `BGEU`    | `Ra, Rb, target` | `Ra >= Rb`, unsigned       | Sí        |
| `0x26–0x2E` | —         | —                | Reservadas                 | —         |
|      `0x2F` | `BRA`     | `target`         | Siempre                    | Sí        |

Los branches son relativos a la instrucción siguiente y expresan el offset en
palabras de 32 bits, no en bytes:

```text
branch condicional: target = PC + 4 + sign_extend(offset16) * 4
BRA:                 target = PC + 4 + sign_extend(offset26) * 4
```

El ensamblador calcula estos offsets al resolver labels.

### Sistema y SIMT

|      Opcode | Mnemónico | Operandos | Estado                                 |
|------------:|-----------|-----------|----------------------------------------|
|      `0x30` | `GETTID`  | `Rd`      | Definida; pendiente en el simulador    |
|      `0x31` | `GETLANE` | `Rd`      | Reservada para GPU                     |
|      `0x32` | `GETWARP` | `Rd`      | Reservada para GPU                     |
|      `0x33` | `BAR`     | —         | Reservada para GPU                     |
| `0x34–0x3D` | —         | —         | Reservadas para GPU                    |
|      `0x3E` | `TRAP`    | —         | Encoding asignado; semántica pendiente |
|      `0x3F` | `HALT`    | —         | Definida e implementada                |

`GETTID` escribe en `Rd` el identificador lineal del work-item. En MiniCPU vale
cero. En MiniGPU será distinto para cada thread y permitirá que un único kernel
calcule diferentes píxeles. Su encoding es I-Type con `X = Rd`, `Y = 0` e
`imm16 = 0`.

`HALT` detiene la MiniCPU. Su uso dentro de un kernel SIMT se definirá junto con
el modelo de finalización de threads.

## 4. Programa binario

Un programa es una secuencia de palabras de instrucción de 32 bits almacenadas
en little-endian. La dirección inicial actual es `0x00000000`; no hay cabecera ni
tabla de símbolos en el fichero `.bin`.

El fichero `.hex` auxiliar contiene una palabra hexadecimal por línea en el
mismo orden de ejecución y está destinado a inspección y carga en herramientas
de hardware.

## 5. Sintaxis del ensamblador

- Los registros se escriben `R0`–`R31` sin distinguir mayúsculas.
- Los operandos se separan mediante comas.
- Los enteros aceptan la sintaxis de Python (`123`, `-4`, `0xFF`).
- Los comentarios comienzan por `;` o `#`.
- Un label puede ocupar su propia línea o preceder a una instrucción.

Ejemplo:

```asm
start:
    MOVI R1, 10
    MOVI R2, 20

loop:
    ADDI R1, R1, 1
    BLT  R1, R2, loop
    HALT
```

La sintaxis de memoria actual expone los tres campos del encoding:

```asm
LOAD  Rd, Ra, offset
STORE Rs, Ra, offset
```

## 6. Conformidad y evolución

Una implementación conforme debe producir el comportamiento descrito para toda
instrucción marcada como definida. Encontrar un opcode reservado o un encoding
inválido debe provocar un trap; mientras no exista el mecanismo de traps, el
simulador puede detenerse con un error diagnóstico.

Los opcodes `0x30–0x3F` permiten añadir SIMT sin romper programas MiniCPU. Los
detalles físicos —número de lanes, ancho de warp, register file, latencias,
pipeline y scheduler— no forman parte de la ISA.
