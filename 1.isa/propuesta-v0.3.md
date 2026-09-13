# Propuesta de MiniISA v0.3

## 1. Objetivos de la revisión

La versión v0.3 reorganiza la ISA antes de estabilizar su codificación. En este momento la compatibilidad binaria con versiones anteriores no es prioritaria, por lo que se aprovecha la revisión para simplificar el mapa de opcodes y hacerlo más ortogonal.

Los principales criterios son:

- Mantener instrucciones de 32 bits.
- Mantener opcodes de 6 bits.
- Evitar gastar un opcode diferente en variantes de una misma operación.
- Utilizar campos secundarios para seleccionar variantes que comparten datapath.
- Mantener una decodificación sencilla en hardware.
- No penalizar innecesariamente el Fmax.
- Incorporar operaciones útiles para C, gráficos y ejecución GPU.
- Mantener espacio suficiente para futuras extensiones.
- Introducir un registro cero arquitectónico sin desperdiciar necesariamente su almacenamiento físico.

La idea general de v0.3 es:

> **El opcode identifica una clase de operación y los campos internos seleccionan sus variantes.**

---

# 2. Estado arquitectónico

La arquitectura mantiene:

- palabra de datos de 32 bits;
- instrucciones de longitud fija de 32 bits;
- 32 identificadores de registro `R0-R31`;
- PC de 32 bits;
- direccionamiento por byte;
- little-endian;
- opcode de 6 bits;
- ausencia de FLAGS;
- ausencia de delay slots;
- overflow entero módulo `2^32`.

La principal modificación respecto a v0.1 es:

```text
R0 = ZERO
```

`R0` es un registro arquitectónico de solo lectura cuyo valor es siempre:

```text
0x00000000
```

Cualquier escritura dirigida a `R0` se descarta.

Por tanto, quedan:

```text
R0      = ZERO
R1-R31  = 31 registros generales
```

Como convención de software se propone:

```text
R31 = link register / dirección de retorno
R30 = stack pointer
```

Estas convenciones no requieren tratamiento especial por hardware.

---

# 3. R0 como registro cero

La semántica arquitectónica es:

```text
read(R0)  = 0
write(R0) = discard
```

Esto permite construir numerosas pseudoinstrucciones sin dedicarles opcode:

```asm
MOV   Rd,Rs      -> ADD  Rd,Rs,R0
NEG   Rd,Rs      -> SUB  Rd,R0,Rs

BEQZ  Rs,label   -> BEQ  Rs,R0,label
BNEZ  Rs,label   -> BNE  Rs,R0,label
BLTZ  Rs,label   -> BLT  Rs,R0,label
BGEZ  Rs,label   -> BGE  Rs,R0,label
```

También permite almacenar cero directamente:

```asm
STORE  R0,Ra,offset
STOREB R0,Ra,offset
STOREH R0,Ra,offset
```

y utilizar `R0` como base para direcciones absolutas pequeñas:

```asm
LOAD R1,R0,0x100
```

---

# 4. Reutilización física del slot R0

Que `R0` valga siempre cero arquitectónicamente no implica que la posición física correspondiente al índice cero del banco de registros deba permanecer inutilizada.

La implementación puede mantener:

```text
R0 arquitectónico     = constante cero
registers[0] físico   = estado microarquitectónico oculto
```

El software, el assembler y el debugger arquitectónico nunca pueden observar el contenido real de `registers[0]`.

Las lecturas de `R0` devuelven cero mediante lógica de selección:

```text
read_address == 0 ? 0 : registers[read_address]
```

y las escrituras arquitectónicas a `R0` se descartan.

Sin embargo, internamente la CPU o GPU puede utilizar la posición física `registers[0]` como almacenamiento temporal.

## 4.1 Uso como valor de cache microarquitectónica

Un uso especialmente interesante es almacenar el **resultado secundario** de operaciones que producen más información de la que devuelve una única instrucción.

Por ejemplo:

