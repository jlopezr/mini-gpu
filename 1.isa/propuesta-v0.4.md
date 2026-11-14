# Propuesta de MiniISA v0.4

## 1. Alcance

Este es el documento único y autocontenido de la propuesta MiniISA v0.4.
Consolida el repertorio y las capabilities propuestos en v0.3 con:

- privilegios, traps precisos, interrupciones y protección física de memoria;
- operaciones atómicas y orden de memoria compartido entre CPU, GPU y DMA.

Este documento es una **propuesta documental**. No afirma que el ensamblador,
los simuladores ni el RTL actuales implementen v0.4.

Para consultar el repertorio, véanse las [capabilities](#3-compatibilidad-y-perfiles)
y los [encodings y contratos](#5-mapa-de-opcodes-v04). Los apartados §6–§14
tratan el sistema privilegiado y la memoria; §15 recoge la validación. Las
[guías gráficas](#18-guía-no-normativa-de-uso-gráfico), de tablas y trigonometría
(§18–§20) son explicativas y no añaden instrucciones al mapa.

El mapa de este documento agrupa ALU y shifts, reserva un opcode por condición
de branch y regulariza las fuentes de branches/MTSR. Esta revisión documental
no cambia los encodings implementados de `isa.md` ni anuncia soporte de v0.4.

v0.4 no conserva binarios de revisiones anteriores. Un ejecutable debe
identificar su versión de ISA independientemente de sus capabilities.

### 1.1 Núcleo consolidado

- Instrucciones, datos y PC son de 32 bits; memoria byte-addressed,
  little-endian; instrucciones alineadas a cuatro bytes.
- `R0` siempre lee cero y descarta escrituras. `R1–R31` son generales;
  `R30` es pila y `R31` enlace por convención ABI.
- No hay FLAGS ni delay slots; la aritmética entera envuelve módulo 2^32.
- `MULFX` usa Q16.16; DIV signed trunca hacia cero; `-2^31 / -1` devuelve
  `0x80000000`; las variantes restantes conservan sus nombres y semántica
  declarados en su familia.
- Los backends anuncian capabilities. Una operación definida pero ausente no
  se convierte en hueco libre; con traps privilegiados causa
  `ILLEGAL_INSTRUCTION`, y sin ellos conserva el fallo fatal del backend.

Las formas canónicas de ensamblador son:

```text
R-Type:  opcode | Rd | Ra | Rb | Rc | func6
I-Type:  opcode | X/Rd | Y/Ra | imm16
B-Type:  opcode | signed offset26 en palabras, relativo a PC+4
```

Cada instrucción define qué campos utiliza y su significado. `Rc` puede actuar
como fuente cuando la instrucción lo especifique, como en `SEL` y `ATOMCAS`.
Los campos no utilizados deben codificarse a cero.

Los shifts usan R-Type con Rc=0 y el modo en func6; no hay bit I separado.
Las fuentes GPR ordinarias están en Ra[20:16] y Rb[15:11]. Los branches usan
esas mismas posiciones, con imm5 en el lugar de Rb para BRI y un off16 repartido
entre los bits [25:21] y [10:0]. JALR conserva el inmediato en palabras y
elimina los dos bits bajos del destino. Los campos reservados deben ser cero.

## 2. Decisiones principales

1. `TRAP` sin argumento sigue siendo una parada fatal; `ABORT` es su alias.
2. `TRAP número` es una entrada síncrona recuperable al supervisor y codifica
   directamente el número de syscall.
3. `ERET`, `MFSR`, `MTSR` y `FENCE` comparten una familia `SYSTEM`.
4. `ATOMADD` y `ATOMCAS` comparten una familia `ATOMIC`.
5. Los atómicos operan inicialmente solo sobre palabras de 32 bits alineadas.
6. `ATOMCAS` usa la dirección exacta de `Ra`; no dispone de offset inmediato.
7. USER/SUPERVISOR no se presenta como aislamiento suficiente: v0.4 define una
   protección física mínima por regiones, separada de una futura MMU.
8. `TRAP`, excepciones e interrupciones entran por el mismo mecanismo preciso.
9. Las operaciones atómicas tienen semántica acquire-release y `FENCE` es una
   barrera completa para el master que la ejecuta.

## 3. Compatibilidad y perfiles

Se añaden las siguientes capabilities:

| Capability          | Contrato                                                   |
|---------------------|------------------------------------------------------------|
| `privileged_traps`  | USER/SUPERVISOR, SR, `TRAP`, `ERET`, `ENTERUSER`, DIRECT  |
| `vectored_traps`    | Modo VECTORED de `TVEC`                                    |
| `interrupts`        | Interrupciones precisas, `IRQ_PENDING` y `IRQ_ENABLE`       |
| `memory_protection` | Cuatro regiones físicas con permisos R/W/X por modo         |
| `atomics`           | `ATOMADD`, `ATOMCAS` y arbitraje atómico del fabric         |
| `memory_fence`      | `FENCE` y el modelo de orden de §11                         |

Las capabilities de repertorio se definen por versión de ISA. Sus nombres no
implican soporte del perfil v0.4 en un backend que solo ejecuta la ISA vigente.
Compartir opcode no obliga a implementar otras capabilities de la misma familia.

| Capability | Instrucciones | Ámbito / dependencia |
|---|---|---|
| `mul_div` | `MUL`, `MULFX`, `DIV` | CPU / GPU |
| `subword_memory` | `LOADB`, `LOADUB`, `LOADH`, `LOADUH`, `STOREB`, `STOREH` | CPU / GPU |
| `calls` | `JAL`, `JALR`, alias `JR/RET` | CPU / GPU |
| `shift_immediate` | `SHLI`, `SHRI`, `SARI` | CPU / GPU |
| `alu_extended` | `MULHI`, `DIVU`, `REM`, `REMU` | CPU / GPU; requiere `mul_div` |
| `compare` | `SLT`, `SLTU`, `SLTI`, `SLTIU` | CPU / GPU |
| `branch_immediate` | `BEQI`, `BNEI`, `BLTI`, `BGEI`, `BLTUI`, `BGEUI` | CPU / GPU |
| `gpu_ids` | `GETLANE`, `GETWARP`, `GETLWARP`, `GETARG` | GPU; incluye configuración del ID lógico y argumento |
| `minmax` | `MIN`, `MAX`, `MINU`, `MAXU` | CPU / GPU |
| `select` | `SEL` | CPU / GPU |
| `macfx` | `MACFX` | CPU / GPU |
| `pack565` | `PACK565` | CPU / GPU |
| `rcpfx` | `RCPFX` | Contrato propuesto en `isa.md` §7.3 |
| `rsqrtfx` | `RSQRTFX` | Propuesta de retirada en favor de `FSQRT` (`isa.md` §7.3) |
| `mul_high_variants` | `MULHU`, `MULHSU` | CPU / GPU |
| `unpack565` | `UNPACK565R`, `UNPACK565G`, `UNPACK565B` | CPU / GPU |
| `bit_count` | `CLZ`, `POPC` | CPU / GPU |
| `store_postincrement` | `STOREBP`, `STOREHP`, `STOREP` | CPU / GPU; requiere `subword_memory` |
| `warp_vote` | `BALLOT`, `ACTIVEMASK` | GPU |
| `warp_shuffle` | `SHFL` | GPU |
| `pc_relative_address` | `LEAPC` | CPU / GPU |
| `indexed_load` | `LOADX` de 32 bits | CPU / GPU |
| `fp32` | `FADD`, `FSUB`, `FMUL`, `FDIV`, `FEQ`, `FLT`, `FLE`, `FTOI`, `ITOF` | CPU / GPU |

`rcpfx` no puede declararse hasta aprobar su contrato (propuesto en `isa.md`
§7.3) y tener modelo de referencia; para `rsqrtfx` se propone la retirada. Las demás capabilities de esta propuesta tampoco se anuncian hasta
implementar y validar todas sus instrucciones. No existe capability de familia
MUL, DIV o EXT que sustituya a esta tabla. `R0=0` es obligatorio y la reutilización
interna de resultados o el número de ciclos no constituyen capabilities.

Dependencias:

- `mul_div` es opcional y comprende `MUL`, `MULFX` y `DIV`, fuera de la base.
  `alu_extended` requiere `mul_div`; cada suboperación conserva su capability
  aunque comparta opcode con otras familias aritméticas.
- `compare` comprende `SLT`, `SLTU`, `SLTI` y `SLTIU` en CPU y GPU, como
  en v0.3. Declararla exige las cuatro; sin ella son operaciones no soportadas.
  En v0.1/v0.2 solo comprende `SLT/SLTU`: se interpreta junto con la versión
  de ISA y no modifica lo exigido a los backends de esas versiones.

- `interrupts`, `memory_protection` y `vectored_traps` requieren
  `privileged_traps`.
- `atomics` requiere que todos los masters coherentes alcancen el mismo punto
  de serialización. No puede declararse si CPU y GPU ven memorias privadas sin
  un fabric que preserve el contrato.
- `memory_fence` puede implementarse como NOP en un master completamente
  bloqueante, pero debe seguir reconociéndose como instrucción válida.

Una implementación v0.4 sin `privileged_traps` puede ejecutar `TRAP` sin
argumento y su alias `ABORT`, pero rechaza `TRAP número` como instrucción no
soportada. No se permite que un `TRAP número` signifique syscall en CPU y aborto
en GPU.

`privileged_traps`, `interrupts`, `memory_protection` y `vectored_traps` son
capabilities de CPU en v0.4. La GPU no tiene warps USER/SUPERVISOR, `ERET` ni
syscalls: conserva su modelo de errores globales. Esta separación evita definir
una entrada de trap ambigua cuando lanes divergentes o varios warps fallan a la
vez; una futura GPU con privilegios requerirá una extensión propia.

## 4. Formatos v0.4

El formato R-Type reparte los campos de registro y la suboperación:

```text
31       26 25   21 20   16 15   11 10    6 5          0
+----------+-------+-------+-------+-------+------------+
| opcode   |  Rd   |  Ra   |  Rb   |  Rc   |   func6    |
+----------+-------+-------+-------+-------+------------+
```

I-Type contiene dos campos cuyo significado depende de la instrucción:

```text
31       26 25   21 20   16 15                         0
+----------+-------+-------+----------------------------+
|  opcode  | X/Rd  | Y/Ra  |           imm16            |
+----------+-------+-------+----------------------------+
     6         5       5                 16
```

X e Y pueden representar destino, fuente, tipo GETID o registro a almacenar.
Lo usan los inmediatos, accesos ordinarios de memoria, JALR y GETID.

B-Type contiene el desplazamiento de BRA y SSY:

```text
31       26 25                                        0
+----------+------------------------------------------+
|  opcode  |             signed off26                 |
+----------+------------------------------------------+
     6                         26
```

El offset está en palabras y es relativo a PC+4. SSY registra el destino de
reconvergencia; no realiza un salto.

Los shifts usan R-Type con opcode 0x04, Rc=0 y Rb/imm5 en bits [15:11].
Func6 selecciona dirección y forma por registro o inmediata (§5.1.10); el bit
10 vuelve a formar parte de Rc reservado a cero. No existe un bit I separado.
Los branches mantienen Ra/Rb en las posiciones de R-Type; su off16 repartido
se define en §5.4.6, no como inmediato I-Type contiguo.

Los campos no utilizados deben ser cero. Una subfunción no soportada produce
`ERROR_INVALID_OPCODE`; campos reservados no nulos producen
`ERROR_INVALID_ENCODING` cuando no existe un trap privilegiado. Con
`privileged_traps`, ambos se convierten en `ILLEGAL_INSTRUCTION`.

### 4.1 Familia ATOMIC — `0x0B`

| `func6` | Instrucción                    | Campos                         |
|---------|--------------------------------|--------------------------------|
| `0x00`  | `ATOMADD Rd, Ra, Rb`           | `Rc=0`                         |
| `0x01`  | `ATOMCAS Rd, Ra, Rb, Rc`       | todos los registros utilizados |

`Ra` contiene la dirección exacta. Esta familia no tiene variante
`[Ra + imm]`: `ATOMCAS` necesita destino, dirección, esperado y deseado, que
ocupan los cuatro campos de registro. El software suma antes el offset cuando
lo necesita.

### 4.2 Familia SYSTEM — `0x36`

| `func6` | Instrucción    | Codificación                                      |
|---------|----------------|---------------------------------------------------|
| `0x00`  | `ERET`         | `Rd=Ra=Rb=Rc=0`                                   |
| `0x01`  | `FENCE`        | `Rd=Ra=Rb=Rc=0`                                   |
| `0x02`  | `MFSR Rd, SRn` | `Rd=destino`, `Ra=SRn`, `Rb=Rc=0`                 |
| `0x03`  | `MTSR SRn, Rs` | `Rd=SRn`, `Ra=Rs`, `Rb=Rc=0`                      |
| `0x04`  | `ENTERUSER`    | `Rd=Ra=Rb=Rc=0`                                   |

MTSR lee su fuente GPR en Ra, como las operaciones ordinarias; su campo Rd
contiene el índice SRn, no un destino GPR. MFSR escribe el Rd normal y usa Ra
como índice SRn, sin leerlo como GPR. El decodificador distingue estos papeles.
El campo de cinco bits `SRn` permite 32 registros de sistema. Los nombres
simbólicos son parte de la sintaxis del ensamblador; el hardware recibe su
índice numérico.

### 4.3 TRAP y ABORT — `0x3E`

`TRAP` utiliza los 26 bits bajos como número de syscall sin signo.

`TRAP` sin argumento codifica cero. Detiene el agente con
`ERROR_EXPLICIT_TRAP` cuando se ejecuta en supervisor, conserva como PC
observable la dirección de la instrucción y no permite `ERET`. En CPU USER no
detiene la máquina: produce `PRIVILEGED_INSTRUCTION`. En GPU el error es global,
pues v0.4 no define modos GPU. `ABORT` es un alias exacto de esta forma y no
consume otro opcode.

`TRAP número`, con `número` entre 1 y `0x03FF_FFFF`, requiere
`privileged_traps` y causa una excepción software recuperable:

```text
EPC     = PC + 4
CAUSE   = 0x04000000 | número
BADADDR = 0
entrar_trap(SUPERVISOR)
```

El handler obtiene el número mediante `CAUSE & 0x03FF_FFFF`. Los argumentos y
resultados pertenecen a la ABI y viajan en registros generales. El valor cero
queda reservado para la forma fatal y no puede nombrar una syscall.

`TRAP número` solo es válido desde USER. Ejecutarlo desde SUPERVISOR produciría
una segunda entrada síncrona sin banco adicional para conservar el contexto;
por ello termina con `ERROR_DOUBLE_FAULT` fatal y no modifica los registros de
trap. El kernel usa `ABORT` si necesita una parada deliberada.

La ABI inicial de syscall fija `R1`–`R4` como los cuatro argumentos de entrada.
Al retornar mediante `ERET`, `R1` contiene el valor de retorno y `R2` el código
de error (`0` significa éxito). Un servicio con menos argumentos simplemente
ignora los registros sobrantes; uno que devuelva más valores puede definirlos
documentadamente en `R3` y `R4`. `R0` permanece siempre cero.

Una syscall es una frontera de llamada voluntaria: conforme a la ABI existente,
`R1–R15` son volátiles y `R16–R29` deben preservarse. `R30` se restaura por el
intercambio con `KSP`; `R31` también debe preservarse, pues `TRAP` no es una
llamada que escriba enlace. En cambio, una interrupción asíncrona debe ser
transparente: su handler preserva todos los registros generales del contexto
interrumpido. Si la interrumpe en USER, el hardware ya conserva `R30` mediante
el intercambio `KSP`; si la interrumpe en supervisor, el handler debe preservar
también el `R30` de kernel que vaya a modificar.

v0.4 no reserva números concretos de syscall. La ISA solo transporta el número
en `TRAP número` y fija los registros de llamada; cada kernel o ABI publica su
propia tabla de servicios sin alterar los opcodes ni el mecanismo de trap.

## 5. Mapa de opcodes v0.4

Este catálogo es el mapa de referencia del perfil v0.4. Las definiciones de
cada fila se enlazan a los contratos detallados de este mismo documento.

#### Lectura y soporte funcional

- **Estado** indica el estado de la instrucción en la propuesta y si su contrato
  está pendiente.
- **Sim. funcional del perfil (CPU / GPU)** se refiere a ejecutar el perfil de
  ISA v0.4. Actualmente no hay selección ni implementación de ese perfil
  en los núcleos de [CPU (2)](../2.cpu-sim-func/minicpu_core.py) y
  [GPU (11)](../11.gpu-sim-func/minigpu_core.py), reutilizados por
  [el integrado (32)](../32.cpu-gpu-func-sim/cpu_gpu_core.py): figura `No / No`.
  Algunas instrucciones coinciden individualmente con el encoding vigente
  (por ejemplo `ADD`); su soporte actual se consulta en el otro índice. La
  coincidencia del nombre o de una palabra no implica soporte de todo el perfil.
- Las capabilities y los mnemónicos son los de esta propuesta. Los IDs
  adicionales de GPU comparten `gpu_ids`; el ID lógico se denomina
  `GETLWARP`/`LOGICAL_WARP_ID`. `GETTID` sigue perteneciendo a la base.
- `SSY` y `BAR` conservan la etiqueta Base (GPU) por su función SIMT. En CPU
  se reconocen como NOP con validación de encoding, sin sincronización ni
  efecto de FENCE; continúan en `PC+4`.
- `compare` exige `SLT`, `SLTU`, `SLTI` y `SLTIU` en v0.4, tanto
  en CPU como en GPU. En v0.1/v0.2 solo exige `SLT/SLTU`; el soporte se
  interpreta siempre junto con la versión de ISA.
- V0.4 incluye las definiciones completas de los selectores heredados y los
  de ATOMIC/SYSTEM/FP32. Las definiciones se enlazan a esa referencia consolidada.

- ALU usa `0x01/func6`; SHIFT usa `0x04/func6` y Rc=0, sin bit I separado.
  BR/BRI mantienen Ra[20:16] y Rb/imm5[15:11]; off16 se reconstruye con
  `{instruction[25:21], instruction[10:0]}`. MTSR lee su fuente en Ra y lleva
  el índice SRn en Rd.

#### Catálogo por opcode y selector

La tabla contiene **98 formas de instrucción** (dos formas de `TRAP`),
que ocupan **55 opcodes primarios** en v0.4, y los **9 huecos**
libres de ese mapa.

| Opcode y selector | Categoría | Extensión / ámbito | Instrucción | Operandos | Estado | Sim. funcional del perfil (CPU / GPU) | Definición |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `0x00` | Sistema | Base | `NOP` | — | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x01`; `func6 = 0x00` | Aritmética | Base | `ADD` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x01`; `func6 = 0x01` | Aritmética | Base | `SUB` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x01`; `func6 = 0x02` | Lógica | Base | `AND` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x01`; `func6 = 0x03` | Lógica | Base | `OR` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x01`; `func6 = 0x04` | Lógica | Base | `XOR` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x01`; `func6 = 0x05` | Comparaciones | `compare` | `SLT` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#548-comparaciones-y-alias-de-ensamblador) |
| `0x01`; `func6 = 0x06` | Comparaciones | `compare` | `SLTU` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#548-comparaciones-y-alias-de-ensamblador) |
| `0x02`; `func6 = 0x00` | Multiplicación | `mul_div` | `MUL` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#511-mul--0x02) |
| `0x02`; `func6 = 0x01` | Multiplicación | `alu_extended` | `MULHI` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#511-mul--0x02) |
| `0x02`; `func6 = 0x02` | Multiplicación | `mul_high_variants` | `MULHU` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#511-mul--0x02) |
| `0x02`; `func6 = 0x03` | Multiplicación | `mul_high_variants` | `MULHSU` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#511-mul--0x02) |
| `0x02`; `func6 = 0x04` | Multiplicación | `mul_div` | `MULFX` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#511-mul--0x02) |
| `0x02`; `func6 = 0x05` | Multiplicación | `macfx` | `MACFX` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#511-mul--0x02) |
| `0x03`; `func6 = 0x00` | División | `mul_div` | `DIV` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#512-div--0x03) |
| `0x03`; `func6 = 0x01` | División | `alu_extended` | `DIVU` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#512-div--0x03) |
| `0x03`; `func6 = 0x02` | División | `alu_extended` | `REM` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#512-div--0x03) |
| `0x03`; `func6 = 0x03` | División | `alu_extended` | `REMU` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#512-div--0x03) |
| `0x04`; `func6 = 0x00` | Desplazamientos | Base | `SHL` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#11-núcleo-consolidado) |
| `0x04`; `func6 = 0x01` | Desplazamientos | `shift_immediate` | `SHLI` | `Rd, Ra, imm5` | Propuesta v4 | No / No | [v0.4](#11-núcleo-consolidado) |
| `0x04`; `func6 = 0x02` | Desplazamientos | Base | `SHR` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#11-núcleo-consolidado) |
| `0x04`; `func6 = 0x03` | Desplazamientos | `shift_immediate` | `SHRI` | `Rd, Ra, imm5` | Propuesta v4 | No / No | [v0.4](#11-núcleo-consolidado) |
| `0x04`; `func6 = 0x04` | Desplazamientos | Base | `SAR` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#11-núcleo-consolidado) |
| `0x04`; `func6 = 0x05` | Desplazamientos | `shift_immediate` | `SARI` | `Rd, Ra, imm5` | Propuesta v4 | No / No | [v0.4](#11-núcleo-consolidado) |
| `0x05`; `func6 = 0x00` | Píxeles | `pack565` | `PACK565` | `Rd, Ra` | Propuesta v4 | No / No | [v0.4](#542-pix565--0x05) |
| `0x05`; `func6 = 0x01` | Píxeles | `unpack565` | `UNPACK565R` | `Rd, Ra` | Propuesta v4 | No / No | [v0.4](#542-pix565--0x05) |
| `0x05`; `func6 = 0x02` | Píxeles | `unpack565` | `UNPACK565G` | `Rd, Ra` | Propuesta v4 | No / No | [v0.4](#542-pix565--0x05) |
| `0x05`; `func6 = 0x03` | Píxeles | `unpack565` | `UNPACK565B` | `Rd, Ra` | Propuesta v4 | No / No | [v0.4](#542-pix565--0x05) |
| `0x06`; `func6 = 0x00` | Límites | `minmax` | `MIN` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#513-minmax--0x06) |
| `0x06`; `func6 = 0x01` | Límites | `minmax` | `MAX` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#513-minmax--0x06) |
| `0x06`; `func6 = 0x02` | Límites | `minmax` | `MINU` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#513-minmax--0x06) |
| `0x06`; `func6 = 0x03` | Límites | `minmax` | `MAXU` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#513-minmax--0x06) |
| `0x07`; `func6 = 0x00` | Selección | `select` | `SEL` | `Rd, Ra, Rb, Rc` | Propuesta; uso de Rc unificado | No / No | [v0.4](#514-select--0x07) |
| `0x08`; `func6 = 0x00` | Bits | `bit_count` | `CLZ` | `Rd, Ra` | Propuesta v4 | No / No | [v0.4](#515-bit--0x08) |
| `0x08`; `func6 = 0x01` | Bits | `bit_count` | `POPC` | `Rd, Ra` | Propuesta v4 | No / No | [v0.4](#515-bit--0x08) |
| `0x09`; `func6 = 0x00` | Coma fija | `rcpfx` | `RCPFX` | `Rd, Ra, k` | Contrato propuesto (`isa.md` §7.3) | No / No | [v0.4](#516-fxmath--0x09) |
| `0x09`; `func6 = 0x01` | Coma fija | `rsqrtfx` | `RSQRTFX` | `Rd, Ra` | Propuesta de retirada | No / No | [v0.4](#516-fxmath--0x09) |
| `0x0A`; `func6 = 0x00` | Coma flotante | `fp32` (CPU / GPU) | `FADD` | `Rd, Ra, Rb` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0A`; `func6 = 0x01` | Coma flotante | `fp32` (CPU / GPU) | `FSUB` | `Rd, Ra, Rb` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0A`; `func6 = 0x02` | Coma flotante | `fp32` (CPU / GPU) | `FMUL` | `Rd, Ra, Rb` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0A`; `func6 = 0x03` | Coma flotante | `fp32` (CPU / GPU) | `FDIV` | `Rd, Ra, Rb` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0A`; `func6 = 0x04` | Coma flotante | `fp32` (CPU / GPU) | `FEQ` | `Rd, Ra, Rb` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0A`; `func6 = 0x05` | Coma flotante | `fp32` (CPU / GPU) | `FLT` | `Rd, Ra, Rb` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0A`; `func6 = 0x06` | Coma flotante | `fp32` (CPU / GPU) | `FLE` | `Rd, Ra, Rb` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0A`; `func6 = 0x07` | Coma flotante | `fp32` (CPU / GPU) | `FTOI` | `Rd, Ra, fbits` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0A`; `func6 = 0x08` | Coma flotante | `fp32` (CPU / GPU) | `ITOF` | `Rd, Ra, fbits` | Propuesta v4; contrato numérico vigente | No / No | [v0.4](#55-familia-fp32--0x0a) |
| `0x0B`; `func6 = 0x00` | Atómicos | `atomics` | `ATOMADD` | `Rd, Ra, Rb` | Propuesta v4 | No / No | [v0.4](#41-familia-atomic--0x0b) |
| `0x0B`; `func6 = 0x01` | Atómicos | `atomics` | `ATOMCAS` | `Rd, Ra, Rb, Rc` | Propuesta v4; uso de Rc unificado | No / No | [v0.4](#41-familia-atomic--0x0b) |
| `0x0C` | Comparaciones | `compare` | `SLTI` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#548-comparaciones-y-alias-de-ensamblador) |
| `0x0D` | Comparaciones | `compare` | `SLTIU` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#548-comparaciones-y-alias-de-ensamblador) |
| `0x0E` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x0F` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x10` | Constantes | Base | `MOVI` | `Rd, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x11` | Inmediatos | Base | `ADDI` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x12` | Inmediatos | Base | `ANDI` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x13` | Inmediatos | Base | `ORI` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x14` | Inmediatos | Base | `XORI` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x15` | Memoria | Base | `LOAD` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x16` | Memoria | Base | `STORE` | `Rs, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x17` | Constantes | Base | `MOVHI` | `Rd, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x18` | Memoria | `subword_memory` | `LOADB` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x19` | Memoria | `subword_memory` | `LOADUB` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x1A` | Memoria | `subword_memory` | `LOADH` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x1B` | Memoria | `subword_memory` | `LOADUH` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x1C` | Memoria | `subword_memory` | `STOREB` | `Rs, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x1D` | Memoria | `subword_memory` | `STOREH` | `Rs, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#541-inmediatos-y-accesos-ordinarios) |
| `0x1E`; `size = 0` | Store postincremental | `store_postincrement` | `STOREBP` | `Rs, Ra, imm14` | Propuesta v4 | No / No | [v0.4](#543-stores-postincrementales--0x1e) |
| `0x1E`; `size = 1` | Store postincremental | `store_postincrement` | `STOREHP` | `Rs, Ra, imm14` | Propuesta v4 | No / No | [v0.4](#543-stores-postincrementales--0x1e) |
| `0x1E`; `size = 2` | Store postincremental | `store_postincrement` | `STOREP` | `Rs, Ra, imm14` | Propuesta v4 | No / No | [v0.4](#543-stores-postincrementales--0x1e) |
| `0x1F`; `func6 = escala (0–3)` | Carga indexada | `indexed_load` | `LOADX` | `Rd, Ra, Rb, escala` | Propuesta v4 | No / No | [v0.4](#545-loadx--0x1f) |
| `0x20` | Saltos | Base | `BEQ` | `Ra, Rb, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x21` | Saltos | Base | `BNE` | `Ra, Rb, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x22` | Saltos | Base | `BLT` | `Ra, Rb, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x23` | Saltos | Base | `BGE` | `Ra, Rb, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x24` | Saltos | Base | `BLTU` | `Ra, Rb, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x25` | Saltos | Base | `BGEU` | `Ra, Rb, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x26` | Saltos y llamadas | Base | `BRA` | `target` | Propuesta v4 | No / No | [v0.4](#547-bra-jal-y-jalr) |
| `0x27` | Saltos y llamadas | `calls` | `JAL` | `Rd, target` | Propuesta v4 | No / No | [v0.4](#547-bra-jal-y-jalr) |
| `0x28` | Saltos | `branch_immediate` | `BEQI` | `Ra, imm5, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x29` | Saltos | `branch_immediate` | `BNEI` | `Ra, imm5, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x2A` | Saltos | `branch_immediate` | `BLTI` | `Ra, imm5, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x2B` | Saltos | `branch_immediate` | `BGEI` | `Ra, imm5, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x2C` | Saltos | `branch_immediate` | `BLTUI` | `Ra, imm5, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x2D` | Saltos | `branch_immediate` | `BGEUI` | `Ra, imm5, target` | Propuesta v4 | No / No | [v0.4](#546-branches-condicionales-con-off16) |
| `0x2E` | Saltos y llamadas | `calls` | `JALR` | `Rd, Ra, imm16` | Propuesta v4 | No / No | [v0.4](#547-bra-jal-y-jalr) |
| `0x2F` | Direcciones | `pc_relative_address` | `LEAPC` | `Rd, label` | Propuesta v4 | No / No | [v0.4](#544-leapc--0x2f) |
| `0x30`; `type = 0` | Identificadores | Base | `GETTID` | `Rd` | Propuesta v4 | No / No | [v0.4](#517-getid--0x30) |
| `0x30`; `type = 1` | Identificadores | `gpu_ids` (GPU) | `GETLANE` | `Rd` | Propuesta v4 | No / No | [v0.4](#517-getid--0x30) |
| `0x30`; `type = 2` | Identificadores | `gpu_ids` (GPU) | `GETWARP` | `Rd` | Propuesta v4 | No / No | [v0.4](#517-getid--0x30) |
| `0x30`; `type = 3` | Identificadores | `gpu_ids` (GPU) | `GETLWARP` | `Rd` | Propuesta; nombre y capability unificados | No / No | [v0.4](#517-getid--0x30) |
| `0x30`; `type = 4` | Identificadores | `gpu_ids` (GPU) | `GETARG` | `Rd` | Propuesta v4; incorporada de la ISA vigente | No / No | [v0.4](#517-getid--0x30) |
| `0x31` | Control SIMT | Base (GPU) | `SSY` | `label` | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x32` | Control SIMT | Base (GPU) | `BAR` | — | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x33` | Control SIMT | Base (GPU) | `EXIT` | — | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x34`; `func6 = 0x00` | Votos | `warp_vote` (GPU) | `BALLOT` | `Rd, Ra` | Propuesta v4 | No / No | [v0.4](#518-vote--0x34) |
| `0x34`; `func6 = 0x01` | Votos | `warp_vote` (GPU) | `ACTIVEMASK` | `Rd` | Propuesta v4 | No / No | [v0.4](#518-vote--0x34) |
| `0x35`; `func6 = 0x00` | Intercambio entre lanes | `warp_shuffle` (GPU) | `SHFL` | `Rd, Ra, Rb` | Propuesto en v4; contrato unificado | No / No | [v0.4](#51-contratos-del-repertorio) |
| `0x36`; `func6 = 0x00` | Sistema | `privileged_traps` | `ERET` | — | Propuesta v4; contrato común por referencia | No / No | [v0.4](#42-familia-system--0x36) |
| `0x36`; `func6 = 0x01` | Sistema | `memory_fence` | `FENCE` | — | Propuesta v4; contrato común por referencia | No / No | [v0.4](#42-familia-system--0x36) |
| `0x36`; `func6 = 0x02` | Sistema | `privileged_traps` | `MFSR` | `Rd, SRn` | Propuesta v4; contrato común por referencia | No / No | [v0.4](#42-familia-system--0x36) |
| `0x36`; `func6 = 0x03` | Sistema | `privileged_traps` | `MTSR` | `SRn, Rs` | Propuesta v4; contrato común por referencia | No / No | [v0.4](#42-familia-system--0x36) |
| `0x36`; `func6 = 0x04` | Sistema | `privileged_traps` | `ENTERUSER` | — | Propuesta v4; contrato común por referencia | No / No | [v0.4](#42-familia-system--0x36) |
| `0x37` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x38` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x39` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x3A` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x3B` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x3C` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x3D` | Sin asignar | — | — | — | Libre en v4 | No / No | [v0.4](#5-mapa-de-opcodes-v04) |
| `0x3E`; `número = 0` | Parada | Base | `TRAP` | — | Propuesta v4 | No / No | [v0.4](#43-trap-y-abort--0x3e) |
| `0x3E`; `número = 1–0x03FFFFFF` | Syscall | `privileged_traps` (CPU) | `TRAP` | `número` | Propuesta v4; contrato unificado | No / No | [v0.4](#43-trap-y-abort--0x3e) |
| `0x3F` | Parada | Base | `HALT` | — | Propuesta v4 | No / No | [v0.4](#51-contratos-del-repertorio) |

Los límites y campos reservados forman parte del contrato enlazado. En
particular, BR/BRI usan condición en opcode y off16 repartido, STOREP usa `size + imm14`, LOADX usa
`func6=escala`, GETID usa `type` e `imm16=0`, y `TRAP` en v0.4 dedica
los 26 bits bajos al número. Esta tabla no introduce un encoding alternativo.

El mapa asigna **55 opcodes principales y deja 9 libres**: `0x0E–0x0F` y
`0x37–0x3D`. Agrupar ALU y shifts libera ocho opcodes respecto al borrador
anterior; dedicar uno a cada condición de BR/BRI consume diez más para recuperar
off16. Las fuentes mantienen las posiciones R-Type a cambio de repartir el offset.
La agrupación no obliga a implementar otras capabilities de la misma familia
ni demuestra una reducción de LUTs o latencia. Los selectores libres quedan
reservados para extensiones afines.

### 5.1 Contratos del repertorio

Esta sección define los contratos y selectores completos del repertorio. En todas
las operaciones se leen las fuentes antes de escribir el destino; los alias de
registros son válidos y escribir `R0` descarta el resultado sin omitir efectos
ni errores.

`NOP` conserva opcode 0x00 y exige los 26 bits bajos a cero. Las operaciones
binarias simples usan la familia ALU (§5.1.9) y los shifts la familia SHIFT
(§5.1.10), ambas con Rc=0. Las subfunciones no asignadas están reservadas;
compartir opcode no cambia la capability de cada operación.

#### 5.1.1 MUL — `0x02`

| `func6`   | Mnemónico   | Operandos      | Semántica                                 |
| --------- | ----------- | -------------- | ----------------------------------------- |
| `0x00`    | `MUL`       | `Rd, Ra, Rb`   | low32 del producto                        |
| `0x01`    | `MULHI`     | `Rd, Ra, Rb`   | high32 de signed32 × signed32             |
| `0x02`    | `MULHU`     | `Rd, Ra, Rb`   | high32 de unsigned32 × unsigned32         |
| `0x03`    | `MULHSU`    | `Rd, Ra, Rb`   | high32 de signed32(Ra) × unsigned32(Rb)   |
| `0x04`    | `MULFX`     | `Rd, Ra, Rb`   | Q16.16 según §5.2                            |
| `0x05`    | `MACFX`     | `Rd, Ra, Rb`   | low32(old_Rd + MULFX(Ra, Rb))             |

`Rc=0` en todas. `MACFX` lee el antiguo destino como tercera fuente; no
introduce acumulación de 64 bits ni redondeo fusionado. Con `Rd=R0`, lee cero
y descarta el resultado. Puede requerir un ciclo adicional de lectura.
`MULH` puede aceptarse como alias de `MULHI`; nunca se elimina el nombre vigente.
El signo no afecta a los 32 bits bajos de `MUL`.

#### 5.1.2 DIV — `0x03`

| `func6`   | Mnemónico   | Operandos      |
| --------- | ----------- | -------------- |
| `0x00`    | `DIV`       | `Rd, Ra, Rb`   |
| `0x01`    | `DIVU`      | `Rd, Ra, Rb`   |
| `0x02`    | `REM`       | `Rd, Ra, Rb`   |
| `0x03`    | `REMU`      | `Rd, Ra, Rb`   |

`Rc=0`. DIV/REM interpretan signed32 y DIVU/REMU unsigned32. El cociente
signed trunca hacia cero y el resto tiene el signo del dividendo. En
`-2^31 / -1`, el cociente es `0x80000000` y el resto cero. Un divisor cero no
escribe Rd: causa `DIVISION_BY_ZERO` con traps CPU y error fatal sin ellos;
en GPU se mantiene el modelo de errores globales. No se confunde con FDIV.

Por ejemplo, el resto signed conserva el signo del dividendo:

```text
 7 rem  2 =  1       -7 rem  2 = -1
 7 rem -2 =  1       -7 rem -2 = -1
```

#### 5.1.3 MINMAX — `0x06`

`func6=0,1,2,3` selecciona respectivamente `MIN`, `MAX`, `MINU`, `MAXU`.
Operandos `Rd, Ra, Rb`; `Rc=0`. Se devuelve el menor/mayor operando según
comparación signed32 o unsigned32, sin saturación ni efectos de control.

Las cuatro ya están implementadas (CPU de la 38, simuladores 2 y 32) con el
mapa compatible de `isa.md`: `EXT` `0x1E`, `func6 = 0x00–0x03`, mismo contrato.

#### 5.1.4 SELECT — `0x07`

`func6=0`: `SEL Rd, Ra, Rb, Rc`, resultado `Ra` si el contenido de `Rc` no es
cero; `Rb` en caso contrario. Necesita tres lecturas y una escritura. No cambia
máscaras SIMT ni ejecuta ambas ramas de código: selecciona valores ya calculados.

#### 5.1.5 BIT — `0x08`

| `func6`   | Operación       | Resultado                                           |
| --------- | --------------- | --------------------------------------------------- |
| `0x00`    | `CLZ Rd, Ra`    | Número de ceros iniciales en 32 bits; `CLZ(0)=32`   |
| `0x01`    | `POPC Rd, Ra`   | Número de bits a uno, entre 0 y 32                  |

`Rb=Rc=0`. `CLZ` ayuda a normalizar datos y construir rutinas numéricas;
`POPC` permite contar las lanes seleccionadas por un ballot.

`CLZ` ya está implementada (CPU de la 38, simuladores 2 y 32) con el mapa
compatible de `isa.md`: `EXT` `0x1E`, `func6 = 0x09`, capability `clz`. Aquí
forma `bit_count` junto con `POPC`, que no está implementada.

#### 5.1.6 FXMATH — `0x09`

| `func6`   | Operación          | Objetivo                             |
| --------- | ------------------ | ------------------------------------ |
| `0x00`    | `RCPFX Rd, Ra, k`  | Recíproco `2^(32+k)/x`, Q16.16 con `16+k` bits de fracción |
| `0x01`    | `RSQRTFX Rd, Ra`   | Raíz inversa `1/sqrt(x)` en Q16.16 (propuesta de retirada) |

`RCPFX` reserva `Rb = 0` y lleva `k` en el campo `Rc`; su contrato (exacto,
truncado hacia cero, con saturación y simetría de signo) está propuesto en
`isa.md` §7.3, con ejemplos. Para `RSQRTFX` se propone la retirada en favor de
`FSQRT` en FP32 (`isa.md` §7.3, «Recíproco y raíz: coma fija o FP32»): en
Q16.16 no hay un reparto natural de rango y precisión. Un backend no debe
declarar soporte de ninguna hasta aprobar el contrato y disponer de un modelo de
referencia que permita comprobar resultados entre simulador y RTL.

Se prioriza `RCPFX`: un recíproco de `w` se reutiliza para proyectar coordenadas
y recuperar atributos con perspectiva. `RSQRTFX` se orienta a normalización e
iluminación. El recíproco de valores pequeños puede desbordar Q16.16; no se
asume que todo resultado sea representable. No se sustituyen por `DIV` entero.

Las extensiones SIMT conservan los siguientes límites:

- GETID se define en §5.1.7; GETTID es base y los otros cuatro tipos requieren
  `gpu_ids`. Su configuración sigue MMIO §14.2.
- En GPU, `SSY label` usa off26 signed en palabras y registra
  `join=low32(PC+4+sign_extend(off26)*4)`; continúa en PC+4 sin saltar.
  Reejecutar el SSY de la región más interna reutiliza esa región con el mismo
  destino. `BAR` exige participación
  válida de las lanes y completar sus operaciones de memoria anteriores, como
  ya establece la ISA vigente. §11 precisa esa garantía dentro del modelo de
  memoria v0.4; no introduce por primera vez el orden de memoria de BAR.
- En CPU, `SSY` y `BAR` son NOP reconocidos en USER y SUPERVISOR: continúan
  en `PC+4`, sin modificar registros ni estado de reconvergencia. SSY ignora
  su destino off26 y no salta. BAR no sincroniza agentes ni ordena memoria:
  no sustituye a FENCE. Se siguen validando los encodings; en BAR los 26 bits
  bajos deben ser cero. Un encoding inválido produce `ILLEGAL_INSTRUCTION`
  con `privileged_traps` y `ERROR_INVALID_ENCODING` sin ella. La regla no
  incorpora EXIT al repertorio CPU.
- `EXIT` retira permanentemente las lanes activas de live_mask. Si no quedan
  lanes vivas, termina el warp y vacía las pilas REGION y PATH. HALT tiene el
  mismo efecto en GPU; en CPU SUPERVISOR detiene la CPU y en USER es
  privilegiada según §6. BAR, EXIT y HALT exigen los 26 bits bajos a cero.
- `BALLOT/ACTIVEMASK` y `SHFL` requieren sus capabilities GPU.
- `SHFL Rd, Ra, Rb` usa `func6=0` y `Rc=0`. Cada lane activa usa el valor
  unsigned completo de su propio `Rb` como índice de la lane de la que lee
  `Ra`. La máscara activa y los valores de `Ra` y `Rb` se capturan antes de
  escribir resultados; solo las lanes activas escriben `Rd`. Si el índice está
  fuera del warp o la fuente está inactiva, el resultado es cero, sin error
  por esos casos ni wrap del índice. No es barrera, no reconverge ni comunica
  warps distintos. Solo se define la forma indexada.

Las propuestas de v0.3 que aún no tienen contrato definitivo no se convierten
en comportamiento implícito: `RCPFX` y `RSQRTFX` requieren especificar
casos límite y un modelo de referencia antes de que un backend anuncie soporte.
`SINFX`, `COSFX`, `LDR`, rotaciones, bitfields, `DIVFX` y atómicos adicionales
no forman parte del repertorio v0.4; los dos atómicos definidos son los de §12.

#### 5.1.7 GETID — `0x30`

I-Type: `opcode | Rd | type | imm16`, con `imm16=0`.

| type | Instrucción | Resultado | Capability |
|---:|---|---|---|
| 0 | `GETTID Rd` | thread residente: `warp_id * warp_size + lane_id`; cero en CPU | Base |
| 1 | `GETLANE Rd` | índice de lane dentro del warp | `gpu_ids` |
| 2 | `GETWARP Rd` | slot físico del warp | `gpu_ids` |
| 3 | `GETLWARP Rd` | `LOGICAL_WARP_ID` configurado por el lanzador | `gpu_ids` |
| 4 | `GETARG Rd` | `WARP_ARG` configurado por el lanzador | `gpu_ids` |

Los tipos mayores que 4 y un imm16 no cero son encodings inválidos. En CPU
solo está definido GETTID. En GPU solo escriben las lanes activas; el ID lógico
y argumento son de 32 bits e iguales para todas las lanes del mismo warp.
El ID lógico no es WORKGROUP_ID, no exige unicidad ni asigna trabajo implícitamente.

Se conserva el contrato de [MMIO §14.2](mmio.md#142-gpu-warps--0x82010000):
GPU WARPS tiene base `0x82010000`, LOGICAL_WARP_ID[n] en `+0x200+4n` y
WARP_ARG[n] en `+0x280+4n`. No ocupan SIMT_STATE del descriptor. Acceder a un
warp no implementado o escribirlos con ese warp vivo es error, incluso pausado;
los warps no pueden escribirlos. Valen cero tras reset del sistema y se
conservan con GPU_CONTROL.RESET y HALT/RESUME. Si se mueve trabajo de slot o
SM, el lanzador conserva ambos valores; no se presupone migración automática.

#### 5.1.8 VOTE — `0x34`

Se usa el formato de registros con `func6`:

| `func6`   | Mnemónico      | Operandos   | Reservados     |
| --------- | -------------- | ----------- | -------------- |
| `0x00`    | `BALLOT`       | `Rd, Ra`    | `Rb=Rc=0`      |
| `0x01`    | `ACTIVEMASK`   | `Rd`        | `Ra=Rb=Rc=0`   |

Para una instrucción emitida con máscara activa M:

```text
BALLOT:     bit i = M[i] AND (R[Ra] de lane i != 0)
ACTIVEMASK: resultado = M
```

Los bits fuera del warp valen cero. Todas las lanes participantes reciben el
mismo resultado y solo ellas escriben. Se toman la máscara y fuentes antes de
cualquier escritura. No son barreras, no reconvergen y no esperan lanes inactivas.
Dentro de una rama divergente describen esa participación, no todas las lanes vivas.

La máscara cabe en un registro: esta propuesta limita estas operaciones a warps
de como máximo 32 lanes. La configuración actual de ocho lanes utiliza ocho bits.
Una arquitectura con warps mayores necesita definir otra representación.

`VOTE` es el nombre de la familia, no otro mnemónico. Inicialmente no se asignan
subfunciones a `ANY/ALL`: se pueden obtener comparando el ballot con cero o con
`ACTIVEMASK`, respectivamente, usando el mismo conjunto de participantes.
Podrían añadirse si se demuestra útil reducir esas secuencias.

#### 5.1.9 ALU — `0x01`

Todas usan `Rd, Ra, Rb`, R-Type y Rc=0:

| func6 | Instrucción | Resultado | Capability |
|---:|---|---|---|
| `0x00` | `ADD` | low32(Ra + Rb) | Base |
| `0x01` | `SUB` | low32(Ra - Rb) | Base |
| `0x02` | `AND` | Ra AND Rb | Base |
| `0x03` | `OR` | Ra OR Rb | Base |
| `0x04` | `XOR` | Ra XOR Rb | Base |
| `0x05` | `SLT` | signed32(Ra) < signed32(Rb), como 0/1 | `compare` |
| `0x06` | `SLTU` | unsigned32(Ra) < unsigned32(Rb), como 0/1 | `compare` |

Func6=0x07..0x3F queda reservado. Las comparaciones no añaden FLAGS; los
requisitos completos de `compare` están en §3 y §5.4.8.

#### 5.1.10 SHIFT — `0x04`

R-Type con Rc=0. La cantidad ocupa Rb/imm5[15:11]: las formas por registro
usan los cinco bits bajos del contenido de Rb; las inmediatas codifican 0..31.

| func6 | Instrucción | Operandos | Cantidad | Capability |
|---:|---|---|---|---|
| `0x00` | `SHL` | `Rd, Ra, Rb` | registro | Base |
| `0x01` | `SHLI` | `Rd, Ra, imm5` | inmediata | `shift_immediate` |
| `0x02` | `SHR` | `Rd, Ra, Rb` | registro | Base |
| `0x03` | `SHRI` | `Rd, Ra, imm5` | inmediata | `shift_immediate` |
| `0x04` | `SAR` | `Rd, Ra, Rb` | registro | Base |
| `0x05` | `SARI` | `Rd, Ra, imm5` | inmediata | `shift_immediate` |

Func6[0] distingue registro/inmediato y func6[2:1] la dirección; func6=6..63
está reservado. SHL conserva low32, SHR añade ceros y SAR propaga el signo.
Las formas inmediatas sin capability son operaciones no soportadas, no un
encoding inválido por el antiguo bit I. Un Rc no cero sí es encoding inválido.

### 5.2 Coma fija y acumulación

Los operandos de `MULFX` y `MACFX` se interpretan como enteros signed Q16.16.
Para `MULFX Rd, Ra, Rb`, el resultado arquitectónico es el producto signed de
64 bits desplazado aritméticamente 16 posiciones y truncado a sus 32 bits bajos:

```text
MULFX(Ra, Rb) = low32((signed32(Ra) * signed32(Rb)) >>> 16)
```

`MACFX Rd, Ra, Rb` no es una nueva acumulación de precisión extendida. Lee el
valor antiguo de `Rd` junto con `Ra` y `Rb`, calcula el `MULFX` anterior y
escribe:

```text
Rd = low32(old_Rd + MULFX(Ra, Rb))
```

Todas las fuentes se capturan antes de escribir el destino: `MACFX R5,R5,R5`
es válido y usa el valor anterior de `R5` en los tres papeles. `Rd=R0` aporta
cero como acumulador y descarta el resultado, pero no omite el cálculo ni un
posible error. La operación no promete redondeo, saturación, acumulador de
64 bits ni reutilización arquitectónicamente visible de resultados internos.

Sumar, restar y comparar Q16.16 no requieren instrucciones especiales: `ADD`,
`SUB` y comparaciones signed operan directamente sobre la misma escala.
`SHLI 16` convierte un entero a Q16.16; `SARI 16` vuelve a entero truncando
hacia menos infinito.

No se define `DIVFX` en v0.4. Un cociente Q16.16 correcto requiere desplazar
el dividendo 16 bits antes de dividir, es decir una división signed de 48 entre
32 bits, no la división normal de 32 bits. `a << 16` en 32 bits puede perder
información, y dividir primero para desplazar después pierde la fracción. Para
el uso frecuente de varias coordenadas con el mismo divisor, `RCPFX` seguido de
`MULFX` es la alternativa prevista cuando su contrato numérico esté cerrado.

### 5.3 R0 físico y resultados secundarios (microarquitectura opcional)

`R0` es arquitectónicamente constante: toda lectura devuelve cero y toda
escritura se descarta. Eso no obliga a que su celda física sea cero. Una
implementación puede conservar el almacenamiento físico correspondiente como
estado interno no observable y usarlo de caché de un resultado secundario.

Por ejemplo, tras un `DIV` puede guardar el resto y, tras un `MUL`, la mitad
alta del producto, junto con los operandos y el modo que los produjo. Un
`REM`/`REMU` o `MULHI`/`MULHU`/`MULHSU` posterior puede reutilizar ese valor solo
si la clave coincide; ante fallo o reemplazo de caché ejecuta el cálculo normal.
El depurador, las trazas arquitectónicas y cualquier lectura de `R0` continúan
viendo cero.

Esto no añade registros, formatos ni latencia visible al ISA. Un diseño sin
esta caché, con una caché más pequeña o que use esa celda como scratch interno
es igual de conforme: la corrección nunca puede depender de un acierto.

### 5.4 Píxeles, memoria y control de flujo

#### 5.4.1 Inmediatos y accesos ordinarios

| Opcode | Instrucción | Operandos | Semántica |
|---|---|---|---|
| `0x10` | `MOVI` | `Rd, imm16` | sign_extend(imm16) |
| `0x11` | `ADDI` | `Rd, Ra, imm16` | low32(Ra + sign_extend(imm16)) |
| `0x12` | `ANDI` | `Rd, Ra, imm16` | Ra AND zero_extend(imm16) |
| `0x13` | `ORI` | `Rd, Ra, imm16` | Ra OR zero_extend(imm16) |
| `0x14` | `XORI` | `Rd, Ra, imm16` | Ra XOR zero_extend(imm16) |
| `0x15` | `LOAD` | `Rd, Ra, imm16` | carga de 32 bits |
| `0x16` | `STORE` | `Rs, Ra, imm16` | store de 32 bits |
| `0x17` | `MOVHI` | `Rd, imm16` | imm16 << 16 |
| `0x18` | `LOADB` | `Rd, Ra, imm16` | carga de 8 bits con signo |
| `0x19` | `LOADUB` | `Rd, Ra, imm16` | carga de 8 bits con ceros |
| `0x1A` | `LOADH` | `Rd, Ra, imm16` | carga de 16 bits con signo |
| `0x1B` | `LOADUH` | `Rd, Ra, imm16` | carga de 16 bits con ceros |
| `0x1C` | `STOREB` | `Rs, Ra, imm16` | store de los 8 bits bajos |
| `0x1D` | `STOREH` | `Rs, Ra, imm16` | store de los 16 bits bajos |

Se usa I-Type; MOVI/MOVHI exigen Ra/Y=0. Las cargas y stores calculan
`low32(old_Ra + sign_extend(imm16))`, con offset signed -32768..32767 bytes.
Los bytes no exigen alineación; halfwords requieren dirección par y palabras
múltiplo de cuatro. Se comprueba todo el intervalo. Son little-endian; las
cargas signed extienden el signo, las otras añaden ceros y los stores conservan
los bytes vecinos. Los accesos subpalabra requieren `subword_memory`.

| Instrucción | Tamaño | Resultado o escritura | Alineación |
|---|---:|---|---|
| `LOAD / STORE` | 32 bits | palabra completa | múltiplo de 4 |
| `LOADH / STOREH` | 16 bits | carga con signo / store de low16 | múltiplo de 2 |
| `LOADUH` | 16 bits | carga con ceros | múltiplo de 2 |
| `LOADB / STOREB` | 8 bits | carga con signo / store de low8 | cualquiera |
| `LOADUB` | 8 bits | carga con ceros | cualquiera |

En GPU solo acceden las lanes activas; la LSU conserva la asociación de
respuestas y errores con warp/lane. Aceptar una petición no es completarla:
BAR espera la finalización según §11. En CPU los fallos siguen las causas
precisas de §9; sin traps se mantiene el error fatal de acceso del backend.
La protección MMIO/PMP se rige por §10 y las reglas de [mmio.md](mmio.md).

#### 5.4.2 PIX565 — `0x05`

Todas tienen operandos `Rd, Ra`, `Rb=Rc=0` y un único registro destino.

| `func6`   | Operación      | Resultado en `Rd`                                 |
| --------- | -------------- | ------------------------------------------------- |
| `0x00`    | `PACK565`      | RGB565 en los 16 bits bajos; bits altos cero      |
| `0x01`    | `UNPACK565R`   | Canal rojo expandido a 8 bits; bits altos cero    |
| `0x02`    | `UNPACK565G`   | Canal verde expandido a 8 bits; bits altos cero   |
| `0x03`    | `UNPACK565B`   | Canal azul expandido a 8 bits; bits altos cero    |

`PACK565` conserva el contrato vigente: entrada `0x00RRGGBB`, ignorando el byte
alto, y resultado:

```text
((Ra >> 8) & 0xF800) | ((Ra >> 5) & 0x07E0) | ((Ra >> 3) & 0x001F)
```

Los unpack ignoran los 16 bits altos de la fuente:

```text
r5 = (Ra >> 11) & 31; R8 = (r5 << 3) | (r5 >> 2)
g6 = (Ra >> 5)  & 63; G8 = (g6 << 2) | (g6 >> 4)
b5 = Ra & 31;         B8 = (b5 << 3) | (b5 >> 2)
```

Para separar los canales se ejecutan tres instrucciones:

```asm
UNPACK565R R1, R4
UNPACK565G R2, R4
UNPACK565B R3, R4
```

No se propone una instrucción con tres destinos. Se conserva un puerto de
escritura por lane y se permite extraer únicamente el canal necesario.

#### 5.4.3 Stores postincrementales — `0x1E`

```text
31       26 25    21 20    16 15  14 13                0
+----------+--------+--------+------+--------------------+
|  opcode  |   Rs   |   Ra   | size |    signed imm14    |
+----------+--------+--------+------+--------------------+
```

`size=0,1,2` selecciona `STOREBP`, `STOREHP`, `STOREP` (8, 16, 32 bits).
`size=3` está reservado. Sintaxis: `STOREP Rs, Ra, incremento`, equivalente
para las otras dos variantes. En el mapa compatible de `isa.md`, `0x1E` ya es
`EXT` (MIN/MAX/CLZ, implementado en la 38); llevar estos stores a ese mapa
pide otro opcode, por ejemplo `0x1F`, con este mismo formato. El inmediato es signed en bytes, `-8192..8191`.

```text
address = old_Ra
value = old_Rs
store(address, value, size)
si termina correctamente: Ra = low32(old_Ra + sign_extend(imm14))
```

El incremento no es un offset del acceso. Rigen los errores y alineación del
store normal del mismo tamaño. Con `Rs=Ra`, se almacena el valor anterior;
con `Ra=R0`, se accede a cero y la actualización se descarta. Si falla el acceso,
no se actualiza su base.

En GPU solo actúan lanes activas. El incremento de cada base debe seguir la
finalización exitosa de su acceso; no se promete rollback de lanes ya completadas
si otra falla. Antes de soportarlo en GPU hay que documentar y probar el estado
observable de fallos parciales y la finalización antes de `BAR`.

En CPU, los fallos se traducen a STORE_ALIGNMENT/STORE_ACCESS con traps
privilegiados y no modifican memoria ni base. En GPU se mantiene la posibilidad
de efectos parciales de stores ordinarios del backend; esto no se aplica a los
atómicos de §12.1, que tienen prevalidación de todo el warp.

#### 5.4.4 LEAPC — `0x2F`

```text
31       26 25    21 20                             0
+----------+--------+---------------------------------+
|  0x2F    |   Rd   |           signed off21          |
+----------+--------+---------------------------------+
```

Sintaxis propuesta: `LEAPC Rd, label`. Se propone off21 signed **en bytes**,
relativo a la instrucción siguiente:

```text
Rd = low32(PC + 4 + sign_extend(off21))
PC = low32(PC + 4)
```

El rango exacto es `-1048576..1048575` bytes respecto a PC+4, aproximadamente
±1 MiB. El ensamblador calcula el desplazamiento hasta la etiqueta y rechaza
los destinos fuera de rango; no trunca ni cambia silenciosamente de secuencia.
La dirección calculada puede apuntar a cualquier byte: LEAPC no accede a memoria
ni verifica la alineación o validez de ese futuro acceso.

Se coloca en el bloque de control por su relación con el PC, pero **no salta**:
es una excepción explícita a la clasificación por familia principal. Tiene el
mismo reparto de campos que JAL, pero distinta unidad y semántica. No modifica
el encoding ni las unidades de JAL/JALR, y no requiere la capability `calls`.
Requiere la capability `pc_relative_address`.

En GPU escribe la misma dirección en las lanes activas del warp; no modifica
máscaras ni reconverge. `Rd=R0` descarta el resultado y continúa normalmente.

#### 5.4.5 LOADX — `0x1F`

Se propone inicialmente **solo la carga de 32 bits**, con un único destino:

```asm
LOADX Rd, Ra, Rb, escala
```

Usa el formato de registros de §4. `Rc=0`; `func6=0..3` codifica la escala
0..3, respectivamente. Los restantes valores de func6 están reservados.
Se leen el contenido completo de Ra y Rb, no sus números de registro:

```text
address = low32(old_Ra + (unsigned32(old_Rb) << escala))
Rd = memoria32[address]
```

La escala es un inmediato del ensamblador; fuera de 0..3 se rechaza. La carga
conserva el contrato de LOAD: little-endian, dirección múltiplo de cuatro,
validación de los cuatro bytes y los fallos LOAD_ALIGNMENT/LOAD_ACCESS de §9 con traps CPU, o el error fatal
de acceso del backend sin ellos.
El cálculo hace wrap a 32 bits. Una escala 0 o 1 no autoriza una carga desalineada.
Ra y Rb no se actualizan. `Rd=Ra` o `Rd=Rb` es legal: se usan las fuentes previas.
Con `Rd=R0` se descarta el resultado, pero se realiza el acceso y se detectan errores.

Requiere la capability `indexed_load`. En GPU calcula una
dirección por lane activa y conserva el comportamiento de cargas y fallos por
lane del backend; no introduce coalescencia, atómicos ni una barrera.
Las variantes indexadas de byte/halfword quedan como ampliación posterior,
sin mnemónicos ni subfunciones asignados en esta revisión.

#### 5.4.6 Branches condicionales con off16

BR y BRI son nombres de grupo, no mnemónicos. Cada condición dispone de opcode:

| BR | Opcode | BRI | Opcode | Comparación / extensión de imm5 |
|---|---:|---|---:|---|
| `BEQ` | `0x20` | `BEQI` | `0x28` | igualdad; signo |
| `BNE` | `0x21` | `BNEI` | `0x29` | desigualdad; signo |
| `BLT` | `0x22` | `BLTI` | `0x2A` | menor signed; signo |
| `BGE` | `0x23` | `BGEI` | `0x2B` | mayor o igual signed; signo |
| `BLTU` | `0x24` | `BLTUI` | `0x2C` | menor unsigned; ceros |
| `BGEU` | `0x25` | `BGEUI` | `0x2D` | mayor o igual unsigned; ceros |

El formato conserva las posiciones de lectura Ra y Rb de R-Type:

```text
31:26       25:21        20:16     15:11      10:0
opcode    off16[15:11]     Ra     Rb/imm5   off16[10:0]
```

Se reconstruye `off16 = {instruction[25:21], instruction[10:0]}`; el bit 25
es su signo. No hay campo cond: la condición la identifica el opcode. En BR
se compara el contenido completo de Ra y Rb. En BRI, imm5 ocupa el campo Rb:
-16..15 para EQ/NE/LT/GE y 0..31 para LTU/GEU. La igualdad compara después de
extender a 32 bits; -1 equivale a 0xFFFFFFFF, no a 31.

```text
tomada:    PC = low32(PC + 4 + sign_extend(off16) * 4)
no tomada: PC = low32(PC + 4)
```

Off16 admite -32768..32767 palabras, aproximadamente ±128 KiB. El ensamblador
reparte el offset entre sus dos fragmentos y rechaza valores o destinos fuera
de rango; no trunca ni expande automáticamente el branch. La relajación a rama
inversa y BRA queda como ampliación futura con validación SIMT.

BRI requiere `branch_immediate`; BR pertenece a la base. En GPU se aplican
las reglas vigentes de divergencia y reconvergencia sin región SSY implícita.

#### 5.4.7 BRA, JAL y JALR

| Opcode   | Instrucción            | Formato                      | Semántica                                         |
| -------- | ---------------------- | ---------------------------- | ------------------------------------------------- |
| `0x26`   | `BRA target`           | opcode + signed off26        | Salto relativo en palabras                        |
| `0x27`   | `JAL Rd, target`       | opcode + Rd + signed off21   | Enlace y salto relativo en palabras               |
| `0x2E`   | `JALR Rd, Ra, imm16`   | I-Type                       | Enlace y salto indirecto, inmediato en palabras   |

Tomando `PC` como la dirección de la instrucción y las fuentes antes del enlace:

```text
BRA:  PC = low32(PC + 4 + sign_extend(off26)*4)
JAL:  target = low32(PC + 4 + sign_extend(off21)*4)
      Rd = low32(PC+4); PC = target
JALR: target = low32(old_Ra + sign_extend(imm16)*4) & 0xFFFFFFFC
      Rd = low32(PC+4); PC = target
```

`BRA` conserva aproximadamente ±128 MiB. `JAL` amplía su alcance de ±128 KiB
a ±4 MiB. `JALR` conserva `imm16=-32768..32767` palabras y la alineación vigente.
La coincidencia `Rd=Ra` es legal. `Rd=R0` descarta el enlace, no el salto.

```asm
JR Ra  -> JALR R0, Ra, 0
RET    -> JALR R0, R31, 0
```

`JR` desaparece solo del mapa binario, no del lenguaje ensamblador.
En GPU, todas las lanes activas deben calcular el mismo destino
efectivo. Se comprueba después del cálculo y alineación del destino, usando los
valores fuente anteriores a cualquier escritura de enlace. Las lanes inactivas
no participan en la comparación. Si los destinos difieren, la GPU termina con
`ERROR_SIMT` (`0x06`), sin escribir enlaces ni ejecutar ninguno de los destinos;
no se serializan en silencio destinos divergentes. La comprobación precede a
cualquier escritura de enlace, también cuando `Rd=Ra`. `Rd=R0` no evita la
comprobación ni el salto. La regla se aplica a `JALR` y a sus alias `JR/RET`;
JAL/JALR y sus alias requieren `calls`; BRA pertenece a la base.

#### 5.4.8 Comparaciones y alias de ensamblador

| Opcode / selector | Instrucción | Resultado |
|---|---|---|
| `0x01 / func6=0x05` | `SLT Rd, Ra, Rb` | signed32(Ra) < signed32(Rb) |
| `0x01 / func6=0x06` | `SLTU Rd, Ra, Rb` | unsigned32(Ra) < unsigned32(Rb) |
| `0x0C` | `SLTI Rd, Ra, imm16` | signed32(Ra) < sign_extend(imm16) |
| `0x0D` | `SLTIU Rd, Ra, imm16` | unsigned32(Ra) < unsigned32(sign_extend(imm16)) |

Las cuatro materializan 0/1 y requieren `compare`. SLT/SLTU usan la familia
ALU con Rc=0; SLTI/SLTIU conservan I-Type e inmediato signed de 16 bits.
SLTIU extiende el signo antes de comparar sin signo; SLTIU Rd,Ra,1 materializa
Ra==0. No modifican FLAGS ni máscaras. Las formas inmediatas evitan preparar
una constante en un temporal y combinan con SEL para seleccionar datos sin ramas.
Los dos opcodes I-Type se sitúan junto a las familias aritméticas; el rango
numérico no impone por sí solo un formato.

JR Ra y RET se expanden a JALR R0,Ra,0 y JALR R0,R31,0. Se conservan LI
(una o dos palabras, con la relajación simbólica vigente) y LA (MOVHI+ORI,
siempre dos palabras). El ensamblador recalcula las etiquetas al recompilar,
sin reutilizar PCs ni palabras de máquina del mapa antiguo. MULH puede aceptarse
como alias opcional de MULHI; LOADBU/LOADHU, como alias de LOADUB/LOADUH.
No se necesita un sistema de macros para estas expansiones; la sintaxis y las
reglas de LI/LA se documentan en [ensamblador.md](ensamblador.md).

##### Alias y pseudoinstrucciones

Estas entradas van aparte porque no asignan un opcode primario nuevo. Las
expansiones de JR/RET son las de esta propuesta; en la ISA vigente JR tiene
su propio opcode, como muestra el otro índice.

| Categoría | Mnemónico | Operandos | Expansión propuesta | Estado | Definición |
| --- | --- | --- | --- | --- | --- |
| Retorno | `JR` | `Ra` | `JALR R0, Ra, 0` (`0x2E`) | Alias en v4 | [v0.4](#548-comparaciones-y-alias-de-ensamblador) |
| Retorno | `RET` | — | `JALR R0, R31, 0` (`0x2E`) | Alias en v4 | [v0.4](#548-comparaciones-y-alias-de-ensamblador) |
| Multiplicación | `MULH` | `Rd, Ra, Rb` | `MULHI Rd, Ra, Rb` (`0x02/func6=1`) | Alias opcional | [v0.4](#511-mul--0x02) |
| Memoria | `LOADBU` | `Rd, Ra, imm16` | `LOADUB Rd, Ra, imm16` (`0x19`) | Alias opcional | [v0.4](#548-comparaciones-y-alias-de-ensamblador) |
| Memoria | `LOADHU` | `Rd, Ra, imm16` | `LOADUH Rd, Ra, imm16` (`0x1B`) | Alias opcional | [v0.4](#548-comparaciones-y-alias-de-ensamblador) |
| Parada | `ABORT` | — | `TRAP` con número cero (`0x3E`) | Alias en v4 | [v0.4 §4.3](#43-trap-y-abort--0x3e) |

### 5.5 Familia FP32 — `0x0A`

La capability opcional `fp32` agrupa sus nueve operaciones en un solo opcode
R-Type: `opcode | Rd | Ra | Rb | Rc | func6`, con `Rc=0`.

| func6 | Instrucción | Operandos | Resultado |
|---:|---|---|---|
| `0x00` | `FADD` | `Rd, Ra, Rb` | binary32(Ra) + binary32(Rb) |
| `0x01` | `FSUB` | `Rd, Ra, Rb` | binary32(Ra) − binary32(Rb) |
| `0x02` | `FMUL` | `Rd, Ra, Rb` | binary32(Ra) × binary32(Rb) |
| `0x03` | `FDIV` | `Rd, Ra, Rb` | binary32(Ra) / binary32(Rb) |
| `0x04` | `FEQ` | `Rd, Ra, Rb` | 1 si binary32(Ra) == binary32(Rb), si no 0 |
| `0x05` | `FLT` | `Rd, Ra, Rb` | 1 si binary32(Ra) < binary32(Rb), si no 0 |
| `0x06` | `FLE` | `Rd, Ra, Rb` | 1 si binary32(Ra) <= binary32(Rb), si no 0 |
| `0x07` | `FTOI` | `Rd, Ra, fbits` | int32(trunc(binary32(Ra) × 2^fbits)), saturado |
| `0x08` | `ITOF` | `Rd, Ra, fbits` | binary32(int32(Ra) / 2^fbits), RNE |

En `FTOI` e `ITOF`, `fbits` (0..31) ocupa el campo `Rb` como inmediato sin
signo; no es un registro leído. Los valores `func6=0x09..0x3F` están
reservados; no autorizan a declarar otras operaciones. `Rc` no cero es encoding inválido. Una capability ausente o una
subfunción no soportada sigue las reglas generales del perfil (§1 y §3).

Se hereda normativamente el contrato numérico de
[`isa.md`, aritmética FP32](isa.md#aritmética-fp32-capability-fp32), sin heredar
sus cuatro opcodes independientes:

- Operandos y resultado son patrones binary32 en los GPR; no hay banco FP
  separado ni conversiones implícitas desde enteros o Q16.16. Las fuentes se
  capturan antes de escribir; R0 aporta +0 y descarta el resultado.
- Redondeo fijo RNE después de cada operación, entradas subnormales DAZ y
  resultados subnormales FTZ después de redondear, conservando el signo de cero.
  Se conserva un resultado que redondea al mínimo normal; overflow produce
  infinito con signo.
- NaN e inválidas producen el NaN canónico `0x7FC00000`; se conservan las
  reglas vigentes de infinitos y ceros con signo.
- No hay FMA, flags FP, modo de redondeo configurable ni excepciones numéricas.
  En particular, FDIV por cero no causa DIVISION_BY_ZERO ni entra al handler.

Comparaciones y conversiones heredan también su contrato de `isa.md`
(comparaciones sin DAZ, NaN da 0 y `-0 == +0`; `FTOI` trunca, satura y da 0
con NaN; `ITOF` redondea RNE y nunca da subnormales).

En GPU solo escriben las lanes activas. La capability comprende las nueve
operaciones, aunque un backend puede ejecutarlas con latencias distintas.
No se añaden nuevas pseudoinstrucciones FP.

Este encoding v0.4 es una propuesta: la implementación actual en CPU 2/32 y
RTL 38 usa los opcodes del mapa compatible (`0x38–0x3D`, ver `isa.md`). Compartir contrato numérico no implica soporte del
nuevo encoding ni soporte GPU implementado.

## 6. Modos de ejecución

Se definen dos modos:

- `USER`: aplicaciones sin acceso a estado privilegiado.
- `SUPERVISOR`: kernel, handlers y configuración de plataforma.

Tras reset la CPU arranca en `SUPERVISOR`, con interrupciones deshabilitadas.
El modo no cambia por saltos ordinarios. Solo la entrada de trap fuerza
`SUPERVISOR`; `ERET` restaura el modo previo y `ENTERUSER` realiza la entrada
inicial controlada a USER.

Son privilegiadas:

- `ERET` y `MTSR`;
- `HALT` y `TRAP` sin número (`ABORT`);
- la escritura de configuración de interrupciones y protección;
- cualquier acceso que un registro SR marque como solo supervisor.

Ejecutarlas desde USER produce `PRIVILEGED_INSTRUCTION`. `MFSR` desde USER solo
puede leer registros marcados expresamente como públicos; v0.4 no marca ninguno.
Así se evita exponer accidentalmente estado del kernel —por ejemplo, PC de
retorno, causas, fuentes pendientes o configuración PMP— como una ABI pública.
Un dato que USER necesite debe ofrecerse mediante syscall o un registro MMIO que
la plataforma haya definido explícitamente como accesible.

Restringir `HALT` y `ABORT` evita que una aplicación USER provoque una parada
global como sustituto de una syscall de salida o como denegación de servicio.
Tras reset el código bare-metal sigue en SUPERVISOR, por lo que conserva sus
usos de diagnóstico históricos. La GPU no tiene modo USER en v0.4 y mantiene su
semántica global de `HALT`/`ABORT`.

## 7. Registros de sistema

| Índice | Nombre          | Acceso S | Descripción                                      |
|-------:|-----------------|----------|--------------------------------------------------|
| `0`    | `STATUS`        | R/W      | Modo e interrupciones                            |
| `1`    | `EPC`           | R/W      | PC de retorno                                    |
| `2`    | `CAUSE`         | R        | Causa del último trap                            |
| `3`    | `TVEC`          | R/W      | Base y modo de vectorización                     |
| `4`    | `BADADDR`       | R        | Dirección asociada al fallo                      |
| `5`    | `IRQ_PENDING`   | R        | Fuentes pendientes                               |
| `6`    | `IRQ_ENABLE`    | R/W      | Máscara de fuentes                               |
| `7`    | `KSP`           | R/W      | Registro de intercambio de pila USER/SUPERVISOR  |
| `8`    | `PMP_DEFAULT`   | R/W      | Política USER fuera de las regiones              |
| `9–16` | `PMPn_*`        | R/W      | BASECFG y LIMIT de las regiones 0–3              |
| `17–24`| `PMPn_*` futuro | —        | Reservados para las regiones 4–7                 |
| `25–31`| —               | —        | Reservados                                       |

Cada región consume dos índices consecutivos: `BASECFG` y `LIMIT`. v0.4 solo
implementa las regiones 0–3. Una futura capability `pmp8` podrá habilitar las
regiones 4–7 en los índices ya reservados, sin cambiar `MFSR`, `MTSR` ni los
binarios que utilicen las cuatro primeras.

`EPC` es el único registro de información de trap que supervisor puede
modificar: permite reintentar, omitir o redirigir la instrucción causante antes
de `ERET`. `CAUSE` y `BADADDR` son de solo lectura para preservar un diagnóstico
fiable del último trap; una escritura `MTSR` sobre ellos se rechaza sin cambio.
`MTSR EPC` exige una dirección múltiplo de cuatro: un valor desalineado se
rechaza sin modificar `EPC` y produce `ILLEGAL_INSTRUCTION` cuando existen
traps privilegiados. `ERET` y `ENTERUSER` conservan además su comprobación de
alineación como defensa de integridad.

`KSP` es un registro de intercambio, no una segunda pila accesible a la vez:
durante USER contiene la pila de supervisor; durante un handler procedente de
USER contiene temporalmente la pila USER. Al aceptar un trap desde USER, el
hardware intercambia atómicamente `R30` y `KSP`: `R30` pasa a apuntar a la pila
segura del kernel y `KSP` conserva la pila de la aplicación. Al ejecutar `ERET`
hacia USER los intercambia otra vez. Un trap tomado desde SUPERVISOR no toca
ninguno de los dos. Supervisor puede escribir `KSP` mediante `MTSR` antes de
una primera entrada USER.

`STATUS`:

| Bit | Nombre  | Significado                         |
|----:|---------|-------------------------------------|
| `0` | `IE`    | habilitación global de interrupción |
| `1` | `PIE`   | valor anterior de `IE`              |
| `2` | `MODE`  | `0=USER`, `1=SUPERVISOR`            |
| `3` | `PMODE` | modo anterior                       |

Los demás bits se leen como cero y deben escribirse como cero. `MTSR STATUS`
ejecutado en supervisor solo puede modificar `IE` y `PIE`; `MODE` y `PMODE` son
de solo lectura para software y solo los cambia reset, la entrada de trap y
`ERET`.

Esta restricción evita dos caminos distintos para bajar privilegio. Si `MTSR`
pudiera escribir `MODE=USER`, el supervisor pasaría a USER en la instrucción
siguiente sin restaurar `EPC` ni aplicar la restauración conjunta de `IE` que
define `ERET`. Obligar a usar `ERET` mantiene una única transición verificable:
restaura en el mismo punto el PC de retorno, el modo previo y el estado de
interrupciones. También impide que un handler deje un `PMODE` fabricado que no
corresponda al trap que está retornando.

## 8. Entrada y retorno de trap

Todo trap aceptado realiza atómicamente:

```text
EPC     <- PC de retorno definido por la causa
CAUSE   <- causa
BADADDR <- dirección del fallo, o 0
PMODE   <- MODE
PIE     <- IE
MODE    <- SUPERVISOR
IE      <- 0
PC      <- destino(TVEC, VECTOR)
```

Si el modo anterior era USER, en la misma entrada se intercambian `R30` y
`KSP`, antes de ejecutar la primera instrucción del handler. Así el handler no
utiliza accidentalmente la pila de la aplicación.

La entrada de trap no guarda registros generales `R1–R31`: conservarlos todos
en hardware elevaría el estado y la latencia de cada syscall o interrupción.
El handler usa su pila de supervisor para salvar cualquier registro que vaya a
modificar antes de llamar a código auxiliar.
`R0` sigue siendo cero y no requiere salvado.

`TVEC[1:0]` selecciona:

- `00`, DIRECT: `PC = TVEC.BASE`;
- `01`, VECTORED: `PC = TVEC.BASE + 4 * VECTOR`, requiere `vectored_traps`;
- `10` y `11`, reservados.

`TVEC.BASE` debe estar alineada a 64 bytes. El modo VECTORED dispone de 16
entradas de cuatro bytes, suficientes para las causas de v0.4. Las fuentes
externas comparten vector y se distinguen leyendo `IRQ_PENDING`.

`TVEC.BASE=0` significa vector no configurado, aunque el modo sea DIRECT. Un
trap en ese estado termina con `ERROR_UNCONFIGURED_TRAP` fatal en vez de saltar
a la dirección de reset. El supervisor debe configurar una base no nula antes
de entrar USER o habilitar interrupciones.

DIRECT forma parte obligatoria de `privileged_traps`: permite un kernel mínimo
con un solo handler que despacha leyendo `CAUSE`. VECTORED es opcional; una
implementación que no declare `vectored_traps` rechaza escribir `TVEC.MODE=01`
como configuración no soportada, en vez de ignorarla o caer silenciosamente a
DIRECT.

`MTSR TVEC` exige que los seis bits bajos de la base sean cero y que el modo
esté soportado. Si la base no está alineada a 64 bytes, el modo vale `10/11` o
se intenta VECTORED sin `vectored_traps`, la instrucción no modifica `TVEC` y
produce `ILLEGAL_INSTRUCTION` cuando existen traps privilegiados; sin ellos
produce el error fatal normal de encoding/configuración no soportada.

`ERET` realiza:

```text
PC   <- EPC
MODE <- PMODE
IE   <- PIE
PIE  <- 0
```

Si `PMODE=USER`, `ERET` intercambia también `R30` y `KSP` antes de continuar en
`EPC`; así recupera la pila USER y conserva la pila actual del kernel para la
próxima entrada.

`ENTERUSER` solo es válido en supervisor con `IN_TRAP=0`. Exige `EPC` alineado
a cuatro bytes y realiza atómicamente:

```text
intercambiar R30, KSP
MODE    <- USER
PMODE   <- SUPERVISOR
PIE     <- 0
PC      <- EPC
```

`IE` conserva el valor que el supervisor haya configurado antes de ejecutar
`ENTERUSER`; queda fijado que esta instrucción no activa ni desactiva por sí
misma las interrupciones. Para iniciar una tarea, el kernel deja su propia pila en `R30`,
escribe la pila USER deseada en `KSP`, escribe el punto de entrada en `EPC` y
ejecuta `ENTERUSER`; el intercambio deja cada pila en su dueño correcto. Un
`ENTERUSER` con `EPC` no alineado o con `IN_TRAP=1` se rechaza sin modificar
pilas, modo ni PC.

`IN_TRAP` es un bit interno no visible por `MFSR`: la entrada de trap lo pone a
uno y un `ERET` completado lo borra. `ERET` solo es válido en supervisor con
`IN_TRAP=1`; fuera de ese estado se rechaza como `ILLEGAL_INSTRUCTION` con
traps privilegiados o como error fatal en un perfil sin ellos. Si `EPC` está mal
alineado, `ERET` no cambia PC, modo, pilas ni `IN_TRAP`, de modo que el handler
puede corregir `EPC` y volver a intentarlo.

`ERET` comprueba defensivamente que `EPC` está alineado a cuatro bytes. En caso
de corrupción interna no cambia estado ni retorna; un programa correcto no
puede llegar a ese caso porque `MTSR EPC` ya rechaza valores desalineados.

### 8.1 EPC

`EPC` contiene la dirección en la que debe continuar `ERET`:

- Syscall mediante `TRAP número` válido: dirección de la instrucción siguiente
  (`PC+4`); el handler no necesita incrementar `EPC` para continuar.
- interrupción: dirección de la siguiente instrucción aún no ejecutada.
- excepción por fallo (instrucción ilegal o privilegiada, división por cero,
  fallo de fetch/load/store/atómico): PC de la instrucción causante, para poder
  corregir y reintentar. Si el handler la emula o decide omitirla, debe ajustar
  `EPC` antes de retornar.

### 8.2 Precisión y anidamiento

Las excepciones son precisas: las instrucciones anteriores han terminado y la
causante no deja efectos parciales. Una interrupción solo se acepta entre dos
instrucciones retiradas.

v0.4 dispone de un único juego `EPC/CAUSE/BADADDR/PMODE/PIE`; por tanto el
hardware no apila traps ni ofrece anidamiento. La entrada deshabilita
interrupciones y, mientras `IN_TRAP=1`, las interrupciones pendientes permanecen
aplazadas aunque el handler escriba `IE=1`. Una excepción síncrona dentro del
handler produce `ERROR_DOUBLE_FAULT` y una parada fatal. Esta regla evita que
un segundo evento sobrescriba el único contexto de retorno.

## 9. Causas y vectores

`CAUSE[31]` distingue interrupciones. Las excepciones hardware ordinarias usan
los códigos bajos de la tabla; un trap software usa
`0x04000000 | número_de_syscall`. `VECTOR` es interno y se calcula así:

```text
trap software: VECTOR = 0
otra excepción: VECTOR = CAUSE[3:0]
timer: VECTOR = 12
externa: VECTOR = 13
GPU: VECTOR = 14
DMA: VECTOR = 15
```

Así, por ejemplo, `ILLEGAL_INSTRUCTION` entra por el vector 1 y
`TIMER_INTERRUPT` por el 12. Los vectores 0–11 corresponden a traps y
excepciones síncronas, 12–15 a interrupciones estándar. La
plataforma agrupa las fuentes externas bajo el vector 13 y expone el detalle
mediante `IRQ_PENDING`.

| `CAUSE`      | Nombre                       | `EPC`       | `BADADDR`             |
|--------------|------------------------------|-------------|-----------------------|
| `0x04000001`–`0x07FFFFFF` | `SOFTWARE_TRAP(número)` | `PC+4` | `0`              |
| `0x00000001` | `ILLEGAL_INSTRUCTION`        | `PC`        | `0`                   |
| `0x00000002` | `PRIVILEGED_INSTRUCTION`     | `PC`        | `0`                   |
| `0x00000003` | `INSTRUCTION_ALIGNMENT`      | `PC`        | destino                |
| `0x00000004` | `INSTRUCTION_ACCESS`         | `PC`        | dirección de fetch     |
| `0x00000005` | `LOAD_ALIGNMENT`             | `PC`        | dirección efectiva     |
| `0x00000006` | `LOAD_ACCESS`                | `PC`        | dirección efectiva     |
| `0x00000007` | `STORE_ALIGNMENT`            | `PC`        | dirección efectiva     |
| `0x00000008` | `STORE_ACCESS`               | `PC`        | dirección efectiva     |
| `0x00000009` | `ATOMIC_ALIGNMENT`           | `PC`        | dirección efectiva     |
| `0x0000000A` | `ATOMIC_ACCESS`              | `PC`        | dirección efectiva     |
| `0x0000000B` | `DIVISION_BY_ZERO`           | `PC`        | `0`                   |
| `0x80000001` | `TIMER_INTERRUPT`            | siguiente   | `0`                   |
| `0x80000002` | `EXTERNAL_INTERRUPT`         | siguiente   | `0`                   |
| `0x80000003` | `GPU_INTERRUPT`              | siguiente   | `0`                   |
| `0x80000004` | `DMA_INTERRUPT`              | siguiente   | `0`                   |

Los fallos que antes detenían una CPU con `ERROR_*` se convierten en traps si
la CPU declara `privileged_traps`. `TRAP` sin argumento, su alias `ABORT` y
`ERROR_DOUBLE_FAULT` siguen siendo fatales. Una GPU sin soporte de privilegios
rechaza `TRAP número`, en vez de darle una interpretación alternativa.

Esta regla queda fijada también para binarios portables: en GPU sin
`privileged_traps`, `TRAP número` es una instrucción no soportada y termina con
el error normal del backend; únicamente `TRAP` sin argumento (`ABORT`) conserva
la parada global fatal. El mismo encoding no representa una syscall en CPU y
una parada con código en GPU.

En particular, un opcode desconocido, una subfunción no soportada, una
capability ausente o un encoding reservado producen `ILLEGAL_INSTRUCTION`
precisa cuando existe `privileged_traps`. Esto permite al supervisor terminar
la tarea o emular deliberadamente una extensión; sin esa capability se conserva
el error fatal vigente.

También, `DIV/DIVU/REM/REMU` con divisor cero producen
`DIVISION_BY_ZERO`, con `EPC` en la instrucción causante y sin escribir su
destino, cuando existe `privileged_traps`. Sin esa capability conservan el
error fatal vigente. Esto permite que el supervisor termine la tarea, emule un
resultado o modifique el contexto y reintente de forma explícita.

## 10. Protección física mínima

Dos modos sin permisos de memoria no aíslan aplicaciones. La capability
`memory_protection` define cuatro regiones PMP numeradas `0..3`:

```text
PMPn_BASECFG
    bits 31:5  dirección inicial inclusiva, alineada a 32 bytes
    bit 0 R     lectura USER
    bit 1 W     escritura USER
    bit 2 X     fetch USER
    bit 3 S     aplicar también a SUPERVISOR
    bit 4 L     bloquear hasta reset BASECFG/LIMIT
PMPn_LIMIT    dirección final exclusiva, alineada a 32 bytes
```

Una región está deshabilitada si `BASE >= LIMIT`. Si varias coinciden, gana la
de menor número; las regiones de índice bajo son por tanto las reglas de máxima
prioridad. Se comprueba el intervalo completo del acceso; cruzar un límite
falla, aunque su primer byte esté permitido.

`PMPn_BASECFG[31:5]` y `PMPn_LIMIT` definen límites múltiplos de 32 bytes. Una
escritura con los cinco bits bajos de `LIMIT` no nulos se rechaza sin modificar
el registro; con `privileged_traps` produce `ILLEGAL_INSTRUCTION`. `BASE >=
LIMIT` no es un error: es la forma explícita de deshabilitar temporalmente una
región sin reutilizar sus índices SR.

Para un acceso de datos, primero se valida la alineación exigida por su tamaño y
solo después se consulta PMP. Por tanto, una dirección que sea simultáneamente
mal alineada y no autorizada informa `LOAD_ALIGNMENT`, `STORE_ALIGNMENT` o
`ATOMIC_ALIGNMENT`, no un fallo de acceso. Esta prioridad es fija y evita que
la causa dependa del orden interno de comparadores del LSU.

El fetch de una instrucción comprueba permiso X sobre sus cuatro bytes completos.
Una instrucción alineada que cruce el límite de una región no puede ejecutarse
por tener permiso solo en su primer byte: produce `INSTRUCTION_ACCESS` con
`BADADDR` igual a la dirección de fetch.

Fuera de todas las regiones, `PMP_DEFAULT[2:0]` proporciona R/W/X para USER.
Tras reset vale `0b111`: USER conserva acceso de lectura, escritura y ejecución
a toda dirección no cubierta por una región, para mantener la compatibilidad
bare-metal existente. Por tanto, declarar `memory_protection` no implica que el
aislamiento esté activo desde reset: el supervisor debe configurar regiones o
cambiar explícitamente `PMP_DEFAULT` antes de ejecutar código no confiable.
Supervisor ignora permisos salvo en regiones con `S=1`. `L=1` impide cambios
incluso desde supervisor hasta el próximo reset.

El bit `S` queda fijado como una protección opcional también frente al
supervisor: una región con `S=0` deja al kernel acceder para inicialización,
drivers y recuperación; con `S=1` se convierte en una restricción efectiva
para ambos modos. Esto permite aislar una zona crítica sin obligar a que todo
acceso supervisor atraviese una política PMP restrictiva.

El bit `L` queda fijado y bloquea de forma irreversible hasta reset los dos
registros de su región (`BASECFG` y `LIMIT`), incluso desde supervisor.
Debe activarse al final de la secuencia de arranque, después de comprobar los
límites: no es un mecanismo de suspensión temporal ni admite desbloqueo por
software.

Los accesos MMIO también pasan por PMP. Esto evita que USER controle DMA, vídeo
o interrupciones solo porque sus direcciones estén mapeadas. PMP protege
direcciones físicas de accesos ejecutados por la CPU; no se aplica a GPU ni DMA
en v0.4, porque esos masters no tienen modo USER/SUPERVISOR ni contexto de
proceso. Una plataforma que deba aislarlos requiere un firewall o contextos de
memoria propios. Traducción, espacios virtuales, TLB y page faults quedan fuera
del alcance de v0.4 y se reservan para una revisión posterior, previsiblemente
v0.5.

## 11. Modelo de memoria y FENCE

Cada master observa sus propias operaciones ordinarias en orden de programa.
Masters distintos pueden observarlas en órdenes diferentes mientras no exista
sincronización. Los stores ordinarios conflictivos no son atómicos y su ganador
queda sin especificar.

`FENCE` es una barrera completa del master que la ejecuta:

- no termina hasta que todas sus lecturas y escrituras anteriores sean
  globalmente visibles y hayan finalizado;
- ninguna operación posterior puede presentarse al fabric antes de terminar;
- no espera a que otros masters alcancen ningún punto de control.

Estas reglas incluyen accesos ordinarios a MMIO. Por ejemplo, un programa puede
publicar datos en RAM, ejecutar `FENCE` y después escribir un registro MMIO de
puerta/READY con la garantía de que el dispositivo no observará la notificación
antes de los datos. Esto no autoriza `ATOMADD` ni `ATOMCAS` sobre MMIO.

Cuando una plataforma declara que DMA pertenece al dominio coherente, una
interrupción DMA de finalización solo puede hacerse pendiente después de que sus
escrituras anteriores sean globalmente visibles. El handler puede entonces leer
los datos transferidos al aceptar la IRQ, sin un protocolo adicional. En una
plataforma que declare `atomics`, ese mismo DMA debe participar del punto de
serialización del fabric si accede a la RAM compartida.

En GPU, `BAR` conserva el contrato vigente de [isa.md](isa.md): sincroniza los warps
participantes del mismo `workgroup_id`, exige `active_mask == live_mask` en
cada warp y completa sus operaciones de memoria anteriores antes de continuar.
Una máscara parcial produce `ERROR_BARRIER`.

En el modelo de memoria v0.4, «completar» exige finalización y visibilidad
global de los accesos anteriores, en el dominio de memoria compartida de la
plataforma, antes de liberar a los participantes. Ninguna operación de memoria
posterior de esos participantes puede adelantarse a esa finalización. Esto
precisa la garantía de memoria existente de BAR; no es una nueva capability.

Así, BAR incluye el efecto de un `FENCE` para cada lane participante y añade
la sincronización del workgroup. FENCE por sí solo no espera a otros
participantes. BAR no espera a CPU, DMA ni warps ajenos al grupo, y no convierte
accesos conflictivos ordinarios en operaciones atómicas frente a esos agentes.

En CPU, BAR es el NOP definido en §5.1 y no tiene los efectos de memoria de
este apartado. El código que necesite ordenar memoria tanto en CPU como en
GPU debe usar FENCE y requerir `memory_fence`.

## 12. Operaciones atómicas

Los atómicos operan sobre una palabra little-endian de 32 bits y exigen una
dirección múltiplo de cuatro. MMIO no admite atómicos por defecto y produce
`ATOMIC_ACCESS`; la única excepción es un dispositivo que documente
expresamente soporte atómico y su semántica de efectos laterales.

En CPU, `ATOMADD` y `ATOMCAS` exigen simultáneamente permisos PMP de lectura y
escritura. En `ATOMCAS` se comprueban ambos antes de leer, aunque la comparación
posterior no coincida y por tanto no se llegue a escribir; así CAS no abre un
camino de lectura especial sobre memoria de solo lectura. GPU y DMA aplican su
política de acceso de plataforma, pues PMP en v0.4 solo regula CPU.

`ATOMADD Rd, Ra, Rb`:

```text
address = old_Ra
value   = old_Rb
old     = MEM32[address]
MEM32[address] = low32(old + value)
Rd = old
```

`ATOMCAS Rd, Ra, Rb, Rc`:

```text
address  = old_Ra
expected = old_Rb
desired  = old_Rc
old      = MEM32[address]
if old == expected:
    MEM32[address] = desired
Rd = old
```

Todos los operandos se capturan antes de escribir `Rd`; los alias de registros
son válidos. `Rd=R0` descarta únicamente el resultado, no el acceso ni sus
errores.

`ATOMADD`, `ATOMCAS` y `FENCE` no son instrucciones privilegiadas. Pueden
ejecutarse en USER siempre que el acceso de memoria correspondiente esté
permitido por PMP; negar una región sigue produciendo `ATOMIC_ACCESS` sin
modificar memoria. Esto permite sincronización y colas compartidas entre
aplicaciones sin entregarles registros de control o acceso a memoria del kernel.

Cada atómico ocupa un único punto en un orden total de operaciones atómicas del
fabric. La lectura y posible escritura son indivisibles respecto a cualquier
acceso conflictivo de CPU, GPU, DMA u otro master coherente. Además:

- tiene semántica acquire para operaciones posteriores del mismo master;
- tiene semántica release para operaciones anteriores del mismo master;
- equivale a `FENCE; operación_atómica; FENCE` para ese master, aunque el
  hardware puede implementarlo de forma más eficiente.

Un fallo de alineación, permiso o acceso se detecta antes de modificar memoria
y tampoco escribe `Rd`.

### 12.1 GPU

Cada lane activa ejecuta su propia operación. Cuando varias lanes acceden a la
misma palabra, se serializan en un orden no especificado; cada lane recibe el
valor anterior correspondiente a su posición real en esa serialización.

La instrucción GPU es precisa a nivel de warp: todas las direcciones, la
alineación y la política de acceso de memoria de plataforma para las lanes
activas se validan antes de efectuar la primera modificación. PMP no participa,
pues en v0.4 solo regula CPU. Si una lane falla, ninguna lane modifica memoria
ni su registro destino, y el fallo identifica la dirección de la lane de índice
más bajo que falló. Esta regla evita resultados parciales no recuperables, a
costa de una fase previa de validación en el LSU.

En una GPU sin `privileged_traps`, ese fallo termina la GPU de forma global,
como los faults GPU vigentes. La parada fatal no relaja la precisión: ninguna
lane deja una modificación de memoria ni un registro destino actualizado para
la instrucción fallida.

Los masters no coherentes o memorias privadas quedan fuera del dominio de los
atómicos. La plataforma debe documentar el dominio coherente; declarar
`atomics` sin incluir todos los masters que acceden a esa RAM viola v0.4.

### 12.2 Implementación orientativa en fabric y LSU

La atomicidad se garantiza donde convergen los accesos conflictivos de todos
los masters del dominio coherente:

```text
CPU LSU ----+
GPU LSU ----+---- Memory fabric ---- RAM compartida
DMA --------+
```

Bloquear solo el LSU de CPU o GPU no basta: otro master podría intercalar un
acceso entre la lectura y la escritura. Una implementación inicial sencilla
concede exclusividad en el fabric durante toda la operación, haciendo esperar
a los demás masters. Las peticiones conflictivas ya aceptadas deben quedar
ordenadas respecto a esa operación antes de comenzar la lectura.

```text
ATOMADD: adquirir -> leer -> sumar -> escribir -> responder old -> liberar
ATOMCAS: adquirir -> leer -> comparar -> [si igual: escribir desired]
                    -> responder old -> liberar
```

El fabric puede compartir un sumador de 32 bits para ATOMADD y un comparador
de 32 bits más selección de escritura para ATOMCAS. CPU y GPU usan así el mismo
mecanismo de read-modify-write. El bloqueo global es una opción de implementación,
no un requisito de ISA: una evolución puede admitir accesos simultáneos a
direcciones independientes si conserva atomicidad, orden y finalización.
La validación previa de todas las lanes GPU de §12.1 sigue siendo obligatoria.

FENCE es principalmente responsabilidad del LSU/master. Puede esperar a que
no queden peticiones pendientes, la cola de stores esté vacía y todas las
transacciones anteriores hayan finalizado con la visibilidad exigida en §11.
El fabric debe proporcionar confirmaciones de finalización suficientes; no
necesita recibir una operación FENCE explícita si el master puede garantizar
el contrato sin ella.

En un master completamente bloqueante que ya satisface ese orden y visibilidad,
FENCE puede implementarse como NOP. Esa equivalencia debe comprobarse; no se
deduce solo de que no exista una cola visible de stores. Mantener la instrucción
permite introducir buffers, FIFOs, cachés, bursts y varias operaciones pendientes
sin cambiar el software. Estas opciones son orientativas y no afirman que los
backends actuales implementen atomics o memory_fence.

### 12.3 Ejemplos y usos

Con un contador inicial de 10, dos agentes que ejecutan ATOMADD con incremento
1 reciben 10 y 11 en algún orden, y dejan 12 en memoria. Una secuencia ordinaria
LOAD/ADD/STORE puede perder un incremento. ATOMADD sirve para contadores,
reservar posiciones en colas o arrays, contabilizar resultados, asignar IDs
únicos y acumular valores enteros módulo 2^32.

Con un lock inicial de cero, dos agentes que ejecutan ATOMCAS con expected=0 y
desired=1 no pueden adquirirlo ambos: uno recibe cero y escribe uno; el otro
recibe uno y no escribe. CAS permite construir locks, flags, máquinas de
estados, colas y asignación condicional de recursos. También permite implementar
otras operaciones atómicas mediante bucles CAS; CAS siempre es atómico en esta
ISA, sin variante no atómica. Estos ejemplos ilustran la primitiva, no un
protocolo completo de locks o de gestión de recursos.

Para publicar una estructura compartida, el productor escribe sus datos,
ejecuta FENCE y después escribe READY. El consumidor necesita la sincronización
apropiada antes de leer los datos; FENCE del productor no espera al consumidor.
BAR coordina participantes GPU y conserva el orden de memoria precisado en §11;
no convierte stores conflictivos en atómicos. Si varias lanes escriben valores
distintos en la misma dirección mediante STORE ordinario, no se garantiza cuál
queda almacenado.

### 12.4 Posible direccionamiento con inmediato

Las formas actuales ATOMADD y ATOMCAS usan como dirección exactamente Ra;
el software calcula los desplazamientos antes de ejecutar el atómico. Queda
abierta la opción de añadir variantes futuras con dirección base más inmediato,
si los programas justifican el ahorro de instrucciones y registros temporales.

ATOMADD necesita dos fuentes y admite estudiar un formato con inmediato más
fácilmente que ATOMCAS, que necesita dirección, expected y desired además del
destino. Antes de incorporar variantes habrá que definir formato, rango, unidad
y extensión del inmediato, capability y encoding. No se asignan ahora selectores
ni opcodes, ni se cambia el significado de las formas existentes. En bucles CAS
la dirección puede calcularse una sola vez fuera del bucle.

ATOMAND, ATOMOR, ATOMXOR, ATOMMIN, ATOMMAX y ATOMXCHG tampoco forman parte
del repertorio inicial; podrán evaluarse según casos de uso medidos.

## 13. Interrupciones

Una interrupción se toma únicamente si `STATUS.IE=1` y su bit está habilitado
en `IRQ_ENABLE` y `IN_TRAP=0`. `IRQ_PENDING` refleja fuentes pendientes aunque estén
enmascaradas. La forma de reconocer o limpiar una fuente pertenece al
dispositivo; leer `IRQ_PENDING` no la limpia. v0.4 define esta interfaz CPU,
las causas y los vectores, pero no fija registros MMIO universales para timer,
UART, GPU ni controlador de interrupciones: cada plataforma documenta su mapa,
la prioridad interna y la operación de acknowledge.

Los cuatro bits bajos de `IRQ_PENDING` e `IRQ_ENABLE` quedan asignados de forma
portable:

| Bit | Fuente                 | Causa                 | Vector |
|----:|------------------------|-----------------------|-------:|
| `0` | timer                  | `TIMER_INTERRUPT`     | `12`   |
| `1` | interrupción externa   | `EXTERNAL_INTERRUPT`  | `13`   |
| `2` | GPU                    | `GPU_INTERRUPT`       | `14`   |
| `3` | DMA                    | `DMA_INTERRUPT`       | `15`   |
| `4–31` | reservados/plataforma | —                   | comparte externa |

Si varias están disponibles simultáneamente, la prioridad inicial es:

1. timer;
2. externa;
3. GPU.
4. DMA.

Este orden queda fijado por v0.4 para que un kernel no dependa de arbitraje
particular de cada placa. Las fuentes agrupadas dentro de la interrupción
externa mantienen la prioridad que documente su controlador, y el handler las
desambiguará mediante `IRQ_PENDING`.

Una excepción síncrona de la instrucción que se retira tiene prioridad sobre
una interrupción pendiente. Tras `ERET`, una interrupción aún pendiente puede
volver a tomarse antes de ejecutar otra instrucción.

## 14. Reset y estado observable

Después de reset:

```text
MODE        = SUPERVISOR
IE = PIE    = 0
PMODE       = SUPERVISOR
IN_TRAP     = 0
EPC         = 0
CAUSE       = 0
BADADDR     = 0
TVEC        = 0, DIRECT
IRQ_ENABLE  = 0
PMP_DEFAULT = 0b111          ; USER R/W/X fuera de regiones
KSP         = 0              ; supervisor lo prepara antes de ENTERUSER
regiones PMP deshabilitadas
PC          = vector de reset de la plataforma
```

El vector de reset no es un trap y no modifica `EPC/CAUSE`.

## 15. Implementación por fases

1. Nuevo ensamblador/perfil v0.4 y alias `ABORT`, preservando los backends
   existentes hasta que declaren explícitamente soporte del nuevo perfil.
2. Familia `SYSTEM`, registros SR, `TRAP/ERET` y modo DIRECT.
3. Conversión de errores CPU en excepciones precisas.
4. PMP y pruebas USER/SUPERVISOR de fetch/load/store/MMIO.
5. Timer, controlador de interrupciones y modo VECTORED.
6. `FENCE`, primero como NOP comprobado en masters bloqueantes.
7. `ATOMADD` CPU y serialización en el memory fabric.
8. `ATOMCAS` CPU y pruebas CPU/DMA concurrentes.
9. Atómicos GPU con prevalidación de lanes y pruebas CPU/GPU concurrentes.
10. Optimización del fabric sin cambiar el orden arquitectónico.

Cada fase debe disponer de modelo funcional y tests diferenciales antes de
declarar su capability en hardware.

### 15.1 Validación del repertorio y del perfil

Cada capability exige un modelo de referencia y pruebas antes de anunciarse.
Los resultados arquitectónicos se comparan por separado de ciclos, área y
frecuencia; agrupar opcodes no garantiza acelerar el backend.

- Recompilar programas comunes de la ISA vigente para v0.4 y comparar sus
  resultados cuando caben los inmediatos y el backend ofrece las capabilities;
  no exigir igualdad de binarios, PCs numéricos ni número de instrucciones.
- Verificar versión de ISA y capabilities del binario/backend antes de ejecutar.
  Un subopcode no soportado o campo reservado no nulo debe seguir los errores
  de §4 y las reglas de traps, sin activar toda una familia por una sola variante.
- Cubrir R0, fuentes/destinos coincidentes, signos, wrap, división por cero,
  suboperaciones altas de MUL y equivalencia MACFX a MULFX+ADD.
- Probar límites y extensión de imm5/off16, ramas tomadas/no tomadas,
  divergencia/reconvergencia y destinos uniformes o divergentes de JALR/RET
  antes de escribir enlaces.
- Probar LEAPC con reubicación, límites de off21 y wrap; LOADX con escalas
  0..3, desalineación, intervalo completo, aliases de registros y máscaras GPU.
- Cubrir bytes vecinos, accesos pequeños, postincremento y fallos parciales
  GPU observables. BAR no puede liberar participantes con accesos pendientes.
- Cubrir máscaras divergentes, BALLOT/ACTIVEMASK y fuentes SHFL inactivas o
  fuera del warp, incluida captura previa de fuentes cuando Rd coincide con ellas.
- Probar ID lógico y argumento por warp, reset del sistema, conservación con
  GPU_CONTROL.RESET y HALT/RESUME, y traslado de valores por el lanzador.
- Verificar traps precisos, permisos, vectorización, intercambio de pilas,
  errores anidados y arbitraje de atómicos CPU/GPU/DMA según §8–§13.
- Comparar FP32 con su referencia numérica, incluidos subnormales, NaN,
  infinitos, ceros con signo, RNE, DAZ/FTZ y FDIV por cero sin trap.
- Cerrar contratos y modelos numéricos de RCPFX/RSQRTFX antes de habilitarlas.
  Medir después el coste de lecturas adicionales, subdecodificadores y redes
  de comunicación entre lanes, sin convertir una latencia en contrato de ISA.

## 16. Decisiones cerradas y evolución posterior

Los siguientes puntos quedan fijados para v0.4 o se posponen explícitamente;
no son permisos para que una implementación elija otra semántica:

1. **PMP de cuatro regiones.** v0.4 implementa cuatro regiones de granularidad
   32 bytes, compactadas en `BASECFG/LIMIT`; reserva `SR17–SR24` para elevarlas
   a ocho mediante una futura capability `pmp8` y conserva `SR25–SR31` libres.
2. **Dieciséis vectores.** La tabla compacta ocupa 64 bytes. Nuevas fuentes de
   interrupción deberán compartir el vector externo y distinguirse mediante
   `IRQ_PENDING`, o exigir una futura revisión del mecanismo de vectorización.
3. **Compatibilidad PMP tras reset.** Queda fijado `PMP_DEFAULT=0b111`: USER
   conserva acceso completo hasta que supervisor configure protección. Es un
   modo deliberadamente compatible, no seguro para ejecutar código no confiable.
4. **Solapamiento PMP.** Queda fijada la prioridad de la región de menor índice.
   Permite instalar primero una denegación específica y después reglas más
   generales, sin que estas la reabran por accidente.
5. **Atómicos con orden fuerte.** Queda fijado que `ATOMADD` y `ATOMCAS`
   equivalen arquitectónicamente a `FENCE; atómico; FENCE`. Variantes con orden
   más débil solo podrán añadirse como instrucciones o subfunciones nuevas, no
   reinterpretando estas dos.
6. **Precisión GPU por warp.** Queda fijada la prevalidación de todas las lanes
   activas antes de iniciar la operación. Un fallo en cualquiera de ellas anula
   la instrucción entera del warp; el coste de área y latencia no autoriza una
   implementación con efectos parciales.
7. **Rango de syscall en `TRAP`.** Se reservan los 26 bits bajos y el cero
   conserva la parada fatal. Es un espacio muy amplio, pero convierte `TRAP`
   en el único opcode cuyo formato cambia según que esos bits sean cero.
8. **Un solo nivel hardware de trap.** Queda fijado un único banco de
`EPC/CAUSE/BADADDR/PMODE/PIE`. Mientras `IN_TRAP=1`, las interrupciones siguen
aplazadas y un segundo fallo síncrono produce `ERROR_DOUBLE_FAULT` fatal. Un
anidamiento futuro requiere una extensión arquitectónica con contexto adicional.
9. **Atómicos actuales sin inmediato.** La dirección es exactamente
   `Ra`; el software calcula cualquier offset antes de ejecutar el atómico.
   No se añade un formato especial ni un opcode adicional. Se deja abierta
   la evaluación de variantes futuras con inmediato según §12.4.
10. **ABI de syscall.** Queda fijada: `R1–R4` son argumentos, `R1` devuelve el
   valor y `R2` el código de error. Los retornos adicionales, si se necesitan,
   usan `R3` y `R4` por contrato del servicio.
11. **MMU.** Queda fuera de v0.4. PMP proporciona aislamiento físico, no
   procesos con memoria virtual; PTBASE, TLB y page faults se abordarán en una
   revisión posterior, previsiblemente v0.5.

## 17. Extensión opcional: interfaz con etapas fijas GPU

Esta sección describe una dirección de microarquitectura para conectar shaders,
CPU y etapas fijas como ensamblado de primitivas, rasterizador o compositor. No
asigna todavía opcodes, registros ABI ni capabilities: no forma parte del
contrato ejecutable de v0.4 hasta que exista RTL, un modelo de referencia y
medidas de coste.

### 17.1 Dos productores, una cola lógica

```text
GPU shader ── exportación interna ─┐
                                   ├─ cola/FIFO on-chip ── etapas fijas
CPU ── command port MMIO ──────────┘
```

La cola puede estar implementada en EBR/FIFO interna; “cola” no implica una ida
a SDRAM por cada vértice o fragmento. La RAM queda para command buffers grandes,
descriptores, texturas y buffers persistentes. El frontend arbitra los dos
productores y conserva el orden de cada paquete aceptado.

### 17.2 Exportación GPU propuesta

Un futuro `PIPE.EMIT` podría capturar registros de salida fijos del shader y
emitir un paquete por cada lane activa. Una ABI posible reservaría una ventana
alta de registros para posición, color, coordenadas de textura y flags. Con ocho
lanes activas, una emisión genera ocho entradas en orden de lane 0 a 7.

La operación debe ser atómica a nivel de warp: si la FIFO no tiene espacio para
todas las entradas activas, no acepta ninguna y el warp espera. El scheduler
puede ejecutar otros warps mientras tanto. Nunca se deja una emisión a medio
encolar, porque complicaría reintentos y recovery.

No se reserva aún `0x37` para ello. Si los perfiles demuestran que la interfaz
merece una instrucción, una familia `PIPE` en uno de los opcodes libres de
sistema/SIMT permitiría múltiples suboperaciones sin consumir el mapa entero.

### 17.3 Camino CPU

La CPU no necesita usar la ABI de registros GPU ni emitir píxeles uno a uno.
Puede publicar comandos compactos mediante un puerto MMIO, por ejemplo
`CLEAR`, `FILL_RECT`, `BLIT` o configuración de estado. Una secuencia típica
publica argumentos, ejecuta `FENCE` y escribe un registro de submit/doorbell:

```asm
STORE argumentos, RASTER_ARGn
FENCE
STORE comando,    RASTER_SUBMIT
```

El `FENCE` de v0.4 ya garantiza que el frontend no observe el submit antes de
los argumentos. Un estado, ticket o interrupción permite a CPU esperar la
finalización si la operación lo necesita.

### 17.4 Relación con GPUs comerciales

El esquema reproduce a escala educativa una separación común: CPU/driver
publica comandos para un frontend, mientras los shaders exportan resultados por
rutas internas hacia el pipeline fijo. En hardware comercial esas rutas suelen
ser varias colas y arbitrajes, no necesariamente una FIFO física única; aquí la
cola lógica hace visible el contrato sin imponer la implementación.

## 18. Guía no normativa de uso gráfico

Estas instrucciones no dibujan un triángulo por sí solas. Aceleran pasos pequeños
que se repiten en transformaciones, rasterización y escritura de imágenes.
Los ejemplos son ensamblador **propuesto para v0.4**; no implican que el
ensamblador actual ya acepte los mnemónicos nuevos. Requieren las capabilities
correspondientes. En GPU cada lane trabaja con sus propios registros y solo
participan las lanes activas.

En los ejemplos Q16.16, el entero 65536 representa 1.0; 32768 representa 0.5.
Las fórmulas deben mantenerse dentro del rango representable: estas operaciones
no eliminan la cuantización ni el overflow. Menos instrucciones suele reducir
fetch, decodificación y temporales, pero el ahorro de ciclos depende del RTL y
de la memoria. Aquí se comparan secuencias, no se prometen aceleraciones medidas.

### 18.1. PACK565: guardar un color en el framebuffer

Un color RGB888 ocupa tres canales de ocho bits. RGB565 usa cinco para rojo,
seis para verde y cinco para azul: cabe en dos bytes y conserva más precisión
en verde. Por ejemplo, rojo puro `0x00FF0000` se convierte en `0xF800`.

```asm
; R1 = 0x00RRGGBB; R2 = direccion par del pixel
PACK565 R3, R1
STOREH  R3, R2, 0
```

Sin `PACK565`, una conversión equivalente con shifts inmediatos sería:

```asm
SHRI R3, R1, 8
ANDI R3, R3, 0xF800
SHRI R4, R1, 5
ANDI R4, R4, 0x07E0
OR   R3, R3, R4
SHRI R4, R1, 3
ANDI R4, R4, 0x001F
OR   R3, R3, R4
STOREH R3, R2, 0
```

El empaquetado pasa de ocho instrucciones a una y evita el temporal R4.
No añade precisión: ambas secuencias descartan los mismos bits bajos de color.
Tampoco transforma tres registros RGB en uno: recibe los canales ya reunidos
como `0x00RRGGBB`. Si el cálculo produjo canales separados, hay que reunirlos
antes; su coste debe incluirse al medir el beneficio.

### 18.2. UNPACK565R/G/B: operar sobre los canales de un color

Para iluminar un color, mezclarlo con otro o aplicar una ganancia, interesa
obtener canales independientes. Primero se carga el pixel sin signo:

```asm
LOADUH     R4, R5, 0
UNPACK565R R1, R4
UNPACK565G R2, R4
UNPACK565B R3, R4
; R1, R2 y R3 contienen enteros de 0 a 255
```

Cada canal se expande replicando bits; por ejemplo, rojo 31 pasa a 255.
No recupera los bits originales perdidos al empaquetar, pero cubre todo el
rango de ocho bits. Un simple `r5 << 3` solo llegaría a 248.

La alternativa para extraer y expandir únicamente rojo es:

```asm
SHRI R1, R4, 11
ANDI R1, R1, 31
SHRI R6, R1, 2
SHLI R1, R1, 3
OR   R1, R1, R6
```

`UNPACK565R` sustituye esas cinco instrucciones y el temporal R6. Si solo se
necesita rojo, no se calculan verde y azul. Mantener una instrucción por canal
permite usar el banco de registros con un único destino por instrucción;
una operación con tres destinos necesitaría más puertos o secuenciar escrituras.

### 18.3. MULFX y MACFX: transformar coordenadas

Una transformación 2D puede calcular una coordenada como:

```text
x_nueva = a*x + b*y + tx
```

Si todos los valores están en Q16.16:

```asm
; R1=a, R2=x, R3=b, R4=y, R5=tx
MULFX R6, R1, R2
MACFX R6, R3, R4
ADD   R6, R6, R5
```

Sin `MACFX`, el segundo producto necesita un temporal y una suma explícita:

```asm
MULFX R6, R1, R2
MULFX R7, R3, R4
ADD   R6, R6, R7
ADD   R6, R6, R5
```

`MACFX` ahorra una instrucción y un temporal en esta secuencia. Su resultado es
exactamente el de multiplicar con `MULFX` y sumar: no es una operación fusionada
con mayor precisión. Es útil también para productos escalares 3D y sumas
ponderadas de atributos. Al leer el antiguo destino, puede necesitar otro ciclo
en un banco con dos puertos de lectura; el ahorro de ciclos debe medirse.

`MULFX` por su parte integra el ajuste de escala: multiplicar dos valores Q16.16
produce un producto con 32 bits fraccionales, y desplazarlo 16 bits devuelve
Q16.16. `MUL` seguido de `SAR` no es equivalente en general, porque `MUL` ya
ha descartado la mitad alta del producto antes del desplazamiento.

### 18.4. RCPFX: perspectiva y atributos de textura

En proyección perspectiva se divide por la coordenada homogénea w:

```text
x_proyectada = x / w
y_proyectada = y / w
```

Un único recíproco permite compartir el trabajo entre ambas coordenadas:

```asm
; R1=x, R2=y, R3=w, todos Q16.16
RCPFX R4, R3
MULFX R5, R1, R4
MULFX R6, R2, R4
```

Por ejemplo, con x=2, y=1 y w=4, los resultados ideales son 0.5 y 0.25.
Después todavía faltan la transformación al viewport y la conversión a pixel.
No toda transformación 2D necesita este paso: una transformación afín no divide
por w; una transformación proyectiva sí puede hacerlo.

Otra aplicación es la interpolación de texturas con corrección de perspectiva.
Durante la rasterización se interpolan `u/w`, `v/w` y `1/w`. En cada pixel:

```text
d = interpolacion(1/w)
u = interpolacion(u/w) * RCPFX(d)
v = interpolacion(v/w) * RCPFX(d)
```

Se reutiliza el mismo recíproco de d para ambos atributos. Interpolar u y v
directamente en pantalla no da en general el mismo resultado perspectivo.

La alternativa es una rutina software de división fixed-point o una tabla con
refinamiento. Para representar `1/x` en Q16.16 se necesita conceptualmente
`2^32 / X`, donde X es la representación entera de x: el numerador no cabe en
un registro unsigned de 32 bits. `DIV Rdest, R0, X` no resuelve este problema,
ni lo hace dividir el entero 1 por X.

El beneficio esperado es expresar una operación numérica reutilizable con una
instrucción y evitar repetir divisiones. **Precisión y rendimiento siguen
pendientes:** antes de implementar hay que definir redondeo, cero y overflow,
y comprobar el error visual y numérico frente al modelo de referencia.

### 18.5. RSQRTFX: normalizar normales para iluminación

Una normal indica hacia dónde apunta una superficie. Para cálculos como el
producto escalar con la dirección de la luz suele interesar que tenga longitud 1.
Para el vector (x,y,z):

```text
longitud2 = x*x + y*y + z*z
factor = 1 / sqrt(longitud2)
normal = (x*factor, y*factor, z*factor)
```

```asm
; R1=x, R2=y, R3=z, Q16.16 y en un rango seguro
MULFX   R4, R1, R1
MACFX   R4, R2, R2
MACFX   R4, R3, R3
RSQRTFX R5, R4
MULFX   R6, R1, R5
MULFX   R7, R2, R5
MULFX   R8, R3, R5
```

El vector (3,0,4) tiene longitud 5: idealmente el factor es 0.2 y la normal
(0.6,0,0.8), con las aproximaciones propias de Q16.16.

La alternativa calcula una raíz y después un recíproco, o ejecuta una rutina
iterativa equivalente. `RSQRTFX` ofrece directamente el factor que se reutiliza
en las tres componentes. No sustituye una raíz general cuando se necesita la
longitud en sí. El vector cero, valores diminutos y overflow de `longitud2`
necesitan tratamiento explícito; el contrato de la instrucción sigue pendiente.

### 18.6. MIN/MAX: limitar coordenadas y valores

Antes de recorrer una caja de pixeles conviene limitarla al framebuffer.
Por ejemplo, fijar una coordenada signed al intervalo `[0, ancho-1]`:

```asm
; R1=x, R2=ancho-1
MAX R3, R1, R0
MIN R3, R3, R2
```

Una alternativa con control de flujo sería:

```asm
ADD R3, R1, R0
BGE R3, R0, no_negativo
ADD R3, R0, R0
no_negativo:
BGE R2, R3, dentro
ADD R3, R2, R0
dentro:
```

En CPU, `MIN/MAX` evitan los saltos y expresan el límite con dos instrucciones.
En GPU, si cada lane tiene una coordenada distinta, las decisiones del ejemplo
pueden divergir y necesitar el control SIMT apropiado; `MIN/MAX` seleccionan
por lane sin cambiar la máscara activa. El ejemplo alternativo ilustra la
lógica escalar, no una región SIMT ya preparada con `SSY`.

Hay que elegir el signo correcto: `MINU/MAXU` son útiles para magnitudes
unsigned, pero interpretar una coordenada negativa como unsigned la convierte
en un número grande. Limitar una coordenada tampoco sustituye decidir si una
primitiva debe descartarse por estar completamente fuera de pantalla.

### 18.7. SEL: elegir valores sin abrir una rama

Supongamos que se han calculado dos colores y una condición de cobertura:

```asm
; R1=color interior, R2=color exterior, R3=condicion (cero/no cero)
SEL R4, R1, R2, R3
```

La alternativa escalar copia uno de los colores y salta para cambiarlo:

```asm
ADD R4, R2, R0
BEQ R3, R0, elegido
ADD R4, R1, R0
elegido:
```

`SEL` usa una instrucción y evita divergencia para seleccionar datos ya
calculados. No evita el coste de producir ambos colores ni suprime cargas o
stores de una rama: no sustituye un condicional con efectos laterales.
Tampoco implementa por sí sola depth testing atómico ni hace que varias lanes
puedan actualizar un mismo pixel sin coordinación.

### 18.8. STOREHP y STOREBP: recorrer una imagen

Para escribir una fila RGB565, cada pixel ocupa dos bytes:

```asm
; R1=color RGB565; R2=puntero par
STOREHP R1, R2, 2
```

En ejecución sin errores, el efecto corresponde a:

```asm
STOREH R1, R2, 0
ADDI   R2, R2, 2
```

Se ahorra una instrucción por pixel y se expresa directamente el patrón de
recorrido. `STOREBP ... ,1` hace lo mismo para índices de paleta de un byte;
`STOREP ... ,4`, para palabras. El incremento también puede ser un stride para
recorrer una columna, si cabe en signed imm14.

El acceso utiliza la base anterior: el inmediato es el incremento posterior,
no un desplazamiento de la escritura. La base solo se actualiza cuando el
acceso termina correctamente. Esto no incrementa automáticamente el ancho de
banda SDRAM ni crea ráfagas; esas mejoras pertenecen al controlador de memoria.

### 18.9. Votos SIMT: saber qué lanes tienen trabajo

Una lane puede representar un pixel candidato. Después de calcular una
condición de cobertura en R1, `BALLOT` construye una máscara común:

```asm
BALLOT R2, R1
POPC   R3, R2
; R3 = numero de lanes participantes cuya condicion era verdadera
```

Con ocho lanes activas y resultados verdaderos en las lanes 0, 2 y 5, el ballot
es `0x25` y el recuento es 3. Puede servir para contar cobertura, organizar una
compactación o tomar una decisión común. La máscara por sí sola no redistribuye
trabajo ni modifica `active_mask`.

Sin estas operaciones, las lanes tendrían que comunicar sus condiciones por
memoria y combinarlas, con almacenamiento y sincronización apropiados.
`BALLOT` expresa la comunicación de un bit por lane; `POPC` cuenta los bits sin
un bucle software. Si se calcula dentro de una rama divergente, solo describe
las lanes activas en esa rama. `ACTIVEMASK` permite conocer ese conjunto:
comparar ballot con cero responde a «alguna», y compararlo con la máscara
participante responde a «todas», sin crear una barrera.

### 18.10. SHFL: compartir un dato calculado por otra lane

Si todas las lanes participantes necesitan un valor que ha calculado la lane 0:

```asm
; La lane 0 esta activa y tiene el valor en R1
SHFL R2, R1, R0
```

Cada participante selecciona la fuente 0 porque su R0 vale cero. El valor de R1
de esa lane se distribuye a R2 de las participantes. Esto puede servir para
compartir un parámetro común de un tile o como paso de una reducción.

La alternativa escribe el dato a memoria, establece la sincronización y
visibilidad necesarias, y lo carga en las consumidoras. SHFL propone un camino
directo entre lanes del mismo warp; no comunica warps distintos. No espera a
que una lane inactiva produzca el valor ni sustituye una barrera.
El ejemplo presupone fuente válida y activa; si la lane 0 está inactiva, las
participantes reciben cero. El coste de hardware debe medirse.

## 19. Guía no normativa de tablas y direccionamiento

LEAPC obtiene una dirección y LOADX lee su contenido mediante base e índice
escalado. Sus contratos completos están en §5.4.4 y §5.4.5. LDR relativo al PC
es una alternativa sin encoding ni capability asignados, no una instrucción v0.4.

### 19.1 Dirección cercana con LEAPC

```asm
LEAPC R1, tabla_senos
; R1 es la dirección de la tabla, no su primer valor
```

La alternativa es construir una dirección absoluta con MOVHI y ORI, con el
soporte de símbolos/relocaciones correspondiente. LEAPC evita una instrucción
cuando la tabla cabe en alcance. Si código y tabla se desplazan juntos, la
distancia permanece igual: el cálculo sigue funcionando sin corregir una
constante absoluta. Esto no hace reubicable automáticamente el resto del programa.

### 19.2 Entradas de cuatro bytes con LOADX

```asm
; R1 = base; R2 = indice
LOADX R3, R1, R2, 2
```

Con base 0x1000 e índice 3, lee desde 0x100C. La alternativa es:

```asm
SHLI R4, R2, 2
ADD  R4, R1, R4
LOAD R3, R4, 0
```

LOADX sustituye tres instrucciones por una y elimina R4. Lee dos registros y
escribe uno, pero añade el índice escalado al camino de dirección: el RTL puede
necesitar varios ciclos para no empeorar timing. No acorta por sí sola la lectura
SDRAM ni crea una caché.

### 19.3 Combinación para tablas

```asm
LEAPC R1, tabla_senos   ; normalmente fuera del bucle
; ... calcular el indice en R2 ...
LOADX R3, R1, R2, 2    ; tabla_senos[indice], entrada de 32 bits
```

LEAPC localiza la tabla; LOADX selecciona su elemento. La base se reutiliza
para muchos índices. El mismo patrón sirve para paletas de palabras, tablas de
coeficientes y datos de vértices. Ambas operaciones mantienen un único destino.

### 19.4 LDR relativo al PC: alternativa sin asignación

Idea sin encoding asignado, con sintaxis todavía orientativa:

```asm
LDR R1, constante
; Conceptualmente: R1 = memoria32[PC + 4 + offset]
```

Si constante contiene 0x12345678, LDR devuelve ese valor, mientras que LEAPC
devolvería la dirección donde está almacenado. Frente a:

```asm
MOVHI R1, 0x1234
ORI   R1, R1, 0x5678
```

LDR ejecutaría una instrucción, pero añade una lectura de memoria y requiere
almacenar cuatro bytes de constante. Si solo se usa una vez, instrucción más
constante ocupa lo mismo que las dos instrucciones anteriores. Varias cargas
pueden compartir el literal; su rentabilidad depende de la memoria.

El offset de LDR es fijo: no sustituye el índice variable de LOADX. Para una
tabla, la propuesta prioriza LEAPC + LOADX. LDR queda pendiente de utilidad medida,
encoding, alcance, unidad del offset y errores. PC+4 en este ejemplo es una
posible base, no un contrato ya adoptado para una instrucción asignada.

## 20. Guía no normativa de trigonometría

### 20.1. Tabla de seno con fase en vueltas

Se propone explorar una convención software de fase con 65536 unidades por
vuelta: fase 0 es 0 grados, 16384 es 90 grados, 32768 es 180 grados.
La fase se toma módulo 65536. **No es Q16.16 en radianes** ni una decisión
adoptada para las futuras instrucciones trigonométricas.

Una tabla con 256 intervalos puede guardar muestras Q16.16:

```text
tabla[i] = cuantizar_Q16.16(sin(2*pi*i/256)), i=0..256
```

La entrada 256 repite la entrada 0. Ocupa 257 palabras, 1028 bytes. Esa entrada
extra permite leer i+1 sin un caso especial al final de la vuelta.
Para una fase de 16 bits, el byte alto selecciona el intervalo y el byte bajo
indica la fracción dentro de él.

```asm
; R1 = base de una tabla de 257 muestras, obtenida con LEAPC
; R2 = fase; resultado en R8; R3..R7 son temporales
ANDI R2, R2, 0xFFFF
SHRI R3, R2, 8          ; indice 0..255
ANDI R4, R2, 0xFF
SHLI R4, R4, 8          ; fraccion Q16.16: (fase & 255)/256
LOADX R5, R1, R3, 2    ; muestra[i]
ADDI R6, R3, 1
LOADX R7, R1, R6, 2    ; muestra[i+1], incluida la entrada 256
SUB   R7, R7, R5
ADD   R8, R5, R0
MACFX R8, R7, R4        ; a + (b-a)*fraccion
```

La interpolación suaviza los escalones frente a seleccionar solamente la
muestra más cercana. Introduce error de aproximación y cuantización; no produce
el seno exacto. El tamaño de tabla, formato y redondeo deben elegirse según el
error permitido. No hace falta una instrucción nueva de interpolación:
SUB y MACFX cubren el cálculo una vez cargadas las muestras.

El coseno reutiliza la misma tabla evaluando la fase más 16384, reducida módulo
65536. No hace falta una segunda tabla. Este formato de fase facilita extraer
índice y fracción con bits y expresar la periodicidad sin dividir por 2*pi.

### 20.2. Elegir entre memoria y cálculo

| Método                    | Ventaja                                               | Coste o límite                                         |
| ------------------------- | ----------------------------------------------------- | ------------------------------------------------------ |
| Tabla sin interpolación   | Una consulta y cálculo de índice sencillo             | Más escalones o una tabla mayor                        |
| Tabla con interpolación   | Mejor aproximación con tabla pequeña                  | Dos cargas y aritmética; error por cuantización        |
| Aproximación polinómica   | Puede reducir accesos a memoria                       | Coeficientes, reducción de rango y varios productos    |
| CORDIC                    | Calcula funciones mediante etapas de sumas y shifts   | Iteraciones o área de pipeline; escalado y precisión   |

Una tabla en EBR/ROM cercana puede ser más útil que una tabla en SDRAM, pero
las lanes pueden consultar índices distintos. El número de puertos puede
obligar a serializar accesos. Ubicación, bancos y cachés son decisiones de
microarquitectura: LEAPC y LOADX no garantizan una memoria más rápida.

El software puede probar primero una tabla y su error con las instrucciones
existentes/propuestas. No se necesita añadir una instrucción específica por
cada tabla de seno, gamma, iluminación o animación.

### 20.3. SINFX y COSFX como posibles instrucciones

Se conservan como ideas opcionales, **sin opcode, func6 ni capability asignados**:

```asm
SINFX Rd, Ra
COSFX Rd, Ra
```

Cada una escribe un único resultado. No se propone SINCOS con dos destinos.
Una implementación podría compartir una tabla interna o una unidad CORDIC;
si reutiliza resultados entre instrucciones, debe ser transparente y conservar
el resultado cuando no exista reutilización.

Antes de asignarlas falta decidir:

- Ángulo en radianes Q16.16 o fase en fracciones de vuelta; no intercambiarlos
  bajo el mismo mnemónico sin una definición explícita.
- Formato de salida, previsiblemente Q16.16, y representación exacta de ±1.
- Periodicidad, reducción de rango, redondeo y error máximo.
- Referencia numérica verificable y resultados permitidos entre backends.
- Área, latencia y frecuencia comparadas con la rutina de tablas.

La prioridad propuesta es validar LEAPC + LOADX y una rutina de tabla con
interpolación. SINFX/COSFX se justificarían si el uso y las medidas compensan
una unidad dedicada. Estas alternativas trigonométricas y LDR no cambian el
recuento: el mapa contiene **55 opcodes principales asignados y 9 libres**,
incluyendo LEAPC y LOADX.

## 21. Otras extensiones sin asignación

Quedan como posibilidades de estudio, sin opcode, capability ni expansión de
ensamblador definidos:

- `DIVFX`: división Q16.16, con las limitaciones expuestas en §5.
- `MULFXR`: multiplicación con redondeo, cuyo modo y casos límite habría que fijar.
- `FXTOI`: conversión a entero con contrato explícito de redondeo y overflow.
- Pseudoinstrucciones para rutinas de redondeo, saturación y conversión, definiendo
  sus expansiones y registros temporales.

Estas ideas no modifican el repertorio ni el recuento de opcodes de esta revisión.

También quedan fuera del mapa BFEXT/BFINS/BSET/BCLR, ROL/ROR y MADD entero.
Las variantes ANY/ALL y otras formas de SHFL se evaluarán según usos medidos;
las secuencias con BALLOT/ACTIVEMASK de §5.1.8 ya cubren esos votos básicos.
Los atómicos adicionales y posibles offsets inmediatos se tratan en §12.4;
la interfaz propuesta con etapas fijas de §17 no tiene opcode asignado.
