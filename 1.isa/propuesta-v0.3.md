# Propuesta de MiniISA v0.3

## 1. Objetivo y compatibilidad

v0.3 reorganiza la codificación de la [ISA vigente](isa.md), representada en
CPU por `21.fpga-cpu-hdmi-alu`, e incorpora **todas** las operaciones de
[propuesta-v0.2.md](propuesta-v0.2.md). Añade operaciones SIMT y gráficas sin
obligar a implementarlas simultáneamente: las capabilities expresan el soporte.

El objetivo es conservar el programa ensamblador al recompilar: mismos
mnemónicos, operandos y resultados, siempre que los inmediatos y destinos
quepan en los nuevos límites y el backend ofrezca las capabilities necesarias.
**El binario cambia y no es compatible con v0.1/v0.2.** El ensamblador deberá
seleccionar explícitamente la ISA objetivo; el cargador deberá verificar el
perfil del backend antes de ejecutar. Las capabilities por sí solas no
identifican qué codificación utiliza un binario.

No se garantiza compatibilidad para palabras de máquina incrustadas, código
que inspeccione sus propios opcodes o direcciones numéricas dependientes del
layout. Las etiquetas deben resolverse de nuevo. Inicialmente un branch fuera
de rango produce error: no se expande automáticamente en varias instrucciones.

Esta es una propuesta documental. Ninguna asignación ni capability nueva de
este documento implica que exista ya implementación.

## 2. Reglas heredadas

- Datos, PC e instrucciones de 32 bits; opcode principal de 6 bits.
- Direccionamiento por byte, little-endian, instrucciones alineadas a 4 bytes.
- `R0` siempre cero; escrituras descartadas, sin omitir otros efectos o errores.
- `R1`–`R31` generales; sin FLAGS ni delay slots; wrap entero módulo 2^32.
- Convención de software: `R31` enlace y `R30` pila, sin tratamiento especial.
- `MULFX` signed Q16.16, desplazamiento aritmético de 16 bits y resultado low32.
- División signed truncada hacia cero, resto con signo del dividendo;
  `-2^31 / -1` devuelve `0x80000000` y resto cero.
- División por cero: `ERROR_DIVISION_BY_ZERO` en `DIV/DIVU/REM/REMU`.
- Memoria: mismo tamaño, extensión, alineación y errores que v0.1.
- `JALR` conserva el inmediato **en palabras** y descarta los dos bits bajos
  del destino; no pasa a bytes.
- `GETTID`, `SSY`, `BAR`, `EXIT`, `TRAP` y `HALT` conservan sus contratos.

Todos los operandos se leen antes de escribir destinos, también cuando
coinciden registros. Los nuevos errores y las operaciones aproximadas deben
cerrar su contrato antes de implementarse; no se les atribuye una semántica
implícita por compartir unidad funcional.

## 3. Inventario: nada de v0.2 se pierde

| Procedencia               | Operaciones                                  | Destino en v0.3                                                |
|---------------------------|----------------------------------------------|----------------------------------------------------------------|
| v0.2                      | `GETLANE`, `GETWARP`, `GETWID`               | Familia `GETID` junto a `GETTID`                               |
| v0.2                      | `MACFX`                                      | Familia `MUL`                                                  |
| v0.2                      | `MIN`, `MAX`, `MINU`, `MAXU`                 | Familia `MINMAX`                                               |
| v0.2                      | `PACK565`                                    | Familia `PIX565`                                               |
| v0.2                      | `RCPFX`, `RSQRTFX`                           | Familia `FXMATH`; contratos numéricos pendientes               |
| v0.2                      | `SEL`                                        | Familia `SELECT`                                               |
| v0.2                      | Los seis branches inmediatos                 | Familia `BRI`                                                  |
| v0.1                      | `JR`, `RET`                                  | Pseudoinstrucciones de `JALR`, sin opcode propio               |
| v0.1                      | `LOADUB`, `LOADUH`                           | Se conservan los nombres; `LOADBU/LOADHU` son alias opcionales |
| v0.1                      | `MULHI`                                      | Se conserva el nombre; `MULH` es alias opcional                |
| v0.1                      | ALU, inmediatos, memoria, branches y sistema | Se conservan; algunos encodings cambian                        |
| Nuevas                    | `BALLOT`, `ACTIVEMASK`                       | Familia `VOTE`                                                 |
| Nuevas                    | `CLZ`, `POPC`                                | Familia `BIT`                                                  |
| Nuevas                    | `LEAPC`, `LOADX`                             | Dirección relativa al PC y carga indexada                      |
| Nuevas                    | `MULHU`, `MULHSU`                            | Familia `MUL`                                                  |
| Nuevas                    | `STOREBP`, `STOREHP`, `STOREP`               | Stores con postincremento                                      |
| Nuevas                    | `UNPACK565R/G/B`                             | Familia `PIX565`, un destino por instrucción                   |
| Nueva, contrato pendiente | `SHFL` indexado                              | Familia `SHFL`                                                 |

