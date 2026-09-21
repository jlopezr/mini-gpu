# MiniISA v0.4

## 1. Alcance y conformidad

Esta es la especificación consolidada de MiniISA v0.4. Un binario identifica su versión de ISA y se recompila al cambiar de versión; no hay compatibilidad para opcodes o direcciones numéricas históricas. Un backend declara las capabilities que implementa. Una capability ausente no libera su opcode. Sin privileged_traps, una instrucción ausente falla fatalmente; con ella causa ILLEGAL_INSTRUCTION.

Capabilities de repertorio: subword_memory, calls, shift_immediate, alu_extended, compare, branch_immediate, gpu_ids, warp_user_id, minmax, select, macfx, pack565, mul_high_variants, unpack565, bit_count, store_postincrement, warp_vote, warp_shuffle, pc_relative_address e indexed_load.

Capabilities de sistema: privileged_traps (USER/SUPERVISOR, SR, TRAP, ERET, ENTERUSER), vectored_traps, interrupts, memory_protection, memory_fence y atomics. Vectored_traps, interrupts y memory_protection requieren privileged_traps. RCPFX y RSQRTFX no se declaran hasta cerrar su contrato numérico.

## 2. Estado y formatos

Datos, PC, direcciones, instrucciones y registros tienen 32 bits. La memoria es byte-addressed y little-endian; instrucciones alineadas a cuatro bytes. Hay R0–R31; R0 siempre lee cero y descarta escrituras sin omitir efectos. R30 es pila y R31 enlace por ABI. No hay FLAGS, CMP ni delay slots; enteros envuelven módulo 2^32. Las fuentes se leen antes de escribir destinos.

### R-Type

```text
31       26 25   21 20   16 15   11 10    6 5          0
+----------+-------+-------+-------+-------+------------+
| opcode   |  Rd   |  Ra   |  Rb   |  Rc   |   func6    |
+----------+-------+-------+-------+-------+------------+
     6         5       5       5       5         6
```

Lo usan las familias MUL, PIX565, MINMAX, SELECT, BIT, FXMATH, LOADX, VOTE y
SHFL. Fuentes no usadas y `Rc` deben codificarse a cero.

### I-Type

```text
31       26 25   21 20   16 15                         0
+----------+-------+-------+-----------------------------+
| opcode   | X/Rd  | Y/Ra  |            imm16            |
+----------+-------+-------+-----------------------------+
     6         5       5                16
```

`X` y `Y` son destino, fuente, tipo o registro a almacenar según la
instrucción. Lo usan inmediatos, memoria ordinaria, `JALR` y GETID.

### B-Type

```text
31       26 25                                          0
+----------+---------------------------------------------+
| opcode   |            signed offset26                 |
+----------+---------------------------------------------+
     6                         26
```

`BRA` y `SSY` usan este formato; su offset está en palabras y es relativo a
`PC+4`.

Campos reservados no nulos dan ERROR_INVALID_ENCODING, o ILLEGAL_INSTRUCTION con traps. Opcode/subfunción desconocidos dan ERROR_INVALID_OPCODE, o ILLEGAL_INSTRUCTION con traps.

### Shifts con cantidad inmediata

```text
31       26 25   21 20   16 15   11 10   9              0
+----------+-------+-------+-------+-------+---+----------+
| opcode   |  Rd   |  Ra   | Rb/imm | I=1 |     0      |
+----------+-------+-------+-------+-------+---+----------+
```

En `SHL`, `SHR` y `SAR`, `I=1` codifica `SHLI`, `SHRI` o `SARI`; la cantidad
inmediata es 0..31. Con `I=0`, se usan los cinco bits bajos del contenido de
`Rb`. Los diez bits restantes deben ser cero.

## 3. Mapa de opcodes

Los dos bits altos del opcode separan cuatro familias de decodificación:

| Rango | Prefijo | Familia |
|---|---|---|
| 0x00–0x0F | 00xxxx | ALU y aritmética |
| 0x10–0x1F | 01xxxx | inmediatos y memoria |
| 0x20–0x2F | 10xxxx | control, llamadas y atómicos |
| 0x30–0x3F | 11xxxx | sistema, SIMT y traps |

El siguiente mapa asigna los opcodes dentro de esas familias. El rango no fija
por sí solo el formato: LOADX y las familias de registros tienen formatos
propios aunque compartan cuarto del mapa con I-Type.