```text
DIV -> cociente + resto
MUL -> low32 + high32
```

Después de:

```asm
DIV R5,R2,R3
```

puede quedar:

```text
R5                   = quotient
physical registers[0] = remainder
```

La unidad DIV mantiene aparte la información necesaria para determinar si ese valor es reutilizable:

```text
cached dividend
cached divisor
signed/unsigned
valid
```

Por tanto, una instrucción posterior:

```asm
REM R6,R2,R3
```

puede comprobar la key de la cache.

Si existe hit:

```text
R6 <- physical registers[0]
```

sin repetir la división.

Si no existe hit, `REM` realiza normalmente la división.

La misma estrategia puede aplicarse a multiplicación:

```asm
MUL  R5,R2,R3
MULH R6,R2,R3
```

donde `MUL` puede dejar temporalmente:

```text
physical registers[0] = high32(product)
```

y la unidad MUL conserva los operandos y modo necesarios para validar el resultado.

## 4.2 La cache es transparente

Este mecanismo es estrictamente microarquitectónico.

Una instrucción como:

```asm
REM R6,R2,R3
```

debe funcionar correctamente aunque:

- no se haya ejecutado anteriormente `DIV`;
- la cache no sea válida;
- los operandos anteriores sean distintos;
- el contenido físico de `registers[0]` haya sido reemplazado;
- la implementación concreta no incorpore esta optimización.

Por tanto:

> **El comportamiento arquitectónico nunca depende del contenido oculto del slot físico R0.**

Su utilización únicamente permite evitar cálculos redundantes.

## 4.3 Uso alternativo como scratch

El slot físico también puede utilizarse como registro temporal genérico para operaciones multicycle:

```text
MUL
DIV
LSU
operaciones SIMT
futuras instrucciones complejas
```

La decisión exacta es microarquitectónica y puede cambiar entre implementaciones.

---

# 5. Organización general de opcodes

Se mantienen cuatro grupos principales:

| Rango | Grupo |
|---|---|
| `0x00-0x0F` | ALU / aritmética |
| `0x10-0x1F` | inmediatos / memoria |
| `0x20-0x2F` | control |
| `0x30-0x3F` | sistema / SIMT |

---

# 6. ALU y aritmética — `0x00-0x0F`

| Opcode | Operación |
|---:|---|
| `0x00` | `NOP` |
| `0x01` | `ADD` |
| `0x02` | `SUB` |
| `0x03` | familia `MUL` |
| `0x04` | `AND` |
| `0x05` | `OR` |
| `0x06` | `XOR` |
| `0x07` | familia `SHL` |
| `0x08` | familia `SHR` |
| `0x09` | familia `SAR` |
| `0x0A` | familia `DIV` |
| `0x0B` | familia `PIX565` |
| `0x0C` | libre |
| `0x0D` | libre |
| `0x0E` | libre |
| `0x0F` | libre |

Quedan **4 opcodes libres**.

---

# 7. Familia MUL

Las diferentes formas de multiplicación comparten:

```text
opcode = 0x03
```

Propuesta:

| `extra` | Operación |
|---:|---|
| `0` | `MUL` |
| `1` | `MULH` |
| `2` | `MULHU` |
| `3` | `MULHSU` |
| `4` | `MULFX` |
| resto | reservado |

Semántica:

```text
MUL     -> low32(product)
MULH    -> high32(signed × signed)
MULHU   -> high32(unsigned × unsigned)
MULHSU  -> high32(signed × unsigned)
MULFX   -> signed Q16.16 product[47:16]
```

Todas las variantes reutilizan el mismo multiplicador.

La implementación puede conservar transparentemente el resultado secundario del último producto. Una posibilidad es utilizar el slot físico oculto de `R0` para almacenar `high32(product)`.

Así:

```asm
MUL  R1,R2,R3
MULH R4,R2,R3
```

puede evitar una segunda multiplicación si coinciden los operandos y el modo.