`EXT` de v0.2 desaparece como contenedor; sus nueve operaciones se distribuyen
en familias. El trabajo pendiente de portar capabilities a GPU sigue siendo
necesario: reorganizar el encoding no implementa los datapaths.

## 4. Formatos y suboperaciones

Se mantienen cuatro bloques: ALU `0x00–0x0F`, inmediatos/memoria `0x10–0x1F`,
control `0x20–0x2F` y sistema/SIMT `0x30–0x3F`.

### Registro con suboperación

```text
31       26 25   21 20   16 15   11 10    6 5          0
+----------+-------+-------+-------+-------+------------+
| opcode   |  Rd   |  Ra   |  Rb   |  Rc   |   func6    |
+----------+-------+-------+-------+-------+------------+
```

La propuesta fija `func6` en los seis bits bajos. `Rc` solo se lee cuando la
operación lo requiere; en las demás debe codificarse a cero. Los campos de
fuentes no utilizados también son cero. `Rd` es siempre un único destino,
excepto los stores postincrementales, cuyo destino implícito es su base.

Los shifts mantienen su formato existente como excepción explícita:
`opcode | Rd | Ra | Rb/imm5 | I | 0[9:0]`. `I` es el bit 10. El rango inmediato
es `0..31`; en modo registro se usan los cinco bits bajos del contenido de `Rb`.

Las operaciones I-Type conservan `opcode | X | Y | imm16`, salvo los formatos
específicos de branch y postincremento descritos abajo. Los campos reservados
no nulos producen `ERROR_INVALID_ENCODING`; opcodes o subfunciones no soportados
producen `ERROR_INVALID_OPCODE`. Los modos de instrucciones que ya tienen una
regla específica, como los shifts inmediatos ausentes, conservan esa regla.

## 5. ALU y aritmética

`NOP`, `ADD`, `SUB`, `AND`, `OR`, `XOR` conservan sus encodings y semántica.
`NOP` exige los 26 bits bajos a cero. En las operaciones binarias simples,
`Rc=0` y `func6=0`.

### Familia MUL — `0x03`

| `func6` | Mnemónico | Operandos    | Semántica                               |
|---------|-----------|--------------|-----------------------------------------|
| `0x00`  | `MUL`     | `Rd, Ra, Rb` | low32 del producto                      |
| `0x01`  | `MULHI`   | `Rd, Ra, Rb` | high32 de signed32 × signed32           |
| `0x02`  | `MULHU`   | `Rd, Ra, Rb` | high32 de unsigned32 × unsigned32       |
| `0x03`  | `MULHSU`  | `Rd, Ra, Rb` | high32 de signed32(Ra) × unsigned32(Rb) |
| `0x04`  | `MULFX`   | `Rd, Ra, Rb` | Q16.16 vigente                          |
| `0x05`  | `MACFX`   | `Rd, Ra, Rb` | low32(old_Rd + MULFX(Ra, Rb))           |

`Rc=0` en todas. `MACFX` lee el antiguo destino como tercera fuente; no
introduce acumulación de 64 bits ni redondeo fusionado. Con `Rd=R0`, lee cero
y descarta el resultado. Puede requerir un ciclo adicional de lectura.
`MULH` puede aceptarse como alias de `MULHI`; nunca se elimina el nombre vigente.
El signo no afecta a los 32 bits bajos de `MUL`.

### Familia DIV — `0x0A`

| `func6` | Mnemónico | Operandos    |
|---------|-----------|--------------|
| `0x00`  | `DIV`     | `Rd, Ra, Rb` |
| `0x01`  | `DIVU`    | `Rd, Ra, Rb` |
| `0x02`  | `REM`     | `Rd, Ra, Rb` |
| `0x03`  | `REMU`    | `Rd, Ra, Rb` |

