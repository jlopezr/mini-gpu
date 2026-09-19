# Propuesta de MiniISA v0.4

## 1. Alcance

Este es el documento único y autocontenido de la propuesta MiniISA v0.4.
Consolida el repertorio y las capabilities propuestos en v0.3 con:

- privilegios, traps precisos, interrupciones y protección física de memoria;
- operaciones atómicas y orden de memoria compartido entre CPU, GPU y DMA.

Este documento es una **propuesta documental**. No afirma que el ensamblador,
los simuladores ni el RTL actuales implementen v0.4.

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

Las instrucciones de shift conservan su formato especial de v0.3:
`opcode | Rd | Ra | Rb/imm5 | I | 0[9:0]`; `I=1` selecciona
`SHLI/SHRI/SARI`. `JALR` conserva inmediato en palabras y elimina los dos bits
bajos del destino. Los campos reservados deben ser cero.

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

Las capabilities consolidadas de repertorio siguen siendo: `mul_div`,
`subword_memory`, `calls`, `shift_immediate`, `alu_extended`, `compare`,
`branch_immediate`, `gpu_ids`, `warp_user_id`, `minmax`, `select`, `macfx`,
`pack565`, `rcpfx`, `rsqrtfx`, `mul_high_variants`, `unpack565`, `bit_count`,
`store_postincrement`, `warp_vote`, `warp_shuffle`, `pc_relative_address` e
`indexed_load`. Las que tenían contrato pendiente en v0.3 (`rcpfx`, `rsqrtfx`
y `warp_shuffle`) continúan sin poder declararse hasta cerrar su semántica y
modelo de referencia.

Dependencias:

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

## 4. Formatos nuevos

Se conserva el formato de registro de v0.3:

```text
31       26 25   21 20   16 15   11 10    6 5          0
+----------+-------+-------+-------+-------+------------+
| opcode   |  Rd   |  Ra   |  Rb   |  Rc   |   func6    |
+----------+-------+-------+-------+-------+------------+
```

Los campos no utilizados deben ser cero. Una subfunción no soportada produce
`ERROR_INVALID_OPCODE`; campos reservados no nulos producen
`ERROR_INVALID_ENCODING` cuando no existe un trap privilegiado. Con
`privileged_traps`, ambos se convierten en `ILLEGAL_INSTRUCTION`.

### 4.1 Familia ATOMIC — `0x2A`

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
| `0x03`  | `MTSR SRn, Rs` | `Rd=Rs`, `Ra=SRn`, `Rb=Rc=0`                      |
| `0x04`  | `ENTERUSER`    | `Rd=Ra=Rb=Rc=0`                                   |

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

| Opcode | Operación / familia |
|--------|---------------------|
| `0x00` | `NOP` |
| `0x01–0x02` | `ADD`, `SUB` |
| `0x03` | MUL: `MUL/MULHI/MULHU/MULHSU/MULFX/MACFX` |
| `0x04–0x06` | `AND`, `OR`, `XOR` |
| `0x07–0x09` | `SHL/SHLI`, `SHR/SHRI`, `SAR/SARI` |
| `0x0A` | DIV: `DIV/DIVU/REM/REMU` |
| `0x0B` | PIX565: `PACK565/UNPACK565R/G/B` |
| `0x0C` | MINMAX: `MIN/MAX/MINU/MAXU` |
| `0x0D` | SELECT: `SEL` |
| `0x0E` | BIT: `CLZ/POPC` |
| `0x0F` | FXMATH: `RCPFX/RSQRTFX` (contrato numérico pendiente) |
| `0x10–0x14` | `MOVI/ADDI/ANDI/ORI/XORI` |
| `0x15–0x16` | `LOAD`, `STORE` |
| `0x17` | `MOVHI` |
| `0x18–0x1D` | `LOADB/LOADUB/LOADH/LOADUH/STOREB/STOREH` |
| `0x1E` | `STOREBP/STOREHP/STOREP` |
| `0x1F` | `LOADX` |
| `0x20` | BR: `BEQ/BNE/BLT/BGE/BLTU/BGEU` |
| `0x21` | BRI: `BEQI/BNEI/BLTI/BGEI/BLTUI/BGEUI` |
| `0x22–0x25` | `BRA`, `JAL`, `JALR` (`JR/RET` alias), `LEAPC` |
| `0x26–0x29` | `SLT`, `SLTU`, `SLTI`, `SLTIU` |
| `0x2A` | ATOMIC: `ATOMADD/ATOMCAS` |
| `0x2B–0x2F` | Libres |
| `0x30` | GETID: `GETTID/GETLANE/GETWARP/GETWID` |
| `0x31–0x33` | `SSY`, `BAR`, `EXIT` |
| `0x34` | VOTE: `BALLOT/ACTIVEMASK` |
| `0x35` | `SHFL` (contrato pendiente) |
| `0x36` | SYSTEM: `ERET/FENCE/MFSR/MTSR/ENTERUSER` |
| `0x37–0x3D` | Libres |
| `0x3E` | `TRAP número`; `TRAP`/`ABORT` fatal con número cero |
| `0x3F` | `HALT` |