`MULH` continúa siendo completamente independiente arquitectónicamente.

---

# 8. Shifts

Se mantienen:

```text
0x07 SHL
0x08 SHR
0x09 SAR
```

Cada opcode permite seleccionar desplazamiento por registro o inmediato utilizando `extra`.

Conceptualmente:

```asm
SHL  Rd,Ra,Rb
SHLI Rd,Ra,imm5
```

y de forma equivalente para `SHR` y `SAR`.

El hardware únicamente selecciona el contador entre:

```text
Rb[4:0]
```

e:

```text
imm5
```

antes de entrar en el shifter.

---

# 9. Familia DIV

Las operaciones comparten:

```text
opcode = 0x0A
```

| `extra` | Operación |
|---:|---|
| `0` | `DIV` |
| `1` | `DIVU` |
| `2` | `REM` |
| `3` | `REMU` |
| resto | reservado |

El divisor iterativo produce naturalmente cociente y resto.

Una implementación optimizada puede conservar:

```text
key:
    dividend
    divisor
    signed/unsigned
    valid

value:
    resultado secundario
```

Por ejemplo, tras:

```asm
DIV R1,R2,R3
```

puede mantenerse:

```text
R1                    = quotient
physical registers[0] = remainder
```

Después:

```asm
REM R4,R2,R3
```

puede reutilizar el resto si la key coincide.

En caso contrario se realiza una división completa.

La cache no forma parte del estado arquitectónico.

---

# 10. PIX565

Se reserva:

```text
opcode = 0x0B
```

para:

```text
PACK565
UNPACK565R
UNPACK565G
UNPACK565B
```

`PACK565` recibe componentes RGB de 8 bits:

```text
15          11 10          5 4           0
+--------------+-------------+-------------+
|    R[7:3]    |    G[7:2]   |    B[7:3]   |
+--------------+-------------+-------------+
```

Las operaciones `UNPACK565*` devuelven un único canal por instrucción:

```text
R8 = (R5 << 3) | (R5 >> 2)
G8 = (G6 << 2) | (G6 >> 4)
B8 = (B5 << 3) | (B5 >> 2)
```

---

# 11. Inmediatos y memoria — `0x10-0x1F`

| Opcode | Operación |
|---:|---|
| `0x10` | `MOVI` |
| `0x11` | `ADDI` |
| `0x12` | `ANDI` |
| `0x13` | `ORI` |
| `0x14` | `XORI` |
| `0x15` | `LOAD` |
| `0x16` | `STORE` |
| `0x17` | `MOVHI` |
| `0x18` | `LOADB` |
| `0x19` | `LOADBU` |
| `0x1A` | `LOADH` |
| `0x1B` | `LOADHU` |
| `0x1C` | `STOREB` |
| `0x1D` | `STOREH` |
| `0x1E` | familia `STOREP` |
| `0x1F` | libre |

Queda **1 opcode libre**.

---

# 12. Loads y stores pequeños

```text
LOADB   -> 8 bits + sign extension
LOADBU  -> 8 bits + zero extension

LOADH   -> 16 bits + sign extension
LOADHU  -> 16 bits + zero extension

STOREB  -> almacena Rs[7:0]
STOREH  -> almacena Rs[15:0]
```

Estas operaciones son especialmente útiles para C, texto, INDEX8 y RGB565.

---

# 13. STOREP

Se propone:

```text
opcode = 0x1E
```

Formato:

```text
31       26 25    21 20    16 15  14 13                0
+----------+--------+--------+------+--------------------+
|  opcode  |   Rs   |   Ra   | size |   signed imm14    |
+----------+--------+--------+------+--------------------+
     6         5        5       2           14
```

`size`:

```text
00 -> STOREBP
01 -> STOREHP
10 -> STOREP
11 -> reservado
```

Semántica:

```text
address = Ra
store(address, Rs)
Ra = Ra + sext(imm14)
```

Si el acceso falla, `Ra` no se actualiza.