`Rc=0`; se conservan exactamente los resultados y errores de v0.1.

### Familia MINMAX — `0x0C`

`func6=0,1,2,3` selecciona respectivamente `MIN`, `MAX`, `MINU`, `MAXU`.
Operandos `Rd, Ra, Rb`; `Rc=0`. Se devuelve el menor/mayor operando según
comparación signed32 o unsigned32, sin saturación ni efectos de control.

### Familia SELECT — `0x0D`

`func6=0`: `SEL Rd, Ra, Rb, Rc`, resultado `Ra` si el contenido de `Rc` no es
cero; `Rb` en caso contrario. Necesita tres lecturas y una escritura. No cambia
máscaras SIMT ni ejecuta ambas ramas de código: selecciona valores ya calculados.

### Familia BIT — `0x0E`

| `func6` | Operación     | Resultado                                         |
|---------|---------------|---------------------------------------------------|
| `0x00`  | `CLZ Rd, Ra`  | Número de ceros iniciales en 32 bits; `CLZ(0)=32` |
| `0x01`  | `POPC Rd, Ra` | Número de bits a uno, entre 0 y 32                |

`Rb=Rc=0`. `CLZ` ayuda a normalizar datos y construir rutinas numéricas;
`POPC` permite contar las lanes seleccionadas por un ballot.

### Familia FXMATH — `0x0F`

| `func6` | Operación        | Objetivo                           |
|---------|------------------|------------------------------------|
| `0x00`  | `RCPFX Rd, Ra`   | Recíproco `1/x` en Q16.16          |
| `0x01`  | `RSQRTFX Rd, Ra` | Raíz inversa `1/sqrt(x)` en Q16.16 |

`Rb=Rc=0`. Se proponen estos encodings, pero ambas operaciones siguen pendientes
de definir dominio, rango, precisión, redondeo, overflow y errores. Un backend
no debe declarar soporte hasta disponer del contrato y un modelo de referencia.
El contrato debe permitir comprobar resultados entre simulador y RTL.

Se prioriza `RCPFX`: un recíproco de `w` se reutiliza para proyectar coordenadas
y recuperar atributos con perspectiva. `RSQRTFX` se orienta a normalización e
iluminación. El recíproco de valores pequeños puede desbordar Q16.16; no se
asume que todo resultado sea representable. No se sustituyen por `DIV` entero.

## 6. Colores: PIX565 — `0x0B`

Todas tienen operandos `Rd, Ra`, `Rb=Rc=0` y un único registro destino.

| `func6` | Operación    | Resultado en `Rd`                               |
|---------|--------------|-------------------------------------------------|
| `0x00`  | `PACK565`    | RGB565 en los 16 bits bajos; bits altos cero    |
| `0x01`  | `UNPACK565R` | Canal rojo expandido a 8 bits; bits altos cero  |
| `0x02`  | `UNPACK565G` | Canal verde expandido a 8 bits; bits altos cero |
| `0x03`  | `UNPACK565B` | Canal azul expandido a 8 bits; bits altos cero  |

`PACK565` conserva el contrato de v0.2: entrada `0x00RRGGBB`, ignorando el byte
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

## 7. Inmediatos, memoria y postincremento

`MOVI`, `ADDI`, `ANDI`, `ORI`, `XORI`, `LOAD`, `STORE`, `MOVHI` conservan
sus encodings `0x10–0x17`, extensiones de inmediato y semántica de v0.1.
`MOVI/MOVHI` exigen `Y=0`. Construir constantes con `MOVHI` + `ORI` sigue válido.

Los accesos pequeños se reordenan: `LOADB=0x18`, `LOADUB=0x19`, `LOADH=0x1A`,
`LOADUH=0x1B`, `STOREB=0x1C`, `STOREH=0x1D`. Todos conservan la sintaxis
`Rd/Rs, Ra, imm16`, con offset signed en bytes, dirección low32 y little-endian.
Bytes admiten cualquier dirección; medias palabras requieren dirección par;
palabras, múltiplos de cuatro. Se valida el intervalo completo y se conservan
los bytes vecinos. El error sigue siendo `ERROR_MEMORY_ACCESS`.

