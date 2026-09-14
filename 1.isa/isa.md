# MiniISA v0.1

Este documento es la especificación de la ISA usada por MiniCPU y MiniGPU. Cuando el código y este texto discrepen, la discrepancia debe tratarse
como un error; no se debe deducir la ISA exclusivamente del simulador.

Este documento describe **MiniISA v0.1 vigente**. La implementación escalar más
completa, y referencia para su repertorio y encoding, es
[`21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu/README.md). También se documenta
el repertorio SIMT de MiniGPU, que la CPU escalar no ejecuta.
[`propuesta-v0.2.md`](propuesta-v0.2.md) y
[`propuesta-v0.3.md`](propuesta-v0.3.md) son propuestas de evolución: sus mapas
no sustituyen al definido aquí.

### Capabilities de instrucciones

Una capability identifica una extensión que una implementación puede ofrecer.
La ISA fija su encoding y comportamiento; cada backend declara cuáles tiene.
Las extensiones son independientes y pueden incorporarse a otras versiones.

| Capability        | Opcodes o variantes     | Instrucciones                                            |
|-------------------|-------------------------|----------------------------------------------------------|
| `subword_memory`  | `0x18–0x1D`             | `LOADB`, `LOADUB`, `STOREB`, `LOADH`, `LOADUH`, `STOREH` |
| `calls`           | `0x2C–0x2E`             | `JAL`, `JALR`, `JR`                                      |
| `alu_extended`    | `0x0B`, `0x0D–0x0F`     | `MULHI`, `DIVU`, `REM`, `REMU`                           |
| `shift_immediate` | `0x07–0x09`, bit 10 = 1 | `SHLI`, `SHRI`, `SARI`                                   |

En las tablas de opcodes, **Base** significa que no se requiere una capability
adicional; no es el nombre de una capability del runner. Los desplazamientos
por registro pertenecen a la base, aunque sus variantes inmediatas sean opcionales.

Disponibilidad actual de las capabilities de instrucciones en MiniCPU:

| Implementación                     | `subword_memory` | `calls` | `alu_extended` | `shift_immediate` |
|------------------------------------|------------------|---------|----------------|-------------------|
| `6.fpga-cpu` / `ebr`               | —                | —       | —              | —                 |
| `10.fpga-cpu-ram` / `sdram`        | —                | —       | —              | —                 |
| `16.fpga-cpu-hdmi` / `hdmi`        | —                | —       | —              | —                 |
| `18.fpga-cpu-hdmi-bl8` / `bl8`     | —                | —       | —              | —                 |
| `19.fpga-cpu-hdmi-ls` / `subword`  | Sí               | Sí      | —              | —                 |
| `21.fpga-cpu-hdmi-alu` / `alu`     | Sí               | Sí      | Sí             | Sí                |
| `2.cpu-sim-func` / `cpu-simulator` | Sí               | Sí      | Sí             | Sí                |

Las declaraciones del runner están en
[`backends/fpga.py`](../x.tests/backends/fpga.py) y
[`backends/simulator.py`](../x.tests/backends/simulator.py); los casos usan
`requires` para indicar las capabilities necesarias y se omiten si faltan.
La versión de monitor identifica el bitstream y permite comprobarlo contra la
configuración del backend; no existe aquí una instrucción para consultar capabilities.

Sin una extensión de opcodes, ejecutarlos produce `ERROR_INVALID_OPCODE`.
Sin `shift_immediate`, el bit 10 sigue reservado y usarlo produce
`ERROR_INVALID_ENCODING`. Son extensiones aditivas, pero no fallan con el mismo error.

`R0=0` es obligatorio en todas las implementaciones y **no es una capability**:
`zero_register` dejó de existir tras el backport. `video`, `frame_capture` y
`serial` describen funciones de plataforma, sin opcodes propios. La reutilización
de resultados MUL/DIV solo afecta a los ciclos y tampoco tiene capability.
El repertorio SIMT se identifica por la arquitectura GPU; el runner no define
una capability llamada `simt`.

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

Las escrituras conservan los 32 bits bajos; el overflow hace wrap módulo 2^32.
No existen FLAGS, `CMP` ni delay slots.

### `R0` está cableado a cero

Las escrituras a `R0` se descartan y las lecturas valen siempre cero. Es una
regla de la ISA y **la cumplen todas las implementaciones**, MiniCPU y MiniGPU,
desde la 6 hasta la 21.

Hay 31 registros generales, `R1`–`R31`, y un registro cero, `R0`. Descartar una
escritura a `R0` no elimina los demás efectos de la instrucción: una carga debe
realizar el acceso y detectar sus errores, y `JALR R0, Ra, 0` debe saltar.

Las revisiones históricas permitían escribir `R0`. El backport corrigió esa
semántica en CPU y GPU y actualizó las versiones de monitor afectadas. Los
binarios que dependían de almacenar valores en `R0` requieren adaptación;
aquellos bitstreams antiguos no cumplen esta especificación vigente.

## 2. Formatos de instrucción

### R-Type

```text
31          26 25    21 20    16 15    11 10                0
┌─────────────┬────────┬────────┬────────┬────────────────────┐
│   opcode    │   Rd   │   Ra   │   Rb   │       extra        │
└─────────────┴────────┴────────┴────────┴────────────────────┘
      6           5         5         5            11
```

`extra` debe ser cero, con **una excepción**: en `SHL`, `SHR` y `SAR` el bit 10
significa «la cantidad es inmediata» y solo `extra[9:0]` está reservado. Ver
[§3, desplazamientos](#desplazamientos-con-cantidad-inmediata).

### I-Type

```text
31          26 25    21 20    16 15                         0
┌─────────────┬────────┬────────┬─────────────────────────────┐
│   opcode    │    X   │    Y   │           imm16             │
└─────────────┴────────┴────────┴─────────────────────────────┘
      6           5         5               16
```

El significado de `X`, `Y` e `imm16` depende de la instrucción:

| Familia             | X    | Y    | `imm16`                     |
|---------------------|------|------|-----------------------------|
| ALU inmediata       | `Rd` | `Ra` | operando inmediato          |
| `LOAD`              | `Rd` | `Ra` | desplazamiento              |
| `STORE`             | `Rs` | `Ra` | desplazamiento              |
| Branch condicional  | `Ra` | `Rb` | desplazamiento relativo     |
| `GETTID`            | `Rd` | 0    | 0                           |
| `MOVI`, `MOVHI`     | `Rd` | 0    | constante                   |
| Cargas de 8/16 bits | `Rd` | `Ra` | desplazamiento en bytes     |
| Stores de 8/16 bits | `Rs` | `Ra` | desplazamiento en bytes     |
| `JAL`               | `Rd` | 0    | offset relativo en palabras |
| `JALR`              | `Rd` | `Ra` | desplazamiento en palabras  |
| `JR`                | 0    | `Ra` | 0                           |

Los ceros de esta tabla son campos reservados, no lecturas de `R0`.
`MOVI` y `MOVHI` son las excepciones a la fila genérica de ALU inmediata.

### B-Type

```text
31          26 25                                          0
┌─────────────┬─────────────────────────────────────────────┐
│   opcode    │               signed offset26               │
└─────────────┴─────────────────────────────────────────────┘
      6                         26
```

`BRA` y la instrucción SIMT `SSY` usan este formato.

## 3. Mapa de opcodes

Los dos bits altos del opcode separan cuatro familias:

| Rango       | Prefijo  | Uso                  |
|-------------|----------|----------------------|
| `0x00–0x0F` | `00xxxx` | ALU y aritmética     |
| `0x10–0x1F` | `01xxxx` | Inmediatos y memoria |
| `0x20–0x2F` | `10xxxx` | Control de flujo     |
| `0x30–0x3F` | `11xxxx` | Sistema y SIMT       |

### ALU y aritmética

| Opcode | Mnemónico | Operandos    | Semántica                         | Capability     |
|-------:|-----------|--------------|-----------------------------------|----------------|
| `0x00` | `NOP`     | —            | Sin efecto                        | Base           |
| `0x01` | `ADD`     | `Rd, Ra, Rb` | `Rd = Ra + Rb`                    | Base           |
| `0x02` | `SUB`     | `Rd, Ra, Rb` | `Rd = Ra - Rb`                    | Base           |
| `0x03` | `MULFX`   | `Rd, Ra, Rb` | multiplicación signed Q16.16      | Base           |
| `0x04` | `AND`     | `Rd, Ra, Rb` | AND bit a bit                     | Base           |
| `0x05` | `OR`      | `Rd, Ra, Rb` | OR bit a bit                      | Base           |
| `0x06` | `XOR`     | `Rd, Ra, Rb` | XOR bit a bit                     | Base           |
| `0x07` | `SHL`     | `Rd, Ra, Rb` | desplazamiento lógico izquierdo   | Base           |
| `0x08` | `SHR`     | `Rd, Ra, Rb` | desplazamiento lógico derecho     | Base           |
| `0x09` | `SAR`     | `Rd, Ra, Rb` | desplazamiento aritmético derecho | Base           |
| `0x0A` | `MUL`     | `Rd, Ra, Rb` | 32 bits bajos de `Ra × Rb`        | Base           |
| `0x0B` | `MULHI`   | `Rd, Ra, Rb` | 32 bits altos, **signed**         | `alu_extended` |
| `0x0C` | `DIV`     | `Rd, Ra, Rb` | división signed, hacia cero       | Base           |
| `0x0D` | `DIVU`    | `Rd, Ra, Rb` | división unsigned                 | `alu_extended` |
| `0x0E` | `REM`     | `Rd, Ra, Rb` | resto signed, signo del dividendo | `alu_extended` |
| `0x0F` | `REMU`    | `Rd, Ra, Rb` | resto unsigned                    | `alu_extended` |

**La familia ALU queda completa.** No hay ningún opcode libre entre `0x00` y
`0x0F`, y cualquier operación aritmética nueva tendrá que buscar hueco en otra
familia o entrar por una codificación extendida.

#### Desplazamientos con cantidad inmediata

Para `SHL`, `SHR` y `SAR` por registro, la cantidad son los cinco bits bajos
del contenido de `Rb`. Desde
`21.fpga-cpu-hdmi-alu`, el **bit 10** del campo `extra` indica que la cantidad
es inmediata y viaja en los cinco bits del propio campo `Rb`:

```text
31          26 25    21 20    16 15    11 10   9              0
┌─────────────┬────────┬────────┬────────┬───┬────────────────┐
│   opcode    │   Rd   │   Ra   │ Rb/imm │ I │       0        │
└─────────────┴────────┴────────┴────────┴───┴────────────────┘
                                            ↑ 1 = cantidad inmediata
```

Esta variante requiere `shift_immediate` y no consume opcodes nuevos. Los
mnemónicos del ensamblador son `SHLI`, `SHRI` y `SARI`. Con la capability,
`extra = 0x400` es válido; cualquier bit de `extra[9:0]` puesto produce
`ERROR_INVALID_ENCODING`. Sin ella, los once bits de `extra` deben ser cero.

#### Multiplicación y división

`MULFX` interpreta ambos operandos como signed Q16.16, forma un producto signed
de 64 bits, lo desplaza aritméticamente 16 bits a la derecha y escribe los 32
bits bajos.

`MUL` y `MULHI` son las dos mitades del **mismo producto signed de 64 bits**:
`MUL` escribe `(Ra × Rb)[31:0]` y `MULHI` escribe `(Ra × Rb)[63:32]`, con ambos
operandos interpretados como signed32. Los bits bajos no dependen del signo, así
que `MUL` sirve igual para operandos unsigned; los altos sí, y ahí la ISA toma
partido.

No hay `MULHU`. La mitad alta unsigned se obtiene sumando, módulo 2^32,
`(Ra[31] ? Rb : 0) + (Rb[31] ? Ra : 0)` al resultado de `MULHI`.
La conversión inversa resta esa misma corrección.

`DIV` y `REM` interpretan ambos operandos como signed32; `DIVU` y `REMU`, como
unsigned32. El cociente signed se trunca hacia cero, y el resto acompaña a esa
división, de modo que lleva el **signo del dividendo**:

```text
REM(a, b) = a - DIV(a, b) * b

 7 rem  2 =  1        -7 rem  2 = -1
 7 rem -2 =  1        -7 rem -2 = -1
```

El caso `-2^31 / -1` no cabe en signed32: el cociente hace wrap a `0x80000000`
y el resto es cero.

La división por cero detiene la ejecución con `ERROR_DIVISION_BY_ZERO` en las
cuatro instrucciones, incluidas `REM` y `REMU`. No hay vector de excepción ni
recuperación arquitectónica.

### Inmediatos y memoria

|      Opcode | Mnemónico | Operandos       | Semántica                             | Capability       |
|------------:|-----------|-----------------|---------------------------------------|------------------|
|      `0x10` | `MOVI`    | `Rd, imm16`     | `Rd = sign_extend(imm16)`             | Base             |
|      `0x11` | `ADDI`    | `Rd, Ra, imm16` | `Rd = Ra + sign_extend(imm16)`        | Base             |
|      `0x12` | `ANDI`    | `Rd, Ra, imm16` | `Rd = Ra AND zero_extend(imm16)`      | Base             |
|      `0x13` | `ORI`     | `Rd, Ra, imm16` | `Rd = Ra OR zero_extend(imm16)`       | Base             |
|      `0x14` | `XORI`    | `Rd, Ra, imm16` | `Rd = Ra XOR zero_extend(imm16)`      | Base             |
|      `0x15` | `LOAD`    | `Rd, Ra, imm16` | `Rd = mem32[Ra + sign_extend(imm16)]` | Base             |
|      `0x16` | `STORE`   | `Rs, Ra, imm16` | `mem32[Ra + sign_extend(imm16)] = Rs` | Base             |
|      `0x17` | `MOVHI`   | `Rd, imm16`     | `Rd = imm16 << 16`                    | Base             |
|      `0x18` | `LOADB`   | `Rd, Ra, imm16` | 8 bits, extensión con signo           | `subword_memory` |
|      `0x19` | `LOADUB`  | `Rd, Ra, imm16` | 8 bits, extensión con ceros           | `subword_memory` |
|      `0x1A` | `STOREB`  | `Rs, Ra, imm16` | escribe `Rs[7:0]`                     | `subword_memory` |
|      `0x1B` | `LOADH`   | `Rd, Ra, imm16` | 16 bits, extensión con signo          | `subword_memory` |
|      `0x1C` | `LOADUH`  | `Rd, Ra, imm16` | 16 bits, extensión con ceros          | `subword_memory` |
|      `0x1D` | `STOREH`  | `Rs, Ra, imm16` | escribe `Rs[15:0]`                    | `subword_memory` |
| `0x1E–0x1F` | —         | —               | Reservadas                            | —                |

Los seis accesos sub-palabra siguen el mapa de `propuesta-v0.2.md` §6 y
aparecieron en `19.fpga-cpu-hdmi-ls`. Quedan **dos opcodes libres** en esta
familia.

Todas las cargas y stores calculan `address = low32(Ra + sign_extend(imm16))`.
El desplazamiento está en bytes y admite `-32768..32767`.

| Tamaño  | Instrucciones               | Alineación                  |
|---------|-----------------------------|-----------------------------|
| 32 bits | `LOAD`, `STORE`             | Múltiplo de 4               |
| 16 bits | `LOADH`, `LOADUH`, `STOREH` | Múltiplo de 2               |
| 8 bits  | `LOADB`, `LOADUB`, `STOREB` | Cualquier dirección de byte |

Los accesos son little-endian. Las cargas signed extienden el signo hasta
32 bits y las unsigned extienden con ceros. Los stores escriben solo los bits
bajos correspondientes al tamaño y conservan los bytes vecinos.
Se valida el intervalo completo del acceso; una dirección desalineada o fuera
de la memoria disponible produce `ERROR_MEMORY_ACCESS`.

Para formar una constante arbitraria de 32 bits:

```asm
MOVHI R1, 0x1234
ORI   R1, R1, 0x5678    ; R1 = 0x12345678
```

### Control de flujo

|      Opcode | Mnemónico | Operandos        | Condición                  | Capability |
|------------:|-----------|------------------|----------------------------|------------|
|      `0x20` | `BEQ`     | `Ra, Rb, target` | `Ra == Rb`                 | Base       |
|      `0x21` | `BNE`     | `Ra, Rb, target` | `Ra != Rb`                 | Base       |
|      `0x22` | `BLT`     | `Ra, Rb, target` | `signed(Ra) < signed(Rb)`  | Base       |
|      `0x23` | `BGE`     | `Ra, Rb, target` | `signed(Ra) >= signed(Rb)` | Base       |
|      `0x24` | `BLTU`    | `Ra, Rb, target` | `Ra < Rb`, unsigned        | Base       |
|      `0x25` | `BGEU`    | `Ra, Rb, target` | `Ra >= Rb`, unsigned       | Base       |
| `0x26–0x2B` | —         | —                | Reservadas                 | —          |
|      `0x2C` | `JAL`     | `Rd, target`     | `Rd = PC+4`, relativo      | `calls`    |
|      `0x2D` | `JALR`    | `Rd, Ra, imm16`  | `Rd = PC+4`, a `Ra+imm*4`  | `calls`    |
|      `0x2E` | `JR`      | `Ra`             | a `Ra`, sin enlace         | `calls`    |
|      `0x2F` | `BRA`     | `target`         | Siempre                    | Base       |

`JAL`, `JALR` y `JR` requieren `calls` y usan I-Type, con los campos de §2.
Los desplazamientos de `JAL` y `JALR` son signed de 16 bits en palabras.
Tomando `PC` como la dirección de la instrucción y leyendo los operandos antes
de escribir el enlace, incluso cuando `Rd = Ra`:

```text
JAL:  target = low32(PC + 4 + sign_extend(imm16) * 4)
      Rd = low32(PC + 4); PC = target
JALR: target = low32(Ra + sign_extend(imm16) * 4) & 0xFFFFFFFC
      Rd = low32(PC + 4); PC = target
JR:   PC = Ra & 0xFFFFFFFC
```

`JR` conserva su opcode `0x2E` y es válido. Su efecto equivale a
`JALR R0, Ra, 0`. El ensamblador actual traduce `RET` a `JR R31`.
Por convención de software, `R31` es el registro de enlace y `R30` el puntero
de pila; el hardware no les da un tratamiento especial.
Estas instrucciones están implementadas en MiniCPU. Su incorporación a
MiniGPU requiere fijar el comportamiento de los destinos indirectos divergentes;
esta especificación no les atribuye soporte SIMT.

En los saltos indirectos el destino sale de un registro y puede venir
desalineado: se descartan los dos bits bajos en lugar de añadir una ruta de
error.

Los branches son relativos a la instrucción siguiente y expresan el offset en
palabras de 32 bits, no en bytes:

```text
branch condicional: target = PC + 4 + sign_extend(offset16) * 4
BRA:                 target = PC + 4 + sign_extend(offset26) * 4
```

El ensamblador calcula estos offsets al resolver labels.

### Sistema y SIMT

`GETTID`, `TRAP` y `HALT` pertenecen a la base. `SSY`, `BAR` y `EXIT`
son instrucciones de la arquitectura GPU, sin capability adicional en el runner.

|      Opcode | Mnemónico | Operandos | Estado                               |
|------------:|-----------|-----------|--------------------------------------|
|      `0x30` | `GETTID`  | `Rd`      | Implementada en MiniCPU y MiniGPU    |
|      `0x31` | `SSY`     | `label`   | Implementada en MiniGPU; B-Type      |
|      `0x32` | `BAR`     | —         | Implementada en MiniGPU              |
|      `0x33` | `EXIT`    | —         | Implementada en MiniGPU              |
| `0x34–0x3D` | —         | —         | Reservadas para GPU                  |
|      `0x3E` | `TRAP`    | —         | Parada explícita con estado de error |
|      `0x3F` | `HALT`    | —         | Definida e implementada              |

`GETTID` escribe en `Rd` el identificador lineal del thread residente. En
MiniCPU vale cero. En la MiniGPU actual vale `warp_id * warp_size + lane_id`
(0…63 con ocho warps de ocho lanes). Su encoding es I-Type con `X = Rd`,
`Y = 0` e `imm16 = 0`.

`SSY label` establece el punto de reconvergencia de una región SIMT. Usa
B-Type, con desplazamiento con signo en palabras relativo a la instrucción
siguiente, igual que `BRA`:

```text
join = PC + 4 + sign_extend(offset26) * 4
```

`SSY` no salta al punto de reconvergencia: registra la región y continúa en
`PC + 4`. Si se vuelve a ejecutar el `SSY` que abrió la región más interna,
se reutiliza esa región con el mismo destino.

`BAR` sincroniza los warps participantes del mismo `workgroup_id`. Exige que
participen todas las lanes vivas del warp: `active_mask != live_mask` produce
`ERROR_BARRIER`. Las operaciones de memoria anteriores deben completarse antes
de continuar tras la barrera.

`EXIT` retira permanentemente las lanes activas de `live_mask`. Cuando no
quedan lanes vivas, el warp termina y se vacían sus pilas REGION y PATH.
`BAR` y `EXIT` no tienen operandos: sus 26 bits bajos deben ser cero
(`X = 0`, `Y = 0`, `imm16 = 0`). Son instrucciones de MiniGPU; no se añaden
al repertorio implementado por la MiniCPU escalar.

`GETLANE` y `GETWARP` no están implementadas ni tienen opcode asignado en esta
versión. Su posible incorporación se describe en `propuesta-v0.2.md`.

`HALT` detiene la MiniCPU. En la MiniGPU actual retira las lanes activas con
la misma semántica que `EXIT`.

`TRAP` detiene la CPU con un error distinguible de `HALT`. El PC observable
queda en la dirección de `TRAP`. No salta a un vector y no puede reanudarse sin
reset. En MiniGPU provoca una parada global con error.

`NOP`, `TRAP` y `HALT` exigen sus 26 bits bajos a cero. Los campos marcados
como reservados deben ser cero. Un opcode soportado con
campos reservados distintos de cero produce `ERROR_INVALID_ENCODING`; un opcode
reservado o desconocido produce `ERROR_INVALID_OPCODE`. La única excepción es la
descrita arriba: en `SHL`, `SHR` y `SAR` el campo reservado es `extra[9:0]`
porque el bit 10 selecciona la cantidad inmediata.

## 4. Programa binario

Un programa es una secuencia de palabras de instrucción de 32 bits almacenadas
en little-endian. La dirección inicial actual es `0x00000000`; no hay cabecera ni
tabla de símbolos en el fichero `.bin`.

El fichero `.hex` auxiliar contiene una palabra hexadecimal por línea en el
orden de direcciones del binario y está destinado a inspección y carga en herramientas
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

`SHLI`, `SHRI` y `SARI` **no son opcodes**: son la forma de escribir `SHL`,
`SHR` y `SAR` con el bit de cantidad inmediata puesto. La cantidad va de 0 a 31
y el ensamblador rechaza cualquier otra en vez de truncarla:

```asm
SHLI R3, R2, 2      ; indice -> desplazamiento en bytes, sin gastar un MOVI
SHL  R3, R2, R4     ; la misma operacion con la cantidad en un registro
```

## 6. Conformidad y evolución

Una implementación conforme debe cumplir las reglas comunes, incluido `R0=0`,
el repertorio base de su arquitectura y todas las variantes de las capabilities
que declara. No necesita implementar las capabilities ausentes. Un opcode
definido pero no soportado no se convierte por ello en un hueco libre del mapa.

Un opcode reservado o no soportado produce `ERROR_INVALID_OPCODE`; un encoding
inválido de una instrucción soportada produce `ERROR_INVALID_ENCODING`.
En particular, sin `shift_immediate` el bit 10 de los shifts es reservado.
Estos errores detienen la ejecución; no existe un mecanismo de excepción con
vector y retorno.

Los opcodes `0x30–0x3F` permiten añadir SIMT sin romper programas MiniCPU. Los
detalles físicos —número de lanes, ancho de warp, register file, latencias,
pipeline y scheduler— no forman parte de la ISA.

### Nota de evolución: posible eliminación del opcode `JR`

Con `R0=0`, una revisión futura puede eliminar el opcode independiente de `JR`
y conservar el mnemónico como pseudoinstrucción del ensamblador:

```asm
JR Ra  -> JALR R0, Ra, 0
RET    -> JALR R0, R31, 0
```

La propuesta v0.2 conserva `JR` en `0x2E` y plantea esta alternativa como
evolución; la v0.3 sí elimina su opcode y adopta la pseudoinstrucción.
**MiniISA v0.1 vigente conserva `JR` y `0x2E` sigue ocupado.** Eliminarlo o
reasignarlo rompería los binarios que lo utilizan y requeriría una revisión
explícita de la codificación y del ensamblador.
 