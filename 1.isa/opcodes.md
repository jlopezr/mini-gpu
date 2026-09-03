## MiniISA v0.1 — Mapa preliminar de opcodes

La ISA utiliza opcodes de **6 bits**, permitiendo un máximo de 64 instrucciones.

Organización general:

| Rango | Prefijo | Uso |
|---|---|---|
| `0x00–0x0F` | `00xxxx` | ALU / aritmética / lógica |
| `0x10–0x1F` | `01xxxx` | Inmediatos / memoria |
| `0x20–0x2F` | `10xxxx` | Control de flujo |
| `0x30–0x3F` | `11xxxx` | Sistema / SIMT / GPU |

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
| `0x0C` | `001100` | — | — | Reservada |
| `0x0D` | `001101` | — | — | Reservada |
| `0x0E` | `001110` | — | — | Reservada |
| `0x0F` | `001111` | — | — | Reservada |

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

Los saltos condicionales comparan directamente dos registros.  
La arquitectura **no dispone de FLAGS ni de una instrucción CMP**.

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

Esta zona se reserva deliberadamente para la evolución de MiniCPU hacia MiniGPU.

| Opcode | Binario | Instrucción | Formato | Estado |
|---|---|---|---|---|
| `0x30` | `110000` | `GETTID` | I/especial | Propuesta |
| `0x31` | `110001` | `GETLANE` | especial | Reservada GPU |
| `0x32` | `110010` | `GETWARP` | especial | Reservada GPU |
| `0x33` | `110011` | `BAR` | especial | Reservada GPU |
| `0x34–0x3D` | — | — | — | Reservadas GPU |
| `0x3E` | `111110` | `TRAP` | especial | Propuesta |
| `0x3F` | `111111` | `HALT` | especial | Definida |

---

## Formatos de instrucción

### R-Type

Operaciones entre registros.

```text
31          26 25    21 20    16 15    11 10                0
┌─────────────┬────────┬────────┬────────┬────────────────────┐
│   opcode    │   Rd   │   Ra   │   Rb   │       extra        │
└─────────────┴────────┴────────┴────────┴────────────────────┘
      6           5         5         5            11

### I-Type

Operaciones con inmediatos, memoria y branches condicionales.

```text
31          26 25    21 20    16 15                         0
┌─────────────┬────────┬────────┬─────────────────────────────┐
│   opcode    │    X   │    Y   │          imm16              │
└─────────────┴────────┴────────┴─────────────────────────────┘
      6           5         5               16
```

El significado de X, Y e imm16 depende del opcode.

Ejemplos:

```text
ADDI  R3, R2, 10
LOAD  R3, [R2 + 12]
STORE [R2 + 12], R3
BLT   R3, R7, loop
```

Para un branch condicional:
X     = Ra
Y     = Rb
imm16 = offset relativo


### B-Type

Reservado inicialmente para BRA.

```text
31          26 25                                          0
┌─────────────┬─────────────────────────────────────────────┐
│   opcode    │               signed offset26               │
└─────────────┴─────────────────────────────────────────────┘
      6                         26
```

Convención preliminar de branches

Para branches condicionales:
    target = PC + 4 + sign_extend(offset16) × 4
Para BRA:
    target = PC + 4 + sign_extend(offset26) × 4

Los offsets están expresados en instrucciones de 32 bits, no en bytes.

Ejemplo:
BLT R3, R7, loop

equivale conceptualmente a:

if signed(R3) < signed(R7):
    PC = target
else:
    PC = PC + 4

BLTU y BGEU realizan la misma operación interpretando los registros como valores unsigned.

### Decisiones todavía pendientes

- Semántica exacta de SHL, SHR y SAR respecto al número de bits de desplazamiento.
- Semántica exacta de MULFX y formato fixed-point definitivo.
- Semántica de MUL y MULHI si finalmente se implementan.
- Signed/unsigned y extensión de cada inmediato.
- Semántica exacta de MOVHI.
- Alineamiento y tamaño de LOAD/STORE.
- Comportamiento ante instrucciones reservadas o encoding inválido.
- Semántica definitiva de TRAP.
- Encoding definitivo de GETTID y futuras instrucciones SIMT/GPU.
- Uso futuro de los 11 bits extra del formato R-Type.