### STOREP — `0x1E`

```text
31       26 25    21 20    16 15  14 13                0
+----------+--------+--------+------+--------------------+
| opcode   |   Rs   |   Ra   | size |   signed imm14     |
+----------+--------+--------+------+--------------------+
```

`size=0,1,2` selecciona `STOREBP`, `STOREHP`, `STOREP` (8, 16, 32 bits).
`size=3` está reservado. Sintaxis: `STOREP Rs, Ra, incremento`, equivalente
para las otras dos variantes. El inmediato es signed en bytes, `-8192..8191`.

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

## 8. Control de flujo

### BR y BRI — `0x20` y `0x21`

```text
opcode | Ra[4:0] | Rb/imm5[4:0] | cond[2:0] | signed off13
```

| `cond`    | BR     | BRI     | Comparación / inmediato                     |
|-----------|--------|---------|---------------------------------------------|
| `000`     | `BEQ`  | `BEQI`  | Igualdad; inmediato extendido con signo     |
| `001`     | `BNE`  | `BNEI`  | Desigualdad; inmediato extendido con signo  |
| `010`     | `BLT`  | `BLTI`  | Signed menor; inmediato con signo           |
| `011`     | `BGE`  | `BGEI`  | Signed mayor o igual; inmediato con signo   |
| `100`     | `BLTU` | `BLTUI` | Unsigned menor; inmediato con ceros         |
| `101`     | `BGEU` | `BGEUI` | Unsigned mayor o igual; inmediato con ceros |
| `110–111` | —      | —       | Reservadas                                  |

Los inmediatos signed admiten `-16..15`; unsigned, `0..31`. La igualdad se
compara después de extender a 32 bits: `-1` corresponde a `0xFFFFFFFF`.
Destino tomado: `low32(PC + 4 + sign_extend(off13)*4)`; no tomado: `low32(PC+4)`.
Alcance `-4096..4095` palabras, aproximadamente ±16 KiB.

Los mnemónicos no cambian. Si el salto no cabe, el ensamblador da error.
La relajación automática a branch inverso y `BRA` queda como trabajo posterior,
con validación de layout y reconvergencia SIMT; no forma parte de la garantía inicial.

### BRA, JAL y JALR

| Opcode | Instrucción          | Formato                    | Semántica                                       |
|--------|----------------------|----------------------------|-------------------------------------------------|
| `0x22` | `BRA target`         | opcode + signed off26      | Salto relativo en palabras                      |
| `0x23` | `JAL Rd, target`     | opcode + Rd + signed off21 | Enlace y salto relativo en palabras             |
| `0x24` | `JALR Rd, Ra, imm16` | I-Type                     | Enlace y salto indirecto, inmediato en palabras |

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
En GPU se propone destino efectivo uniforme para las lanes activas y detección
antes de escribir enlaces. El código y estado del fallo deben cerrarse al
incorporar `calls` a GPU, siguiendo el trabajo pendiente de v0.2.

## 9. Identificadores y sistema

### GETID — `0x30`

I-Type: `opcode | Rd | type | imm16`, con `imm16=0`.
`type=0,1,2,3` selecciona `GETTID`, `GETLANE`, `GETWARP`, `GETWID`.
El resto de tipos está reservado. El ensamblador conserva los cuatro mnemónicos.

Se heredan los contratos de v0.1/v0.2: thread residente, lane dentro del warp,
slot de warp e ID lógico configurable, respectivamente. `GETWID` no pasa a
significar `workgroup_id` ni un índice global automático. Su configuración MMIO,
reset y traslado de contexto siguen pendientes según v0.2.
En CPU, `GETTID` vale cero y se propone lo mismo para `GETWID` cuando se incorpore;
`GETLANE/GETWARP` se proponen inicialmente para GPU.

### SSY, BAR, EXIT, TRAP, HALT

Mantienen opcodes `0x31`, `0x32`, `0x33`, `0x3E`, `0x3F` y sus contratos.
`SSY` conserva off26 relativo a PC+4 en palabras. Las otras cuatro instrucciones
exigen sus 26 bits bajos a cero. `SSY/BAR/EXIT` son del repertorio GPU.
`HALT` detiene CPU y retira lanes activas en GPU; `TRAP` produce parada con error.

## 10. Nuevas operaciones SIMT