| Opcode | Operación                                    |
|--------|----------------------------------------------|
| 00     | NOP                                          |
| 01–02  | ADD, SUB                                     |
| 03     | MUL, MULHI, MULHU, MULHSU, MULFX, MACFX      |
| 04–06  | AND, OR, XOR                                 |
| 07–09  | SHL/SHLI, SHR/SHRI, SAR/SARI                 |
| 0A     | DIV, DIVU, REM, REMU                         |
| 0B     | PACK565, UNPACK565R/G/B                      |
| 0C     | MIN, MAX, MINU, MAXU                         |
| 0D     | SEL                                          |
| 0E     | CLZ, POPC                                    |
| 0F     | RCPFX, RSQRTFX (pendientes)                  |
| 10–14  | MOVI, ADDI, ANDI, ORI, XORI                  |
| 15–16  | LOAD, STORE                                  |
| 17     | MOVHI                                        |
| 18–1D  | LOADB, LOADUB, LOADH, LOADUH, STOREB, STOREH |
| 1E     | STOREBP, STOREHP, STOREP                     |
| 1F     | LOADX                                        |
| 20     | BR                                           |
| 21     | BRI                                          |
| 22–25  | BRA, JAL, JALR, LEAPC                        |
| 26–29  | SLT, SLTU, SLTI, SLTIU                       |
| 2A     | ATOMADD, ATOMCAS                             |
| 2B–2F  | libres                                       |
| 30     | GETTID, GETLANE, GETWARP, GETWID             |
| 31–33  | SSY, BAR, EXIT                               |
| 34     | BALLOT, ACTIVEMASK                           |
| 35     | SHFL                                         |
| 36     | ERET, FENCE, MFSR, MTSR, ENTERUSER           |
| 37–3D  | libres                                       |
| 3E     | TRAP número; TRAP/ABORT fatal con cero       |
| 3F     | HALT                                         |

Hay 52 opcodes asignados y 12 libres.

## 4. Instrucciones básicas, ALU y memoria

### 4.1 Operaciones base e inmediatos

| Instrucción | Operandos | Semántica |
|---|---|---|
| NOP | — | sin efecto; exige 26 bits bajos cero |
| ADD / SUB | Rd, Ra, Rb | suma/resta módulo 2^32 |
| AND / OR / XOR | Rd, Ra, Rb | operación lógica bit a bit |
| MOVI | Rd, imm16 | Rd = sext(imm16) |
| ADDI | Rd, Ra, imm16 | Rd = low32(Ra + sext(imm16)) |
| ANDI / ORI / XORI | Rd, Ra, imm16 | inmediato extendido con ceros |
| MOVHI | Rd, imm16 | Rd = imm16 << 16 |

Los campos no usados son reservados. MOVI y MOVHI no leen su campo fuente
I-Type. Para construir una constante arbitraria:

```asm
MOVHI R1, 0x1234
ORI   R1, R1, 0x5678    ; R1 = 0x12345678
```

### 4.2 Cargas y stores

| Instrucción | Tamaño | Resultado o escritura | Alineación |
|---|---:|---|---|
| LOAD / STORE | 32 bits | palabra | múltiplo de 4 |
| LOADH / STOREH | 16 bits | LOADH extiende signo; STOREH escribe low16 | múltiplo de 2 |
| LOADUH | 16 bits | extensión con ceros | múltiplo de 2 |
| LOADB / STOREB | 8 bits | LOADB extiende signo; STOREB escribe low8 | cualquiera |
| LOADUB | 8 bits | extensión con ceros | cualquiera |

Todas usan address = low32(Ra + sext(imm16)), con offset en bytes entre -32768
y 32767. Son little-endian; los stores pequeños conservan bytes vecinos y el
intervalo completo se valida antes de modificar memoria.

### 4.3 Familias ALU

| Opcode | func6 | Mnemónico | Operandos | Semántica |
|---|---:|---|---|---|
| 0x03 | 0..5 | MUL, MULHI, MULHU, MULHSU, MULFX, MACFX | Rd, Ra, Rb | producto o acumulación |
| 0x0A | 0..3 | DIV, DIVU, REM, REMU | Rd, Ra, Rb | cociente o resto |
| 0x0C | 0..3 | MIN, MAX, MINU, MAXU | Rd, Ra, Rb | menor o mayor |
| 0x0D | 0 | SEL | Rd, Ra, Rb, Rc | Ra si Rc!=0; Rb si no |
| 0x0E | 0..1 | CLZ, POPC | Rd, Ra | ceros iniciales o bits a uno |
| 0x0F | 0..1 | RCPFX, RSQRTFX | Rd, Ra | reservado hasta contrato numérico |