Rango:

```text
-8192 .. +8191 bytes
```

---

# 14. Control — `0x20-0x2F`

La v0.3 compacta las condiciones de branch y aprovecha `R0=ZERO` para evitar una instrucción `JR` arquitectónica independiente.

## Mapa propuesto

| Opcode | Operación |
|---:|---|
| `0x20` | familia `BR` registro-registro |
| `0x21` | familia `BRI` registro-inmediato |
| `0x22` | `BRA` |
| `0x23` | `JAL` |
| `0x24` | `JALR` |
| `0x25-0x2F` | libres |

Quedan **11 opcodes libres**.

---

# 15. Branch condicional registro-registro

Formato:

```text
31       26 25    21 20    16 15  13 12             0
+----------+--------+--------+------+-----------------+
|  opcode  |   Ra   |   Rb   | cond | signed off13   |
+----------+--------+--------+------+-----------------+
```

`opcode = 0x20`

| `cond` | Condición | Mnemónico |
|---:|---|---|
| `000` | `Ra == Rb` | `BEQ` |
| `001` | `Ra != Rb` | `BNE` |
| `010` | signed `Ra < Rb` | `BLT` |
| `011` | signed `Ra >= Rb` | `BGE` |
| `100` | unsigned `Ra < Rb` | `BLTU` |
| `101` | unsigned `Ra >= Rb` | `BGEU` |
| `110` | reservado | |
| `111` | reservado | |

Destino:

```text
PCtarget = PC + 4 + sext(off13) * 4
```

Rango:

```text
-4096 .. +4095 instrucciones
≈ ±16 KiB
```

---

# 16. Branch con inmediato

Formato:

```text
31       26 25    21 20    16 15  13 12             0
+----------+--------+--------+------+-----------------+
|  opcode  |   Ra   |  imm5  | cond | signed off13   |
+----------+--------+--------+------+-----------------+
```

`opcode = 0x21`

Permite:

```text
BEQI
BNEI
BLTI
BGEI
BLTUI
BGEUI
```

Inmediato signed:

```text
-16 .. +15
```

Inmediato unsigned:

```text
0 .. 31
```

El salto mantiene aproximadamente ±16 KiB.

---

# 17. Branch condicional largo

Si el destino no cabe en `off13`:

```asm
BEQ R1,R2,far_label
```

el assembler puede generar:

```asm
BNE R1,R2,.skip
BRA far_label
.skip:
```

---

# 18. BRA

Formato:

```text
31       26 25                                      0
+----------+------------------------------------------+
|   BRA    |            signed offset26              |
+----------+------------------------------------------+
```

Semántica:

```text
PC = PC + 4 + sext(offset26) * 4
```

Alcance aproximado:

```text
±128 MiB
```

---

# 19. JAL

Formato:

```text
31       26 25    21 20                             0
+----------+--------+---------------------------------+
|   JAL    |   Rd   |        signed offset21          |
+----------+--------+---------------------------------+
```

Semántica:

```text
Rd = PC + 4
PC = PC + 4 + sext(offset21) * 4
```

Alcance aproximado:

```text
±4 MiB
```

Llamada convencional:

```asm
JAL R31,function
```

También es legal utilizar:

```asm
JAL R0,function
```

En ese caso la dirección de retorno se descarta y la instrucción funciona como un salto relativo con el alcance de `JAL`.

---

# 20. JALR, JR y RET

`JALR` utiliza:

```text
opcode | Rd | Ra | imm16
```

Semántica:

```text
target = Ra + sext(imm16)

Rd = PC + 4
PC = target
```

Llamada indirecta convencional:

```asm
JALR R31,R5,0
```

Gracias a `R0=ZERO`, no se necesita un opcode arquitectónico separado para `JR`.

El assembler define:

```asm
JR R5
```

como pseudoinstrucción:

```asm
JALR R0,R5,0
```

La escritura del link a `R0` se descarta.