### VOTE — `0x34`: BALLOT y ACTIVEMASK

Se usa el formato de registros con `func6`:

| `func6` | Mnemónico    | Operandos | Reservados   |
|---------|--------------|-----------|--------------|
| `0x00`  | `BALLOT`     | `Rd, Ra`  | `Rb=Rc=0`    |
| `0x01`  | `ACTIVEMASK` | `Rd`      | `Ra=Rb=Rc=0` |

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

### SHFL — `0x35`, propuesta pendiente de cerrar

`func6=0`: `SHFL Rd, Ra, Rb`; `Rc=0`. Cada lane activa lee el valor de `Ra`
de la lane indicada por su propio `Rb`. Todas las fuentes se capturan antes
de escribir resultados. Solo se propone la forma indexada, no variantes XOR,
up o down. No tiene efecto de barrera ni reconvergencia.

Antes de declarar soporte hay que fijar el tratamiento del índice fuera del
warp y de una fuente inactiva; no se asume wrap del índice ni lectura válida
de una lane que no participa. También debe cerrarse el estado de error si se
elige rechazar esos casos. Su utilidad es intercambio y reducciones sin memoria,
pero requiere una ruta de comunicación entre lanes cuyo área y timing deben medirse.

## 11. Capabilities

Los nombres existentes conservan su significado funcional, aunque el binario
requiera el ensamblador v0.3. Compartir opcode no obliga a implementar todas las
suboperaciones. Los nombres nuevos son propuestas, no entradas actuales del runner.

| Capability            | Operaciones                    | Estado del nombre                          |
|-----------------------|--------------------------------|--------------------------------------------|
| `subword_memory`      | Seis accesos pequeños          | Existente                                  |
| `calls`               | `JAL`, `JALR`, alias `JR/RET`  | Existente                                  |
| `shift_immediate`     | `SHLI/SHRI/SARI`               | Existente                                  |
| `alu_extended`        | `MULHI`, `DIVU`, `REM`, `REMU` | Existente                                  |
| `branch_immediate`    | Seis branches inmediatos       | Propuesto en v0.2                          |
| `gpu_ids`             | `GETLANE`, `GETWARP`           | Propuesto en v0.2                          |
| `warp_user_id`        | `GETWID` y configuración GPU   | Propuesto en v0.2                          |
| `minmax`              | Cuatro variantes MIN/MAX       | Propuesto en v0.2                          |
| `select`              | `SEL`                          | Propuesto en v0.2                          |
| `macfx`               | `MACFX`                        | Propuesto en v0.2                          |
| `pack565`             | `PACK565`                      | Propuesto en v0.2                          |
| `rcpfx`, `rsqrtfx`    | Respectivas operaciones        | Propuestos; contratos pendientes           |
| `mul_high_variants`   | `MULHU`, `MULHSU`              | Nuevo propuesto                            |
| `unpack565`           | Tres extracciones de canal     | Nuevo propuesto                            |
| `bit_count`           | `CLZ`, `POPC`                  | Nuevo propuesto                            |
| `store_postincrement` | `STOREBP/STOREHP/STOREP`       | Nuevo propuesto; requiere `subword_memory` |
| `warp_vote`           | `BALLOT`, `ACTIVEMASK`         | Nuevo propuesto; GPU                       |
| `warp_shuffle`        | `SHFL` indexado                | Nuevo propuesto; GPU, contrato pendiente   |
| `pc_relative_address` | `LEAPC`                        | Nuevo propuesto; CPU y GPU                 |
| `indexed_load`        | `LOADX` de 32 bits             | Nuevo propuesto; CPU y GPU                 |

El runner deberá admitir capabilities portables en CPU y GPU. Un backend sin
una suboperación debe rechazarla explícitamente. `R0=0` sigue siendo obligatorio,
no una capability. Ni caches MUL/DIV ni número de ciclos forman parte del repertorio.

## 12. Mapa completo propuesto

