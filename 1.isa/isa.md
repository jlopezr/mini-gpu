# MiniISA v0.1

Este documento es la especificación de la ISA usada por MiniCPU y MiniGPU. Cuando el código y este texto discrepen, la discrepancia debe tratarse
como un error; no se debe deducir la ISA exclusivamente del simulador.

El documento describe el estado **actual**, que ya no es exactamente la v0.1:
las carpetas posteriores han ido incorporando extensiones del mapa de
`propuesta-v0.2.md`. Cada una dice en qué carpeta apareció, y hay una sola
incompatible con la v0.1 —`R0` cableado a cero, §1—; el resto son aditivas.

| Extensión | Desde | Compatible con v0.1 |
| --- | --- | --- |
| `LOADB`…`STOREH`, accesos de 8 y 16 bits | `19.fpga-cpu-hdmi-ls` | sí |
| `JAL`, `JALR`, `JR` | `19.fpga-cpu-hdmi-ls` | sí |
| `MULHI`, `DIVU`, `REM`, `REMU` | `21.fpga-cpu-hdmi-alu` | sí |
| Desplazamientos con cantidad inmediata | `21.fpga-cpu-hdmi-alu` | sí |
| **`R0` cableado a cero** | `21.fpga-cpu-hdmi-alu` | **no** |

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

**Desde `21.fpga-cpu-hdmi-alu`**, las escrituras a `R0` se descartan y las
lecturas valen siempre cero. En v0.1 `R0` era un registro general, y las
implementaciones hasta `19.fpga-cpu-hdmi-ls` inclusive se quedan así: es un
cambio **incompatible**, no aditivo. Un programa que use `R0` como registro
general no para con error en una implementación anterior; da otro resultado, en
silencio.

No se hace por área. Ahorra unos 32 flops de los 1024 del banco, que en un
ECP5-85F es ruido. Las dos razones que sí valen:

- **El presupuesto de opcodes.** `JR Ra` pasa a ser exactamente
  `JALR R0, Ra, 0`, con lo que `0x2E` vuelve al bote. La familia de control
  `0x20–0x2F` estaba a cero libres en el mapa de `propuesta-v0.2.md` §6, que ya
  anota esta palanca como la más barata.
- **Los idiomas.** Cero sin gastar un `MOVI` ni un registro, y un destino de
  descarte para cuando solo interesan los efectos de una operación.

`JR` (`0x2E`) **sigue implementado y sigue siendo válido**: quitarlo hoy rompe
programas sin ganar nada. Queda marcado como obsoleto y su hueco como
reclamable, no como libre.

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

| Opcode | Mnemónico | Operandos    | Semántica                         | Simulador |
|-------:|-----------|--------------|-----------------------------------|-----------|
| `0x00` | `NOP`     | —            | Sin efecto                        | Sí        |
| `0x01` | `ADD`     | `Rd, Ra, Rb` | `Rd = Ra + Rb`                    | Sí        |
| `0x02` | `SUB`     | `Rd, Ra, Rb` | `Rd = Ra - Rb`                    | Sí        |
| `0x03` | `MULFX`   | `Rd, Ra, Rb` | multiplicación signed Q16.16      | Sí        |
| `0x04` | `AND`     | `Rd, Ra, Rb` | AND bit a bit                     | Sí        |
| `0x05` | `OR`      | `Rd, Ra, Rb` | OR bit a bit                      | Sí        |
| `0x06` | `XOR`     | `Rd, Ra, Rb` | XOR bit a bit                     | Sí        |
| `0x07` | `SHL`     | `Rd, Ra, Rb` | desplazamiento lógico izquierdo   | Sí        |
| `0x08` | `SHR`     | `Rd, Ra, Rb` | desplazamiento lógico derecho     | Sí        |
| `0x09` | `SAR`     | `Rd, Ra, Rb` | desplazamiento aritmético derecho | Sí        |
| `0x0A` | `MUL`     | `Rd, Ra, Rb` | 32 bits bajos de `Ra × Rb`        | Sí        |
| `0x0B` | `MULHI`   | `Rd, Ra, Rb` | 32 bits altos, **signed**         | Sí        |
| `0x0C` | `DIV`     | `Rd, Ra, Rb` | división signed, hacia cero       | Sí        |
| `0x0D` | `DIVU`    | `Rd, Ra, Rb` | división unsigned                 | Sí        |
| `0x0E` | `REM`     | `Rd, Ra, Rb` | resto signed, signo del dividendo | Sí        |
| `0x0F` | `REMU`    | `Rd, Ra, Rb` | resto unsigned                    | Sí        |