En MUL y DIV, Rc debe ser cero. MUL devuelve los 32 bits bajos; MULHI,
MULHU y MULHSU devuelven los altos de signed×signed, unsigned×unsigned y
signed×unsigned. MULH puede ser alias de MULHI; el signo no modifica low32.

DIV trunca hacia cero. REM conserva el signo del dividendo:

```text
 7 rem  2 =  1       -7 rem  2 = -1
 7 rem -2 =  1       -7 rem -2 = -1
```

El caso -2^31/-1 devuelve 0x80000000 y resto cero. Un divisor cero produce
DIVISION_BY_ZERO; con traps se guarda EPC en la instrucción causante y no se
escribe Rd.

MIN/MAX comparan signed32 y MINU/MAXU unsigned32. SEL no cambia máscaras SIMT
ni ejecuta ambas ramas: selecciona valores ya calculados. CLZ(0)=32 y POPC
devuelve 0..32.

### 4.4 Coma fija

MULFX interpreta Ra y Rb como signed Q16.16:

```text
MULFX(Ra,Rb) = low32((signed32(Ra) * signed32(Rb)) >>> 16)
MACFX(Rd,Ra,Rb) = low32(old_Rd + MULFX(Ra,Rb))
```

MACFX captura el antiguo Rd como tercera fuente; no dispone de acumulador
oculto de 64 bits ni redondeo fusionado. ADD, SUB y comparaciones signed ya
funcionan sobre Q16.16. SHLI 16 convierte entero a Q16.16 y SARI 16 vuelve a
entero truncando hacia menos infinito.

No existe DIVFX deliberadamente. Un cociente Q16.16 correcto necesita
(sign_extend48(a) << 16) / b: una división 48/32. Desplazar a dentro de 32
bits puede desbordar; dividir primero pierde la fracción. Para proyección,
un RCPFX y varios MULFX amortizan mejor el coste de un divisor; RCPFX sigue
pendiente de contrato de dominio, redondeo, cero y overflow.

## 5. Control y tablas

### 5.1 Branches y llamadas

BR y BRI usan el formato:

```text
opcode | Ra | Rb/imm5 | cond[2:0] | signed off13
```

| cond | BR | BRI | Comparación |
|---:|---|---|---|
| 0 | BEQ | BEQI | igualdad |
| 1 | BNE | BNEI | desigualdad |
| 2 | BLT | BLTI | menor signed |
| 3 | BGE | BGEI | mayor o igual signed |
| 4 | BLTU | BLTUI | menor unsigned |
| 5 | BGEU | BGEUI | mayor o igual unsigned |
| 6–7 | — | — | reservado |

Para BRI, igualdad/LT/GE usan imm5 signed -16..15 y LTU/GEU imm5 unsigned
0..31. Una rama tomada ejecuta PC=low32(PC+4+sext(off13)*4); una no tomada
PC=PC+4. El alcance es -4096..4095 palabras. El ensamblador rechaza un destino
fuera de rango; no lo expande a una secuencia alternativa.

| Opcode | Instrucción | Formato y efecto |
|---|---|---|
| 0x22 | BRA target | off26 signed en palabras relativo a PC+4 |
| 0x23 | JAL Rd,target | off21 signed; Rd=PC+4 antes del salto |
| 0x24 | JALR Rd,Ra,imm16 | target=(old_Ra+sext(imm16)*4)&0xFFFFFFFC |
| 0x25 | LEAPC Rd,label | Rd=PC+4+sext(off21); off21 en bytes |

Rd=R0 descarta enlace, no el salto. JR Ra es JALR R0,Ra,0; RET es JALR
R0,R31,0. LEAPC no carga ni salta y alcanza aproximadamente ±1 MiB.

### 5.2 Comparaciones y tablas

SLT y SLTU materializan 0/1 mediante comparación signed o unsigned. SLTI
compara signed contra sext(imm16). SLTIU también extiende el inmediato con
signo, pero compara unsigned: SLTIU Rd,Ra,1 materializa Ra==0.

LEAPC escribe PC+4+sext(off21) con off21 en bytes y no carga ni salta. LOADX usa func6 escala 0..3 y carga de old_Ra+(unsigned(old_Rb)<<escala). LEAPC+LOADX sirve para tablas; LDR no tiene opcode.

## 6. GPU y gráficos

### 6.1 Identificadores y control SIMT

GETID usa I-Type con imm16=0. Su campo type selecciona GETTID, GETLANE,
GETWARP o GETWID. GETTID es el thread residente y vale cero en CPU; GETLANE
es el índice dentro del warp; GETWARP el slot del SM; GETWID los 32 bits de
warp_user_id. Solo escriben lanes activas. warp_user_id no es workgroup_id ni
asigna trabajo: puede representar una base, tile u objeto. Vale cero tras reset
y se conserva al pausar, reanudar o migrar trabajo.