| Opcode      | Operación / familia                                |
|-------------|----------------------------------------------------|
| `0x00`      | `NOP`                                              |
| `0x01`      | `ADD`                                              |
| `0x02`      | `SUB`                                              |
| `0x03`      | MUL: `MUL/MULHI/MULHU/MULHSU/MULFX/MACFX`          |
| `0x04`      | `AND`                                              |
| `0x05`      | `OR`                                               |
| `0x06`      | `XOR`                                              |
| `0x07`      | `SHL/SHLI`                                         |
| `0x08`      | `SHR/SHRI`                                         |
| `0x09`      | `SAR/SARI`                                         |
| `0x0A`      | DIV: `DIV/DIVU/REM/REMU`                           |
| `0x0B`      | PIX565: `PACK565/UNPACK565R/UNPACK565G/UNPACK565B` |
| `0x0C`      | MINMAX: `MIN/MAX/MINU/MAXU`                        |
| `0x0D`      | SELECT: `SEL`                                      |
| `0x0E`      | BIT: `CLZ/POPC`                                    |
| `0x0F`      | FXMATH: `RCPFX/RSQRTFX`, contratos pendientes      |
| `0x10`      | `MOVI`                                             |
| `0x11`      | `ADDI`                                             |
| `0x12`      | `ANDI`                                             |
| `0x13`      | `ORI`                                              |
| `0x14`      | `XORI`                                             |
| `0x15`      | `LOAD`                                             |
| `0x16`      | `STORE`                                            |
| `0x17`      | `MOVHI`                                            |
| `0x18`      | `LOADB`                                            |
| `0x19`      | `LOADUB`                                           |
| `0x1A`      | `LOADH`                                            |
| `0x1B`      | `LOADUH`                                           |
| `0x1C`      | `STOREB`                                           |
| `0x1D`      | `STOREH`                                           |
| `0x1E`      | `STOREBP/STOREHP/STOREP`                           |
| `0x1F`      | `LOADX`, carga indexada de 32 bits                 |
| `0x20`      | BR: `BEQ/BNE/BLT/BGE/BLTU/BGEU`                    |
| `0x21`      | BRI: `BEQI/BNEI/BLTI/BGEI/BLTUI/BGEUI`             |
| `0x22`      | `BRA`                                              |
| `0x23`      | `JAL`                                              |
| `0x24`      | `JALR`; `JR/RET` son alias                         |
| `0x25`      | `LEAPC`, cálculo de dirección relativo al PC       |
| `0x26–0x2F` | Libres                                             |
| `0x30`      | GETID: `GETTID/GETLANE/GETWARP/GETWID`             |
| `0x31`      | `SSY`                                              |
| `0x32`      | `BAR`                                              |
| `0x33`      | `EXIT`                                             |
| `0x34`      | VOTE: `BALLOT/ACTIVEMASK`                          |
| `0x35`      | `SHFL`, contrato pendiente                         |
| `0x36–0x3D` | Libres                                             |
| `0x3E`      | `TRAP`                                             |
| `0x3F`      | `HALT`                                             |

| Grupo              | Ocupados/propuestos | Libres |
|--------------------|--------------------:|-------:|
| ALU                |                  16 |      0 |
| Inmediatos/memoria |                  16 |      0 |
| Control            |                   6 |     10 |
| Sistema/SIMT       |                   8 |      8 |
| **Total**          |              **46** | **18** |

Se cuentan las familias con contrato pendiente como asignaciones propuestas.
Los huecos de subfunción dentro de cada familia siguen disponibles. La familia
ALU principal queda llena, pero nuevas variantes pueden usar esas subfunciones.
No se debe confundir el número de operaciones con el de opcodes principales.

## 13. Extensiones futuras sin asignación

- **Carga directa relativa al PC:** `LDR` para literal pools sigue como alternativa
  sin opcode; véase §16. `LEAPC` y `LOADX` sí se incorporan al mapa propuesto.
- **Trigonometría dedicada:** `SINFX/COSFX` y sus posibles implementaciones se
  estudian en §17, sin asignación ni capability activa todavía.
- **Atómicos:** contadores y arbitraje de escrituras compartidas; requieren un
  contrato de atomicidad y orden en LSU. No se asignan `ATOMADD/ATOMMIN` todavía.
- **Bitfield y rotaciones:** `BFEXT/BFINS/BSET/BCLR`, `ROL/ROR`, pendientes de uso
  y encoding; no se confunden con la capability `bit_count`.
- **Multiply-add entero:** `MADD`, separado de `MACFX`, pendiente de contrato.
- **Votos/reducciones adicionales:** `ANY/ALL` o variantes de SHFL, según medidas.