**La familia ALU queda completa.** No hay ningún opcode libre entre `0x00` y
`0x0F`, y cualquier operación aritmética nueva tendrá que buscar hueco en otra
familia o entrar por una codificación extendida.

#### Desplazamientos con cantidad inmediata

Para `SHL`, `SHR` y `SAR` la cantidad son los cinco bits bajos de `Rb`. Desde
`21.fpga-cpu-hdmi-alu`, el **bit 10** del campo `extra` indica que la cantidad
es inmediata y viaja en los cinco bits del propio campo `Rb`:

```text
31          26 25    21 20    16 15    11 10   9              0
┌─────────────┬────────┬────────┬────────┬───┬────────────────┐
│   opcode    │   Rd   │   Ra   │ Rb/imm │ I │       0        │
└─────────────┴────────┴────────┴────────┴───┴────────────────┘
                                            ↑ 1 = cantidad inmediata
```

Es la **opción B** de `propuesta-v0.2.md` §4.2, y cuesta cero opcodes: la
familia `0x10–0x1F` es la única con presión real y los accesos por bytes valen
más que la elegancia del decodificador. Los mnemónicos del ensamblador son
`SHLI`, `SHRI` y `SARI`; no son opcodes, son azúcar sobre los mismos tres.

La contrapartida está en el decodificador de encoding, y es la única
irregularidad de la ISA: **para estos tres opcodes el campo reservado es
`extra[9:0]`, no `extra` entero**. Un `SHL` con `extra = 0x400` es válido; con
cualquier bit de `extra[9:0]` puesto sigue dando `ERROR_INVALID_ENCODING`.

#### Multiplicación y división

`MULFX` interpreta ambos operandos como signed Q16.16, forma un producto signed
de 64 bits, lo desplaza aritméticamente 16 bits a la derecha y escribe los 32
bits bajos.

`MUL` y `MULHI` son las dos mitades del **mismo producto signed de 64 bits**:
`MUL` escribe `(Ra × Rb)[31:0]` y `MULHI` escribe `(Ra × Rb)[63:32]`, con ambos
operandos interpretados como signed32. Los bits bajos no dependen del signo, así
que `MUL` sirve igual para operandos unsigned; los altos sí, y ahí la ISA toma
partido.

> **`MULHI` es con signo.** La v0.1 dejaba el opcode reservado sin decir cuál de
> las dos era, y hay que elegir. Se elige signed por tres razones: es la
> convención de `MULH` en RISC-V, es coherente con `MULFX`, que es la otra
> multiplicación de esta ISA y también es signed, y con un solo opcode la mitad
> alta signed es la que no se puede reconstruir barata a partir de la otra. No
> hay `MULHU`; quien necesite el alto unsigned lo obtiene sumando la corrección
> `(Ra[31] ? Rb : 0) + (Rb[31] ? Ra : 0)` al resultado de `MULHI`.
>
> No es gratis en el hardware, y por eso está escrito aquí: el producto de 64
> bits que construye el RTL es el **unsigned**, así que la mitad alta signed
> necesita restarle esa misma corrección. Cablear los bits de arriba no basta,
> y un test que solo use operandos positivos no lo nota.

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

La división por cero provoca un trap arquitectónico en las cuatro
instrucciones —también en `REM` y `REMU`, que no tienen más definición que la
división que las acompaña—; hasta que el trap se formalice, el simulador
termina con error y el RTL para con `ERROR_DIVISION_BY_ZERO`.

### Inmediatos y memoria

|      Opcode | Mnemónico | Operandos       | Semántica                             | Simulador |
|------------:|-----------|-----------------|---------------------------------------|-----------|
|      `0x10` | `MOVI`    | `Rd, imm16`     | `Rd = sign_extend(imm16)`             | Sí        |
|      `0x11` | `ADDI`    | `Rd, Ra, imm16` | `Rd = Ra + sign_extend(imm16)`        | Sí        |
|      `0x12` | `ANDI`    | `Rd, Ra, imm16` | `Rd = Ra AND zero_extend(imm16)`      | Sí        |
|      `0x13` | `ORI`     | `Rd, Ra, imm16` | `Rd = Ra OR zero_extend(imm16)`       | Sí        |
|      `0x14` | `XORI`    | `Rd, Ra, imm16` | `Rd = Ra XOR zero_extend(imm16)`      | Sí        |
|      `0x15` | `LOAD`    | `Rd, Ra, imm16` | `Rd = mem32[Ra + sign_extend(imm16)]` | Sí        |
|      `0x16` | `STORE`   | `Rs, Ra, imm16` | `mem32[Ra + sign_extend(imm16)] = Rs` | Sí        |
|      `0x17` | `MOVHI`   | `Rd, imm16`     | `Rd = imm16 << 16`                    | Sí        |
|      `0x18` | `LOADB`   | `Rd, Ra, imm16` | 8 bits, extensión con signo           | Sí        |
|      `0x19` | `LOADUB`  | `Rd, Ra, imm16` | 8 bits, extensión con ceros           | Sí        |
|      `0x1A` | `STOREB`  | `Rs, Ra, imm16` | escribe `Rs[7:0]`                     | Sí        |
|      `0x1B` | `LOADH`   | `Rd, Ra, imm16` | 16 bits, extensión con signo          | Sí        |
|      `0x1C` | `LOADUH`  | `Rd, Ra, imm16` | 16 bits, extensión con ceros          | Sí        |
|      `0x1D` | `STOREH`  | `Rs, Ra, imm16` | escribe `Rs[15:0]`                    | Sí        |
| `0x1E–0x1F` | —         | —               | Reservadas                            | —         |