Después de estas asignaciones quedan **12 opcodes principales libres**: cinco
en control (`0x2B–0x2F`) y siete en sistema/SIMT (`0x37–0x3D`). Los huecos
`func6` de `ATOMIC` y `SYSTEM` quedan reservados para extensiones afines.

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
modificar antes de llamar a código auxiliar o de reactivar interrupciones.
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

`ERET` exige `EPC` alineado a cuatro bytes; en otro caso genera
`INSTRUCTION_ALIGNMENT` sin abandonar supervisor.

### 8.1 EPC

- `TRAP número`: dirección de la instrucción siguiente (`PC+4`).
- interrupción: dirección de la siguiente instrucción aún no ejecutada.
- instrucción ilegal, privilegiada o fallo de fetch/load/store: PC de la
  instrucción causante, para poder corregir o emular y reintentar.

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

`BAR` sincroniza participantes GPU y también ordena su memoria: ninguna lane
participante continúa hasta que todas hayan alcanzado la barrera y todas las
operaciones de memoria anteriores de esas lanes sean globalmente visibles. Por
tanto `BAR` incluye el efecto de un `FENCE` para cada lane participante, pero
no sustituye una operación atómica frente a otros masters o escrituras
conflictivas.

## 12. Operaciones atómicas

Los atómicos operan sobre una palabra little-endian de 32 bits y exigen una
dirección múltiplo de cuatro. MMIO no admite atómicos por defecto y produce
`ATOMIC_ACCESS`; la única excepción es un dispositivo que documente
expresamente soporte atómico y su semántica de efectos laterales.

`ATOMADD` y `ATOMCAS` exigen simultáneamente permisos PMP de lectura y
escritura. En `ATOMCAS` se comprueban ambos antes de leer, aunque la comparación
posterior no coincida y por tanto no se llegue a escribir; así CAS no abre un
camino de lectura especial sobre memoria de solo lectura.

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

## 13. Interrupciones

Una interrupción se toma únicamente si `STATUS.IE=1` y su bit está habilitado
en `IRQ_ENABLE` y `IN_TRAP=0`. `IRQ_PENDING` refleja fuentes pendientes aunque estén
enmascaradas. La forma de reconocer o limpiar una fuente pertenece al
dispositivo; leer `IRQ_PENDING` no la limpia. v0.4 define esta interfaz CPU,
las causas y los vectores, pero no fija registros MMIO universales para timer,
UART, GPU ni controlador de interrupciones: cada plataforma documenta su mapa,
la prioridad interna y la operación de acknowledge.

Los tres bits bajos de `IRQ_PENDING` e `IRQ_ENABLE` quedan asignados de forma
portable, junto con DMA:

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

1. Nuevo ensamblador/perfil v0.4 y alias `ABORT`, sin cambiar aún el RTL v0.3.
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
`EPC/CAUSE/BADADDR/PMODE/PIE`. El handler debe salvarlo antes de reactivar
interrupciones; mientras `IN_TRAP=1`, estas siguen aplazadas y un segundo fallo
síncrono produce `ERROR_DOUBLE_FAULT` fatal. Un anidamiento futuro requiere una
extensión arquitectónica con contexto adicional.
9. **ATOMCAS sin inmediato.** Queda fijado que la dirección es exactamente
   `Ra`; el software calcula cualquier offset antes de ejecutar el atómico.
   No se añade un formato especial ni un opcode adicional.
10. **ABI de syscall.** Queda fijada: `R1–R4` son argumentos, `R1` devuelve el
   valor y `R2` el código de error. Los retornos adicionales, si se necesitan,
   usan `R3` y `R4` por contrato del servicio.
11. **MMU.** Queda fuera de v0.4. PMP proporciona aislamiento físico, no
   procesos con memoria virtual; PTBASE, TLB y page faults se abordarán en una
   revisión posterior, previsiblemente v0.5.