Estas ideas no entran en el recuento de 46 opcodes. Las instrucciones de v0.2
sí están todas incluidas, aunque `RCPFX/RSQRTFX` se implementen más adelante.

## 14. Microarquitectura y validación pendiente

Reutilizar resultados secundarios de MUL/DIV es una optimización transparente;
la 21 ya tiene un camino rápido para determinadas secuencias consecutivas.
No exige usar el slot físico de `R0`, ni forma parte de esta reorganización.
El almacenamiento oculto, sus etiquetas y sus puertos se deciden en el diseño
RTL. Un miss debe recalcular el mismo resultado y no cambiar el comportamiento.

Antes de cerrar v0.3:

1. Aprobar el mapa y los campos propuestos, en especial off13 de branches.
2. Definir selección de ISA en ensamblador y verificación del binario/backend.
3. Cerrar `RCPFX/RSQRTFX`, fuentes inválidas de SHFL y fallos SIMT pendientes.
4. Aprobar capabilities, dependencias y backends iniciales; no activar una
   familia completa por implementar una sola variante.
5. Crear pruebas de recompilación: mismo fuente y resultados en v0.1/v0.3 para
   programas dentro de límites, sin comparar hex ni PCs numéricos entre layouts distintos.
6. Probar `LEAPC` con reubicación, límites de off21 y wrap; `LOADX` con escalas
   0..3, límites de memoria, desalineación, registros coincidentes y máscaras GPU.
   Verificar bordes de inmediatos, alias, campos reservados, registros coincidentes,
   `R0`, división por cero, alineación y conservación de memoria vecina.
7. Probar máscaras divergentes, voto de lanes activas, comunicación SHFL y stores
   postincrementales con fallos parciales antes de declarar soporte GPU.
8. Medir ciclos, área y timing de subdecodificadores, lecturas adicionales y
   comunicación entre lanes. Agrupar opcodes no garantiza mejorar Fmax.

La propuesta conserva el lenguaje de las operaciones existentes, recupera todo
v0.2 y amplía el repertorio con **18 opcodes principales aún libres**. Los cambios
funcionales pendientes están señalados; el repertorio vigente sigue en `isa.md`.

## 15. Guía práctica: para qué sirven las operaciones gráficas

Estas instrucciones no dibujan un triángulo por sí solas. Aceleran pasos pequeños
que se repiten en transformaciones, rasterización y escritura de imágenes.
Los ejemplos son ensamblador **propuesto para v0.3**; no implican que el
ensamblador actual ya acepte los mnemónicos nuevos. Requieren las capabilities
correspondientes. En GPU cada lane trabaja con sus propios registros y solo
participan las lanes activas.

En los ejemplos Q16.16, el entero 65536 representa 1.0; 32768 representa 0.5.
Las fórmulas deben mantenerse dentro del rango representable: estas operaciones
no eliminan la cuantización ni el overflow. Menos instrucciones suele reducir
fetch, decodificación y temporales, pero el ahorro de ciclos depende del RTL y
de la memoria. Aquí se comparan secuencias, no se prometen aceleraciones medidas.

### 15.1. PACK565: guardar un color en el framebuffer

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

### 15.2. UNPACK565R/G/B: operar sobre los canales de un color

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

### 15.3. MULFX y MACFX: transformar coordenadas

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

### 15.4. RCPFX: perspectiva y atributos de textura

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

### 15.5. RSQRTFX: normalizar normales para iluminación

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

### 15.6. MIN/MAX: limitar coordenadas y valores

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

### 15.7. SEL: elegir valores sin abrir una rama

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

### 15.8. STOREHP y STOREBP: recorrer una imagen

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

### 15.9. Votos SIMT: saber qué lanes tienen trabajo

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

### 15.10. SHFL: compartir un dato calculado por otra lane

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
El ejemplo presupone fuente válida y activa: el comportamiento de fuentes
inválidas continúa pendiente de definir y el coste de hardware debe medirse.

## 16. LEAPC, LOADX y la alternativa LDR: acceder a tablas

PC-relative es un modo de direccionamiento, no el nombre de una tercera
instrucción. Conviene distinguir calcular una dirección de leer su contenido:

| Operación | Función | ¿Lee memoria? | Estado en v0.3 |
|---|---|---|---|
| `LEAPC` | Obtiene la dirección de datos cercanos al código | No | Encoding propuesto |
| `LOADX` | Lee tabla[indice] mediante base e índice escalado | Sí | Encoding propuesto |
| `LDR` relativo al PC | Lee directamente un dato cercano al código | Sí | Alternativa sin asignar |