Los seis accesos sub-palabra siguen el mapa de `propuesta-v0.2.md` §7 y
aparecieron en `19.fpga-cpu-hdmi-ls`. Quedan **dos opcodes libres** en esta
familia.

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
| `0x26–0x2B` | —         | —                | Reservadas                 | —         |
|      `0x2C` | `JAL`     | `Rd, target`     | `Rd = PC+4`, relativo      | Sí        |
|      `0x2D` | `JALR`    | `Rd, Ra, imm16`  | `Rd = PC+4`, a `Ra+imm*4`  | Sí        |
|      `0x2E` | `JR`      | `Ra`             | a `Ra`; **obsoleta**       | Sí        |
|      `0x2F` | `BRA`     | `target`         | Siempre                    | Sí        |

`JAL`, `JALR` y `JR` aparecieron en `19.fpga-cpu-hdmi-ls`, con el mapa de
`propuesta-v0.2.md` §3.2, cuando `R0` todavía era un registro general. Desde que
`R0` está cableado a cero, **`JR Ra` es exactamente `JALR R0, Ra, 0`** y `0x2E`
queda obsoleto: sigue implementado y sigue siendo válido, pero es redundante y
su hueco es reclamable por una instrucción futura. Los programas nuevos deberían
usar `JALR R0`. `RET` es un alias del ensamblador, no un opcode.

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

|      Opcode | Mnemónico | Operandos | Estado                                 |
|------------:|-----------|-----------|----------------------------------------|
|      `0x30` | `GETTID`  | `Rd`      | Implementada en MiniCPU y MiniGPU       |
|      `0x31` | `SSY`     | `label`   | Implementada en MiniGPU; B-Type         |
|      `0x32` | `BAR`     | —         | Implementada en MiniGPU                 |
|      `0x33` | `EXIT`    | —         | Implementada en MiniGPU                 |
| `0x34–0x3D` | —         | —         | Reservadas para GPU                    |
|      `0x3E` | `TRAP`    | —         | Parada explícita con estado de error    |
|      `0x3F` | `HALT`    | —         | Definida e implementada                 |

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
reset. En la futura MiniGPU la política inicial será detener globalmente la
ejecución; el contexto de lane o warp podrá añadirse sin cambiar el opcode.

Los campos marcados como reservados deben ser cero. Un opcode conocido con
campos reservados distintos de cero produce `ERROR_INVALID_ENCODING`; un opcode
reservado o desconocido produce `ERROR_INVALID_OPCODE`. La única excepción es la
descrita arriba: en `SHL`, `SHR` y `SAR` el campo reservado es `extra[9:0]`
porque el bit 10 selecciona la cantidad inmediata.

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

`SHLI`, `SHRI` y `SARI` **no son opcodes**: son la forma de escribir `SHL`,
`SHR` y `SAR` con el bit de cantidad inmediata puesto. La cantidad va de 0 a 31
y el ensamblador rechaza cualquier otra en vez de truncarla:

```asm
SHLI R3, R2, 2      ; indice -> desplazamiento en bytes, sin gastar un MOVI
SHL  R3, R2, R4     ; la misma operacion con la cantidad en un registro
```

## 6. Conformidad y evolución

Una implementación conforme debe producir el comportamiento descrito para toda
instrucción marcada como definida. Encontrar un opcode reservado o un encoding
inválido debe provocar un trap; mientras no exista el mecanismo de traps, el
simulador puede detenerse con un error diagnóstico.

Los opcodes `0x30–0x3F` permiten añadir SIMT sin romper programas MiniCPU. Los
detalles físicos —número de lanes, ancho de warp, register file, latencias,
pipeline y scheduler— no forman parte de la ISA.
