# MiniISA: repertorio vigente y extensiones compatibles

Este documento reúne la especificación vigente de **MiniISA v0.1** y las
**extensiones compatibles propuestas en v0.2**. Cuando el código y un contrato
vigente discrepen, la discrepancia debe tratarse como un error; no se deduce la
ISA exclusivamente del simulador.

La referencia escalar para el repertorio entero y su encoding es
[`21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu/README.md); la extensión FP32
se implementa en [`38.fpga-cpu-pipelined`](../38.fpga-cpu-pipelined/README.md).
También se documenta la semántica SIMT de MiniGPU y los NOP SSY/BAR de CPU.

Los apartados §1–§6 describen el repertorio vigente. §7 incorpora las propuestas
compatibles de v0.2, con su estado explícito: **documentarlas no significa que
estén implementadas**. §8 reúne disponibilidad, portabilidad y validación.
El [catálogo de instrucciones](#3-mapa-de-opcodes) distingue ambos estados
y muestra el soporte de cada instrucción en los simuladores funcionales.

Las extensiones compatibles conservan los opcodes, formatos y comportamientos
vigentes: pueden ocupar huecos reservados y añadir capabilities, pero no mover
instrucciones ni reinterpretar encodings válidos. Prevalecen las asignaciones
ya implementadas en CPU (2) y GPU (11), reutilizadas por el integrado (32).
Un programa válido conserva su comportamiento al mantener sus capabilities;
esto no permite ejecutarlo en un backend que carezca de ellas.

El mapa incompatible de [v0.4](propuesta-v0.4.md) se mantiene aparte y no
sustituye al definido aquí.

### Capabilities de instrucciones

Una capability identifica una extensión que una implementación puede ofrecer.
La ISA fija su encoding y comportamiento; cada backend declara cuáles tiene.
Las extensiones pueden incorporarse a otras versiones respetando sus
dependencias. La tabla siguiente recoge las capabilities vigentes; las
propuestas se enumeran en §7.1.

| Capability        | Opcodes o variantes     | Instrucciones                                            |
|-------------------|-------------------------|----------------------------------------------------------|
| `mul_div`         | `0x03`, `0x0A`, `0x0C` | `MULFX`, `MUL`, `DIV` |
| `subword_memory`  | `0x18–0x1D`             | `LOADB`, `LOADUB`, `STOREB`, `LOADH`, `LOADUH`, `STOREH` |
| `calls`           | `0x2C–0x2E`             | `JAL`, `JALR`, `JR`                                      |
| `alu_extended`    | `0x0B`, `0x0D–0x0F`     | `MULHI`, `DIVU`, `REM`, `REMU`                           |
| `shift_immediate` | `0x07–0x09`, bit 10 = 1 | `SHLI`, `SHRI`, `SARI`                                   |
| `gpu_ids`         | `0x30`, `type = 1–4`    | `GETLANE`, `GETWARP`, `GETLWARP`, `GETARG`                 |
| `fp32`            | `0x38–0x3D`             | `FADD`, `FSUB`, `FMUL`, `FDIV`, `FEQ`, `FLT`, `FLE`, `FTOI`, `ITOF` |
| `minmax`          | `0x1E`, `func6 = 0x00–0x03` | `MIN`, `MAX`, `MINU`, `MAXU`                         |
| `clz`             | `0x1E`, `func6 = 0x09`  | `CLZ`                                                    |
| `compare`         | `0x26–0x27`             | `SLT`, `SLTU`                                            |

En las tablas de opcodes, **Base** significa que no se requiere una capability
adicional; no es el nombre de una capability del runner. Los desplazamientos
por registro pertenecen a la base, aunque sus variantes inmediatas sean opcionales.

`mul_div` es una extensión opcional de CPU y GPU que comprende `MUL`,
`MULFX` y `DIV`; no pertenecen al repertorio base. Sin ella, sus opcodes siguen
asignados y ejecutarlos produce `ERROR_INVALID_OPCODE`. `alu_extended` requiere
`mul_div`, sin que la implicación inversa sea válida. Los backends actuales la
ofrecen salvo la CPU de `10.fpga-cpu-ram`, que puede omitirla sin incumplir la base.

Disponibilidad actual de las capabilities de instrucciones en MiniCPU:

| Implementación                     | `subword_memory` | `calls` | `alu_extended` | `shift_immediate` | `compare` |
|------------------------------------|------------------|---------|----------------|--------------------|-----------|
| `6.fpga-cpu` / `ebr`               | —                | —       | —              | —                  | —         |
| `10.fpga-cpu-ram` / `sdram`        | —                | —       | —              | —                  | —         |
| `16.fpga-cpu-hdmi` / `hdmi`        | —                | —       | —              | —                  | —         |
| `18.fpga-cpu-hdmi-bl8` / `bl8`     | —                | —       | —              | —                  | —         |
| `19.fpga-cpu-hdmi-ls` / `subword`  | Sí               | Sí      | —              | —                  | —         |
| `21.fpga-cpu-hdmi-alu` / `alu`     | Sí               | Sí      | Sí             | Sí                 | Sí        |
| `2.cpu-sim-func` / `sim-cpu` | Sí               | Sí      | Sí             | Sí                 | Sí        |

Y en MiniGPU, donde cada **lane** ejecuta las mismas instrucciones que la CPU
(`gpu_lane.v`) y el SM añade las SIMT:

| Implementación                          | `subword_memory` | `calls` | `alu_extended` | `shift_immediate` | `compare` |
|-----------------------------------------|------------------|---------|----------------|--------------------|-----------|
| `12`, `14`, `17`, `22` (GPU)            | —                | —       | —              | —                  | —         |
| `29.fpga-gpu-sm-pipeline`               | Sí               | —       | —              | —                  | —         |
| `37.fpga-cpu-gpu-mk2` (GPU)             | Sí               | Sí      | Sí             | Sí                 | Sí        |
| `11.gpu-sim-func` / `sim-gpu` (`current`)| Sí               | Sí      | —              | —                  | —         |
| `25.gpu-sim-cycle-uarch` (`cycle`)      | Sí               | Sí      | Sí             | Sí                 | Sí        |

En la GPU, `JALR` y `JR` sacan el destino de un registro por lane, y un warp solo
puede seguir si **todas sus lanes activas** llegan al mismo destino. Si no, para
con `ERROR_SIMT` (0x06) en lugar de serializar en silencio: no hay un destino que
apilar en la pila de divergencia. Un warp convergente, o con lanes enmascaradas
que coinciden, funciona como en la CPU. La uniformidad se comprueba sobre los
destinos efectivos después de cálculo y alineación, antes de escribir cualquier
enlace; si falla, no hay escrituras parciales de enlace.

Las declaraciones del runner están en
[`backends/fpga_cpu.py`](../t.tests/backends/fpga_cpu.py) y
[`backends/sim_cpu.py`](../t.tests/backends/sim_cpu.py); los casos usan
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

En el repertorio vigente, `extra` debe ser cero, con **una excepción**: en `SHL`, `SHR` y `SAR` el bit 10
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

Este catálogo reúne el repertorio vigente y las extensiones compatibles
propuestas. La columna Estado y el soporte funcional distinguen definición e
implementación. Las asignaciones propuestas no cambian por sí mismas ningún
backend. Los contratos detallados se desarrollan después de la tabla y en §7.

#### Lectura del soporte funcional

La columna **Sim. funcional (CPU / GPU)** muestra el soporte por arquitectura,
en ese orden: `Sí / No` significa implementada en CPU y ausente en GPU.
`No-op / Sí` indica que la CPU acepta la instrucción sin efecto y la GPU
implementa su semántica SIMT.

Comprobado contra los núcleos de [MiniCPU funcional (2)](../2.cpu-sim-func/minicpu_core.py)
y [MiniGPU funcional (11)](../11.gpu-sim-func/minigpu_core.py). El
[simulador integrado (32)](../32.cpu-gpu-func-sim/cpu_gpu_core.py) reutiliza ambos
núcleos. La columna describe ejecución funcional; la disponibilidad en FPGA se
consulta por separado en las capabilities de cada prototipo.

#### Catálogo por opcode y selector

- **Base** es el repertorio base de la arquitectura, no una capability del
  runner. En las filas vigentes, los nombres entre comillas de código son
  capabilities de `isa.md`.
- **Base (GPU)** identifica el repertorio base de la arquitectura GPU,
  incluidas las instrucciones SIMT; no es una capability llamada `simt`. `SSY` y `BAR` tienen efecto no-op en la CPU escalar.
- **`gpu_ids` (GPU)** añade los identificadores `GETLANE`, `GETWARP`,
  `GETLWARP` y `GETARG` al `GETTID` base. Comparten
  `0x30` con `GETTID`; `type` ocupa el campo Y y `imm16` debe ser cero.
  `GETID` es el nombre de la familia, no un opcode adicional. En CPU solo
  está definido `GETTID`, que devuelve cero.
- `SHLI`, `SHRI` y `SARI` comparten opcode con los desplazamientos por
  registro; el bit 10 selecciona la variante inmediata.

Las filas están ordenadas por **opcode primario y selector** (`bit 10`,
`type` o `func6`). La tabla contiene **69 mnemónicos vigentes y 11 propuestos**,
además de los tres opcodes que seguirían libres al adoptar toda v0.2.
Las capabilities de las filas con estado «Propuesta v0.2» son nombres propuestos.

| Opcode y selector | Categoría | Extensión / ámbito | Instrucción | Operandos | Estado | Sim. funcional (CPU / GPU) | Definición |
|---|---|---|---|---|---|---|---|
| `0x00` | Sistema | Base | `NOP` | — | Vigente | Sí / Sí | [isa.md §3](#sistema-y-simt) |
| `0x01` | Aritmética entera | Base | `ADD` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#alu-y-aritmética) |
| `0x02` | Aritmética entera | Base | `SUB` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#alu-y-aritmética) |
| `0x03` | Aritmética entera | `mul_div` | `MULFX` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#multiplicación-y-división) |
| `0x04` | Lógica | Base | `AND` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#alu-y-aritmética) |
| `0x05` | Lógica | Base | `OR` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#alu-y-aritmética) |
| `0x06` | Lógica | Base | `XOR` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#alu-y-aritmética) |
| `0x07`; `bit 10 = 0` | Desplazamientos | Base | `SHL` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#desplazamientos-con-cantidad-inmediata) |
| `0x07`; `bit 10 = 1` | Desplazamientos | `shift_immediate` | `SHLI` | `Rd, Ra, imm5` | Vigente | Sí / No | [isa.md §3](#desplazamientos-con-cantidad-inmediata) |
| `0x08`; `bit 10 = 0` | Desplazamientos | Base | `SHR` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#desplazamientos-con-cantidad-inmediata) |
| `0x08`; `bit 10 = 1` | Desplazamientos | `shift_immediate` | `SHRI` | `Rd, Ra, imm5` | Vigente | Sí / No | [isa.md §3](#desplazamientos-con-cantidad-inmediata) |
| `0x09`; `bit 10 = 0` | Desplazamientos | Base | `SAR` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#desplazamientos-con-cantidad-inmediata) |
| `0x09`; `bit 10 = 1` | Desplazamientos | `shift_immediate` | `SARI` | `Rd, Ra, imm5` | Vigente | Sí / No | [isa.md §3](#desplazamientos-con-cantidad-inmediata) |
| `0x0A` | Aritmética entera | `mul_div` | `MUL` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#multiplicación-y-división) |
| `0x0B` | Aritmética entera | `alu_extended` | `MULHI` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#multiplicación-y-división) |
| `0x0C` | Aritmética entera | `mul_div` | `DIV` | `Rd, Ra, Rb` | Vigente | Sí / Sí | [isa.md §3](#multiplicación-y-división) |
| `0x0D` | Aritmética entera | `alu_extended` | `DIVU` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#multiplicación-y-división) |
| `0x0E` | Aritmética entera | `alu_extended` | `REM` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#multiplicación-y-división) |
| `0x0F` | Aritmética entera | `alu_extended` | `REMU` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#multiplicación-y-división) |
| `0x10` | Constantes | Base | `MOVI` | `Rd, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x11` | Aritmética inmediata | Base | `ADDI` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x12` | Lógica inmediata | Base | `ANDI` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x13` | Lógica inmediata | Base | `ORI` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x14` | Lógica inmediata | Base | `XORI` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x15` | Memoria | Base | `LOAD` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x16` | Memoria | Base | `STORE` | `Rs, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x17` | Constantes | Base | `MOVHI` | `Rd, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x18` | Memoria | `subword_memory` | `LOADB` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x19` | Memoria | `subword_memory` | `LOADUB` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x1A` | Memoria | `subword_memory` | `STOREB` | `Rs, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x1B` | Memoria | `subword_memory` | `LOADH` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x1C` | Memoria | `subword_memory` | `LOADUH` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x1D` | Memoria | `subword_memory` | `STOREH` | `Rs, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#inmediatos-y-memoria) |
| `0x1E`; `func6 = 0x00` | Límites signed | `minmax` | `MIN` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#ext-minmax-y-clz-capabilities-minmax-y-clz) |
| `0x1E`; `func6 = 0x01` | Límites signed | `minmax` | `MAX` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#ext-minmax-y-clz-capabilities-minmax-y-clz) |
| `0x1E`; `func6 = 0x02` | Límites unsigned | `minmax` | `MINU` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#ext-minmax-y-clz-capabilities-minmax-y-clz) |
| `0x1E`; `func6 = 0x03` | Límites unsigned | `minmax` | `MAXU` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#ext-minmax-y-clz-capabilities-minmax-y-clz) |
| `0x1E`; `func6 = 0x04` | Selección | `select` | `SEL` | `Rd, Ra, Rb, Rc` | Propuesta v0.2 | No / No | [isa.md §7.3](#73-operaciones-nuevas-mediante-ext) |
| `0x1E`; `func6 = 0x05` | Acumulación Q16.16 | `macfx` | `MACFX` | `Rd, Ra, Rb` | Propuesta v0.2 | No / No | [isa.md §7.3](#73-operaciones-nuevas-mediante-ext) |
| `0x1E`; `func6 = 0x06` | Recíproco Q16.16 | `rcpfx` | `RCPFX` | `Rd, Ra` | Propuesta v0.2; contrato numérico pendiente | No / No | [isa.md §7.3](#73-operaciones-nuevas-mediante-ext) |
| `0x1E`; `func6 = 0x07` | Raíz inversa Q16.16 | `rsqrtfx` | `RSQRTFX` | `Rd, Ra` | Propuesta v0.2; contrato numérico pendiente | No / No | [isa.md §7.3](#73-operaciones-nuevas-mediante-ext) |
| `0x1E`; `func6 = 0x08` | Conversión de píxeles | `pack565` | `PACK565` | `Rd, Ra` | Propuesta v0.2 | No / No | [isa.md §7.3](#73-operaciones-nuevas-mediante-ext) |
| `0x1E`; `func6 = 0x09` | Bits | `clz` | `CLZ` | `Rd, Ra` | Vigente | Sí / No | [isa.md §3](#ext-minmax-y-clz-capabilities-minmax-y-clz) |
| `0x1F` | Reservado | — | — | — | Reservado en v0.1 y v0.2 | No / No | [isa.md §3](#inmediatos-y-memoria); [isa.md §7.4](#74-mapa-conjunto-y-ocupación) |
| `0x20` | Saltos | Base | `BEQ` | `Ra, Rb, target` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x21` | Saltos | Base | `BNE` | `Ra, Rb, target` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x22` | Saltos | Base | `BLT` | `Ra, Rb, target` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x23` | Saltos | Base | `BGE` | `Ra, Rb, target` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x24` | Saltos | Base | `BLTU` | `Ra, Rb, target` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x25` | Saltos | Base | `BGEU` | `Ra, Rb, target` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x26` | Comparaciones | `compare` | `SLT` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#control-de-flujo) |
| `0x27` | Comparaciones | `compare` | `SLTU` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#control-de-flujo) |
| `0x28` | Saltos con inmediato | `branch_immediate` | `BLTI` | `Ra, imm5, target` | Propuesta v0.2 | No / No | [isa.md §7.2](#72-branches-con-inmediato) |
| `0x29` | Saltos con inmediato | `branch_immediate` | `BGEI` | `Ra, imm5, target` | Propuesta v0.2 | No / No | [isa.md §7.2](#72-branches-con-inmediato) |
| `0x2A` | Saltos con inmediato | `branch_immediate` | `BLTUI` | `Ra, imm5, target` | Propuesta v0.2 | No / No | [isa.md §7.2](#72-branches-con-inmediato) |
| `0x2B` | Saltos con inmediato | `branch_immediate` | `BGEUI` | `Ra, imm5, target` | Propuesta v0.2 | No / No | [isa.md §7.2](#72-branches-con-inmediato) |
| `0x2C` | Llamadas y retornos | `calls` | `JAL` | `Rd, target` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x2D` | Llamadas y retornos | `calls` | `JALR` | `Rd, Ra, imm16` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x2E` | Llamadas y retornos | `calls` | `JR` | `Ra` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x2F` | Saltos | Base | `BRA` | `target` | Vigente | Sí / Sí | [isa.md §3](#control-de-flujo) |
| `0x30`; `type = 0` | Identificadores de ejecución | Base | `GETTID` | `Rd` | Vigente | Sí / Sí | [isa.md §3](#sistema-y-simt) |
| `0x30`; `type = 1` | Identificadores de ejecución | `gpu_ids` (GPU) | `GETLANE` | `Rd` | Vigente | No / Sí | [isa.md §3](#sistema-y-simt) |
| `0x30`; `type = 2` | Identificadores de ejecución | `gpu_ids` (GPU) | `GETWARP` | `Rd` | Vigente | No / Sí | [isa.md §3](#sistema-y-simt) |
| `0x30`; `type = 3` | Identificadores de ejecución | `gpu_ids` (GPU) | `GETLWARP` | `Rd` | Vigente | No / Sí | [isa.md §3](#sistema-y-simt) |
| `0x30`; `type = 4` | Identificadores de ejecución | `gpu_ids` (GPU) | `GETARG` | `Rd` | Vigente | No / Sí | [isa.md §3](#sistema-y-simt) |
| `0x31` | Control SIMT | Base (GPU) | `SSY` | `label` | Vigente | No-op / Sí | [isa.md §3](#sistema-y-simt) |
| `0x32` | Control SIMT | Base (GPU) | `BAR` | — | Vigente | No-op / Sí | [isa.md §3](#sistema-y-simt) |
| `0x33` | Control SIMT | Base (GPU) | `EXIT` | — | Vigente | No / Sí | [isa.md §3](#sistema-y-simt) |
| `0x34` | Saltos con inmediato | `branch_immediate` | `BEQI` | `Ra, imm5, target` | Propuesta v0.2 | No / No | [isa.md §7.2](#72-branches-con-inmediato) |
| `0x35` | Saltos con inmediato | `branch_immediate` | `BNEI` | `Ra, imm5, target` | Propuesta v0.2 | No / No | [isa.md §7.2](#72-branches-con-inmediato) |
| `0x36` | Reservado | — | — | — | Reservado en v0.1 y v0.2 | No / No | [isa.md §3](#sistema-y-simt); [isa.md §7.4](#74-mapa-conjunto-y-ocupación) |
| `0x37` | Reservado | — | — | — | Reservado en v0.1 y v0.2 | No / No | [isa.md §3](#sistema-y-simt); [isa.md §7.4](#74-mapa-conjunto-y-ocupación) |
| `0x38` | Aritmética FP32 | `fp32` | `FADD` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x39` | Aritmética FP32 | `fp32` | `FSUB` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x3A` | Aritmética FP32 | `fp32` | `FMUL` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x3B` | Aritmética FP32 | `fp32` | `FDIV` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x3C`; `extra = 0` | Comparación FP32 | `fp32` | `FEQ` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x3C`; `extra = 1` | Comparación FP32 | `fp32` | `FLT` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x3C`; `extra = 2` | Comparación FP32 | `fp32` | `FLE` | `Rd, Ra, Rb` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x3D`; `extra[6:5] = 0` | Conversión FP32 | `fp32` | `FTOI` | `Rd, Ra, fbits` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x3D`; `extra[6:5] = 1` | Conversión FP32 | `fp32` | `ITOF` | `Rd, Ra, fbits` | Vigente | Sí / No | [isa.md §3](#aritmética-fp32-capability-fp32) |
| `0x3E` | Sistema | Base | `TRAP` | — | Vigente | Sí / Sí | [isa.md §3](#sistema-y-simt) |
| `0x3F` | Sistema | Base | `HALT` | — | Vigente | Sí / Sí | [isa.md §3](#sistema-y-simt) |

`HALT` detiene la CPU; en GPU retira las lanes activas como `EXIT`. Los detalles
numéricos, formatos, campos reservados y errores se consultan en las secciones
enlazadas, junto con [los formatos de instrucción](#2-formatos-de-instrucción)
y [las reglas de conformidad](#6-conformidad-y-evolución).

En EXT, `Rc = 0` está reservado para `MIN/MAX/MINU/MAXU/MACFX`;
`Rb = Rc = 0` para `RCPFX/RSQRTFX/PACK565`. `SEL` usa los cuatro registros.
La falta de contrato numérico de `RCPFX/RSQRTFX` impide tratarlas como listas
para implementar aunque ya tengan una asignación propuesta.

El mapa vigente tiene **55 opcodes primarios ocupados y 9 reservados**
(`EXT` en `0x1E` y FP32 en `0x3C–0x3D` son los últimos en ocuparse).
V0.2 propone ocupar seis de esos huecos más: `0x28–0x2B` y `0x34–0x35`.
Si se adoptara todo el conjunto, habría **61 ocupados y 3 libres**:
`0x1F`, `0x36` y `0x37`. De las funciones EXT, `0x09` es `CLZ` y `0x0A–0x3F`
(54) seguirían libres. La ocupación por bloques se resume en §7.4.

### ALU y aritmética

| Opcode | Mnemónico | Operandos    | Semántica                         | Capability     |
|-------:|-----------|--------------|-----------------------------------|----------------|
| `0x00` | `NOP`     | —            | Sin efecto                        | Base           |
| `0x01` | `ADD`     | `Rd, Ra, Rb` | `Rd = Ra + Rb`                    | Base           |
| `0x02` | `SUB`     | `Rd, Ra, Rb` | `Rd = Ra - Rb`                    | Base           |
| `0x03` | `MULFX`   | `Rd, Ra, Rb` | multiplicación signed Q16.16      | `mul_div`           |
| `0x04` | `AND`     | `Rd, Ra, Rb` | AND bit a bit                     | Base           |
| `0x05` | `OR`      | `Rd, Ra, Rb` | OR bit a bit                      | Base           |
| `0x06` | `XOR`     | `Rd, Ra, Rb` | XOR bit a bit                     | Base           |
| `0x07` | `SHL`     | `Rd, Ra, Rb` | desplazamiento lógico izquierdo   | Base           |
| `0x08` | `SHR`     | `Rd, Ra, Rb` | desplazamiento lógico derecho     | Base           |
| `0x09` | `SAR`     | `Rd, Ra, Rb` | desplazamiento aritmético derecho | Base           |
| `0x0A` | `MUL`     | `Rd, Ra, Rb` | 32 bits bajos de `Ra × Rb`        | `mul_div`           |
| `0x0B` | `MULHI`   | `Rd, Ra, Rb` | 32 bits altos, **signed**         | `alu_extended` |
| `0x0C` | `DIV`     | `Rd, Ra, Rb` | división signed, hacia cero       | `mul_div`           |
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
|      `0x1E` | `EXT`     | según `func6`   | `MIN`/`MAX`/`MINU`/`MAXU`/`CLZ`, ver [EXT](#ext-minmax-y-clz-capabilities-minmax-y-clz) | `minmax`, `clz` |
|      `0x1F` | —         | —               | Reservada                             | —                |

Los seis accesos sub-palabra siguen el mapa vigente de esta tabla y
aparecieron en `19.fpga-cpu-hdmi-ls`. `0x1E` es `EXT` (MIN/MAX/CLZ) y queda
**un opcode libre** en esta familia, `0x1F`.

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
|      `0x26` | `SLT`     | `Rd, Ra, Rb`     | `Rd = (signed(Ra) < signed(Rb)) ? 1 : 0` | `compare` |
|      `0x27` | `SLTU`    | `Rd, Ra, Rb`     | `Rd = (Ra < Rb) ? 1 : 0`, unsigned       | `compare` |
| `0x28–0x2B` | —         | —                | Reservadas                 | —          |
|      `0x2C` | `JAL`     | `Rd, target`     | `Rd = PC+4`, relativo      | `calls`    |
|      `0x2D` | `JALR`    | `Rd, Ra, imm16`  | `Rd = PC+4`, a `Ra+imm*4`  | `calls`    |
|      `0x2E` | `JR`      | `Ra`             | a `Ra`, sin enlace         | `calls`    |
|      `0x2F` | `BRA`     | `target`         | Siempre                    | Base       |

`SLT` y `SLTU` requieren `compare` y usan R-Type, con los campos de §2; el
campo reservado es `extra[10:0]`, igual que `ADD`. Materializan la comparación
como `0` o `1` en `Rd`, sin efectos de control de flujo: no tocan `PC` ni
consumen `target`. `SLTU` con `Ra = R0` materializa `Rb != 0`, y `SLT` con
`Rb = R0` materializa el signo de `Ra`, ambos sin instrucción dedicada. Ver
[`abi.md`](abi.md#12-materialized-comparisons) para el uso que les
da la ABI en aritmética de 64 bits sin `FLAGS`.

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

### Aritmética FP32 (capability `fp32`)

| Opcode | Mnemónico | Operandos | Resultado |
|-------:|-----------|-----------|-----------|
| `0x38` | `FADD` | `Rd, Ra, Rb` | binary32(Ra) + binary32(Rb) |
| `0x39` | `FSUB` | `Rd, Ra, Rb` | binary32(Ra) − binary32(Rb) |
| `0x3A` | `FMUL` | `Rd, Ra, Rb` | binary32(Ra) × binary32(Rb) |
| `0x3B` | `FDIV` | `Rd, Ra, Rb` | binary32(Ra) / binary32(Rb) |

Son R-Type, con `extra[10:0] = 0` (si no, `ERROR_INVALID_ENCODING`). Los
operandos y el resultado son **patrones IEEE 754 binary32 en los registros
generales R0–R31**; no hay banco FP separado ni conversión implícita desde
enteros o Q16.16. Se cargan con `LI`, `MOVHI`/`ORI` o `LOAD` y se guardan con
`STORE`. R0 representa +0 y descarta la escritura como en las demás operaciones.

Contrato numérico:

- Redondeo fijo **al más cercano, con desempate al par** (RNE), después de
  cada operación. No hay FMA ni registros de modo o flags FP.
- **DAZ**: cada entrada subnormal se trata como cero conservando el signo.
- **FTZ**: se redondea primero a binary32; si el resultado es subnormal, se
  sustituye por cero con su signo. Un valor que redondea al mínimo normal se
  conserva como normal. Un desbordamiento devuelve infinito con signo.
- Cualquier NaN, incluido señalizante, y cualquier operación inválida producen
  el NaN canónico `0x7FC00000`, sin conservar payload ni signo.
- `∞ + (−∞)`, `∞ − ∞`, `0 × ∞`, `0 / 0` e `∞ / ∞` son inválidas. Las reglas
  se aplican después de DAZ. Un finito no nulo dividido por ±0 devuelve infinito
  con el signo XOR; un finito dividido por infinito devuelve cero con signo XOR.
- Suma y resta con cancelación exacta producen +0; sumar dos ceros con el mismo
  signo conserva ese signo (en FSUB se invierte primero el signo de Rb).
  Multiplicación y división usan el signo XOR también para cero e infinito.

Los casos numéricos especiales **no generan excepciones de CPU**: en particular,
FDIV por cero no produce `ERROR_DIVISION_BY_ZERO`. No hay flags de excepción.

Implementado en la CPU del prototipo **38**, el simulador CPU **2** y la CPU del
simulador integrado **32**. Las GPU y los demás prototipos no ofrecen todavía
esta capability. Los opcodes se asignan del espacio antes reservado `0x34–0x3D`,
y no cambian los binarios existentes. Las propuestas v0.2–v0.4 siguen siendo
propuestas, con mapas propios. lcc genera estas instrucciones para `float` con
la opción `-fp32` (`mini-cc --fp32`; ver `u.lcc/README-miniisa.md`): `+ - * /`,
las comparaciones y las conversiones entre `int` y `float`. `double`, `long long`
y `unsigned` siguen en softfloat.

#### Comparaciones: `FEQ`, `FLT`, `FLE` (`0x3C`)

| `extra` | Mnemónico | Operandos | Resultado en `Rd` |
|--------:|-----------|-----------|-------------------|
| `0` | `FEQ` | `Rd, Ra, Rb` | 1 si binary32(Ra) == binary32(Rb), si no 0 |
| `1` | `FLT` | `Rd, Ra, Rb` | 1 si binary32(Ra) < binary32(Rb), si no 0 |
| `2` | `FLE` | `Rd, Ra, Rb` | 1 si binary32(Ra) <= binary32(Rb), si no 0 |

R-Type; `extra[10:2]` debe ser 0 (si no, `ERROR_INVALID_ENCODING`) y
`extra = 3` produce `ERROR_INVALID_OPCODE`. Son comparaciones IEEE sin excepción:

- Si algún operando es NaN, las tres dan 0 (`x != y` es `FEQ` negado, y da 1).
- `-0 == +0`.
- **Sin DAZ**: los subnormales se comparan exactamente. Es más barato que
  aplicar DAZ y da los mismos resultados que el softfloat de lcc.

`>` y `>=` son `FLT`/`FLE` con los operandos intercambiados.

#### Conversiones: `FTOI`, `ITOF` (`0x3D`)

```text
31       26 25   21 20   16 15   11 10    7 6    5 4       0
+----------+-------+-------+-------+-------+------+---------+
|   0x3D   |  Rd   |  Ra   |   0   |   0   |  op  |  fbits  |
+----------+-------+-------+-------+-------+------+---------+
```

| `op` | Mnemónico | Operandos | Resultado en `Rd` |
|-----:|-----------|-----------|-------------------|
| `0` | `FTOI` | `Rd, Ra, fbits` | int32(trunc(binary32(Ra) × 2^fbits)) |
| `1` | `ITOF` | `Rd, Ra, fbits` | binary32(int32(Ra) / 2^fbits), RNE |

`Rb` y `extra[10:7]` deben ser 0 (si no, `ERROR_INVALID_ENCODING`); `op = 2, 3`
producen `ERROR_INVALID_OPCODE`. `fbits` va de 0 a 31: con 0 son las
conversiones de C (`(int)f`, `(float)i`); con 16, de y a Q16.16. El ensamblador
acepta `FTOI Rd, Ra` e `ITOF Rd, Ra` con `fbits = 0`.

- `FTOI` trunca hacia cero. Fuera de rango, e infinito, satura a `0x7FFFFFFF`
  o `0x80000000` según el signo. Un NaN da 0. Cero y subnormales dan 0 (con
  cualquier `fbits`, un subnormal por 2^31 es menor que 1).
- `ITOF` redondea al más cercano con desempate al par. El resultado nunca es
  subnormal (el menor no nulo es 2^-31).
- Con `fbits = 0` dan los mismos bits que `__fixsfsi` y `__floatsisf` del
  softfloat de lcc. El modelo de referencia es `tools/fp32.py`.

Comparaciones e `ITOF` no dependen de DAZ/FTZ, así que el resultado es el mismo
con y sin la extensión; solo `FADD/FSUB/FMUL/FDIV` pueden diferir del softfloat
con subnormales.

```asm
LI R1, 0x3fc00000        ; 1.5
LI R2, 0x40100000        ; 2.25
FADD R3, R1, R2          ; R3 = 0x40700000 (3.75)
FLT  R4, R1, R2          ; R4 = 1
FTOI R5, R1, 16          ; R5 = 0x00018000 (1.5 en Q16.16)
ITOF R6, R5, 16          ; R6 = 0x3fc00000 (1.5)
```

### EXT: MIN/MAX y CLZ (capabilities `minmax` y `clz`)

El opcode `0x1E` (`EXT`) elige la operación por `func6`, con el formato de
[§7.3](#encoding-propuesto-ext-en-0x1e): `Rd`, `Ra`, `Rb`, `Rc` y `func6`.
Están implementadas estas cinco, en la CPU de la **38** y en los simuladores
CPU **2** y **32**:

| `func6` | Mnemónico | Operandos | Resultado | Campos a 0 | Capability |
|--------:|-----------|-----------|-----------|------------|------------|
| `0x00` | `MIN`  | `Rd, Ra, Rb` | el menor con signo | `Rc` | `minmax` |
| `0x01` | `MAX`  | `Rd, Ra, Rb` | el mayor con signo | `Rc` | `minmax` |
| `0x02` | `MINU` | `Rd, Ra, Rb` | el menor sin signo | `Rc` | `minmax` |
| `0x03` | `MAXU` | `Rd, Ra, Rb` | el mayor sin signo | `Rc` | `minmax` |
| `0x09` | `CLZ`  | `Rd, Ra`     | ceros iniciales de `Ra`; `CLZ(0) = 32` | `Rb`, `Rc` | `clz` |

Un campo reservado no nulo produce `ERROR_INVALID_ENCODING`; las demás
funciones (las propuestas de §7.3 incluidas), `ERROR_INVALID_OPCODE`. Las cinco
son de un ciclo en la ALU de la 38. En C se usan con los intrínsecos de
`u.lcc/include/mini/none/mini_ext.h` (`__mini_min`, `__mini_clz`...), que lcc
convierte en la instrucción.

```asm
LI   R1, -5
MOVI R2, 7
MIN  R3, R1, R2          ; R3 = -5
MAXU R4, R1, R2          ; R4 = 0xfffffffb
CLZ  R5, R2              ; R5 = 29
```

### Sistema y SIMT

`GETTID`, `TRAP` y `HALT` pertenecen a la base. `SSY`, `BAR` y `EXIT`
son instrucciones de la arquitectura GPU, sin capability adicional en el runner.

|      Opcode | Mnemónico | Operandos | Estado                               |
|------------:|-----------|-----------|--------------------------------------|
|      `0x30` | `GETID`   | `Rd`      | familia `GETTID`/`GETLANE`/`GETWARP`/`GETLWARP`/`GETARG`; en MiniCPU solo `GETTID`, que devuelve cero |
|      `0x31` | `SSY`     | `label`   | MiniGPU; en MiniCPU no-op. B-Type    |
|      `0x32` | `BAR`     | —         | MiniGPU; en MiniCPU no-op            |
|      `0x33` | `EXIT`    | —         | Implementada en MiniGPU              |
| `0x34–0x37` | — | — | Reservadas para GPU |
| `0x38–0x3D` | `FADD/FSUB/FMUL/FDIV`, `FEQ/FLT/FLE`, `FTOI/ITOF` | — | Extensión `fp32`, ver arriba |
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

**`GETID`** es la familia de identificadores de ejecución: un solo opcode, `0x30`,
con el campo `type` en el campo Y de un I-Type con `imm16 = 0`. `type = 0` es el
`GETTID` de siempre, así que los binarios existentes no cambian.

`GETTID` pertenece a la base. Las otras cuatro variantes requieren la capability
`gpu_ids`, exclusiva de GPU; una implementación sin ella solo admite `type = 0`
y rechaza los otros selectores con `ERROR_INVALID_ENCODING`. El nombre GETID
agrupa el encoding compartido, no identifica una extensión por sí mismo.

| `type` | Mnemónico | Devuelve |
|---:|---|---|
| 0 | `GETTID` | thread residente, `warp_id * warp_size + core_id` |
| 1 | `GETLANE` | índice de lane dentro del warp |
| 2 | `GETWARP` | slot de warp físico |
| 3 | `GETLWARP` | `LOGICAL_WARP_ID`: el id lógico que asigna el lanzador, independiente del slot físico |
| 4 | `GETARG` | `WARP_ARG`: el argumento del warp, típicamente un puntero al bloque de argumentos de su trabajo |

Un `type` mayor que 4, o `imm16` distinto de cero, es `ERROR_INVALID_ENCODING`.
`GETLWARP` y `GETARG` valen lo que el lanzador haya escrito en `LOGICAL_WARP_ID[n]`
y `WARP_ARG[n]` (`mmio.md` §14.2), y cero tras el reset. Son iguales para todas las
lanes del warp, y solo escriben las lanes activas.

`GETLWARP` es el antiguo `GETWID` (`warp_user_id`) usado en borradores anteriores:
se renombró porque `GETWID` se leía como «workgroup id», que es otra cosa
(`WORKGROUP_ID` solo agrupa warps para `BAR`). `GETARG` es nueva.

El identificador lógico es independiente del slot físico y de WORKGROUP_ID;
no exige unicidad ni asigna trabajo implícitamente. Al mover un trabajo de slot
o de SM, el lanzador conserva ID y argumento; no se presupone migración automática.

Su configuración sigue [MMIO §14.2](mmio.md#142-gpu-warps--0x82010000), GPU
WARPS con base `0x82010000`:

| Offset | Registro | Instrucción |
|---|---|---|
| `+0x200 + 4n` | `LOGICAL_WARP_ID[n]` | `GETLWARP` |
| `+0x280 + 4n` | `WARP_ARG[n]` | `GETARG` |

No ocupan el cuarto word del descriptor, reservado a SIMT_STATE. Escribirlos
con ese warp vivo es error, incluso si está pausado; se pueden configurar con
ese warp no vivo. Valen cero tras reset del sistema; GPU_CONTROL.RESET conserva
ambos arrays y los descriptores. HALT/RESUME no los altera. Si el ID representa
un número de bloque, el programa calcula `logical_warp_id * warp_size + lane_id`;
si representa una base de elementos, puede sumar directamente GETLANE.

**Estado:** el ensamblador (`asm2/mini-asm.py`), el simulador funcional de `11`
y el de `32` los implementan. **Faltan** el modelo de ciclos de `25` y el RTL.

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

> Esta sección es un resumen. La referencia completa de `mini_asm.py`
> —directivas de datos y secciones, `.include`, `.once`, etiquetas locales `@`,
> línea de órdenes y API de Python— está en
> [`ensamblador.md`](ensamblador.md). Nada de eso forma parte de la ISA: se
> resuelve antes de emitir un solo bit, y una implementación conforme no tiene
> por qué saber que existe.

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

### Pseudoinstrucciones y alias

Estas tres construcciones se expanden durante el ensamblado y no reservan
opcodes nuevos. Su soporte funcional corresponde a las instrucciones emitidas
por el ensamblador, implementadas tanto en la CPU como en la GPU funcionales.
Cada palabra emitida ocupa cuatro bytes y se ejecuta como una instrucción.

| Categoría | Mnemónico | Operandos | Expansión vigente | Palabras | Sim. funcional (CPU / GPU) | Definición |
|---|---|---|---|---|---|---|
| Constantes / pseudoinstrucción | `LI` | `Rd, expr` | `MOVI`, `ORI Rd, R0, v` o `MOVHI` + `ORI`, según el valor y la forma del operando | 1 o 2 | Sí / Sí (vía expansión) | [ensamblador.md, sintaxis](ensamblador.md#sintaxis) |
| Direcciones / pseudoinstrucción | `LA` | `Rd, etiqueta` | `MOVHI Rd, hi16` + `ORI Rd, Rd, lo16` de la dirección absoluta de 32 bits | 2 | Sí / Sí (vía expansión) | [ensamblador.md, sintaxis](ensamblador.md#sintaxis) |
| Retorno / alias de ensamblador | `RET` | — | `JR R31` (`0x2E`) | 1 | Sí / Sí (vía `JR`) | [ensamblador.md, sintaxis](ensamblador.md#sintaxis); [isa.md §3, control de flujo](#control-de-flujo) |

Para `LI`, los literales numéricos entre −32768 y 32767 emiten un `MOVI`;
los demás literales emiten `MOVHI` + `ORI`, incluso entre 32768 y 65535.
Los operandos simbólicos (etiquetas, constantes `.equ` y sus expresiones)
se relajan: emiten `MOVI` entre −32768 y 32767, `ORI Rd, R0, v` entre
32768 y 65535, y dos palabras en los demás casos.

`LA` siempre emite dos palabras, sin relajación, y admite expresiones de
direcciones como `tabla+8`. `RET` usa el registro de enlace R31 por convención
de software; el hardware ejecuta un `JR` ordinario.

`MOVI` usa `0x10`, `ORI` usa `0x13` y `MOVHI` usa `0x17`: sus definiciones
están en la tabla de instrucciones anterior. Las variantes `SHLI`, `SHRI` y `SARI`
también se describen en `ensamblador.md` y ya figuran en la tabla de instrucciones
como variantes del encoding de los desplazamientos, con una sola palabra.

Los nombres de instrucciones que aparecen como alternativas futuras en
`isa.md` no cambian las expansiones vigentes de esta tabla. Las directivas
como `.word`, `.equ` o `.include` se documentan en
[ensamblador.md, directivas](ensamblador.md#directivas).

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
evolución; la v0.4 sí elimina su opcode y adopta la pseudoinstrucción.
**MiniISA v0.1 vigente conserva `JR` y `0x2E` sigue ocupado.** Eliminarlo o
reasignarlo rompería los binarios que lo utilizan y requeriría una revisión
explícita de la codificación y del ensamblador.


## 7. Extensiones compatibles propuestas (v0.2)

Las siguientes asignaciones son propuestas documentales, no instrucciones
implementadas. Las operaciones vigentes y sus binarios conservan su contrato.
Las capacidades se pueden adoptar por separado; RCPFX y RSQRTFX siguen sin
contrato numérico cerrado y no deben anunciarse como soportadas.

### 7.1 Capabilities propuestas y decisiones pendientes

Los nombres de esta tabla son **propuestas**, no entradas existentes del
runner. `gpu_ids` ya existe con el contrato de §3; no se redefine aquí ni se
añade una capability separada `warp_user_id`:

| Capability propuesta | Operaciones                  | Alcance inicial propuesto                  |
|----------------------|------------------------------|--------------------------------------------|
| `branch_immediate`   | Los seis branches inmediatos | CPU y GPU                                  |
| `minmax`             | `MIN`, `MAX`, `MINU`, `MAXU` | Vigente en la CPU de la 38; falta la GPU   |
| `select`             | `SEL`                        | CPU y GPU                                  |
| `macfx`              | `MACFX`                      | CPU y GPU                                  |
| `pack565`            | `PACK565`                    | CPU y GPU                                  |
| `rcpfx`              | `RCPFX`                      | Pendiente del contrato numérico            |
| `rsqrtfx`            | `RSQRTFX`                    | Pendiente del contrato numérico            |

No se propone una capability única que obligue a implementar todo `EXT`.
Compartir opcode no implica compartir disponibilidad: un backend puede ofrecer
`MIN/MAX` sin recíproco. La implementación de las propuestas debe declarar
estas capabilities en CPU y GPU y comprobar `requires` contra cada backend.

Antes de implementar falta:

1. Aprobar las asignaciones nuevas y los nombres/grupos de capabilities.
2. Cerrar los contratos numéricos de `RCPFX` y `RSQRTFX`.
3. Elegir qué operaciones se incorporan primero y a qué backends, con medidas
   reproducibles de instrucciones, ciclos, área y timing.

Quedan fuera de este alcance la eliminación de `JR`, los branches compactados
de v0.4, el cambio de unidades de `JALR`, rotaciones y las nuevas operaciones de
voto/intercambio (`BALLOT`, `ANY`, `ALL`, `SHFL`), que no reciben encoding aquí.
V0.3 propone LEAPC y LOADX; LDR relativo al PC permanece sin encoding.

### 7.2 Branches con inmediato

Permiten comparar con una constante pequeña sin preparar otro registro:

```asm
; Secuencia vigente:
MOVI R2, 4
BLT  R1, R2, low

; Instrucción propuesta:
BLTI R1, 4, low
```

Las comparaciones contra cero ya pueden usar `R0`; el beneficio de estas nuevas
instrucciones debe medirse sobre todo para otras constantes.

#### Formato y semántica

Se conserva I-Type, sustituyendo el segundo registro por `imm5`:

```text
31          26 25    21 20    16 15                         0
+-------------+--------+--------+----------------------------+
|   opcode    |   Ra   |  imm5  |       signed offset16      |
+-------------+--------+--------+----------------------------+
```

| Opcode propuesto | Mnemónico | Comparación             | Extensión de `imm5`  |
|------------------|-----------|-------------------------|----------------------|
| `0x34`           | `BEQI`    | `Ra == imm`             | Con signo, `-16..15` |
| `0x35`           | `BNEI`    | `Ra != imm`             | Con signo, `-16..15` |
| `0x28`           | `BLTI`    | `signed32(Ra) < imm`    | Con signo, `-16..15` |
| `0x29`           | `BGEI`    | `signed32(Ra) >= imm`   | Con signo, `-16..15` |
| `0x2A`           | `BLTUI`   | `unsigned32(Ra) < imm`  | Con ceros, `0..31`   |
| `0x2B`           | `BGEUI`   | `unsigned32(Ra) >= imm` | Con ceros, `0..31`   |

`SLT` y `SLTU` conservan `0x26/0x27`. Por eso `BEQI/BNEI` se proponen en
`0x34/0x35`; los identificadores GPU permanecen agrupados en `0x30`. El prefijo del opcode no basta para decidir la
operación ni el formato: estos dos branches usan I-Type aunque sus opcodes
estén en el bloque `0x30–0x3F`.

La igualdad compara los 32 bits después de extender el inmediato. Así,
`BEQI Ra, -1, label` compara con `0xFFFFFFFF`, no con 31.

```text
si se cumple: PC = low32(PC + 4 + sign_extend(offset16) * 4)
si no:        PC = low32(PC + 4)
```

`PC` es la dirección de la instrucción. El offset admite `-32768..32767`
palabras, aproximadamente ±128 KiB. El ensamblador resuelve etiquetas y rechaza
inmediatos o destinos fuera de rango. No cambia la codificación de `BEQ`…`BGEU`.
En GPU se aplican las reglas de divergencia y reconvergencia de los branches
registro-registro existentes.

### 7.3 Operaciones nuevas mediante EXT

#### Operaciones y contratos

| Operación propuesta | Utilidad                         | Grado de definición                  |
|---------------------|----------------------------------|--------------------------------------|
| `MIN`, `MAX`        | Límites y recorte signed32       | Vigente en la 38 (§3, EXT)           |
| `MINU`, `MAXU`      | Índices y profundidad unsigned32 | Vigente en la 38 (§3, EXT)           |
| `SEL`               | Selección de datos sin branch    | Semántica definida en esta propuesta |
| `MACFX`             | Acumulación Q16.16               | Semántica definida en esta propuesta |
| `PACK565`           | Conversión RGB888 a RGB565       | Semántica definida en esta propuesta |
| `RCPFX`, `RSQRTFX`  | Recíproco y raíz inversa Q16.16  | Contrato numérico pendiente          |

`MIN/MAX` devuelven el menor/mayor operando según comparación signed32;
`MINU/MAXU` usan unsigned32. `SEL Rd, Ra, Rb, Rc` devuelve `Ra` si el contenido
de `Rc` no es cero y `Rb` en caso contrario.

`MACFX Rd, Ra, Rb` equivale a `MULFX` seguido de suma al antiguo `Rd`:

```text
product = signed64(signed32(Ra) * signed32(Rb))
Rd = low32(old_Rd + low32(product >> 16))
```

El desplazamiento es aritmético. No hay acumulador oculto de 64 bits ni redondeo
fusionado. Se leen todos los valores anteriores, aunque coincidan registros.
Con `Rd = R0`, el acumulador leído es cero y el resultado se descarta.
`MACFX` y `SEL` requieren tres lecturas: pueden necesitar otro ciclo o más
puertos de registro. No se promete latencia de un ciclo.

`PACK565 Rd, Ra` convierte `0x00RRGGBB` a RGB565 en los 16 bits bajos y deja
los 16 altos a cero; ignora el byte alto de `Ra`:

```text
Rd = ((Ra >> 8) & 0xF800) | ((Ra >> 5) & 0x07E0) | ((Ra >> 3) & 0x001F)
```

Para `RCPFX` y `RSQRTFX` faltan dominio, rango, precisión, error máximo,
redondeo, saturación/desbordamiento y tratamiento de cero y negativos. Sus
subopcodes se proponen para planificación, pero **no están listas para implementar**.
`DIV` entero no sustituye directamente esas operaciones Q16.16.

#### Encoding propuesto: `EXT` en `0x1E`

```text
31       26 25   21 20   16 15   11 10    6 5          0
+----------+-------+-------+-------+-------+------------+
| EXT=0x1E |  Rd   |  Ra   |  Rb   |  Rc   |   func6    |
+----------+-------+-------+-------+-------+------------+
```

Son 32 bits: 6 de opcode, cuatro campos de registro de 5 bits y 6 de función.
Solo `EXT` interpreta los once bits bajos como `Rc + func6`. El decodificador
no puede asumir que toda la familia `01xxxx` es I-Type. Ningún encoding vigente
cambia; el ensamblador expondrá los mnemónicos, no un `EXT` genérico.

| `func6` propuesto | Mnemónico  | Operandos        | Campos reservados                 |
|-------------------|------------|------------------|-----------------------------------|
| `0x00`            | `MIN`      | `Rd, Ra, Rb`     | `Rc = 0`                          |
| `0x01`            | `MAX`      | `Rd, Ra, Rb`     | `Rc = 0`                          |
| `0x02`            | `MINU`     | `Rd, Ra, Rb`     | `Rc = 0`                          |
| `0x03`            | `MAXU`     | `Rd, Ra, Rb`     | `Rc = 0`                          |
| `0x04`            | `SEL`      | `Rd, Ra, Rb, Rc` | Ninguno                           |
| `0x05`            | `MACFX`    | `Rd, Ra, Rb`     | `Rc = 0`                          |
| `0x06`            | `RCPFX`    | `Rd, Ra`         | `Rb = Rc = 0`; contrato pendiente |
| `0x07`            | `RSQRTFX`  | `Rd, Ra`         | `Rb = Rc = 0`; contrato pendiente |
| `0x08`            | `PACK565`  | `Rd, Ra`         | `Rb = Rc = 0`                     |
| `0x09`            | `CLZ`      | `Rd, Ra`         | `Rb = Rc = 0`; vigente (§3, EXT)  |
| `0x0A–0x3F`       | Reservadas | —                | 54 suboperaciones disponibles     |

Un campo reservado a cero no es un operando leído. Los campos reservados no
nulos producen `ERROR_INVALID_ENCODING`; una función reservada o no soportada
produce `ERROR_INVALID_OPCODE`. Todas las operaciones respetan `R0=0`; en GPU
solo escriben las lanes activas y no modifican las máscaras SIMT.

### 7.4 Mapa conjunto y ocupación

#### Qué añadiría el conjunto completo

Sobre el repertorio vigente se proponen **11 operaciones nuevas**: seis
branches inmediatos y cinco operaciones bajo `EXT` (`SEL`, `MACFX`, `RCPFX`,
`RSQRTFX`, `PACK565`). Consumen **6 opcodes primarios nuevos**, los de los
branches: `EXT` ya está ocupado con `MIN/MAX/MINU/MAXU` y `CLZ` (vigentes en la
38). Dos operaciones EXT tienen contrato numérico pendiente. Los cinco
mnemónicos GETID ya están incorporados y no cuentan como novedades.

Portar capabilities existentes entre backends no consume nuevos opcodes.
`R0`, `JR`, las unidades de los saltos y todos los encodings vigentes,
incluidos `SLT/SLTU`, GETID y FP32, permanecen iguales.

El [catálogo de §3](#3-mapa-de-opcodes) es el mapa conjunto de referencia:
Vigente identifica asignaciones definidas, Propuesta v0.2 las ampliaciones
compatibles pendientes y Reservado los huecos sin asignar. No se reproduce
otro mapa paralelo aquí.

#### Ocupación

| Bloque de opcodes | Ocupados vigentes | Libres vigentes | Nuevos propuestos | Libres resultantes |
|---|---:|---:|---:|---:|
| `0x00–0x0F` | 16 | 0 | 0 | 0 |
| `0x10–0x1F` | 15 | 1 | 0 | 1 |
| `0x20–0x2F` | 12 | 4 | 4 | 0 |
| `0x30–0x3F` | 12 | 4 | 2 | 2 |
| **Total** | **55** | **9** | **6** | **3** |

El conjunto completo ocuparía **61 de 64 opcodes**, con **3 libres**:
`0x1F`, `0x36` y `0x37`. Quedan también **54 suboperaciones
EXT libres** (`func6 = 0x0A–0x3F`). Los bloques indican posiciones del mapa;
no imponen un formato único ni limitan la categoría semántica de sus operaciones.

No se puede recuperar `0x2E` sin romper compatibilidad. Si las nueve
operaciones EXT consumieran un opcode principal cada una, harían falta ocho
opcodes más que con EXT y se excedería el espacio disponible en tres.

## 8. Implementación y validación por backend

Esta sección describe trabajo por backend, sin nuevas asignaciones de opcode.
El soporte se comprueba en cada implementación; que una capability exista en
CPU o en un RTL GPU no garantiza que esté en la GPU funcional de la 11.

| Capability vigente | CPU funcional (2) | GPU funcional (11) | Trabajo restante en la GPU funcional |
|---|---|---|---|
| `mul_div` | Sí | Sí | Mantener el contrato de `MUL`, `MULFX` y `DIV` |
| `calls` | Sí | Sí | Mantener la regresión de destinos indirectos |
| `subword_memory` | Sí | Sí | Mantener la regresión de tamaños, máscaras y errores |
| `shift_immediate` | Sí | No | Bit 10 y selección de cantidad |
| `alu_extended` | Sí | No | `MULHI`, `DIVU`, `REM`, `REMU` por lane |
| `compare` | Sí | No | `SLT`, `SLTU` por lane |
| `fp32` | Sí | No | Operaciones FP32 por lane, si se incorpora esta capability |
| `minmax` | Sí | No | `MIN`, `MAX`, `MINU`, `MAXU` por lane (`EXT`) |
| `clz` | Sí | No | `CLZ` por lane (`EXT`) |

El estado funcional anterior es el de los núcleos que reutiliza la 32. El
modelo de ciclos de la 25 y los prototipos FPGA tienen su propia disponibilidad;
por ejemplo, el RTL GPU de la 37 ya implementa `shift_immediate`,
`alu_extended` y `compare`. Un port conserva siempre los encodings y los
contratos de `isa.md`.

### 8.1 Portabilidad de accesos pequeños

El contrato de v0.1 ya está en CPU y GPU funcionales: offset16 signed en bytes,
little-endian, alineación par para medias palabras y conservación de bytes
vecinos. Solo acceden las lanes activas; se valida el intervalo completo de
cada acceso. Los accesos subpalabra a MMIO se rechazan según `mmio.md` §4.1.

Al portar a otro backend, la interfaz SM↔LSU debe transportar el tamaño. Las
respuestas conservan la asociación con warp/lane y sus errores. Aceptar una
petición no equivale a completarla: `BAR` debe esperar estos accesos. Esta
propuesta no añade atómicos ni orden entre escrituras solapadas de distintos
warps, ni una garantía nueva de rollback global ante un fallo parcial de un
backend físico.

Un backend EBR necesita habilitaciones por byte; uno SDRAM, máscaras adecuadas
al tamaño y a la posición del dato. Los detalles de ráfagas y transferencias
pertenecen a cada implementación, no al contrato de la instrucción.

### 8.2 Plan de implementación y validación

| Componente              | Trabajo pendiente                                                         |
|-------------------------|---------------------------------------------------------------------------|
| `1.isa/asm2/mini-asm.py` | Mnemónicos y encodings de los seis branches y nueve operaciones EXT; validación de operandos |
| `2.cpu-sim-func`        | Referencia funcional de las operaciones nuevas adoptadas                  |
| `11.gpu-sim-func`       | Nuevas operaciones, capabilities portadas, máscaras y fallos              |
| CPU RTL basada en la 21 | Decodificación y datapaths de las capabilities elegidas                   |
| GPU RTL                 | Portar capabilities existentes y añadir las nuevas elegidas, incluida LSU |
| Monitor/lanzador | Mantener la configuración existente de `LOGICAL_WARP_ID`/`WARP_ARG` y la identificación de backends |
| `t.tests`           | Declaración de capabilities, `requires` y pruebas diferenciales           |
| `1.isa/isa.md` | Actualizar el estado de propuestas adoptadas y su disponibilidad verificada |

No es necesario portar una extensión a todas las carpetas históricas para
incorporarla a un backend. Cada backend debe declarar únicamente lo que implementa.

La validación debe cubrir:

- Branches: límites de `imm5` y `offset16`, extensión signed/unsigned, igualdad
  con `-1`, saltos tomados/no tomados y divergencia/reconvergencia en GPU.
- Identificadores: lanes/warps distintos, máscara activa, descarte en `R0`,
  reset del sistema, conservación de descriptores en `GPU_CONTROL.RESET`,
  pausa/reanudación y traslado del ID lógico entre slots.
- Calls GPU: destinos efectivos uniformes y divergentes, registros coincidentes,
  enlace descartado en `R0`, alineación y efectos observables del fallo.
- Memoria GPU: tamaños, extensión, bytes vecinos, offsets negativos, límites,
  alineación, errores por lane y finalización antes de `BAR`.
- EXT: funciones no soportadas, campos reservados, operandos coincidentes,
  extremos signed/unsigned, equivalencia de `MACFX` a `MULFX`+`ADD` y colores RGB565.
- Aritmética portada a GPU: signos, overflow, división por cero y máscaras activas.
- Regresión: conservar los resultados y encodings de programas v0.1; medir
  rendimiento por separado de la equivalencia funcional.

Esta revisión actualiza la propuesta documental y sus asignaciones aún no
implementadas. No implementa instrucciones, no registra capabilities nuevas y
no cambia los encodings ni los contratos de la ISA vigente.