SSY label registra join=PC+4+sext(off26)*4 y continúa en PC+4; no salta. BAR
sincroniza warps del workgroup y exige active_mask==live_mask; si no, causa
ERROR_BARRIER. EXIT retira permanentemente lanes activas de live_mask; cuando
no queda ninguna, termina el warp y vacía sus pilas de región y camino. HALT
en GPU tiene el mismo efecto que EXIT. BAR ordena memoria según §8.

### 6.2 VOTE y SHFL

| func6 | Instrucción | Efecto |
|---:|---|---|
| 0 | BALLOT Rd,Ra | bit i = active_mask[i] y Ra de lane i != 0 |
| 1 | ACTIVEMASK Rd | copia active_mask |

VOTE admite warps de hasta 32 lanes y pone a cero bits fuera del warp. Captura
máscara y fuentes antes de escribir; todas las lanes participantes reciben el
mismo resultado. No es barrera ni reconverge. ANY y ALL se obtienen comparando
BALLOT con cero o ACTIVEMASK.

SHFL Rd,Ra,Rb usa func6=0. Cada lane activa usa el valor unsigned completo de
Rb como índice de fuente. Captura máscara, Ra y Rb antes de escribir. Un índice
fuera del warp o una fuente inactiva produce cero; no hay wrap. No es barrera,
no reconverge, no comunica warps y solo lanes activas escriben Rd.

PACK565 convierte 0x00RRGGBB a RGB565. UNPACK565R/G/B expanden sus canales. STOREBP/STOREHP/STOREP escriben old_Ra y, solo tras éxito, actualizan Ra con imm14 signed; no hay rollback global de lanes GPU.

## 7. Privilegios, traps e interrupciones

### 7.1 Modos y registros de sistema

La CPU tiene USER y SUPERVISOR; reset entra en SUPERVISOR. Saltos ordinarios no
cambian modo: la entrada de trap fuerza SUPERVISOR, ERET restaura el modo previo
y ENTERUSER realiza la entrada controlada a USER. Son privilegiados ERET, MTSR,
HALT, ABORT, configuración IRQ/PMP y cualquier SR de supervisor. Ejecutarlos en
USER causa PRIVILEGED_INSTRUCTION. MFSR desde USER solo lee SR públicos; v0.4
no marca ninguno.

SYSTEM 0x36 agrupa ERET, FENCE, MFSR, MTSR y ENTERUSER. FENCE no es
privilegiada. Los SR incluyen STATUS (modo, IE, PIE, IN_TRAP), TVEC, EPC,
CAUSE, BADADDR, IRQ_PENDING, IRQ_ENABLE, KSP, PMP_DEFAULT y PMP. La ABI de
syscall usa R1–R4 como argumentos, R1 como resultado y R2 como código de error.

### 7.2 Entrada y retorno de trap

TRAP 0, también escrito ABORT, es parada fatal. TRAP número entra al supervisor
si existe privileged_traps. Al entrar se guarda EPC en la instrucción causante,
CAUSE, BADADDR cuando aplica, modo previo e IE; se deshabilitan interrupciones y
se salta al handler de TVEC. ERET restaura el contexto guardado.

Solo existe un nivel hardware de trap. Mientras IN_TRAP=1 se aplazan IRQ; un
segundo fallo síncrono produce ERROR_DOUBLE_FAULT fatal. Una excepción síncrona
tiene prioridad sobre una IRQ pendiente. TVEC DIRECT salta a TVEC; VECTORED usa
la entrada de cuatro bytes indexada por la causa.

### 7.3 Interrupciones

Una IRQ se toma solo con STATUS.IE=1, su bit habilitado en IRQ_ENABLE e
IN_TRAP=0. IRQ_PENDING refleja fuentes pendientes incluso enmascaradas y leerlo
no las limpia; cada dispositivo documenta acknowledge.

| Bit | Fuente | Causa | Prioridad |
|---:|---|---|---:|
| 0 | timer | TIMER_INTERRUPT | 1 |
| 1 | externa | EXTERNAL_INTERRUPT | 2 |
| 2 | GPU | GPU_INTERRUPT | 3 |
| 3 | DMA | DMA_INTERRUPT | 4 |

Los bits 4–31 son de plataforma y comparten la vía externa. La prioridad fija
evita depender del arbitraje particular de cada placa.

## 8. Protección, memoria y atómicos