Del mismo modo:

```asm
RET
```

es:

```asm
JALR R0,R31,0
```

También puede expresarse un salto indirecto con desplazamiento:

```asm
JALR R0,R5,16
```

sin guardar dirección de retorno.

Esto elimina `JR` del mapa de opcodes y hace `JALR` más general.

En GPU/SIMT deberá exigirse que el destino de `JALR` sea uniforme entre las lanes activas.

---

# 21. Sistema y SIMT — `0x30-0x3F`

| Opcode | Operación |
|---:|---|
| `0x30` | familia `GETID` |
| `0x31` | `SSY` |
| `0x32` | `BAR` |
| `0x33` | `EXIT` |
| `0x34-0x3D` | libres |
| `0x3E` | `TRAP` |
| `0x3F` | `HALT` |

Quedan **10 opcodes libres**.

---

# 22. GETID

En lugar de dedicar un opcode independiente a:

```text
GETTID
GETLANE
GETWARP
GETWID
```

se utiliza:

```text
opcode = 0x30
```

Formato conceptual:

```text
opcode | Rd | type | imm16
```

con `imm16 = 0`.

Tipos:

```text
0 -> GETTID
1 -> GETLANE
2 -> GETWARP
3 -> GETWID
```

El assembler sigue exponiendo:

```asm
GETTID  R1
GETLANE R2
GETWARP R3
GETWID  R4
```

---

# 23. Mapa completo propuesto

```text
00 NOP
01 ADD
02 SUB
03 MUL family
04 AND
05 OR
06 XOR
07 SHL family
08 SHR family
09 SAR family
0A DIV family
0B PIX565 family
0C FREE
0D FREE
0E FREE
0F FREE

10 MOVI
11 ADDI
12 ANDI
13 ORI
14 XORI
15 LOAD
16 STORE
17 MOVHI
18 LOADB
19 LOADBU
1A LOADH
1B LOADHU
1C STOREB
1D STOREH
1E STOREP family
1F FREE

20 BR family
21 BRI family
22 BRA
23 JAL
24 JALR
25 FREE
26 FREE
27 FREE
28 FREE
29 FREE
2A FREE
2B FREE
2C FREE
2D FREE
2E FREE
2F FREE

30 GETID family
31 SSY
32 BAR
33 EXIT
34 FREE
35 FREE
36 FREE
37 FREE
38 FREE
39 FREE
3A FREE
3B FREE
3C FREE
3D FREE
3E TRAP
3F HALT
```

---

# 24. Ocupación del espacio de opcodes

| Grupo | Ocupados | Libres |
|---|---:|---:|
| ALU `00-0F` | 12 | **4** |
| IMM/MEM `10-1F` | 15 | **1** |
| CONTROL `20-2F` | 5 | **11** |
| SYSTEM/SIMT `30-3F` | 6 | **10** |
| **TOTAL** | **38** | **26** |

La propuesta utiliza:

```text
38 / 64 opcodes
```

y deja:

```text
26 / 64 opcodes
```

libres.

---

# 25. Consideraciones sobre el banco de registros

Una implementación directa puede conservar físicamente:

```verilog
reg [31:0] registers[0:31];
```

Las lecturas arquitectónicas se comportan conceptualmente como:

```verilog
read_data_a =
    (read_address_a == 0) ? 32'h00000000 :
                            registers[read_address_a];

read_data_b =
    (read_address_b == 0) ? 32'h00000000 :
                            registers[read_address_b];
```

y una escritura arquitectónica:

```verilog
if (write_enable && write_address != 0)
    registers[write_address] <= write_data;
```

La lógica interna puede disponer de una vía controlada para actualizar:

```text
registers[0]
```

como estado oculto.

El debugger arquitectónico debe mostrar:

```text
R0 = 0
```

independientemente del contenido físico utilizado internamente.