### 16.1. LEAPC — `0x25`

```text
31       26 25    21 20                             0
+----------+--------+---------------------------------+
|  0x25    |   Rd   |        signed off21             |
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
Requiere la nueva capability propuesta `pc_relative_address`.

En GPU escribe la misma dirección en las lanes activas del warp; no modifica
máscaras ni reconverge. `Rd=R0` descarta el resultado y continúa normalmente.

Ejemplo:

```asm
LEAPC R1, tabla_senos
; R1 es la dirección de la tabla, no su primer valor
```

La alternativa es construir una dirección absoluta con MOVHI y ORI, con el
soporte de símbolos/relocaciones correspondiente. LEAPC evita una instrucción
cuando la tabla cabe en alcance. Si código y tabla se desplazan juntos, la
distancia permanece igual: el cálculo sigue funcionando sin corregir una
constante absoluta. Esto no hace reubicable automáticamente el resto del programa.

### 16.2. LOADX — `0x1F`

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
validación de los cuatro bytes y `ERROR_MEMORY_ACCESS` ante un acceso inválido.
El cálculo hace wrap a 32 bits. Una escala 0 o 1 no autoriza una carga desalineada.
Ra y Rb no se actualizan. `Rd=Ra` o `Rd=Rb` es legal: se usan las fuentes previas.
Con `Rd=R0` se descarta el resultado, pero se realiza el acceso y se detectan errores.

Requiere la nueva capability propuesta `indexed_load`. En GPU calcula una
dirección por lane activa y conserva el comportamiento de cargas y fallos por
lane del backend; no introduce coalescencia, atómicos ni una barrera.
Las variantes indexadas de byte/halfword quedan como ampliación posterior,
sin mnemónicos ni subfunciones asignados en esta revisión.

Ejemplo con entradas de cuatro bytes:

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

### 16.3. Combinación para tablas

```asm
LEAPC R1, tabla_senos   ; normalmente fuera del bucle
; ... calcular el indice en R2 ...
LOADX R3, R1, R2, 2    ; tabla_senos[indice], entrada de 32 bits
```

LEAPC localiza la tabla; LOADX selecciona su elemento. La base se reutiliza
para muchos índices. El mismo patrón sirve para paletas de palabras, tablas de
coeficientes y datos de vértices. Ambas operaciones mantienen un único destino.

### 16.4. LDR relativo al PC: alternativa para constantes

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

## 17. Trigonometría: tablas primero, instrucciones dedicadas opcionales

### 17.1. Tabla de seno con fase en vueltas

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

### 17.2. Elegir entre memoria y cálculo

| Método                  | Ventaja                                             | Coste o límite                                       |
|-------------------------|-----------------------------------------------------|------------------------------------------------------|
| Tabla sin interpolación | Una consulta y cálculo de índice sencillo           | Más escalones o una tabla mayor                      |
| Tabla con interpolación | Mejor aproximación con tabla pequeña                | Dos cargas y aritmética; error por cuantización      |
| Aproximación polinómica | Puede reducir accesos a memoria                     | Coeficientes, reducción de rango y varios productos  |
| CORDIC                  | Calcula funciones mediante etapas de sumas y shifts | Iteraciones o área de pipeline; escalado y precisión |

Una tabla en EBR/ROM cercana puede ser más útil que una tabla en SDRAM, pero
las lanes pueden consultar índices distintos. El número de puertos puede
obligar a serializar accesos. Ubicación, bancos y cachés son decisiones de
microarquitectura: LEAPC y LOADX no garantizan una memoria más rápida.

El software puede probar primero una tabla y su error con las instrucciones
existentes/propuestas. No se necesita añadir una instrucción específica por
cada tabla de seno, gamma, iluminación o animación.

### 17.3. SINFX y COSFX como posibles instrucciones

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
recuento: con LEAPC y LOADX, el mapa contiene **46 opcodes propuestos y 18 libres**.

-----------------------------

DIVFX?
MULFXR (redondeando)
FXTOI

añadir pseudoinstrucciones en el ensamblador para generar operaciones de punto fijo con redondeo, saturación y conversión a entero.