### 8.1 Protección física PMP

memory_protection define cuatro regiones PMP 0..3:

```text
PMPn_BASECFG: bits 31:5 base inclusiva alineada a 32; bits 0..2 USER R/W/X;
               bit 3 S aplica también a SUPERVISOR; bit 4 L bloquea hasta reset
PMPn_LIMIT:   límite exclusivo alineado a 32 bytes
```

BASE>=LIMIT deshabilita la región. Si varias coinciden, gana el índice menor.
Se valida primero la alineación y después el intervalo completo: un acceso que
cruza límite falla aunque su primer byte esté permitido. PMP_DEFAULT entrega
R/W/X a USER fuera de regiones y tras reset vale 0b111. Supervisor ignora PMP
salvo regiones S; L bloquea BASECFG y LIMIT hasta reset. PMP cubre MMIO y CPU,
no GPU ni DMA.

### 8.2 Orden de memoria y FENCE

Cada master observa sus accesos ordinarios en orden de programa; masters
distintos pueden observar órdenes distintos sin sincronización. FENCE no termina
hasta que lecturas y escrituras anteriores del master sean globalmente visibles
y finalizadas, y ninguna posterior puede presentarse antes. Incluye MMIO. BAR
incluye ese efecto para lanes participantes, pero no reemplaza un atómico.

### 8.3 ATOMADD y ATOMCAS

Los atómicos operan sobre una palabra little-endian alineada a cuatro bytes.
MMIO no los admite salvo contrato expreso. En CPU exigen permisos PMP de lectura
y escritura; un fallo de alineación, permiso o acceso no modifica memoria ni Rd.

```text
ATOMADD Rd,Ra,Rb:
  old = MEM32[old_Ra]; MEM32[old_Ra] = low32(old + old_Rb); Rd = old

ATOMCAS Rd,Ra,Rb,Rc:
  old = MEM32[old_Ra]; si old == old_Rb: MEM32[old_Ra] = old_Rc; Rd = old
```

Cada atómico ocupa un punto único del orden total del fabric y equivale a
FENCE; atómico; FENCE para ese master. En GPU cada lane activa ejecuta el suyo;
se validan direcciones, alineación y política de todas las lanes antes de la
primera modificación. Si una falla, se anula toda la instrucción del warp y la
dirección informada es la de la lane fallida de menor índice.

## 9. Reset y validación

Después de reset:

```text
MODE = SUPERVISOR       IE = PIE = IN_TRAP = 0
EPC = CAUSE = BADADDR = 0
TVEC = 0, modo DIRECT   IRQ_ENABLE = 0
PMP_DEFAULT = 0b111     KSP = 0
regiones PMP deshabilitadas
PC = vector de reset de la plataforma
```

El vector de reset no es un trap y no modifica EPC, CAUSE ni BADADDR. Cada
capability requiere modelo funcional y pruebas diferenciales antes de declararse.
Las pruebas comunes cubren límites de inmediato, campos reservados, aliases,
registros coincidentes, R0, alineación y conservación de bytes vecinos. GPU
añade máscaras divergentes, votos, SHFL, IDs, BAR, stores postincrementales y
finalización de LSU. RCPFX y RSQRTFX necesitan contrato numérico y referencia.

## Anexo no normativo

### Gráficos y coma fija

PACK565 más STOREHP recorre framebuffer RGB565; STOREBP sirve para índices de
paleta y STOREP para palabras. UNPACK565R/G/B permite operar sobre un canal por
vez. MIN/MAX limita coordenadas sin divergencia y SEL selecciona valores ya
calculados, no cargas, stores u otros efectos laterales.

Una transformación Q16.16 a*x+b*y+tx se expresa como:

```asm
MULFX R6, R1, R2
MACFX R6, R3, R4
ADD   R6, R6, R5
```

RCPFX sería útil para reutilizar 1/w en perspectiva; RSQRTFX para normalizar
normales tras acumular x*x+y*y+z*z. Ninguna puede usarse hasta cerrar su
contrato numérico.

### Tablas y trigonometría

LEAPC obtiene una base cercana y LOADX selecciona entradas escaladas. Una tabla
de seno Q16.16 puede usar 65536 unidades por vuelta, 257 muestras —la última
repite la primera— e interpolación con LOADX, SUB y MACFX. El coseno reutiliza
la misma tabla con fase+16384. Tabla simple, polinomios y CORDIC son alternativas
de software. SINFX y COSFX no tienen opcode ni capability: antes de asignarlos
deben definir formato de entrada/salida, redondeo, error y coste.