La reutilización del slot físico debe diseñarse de forma que no añada conflictos de puerto ni empeore innecesariamente el camino crítico. Si una implementación determinada no puede aprovecharlo de forma eficiente, puede simplemente ignorar dicha optimización.

---

# 26. Comparadores de branch

La compactación de branch puede basarse en tres comparaciones fundamentales:

```text
eq  = A == B
lt  = signed(A) < signed(B)
ltu = unsigned(A) < unsigned(B)
```

Las seis condiciones se obtienen como:

```text
EQ   -> eq
NE   -> !eq
LT   -> lt
GE   -> !lt
LTU  -> ltu
GEU  -> !ltu
```

El campo `cond[2:0]` selecciona el resultado.

El cambio de `offset16` a `offset13` no reduce sustancialmente el ancho del sumador de dirección, ya que el PC continúa siendo de 32 bits.

La motivación es mejorar el encoding y recuperar espacio de opcode.

---

# 27. Extensiones futuras no asignadas

## Bitfield

```text
BFEXT
BFINS
BSET
BCLR
```

Podrían compartir una única familia.

## MIN/MAX

```text
MIN
MAX
MINU
MAXU
```

Podrían compartir un opcode ALU.

## Multiply-add

```text
MADD
MACFX
```

Posibles reutilizando multiplicador y ALU en varios ciclos.

## Matemática fixed-point

```text
RCPFX
RSQRTFX
```

No se asignan hasta definir precisión y comportamiento.

Las funciones trigonométricas pueden implementarse inicialmente mediante LUTs en memoria.

---

# 28. Puntos todavía abiertos

Antes de considerar cerrada v0.3 quedan por validar:

1. Confirmar `off13` para los branches condicionales.
2. Confirmar definitivamente el formato `JAL Rd,off21`.
3. Confirmar definitivamente `JALR Rd,Ra,imm16`.
4. Definir los subcampos exactos de `extra`.
5. Decidir definitivamente `LOADBU/LOADHU` frente a `LOADUB/LOADUH`.
6. Definir accesos byte/halfword no alineados.
7. Definir división por cero.
8. Definir restricciones SIMT para saltos indirectos.
9. Determinar cómo se reutiliza físicamente el slot oculto correspondiente a `R0`.
10. Decidir qué caches MUL/DIV se implementan inicialmente.
11. Definir exactamente qué estado constituye la key de cada cache.
12. Comprobar mediante síntesis el coste de los muxes asociados a `R0=ZERO`.
13. Comprobar que la reutilización física de `registers[0]` no introduce conflictos de puerto.
14. Validar área y Fmax con síntesis y place-and-route en ECP5.

---

# 29. Resumen

La v0.3 reorganiza la ISA alrededor de familias:

```text
MUL      -> una familia
DIV      -> una familia
SHL/SHR/SAR -> variantes reg/immediate
BR       -> seis condiciones en un opcode
BRI      -> seis condiciones inmediatas en un opcode
GETID    -> una familia
PIX565   -> una familia
STOREP   -> una familia
```

Además:

```text
R0 = ZERO
```

lo que permite obtener numerosas pseudoinstrucciones y simplificar el control indirecto:

```text
JR Rs -> JALR R0,Rs,0
RET   -> JALR R0,R31,0
```

El almacenamiento físico correspondiente a `R0` no tiene por qué desperdiciarse. Puede quedar oculto al estado arquitectónico y utilizarse como scratch microarquitectónico o como almacenamiento del valor secundario de caches como:

```text
DIV -> remainder
MUL -> high32
```

La key necesaria para validar estas caches permanece en registros internos de las correspondientes unidades funcionales.

Este mecanismo es completamente transparente: ante un miss, la operación se recalcula normalmente.

El mapa final utiliza **38 de 64 opcodes** y deja **26 opcodes libres**, incluyendo **11 libres dentro del bloque de Control**.

El cambio además mejora un poco más el mapa: al poder expresar JR y RET mediante JALR escribiendo el link en R0, Control pasa de 10 a 11 opcodes libres.