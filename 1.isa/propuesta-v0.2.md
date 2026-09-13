# Propuesta de MiniISA v0.2

## 1. Alcance: ampliación compatible

Este documento reúne instrucciones pendientes y trabajo de implementación para
ampliar la [MiniISA v0.1 vigente](isa.md), cuya referencia escalar más completa
es `21.fpga-cpu-hdmi-alu`.

**v0.2 conserva los opcodes, formatos y comportamientos ya definidos.** Puede
asignar huecos reservados y añadir capabilities, pero no mover instrucciones ni
reinterpretar encodings válidos. La reorganización incompatible del mapa se
estudia por separado en [propuesta-v0.3.md](propuesta-v0.3.md).

La compatibilidad significa que un programa válido para la ISA vigente conserva
su comportamiento en un backend que mantenga sus capabilities. No significa
que un backend antiguo pueda ejecutar las instrucciones nuevas.

### Lo que ya está resuelto en v0.1

| Elemento                       | Estado vigente                                                  |
|--------------------------------|-----------------------------------------------------------------|
| `R0=0`                         | Regla común de todas las implementaciones; no es una capability |
| `GETTID`, `SSY`, `BAR`, `EXIT` | Repertorio documentado de CPU/GPU; `SSY/BAR/EXIT` son de GPU    |
| `JAL`, `JALR`, `JR`            | Capability `calls`, implementada en CPU                         |
| `SHLI`, `SHRI`, `SARI`         | Capability `shift_immediate`; bit 10 de los shifts existentes   |
| Accesos de 8 y 16 bits         | Capability `subword_memory`, implementada en CPU                |
| `MULHI`, `DIVU`, `REM`, `REMU` | Capability `alu_extended`, implementada en CPU                  |

Sus contratos y disponibilidad por backend están en `isa.md`. Las explicaciones
históricas sobre corregir SIMT, elegir el registro cero o escoger un encoding
para shifts no son decisiones pendientes de v0.2.

`JR` sigue en `0x2E`. Aunque equivale a `JALR R0, Ra, 0`, eliminarlo o reasignar
su opcode rompería la compatibilidad. `RET` sigue siendo el alias actual de
`JR R31`; `R31` y `R30` conservan las convenciones de enlace y pila.

## 2. Branches con inmediato

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

### Formato y semántica

Se conserva I-Type, sustituyendo el segundo registro por `imm5`:

```text
31          26 25    21 20    16 15                         0
+-------------+--------+--------+----------------------------+
|   opcode    |   Ra   |  imm5  |       signed offset16      |
+-------------+--------+--------+----------------------------+
```

| Opcode propuesto | Mnemónico | Comparación             | Extensión de `imm5`  |
|------------------|-----------|-------------------------|----------------------|
| `0x26`           | `BEQI`    | `Ra == imm`             | Con signo, `-16..15` |
| `0x27`           | `BNEI`    | `Ra != imm`             | Con signo, `-16..15` |
| `0x28`           | `BLTI`    | `signed32(Ra) < imm`    | Con signo, `-16..15` |
| `0x29`           | `BGEI`    | `signed32(Ra) >= imm`   | Con signo, `-16..15` |
| `0x2A`           | `BLTUI`   | `unsigned32(Ra) < imm`  | Con ceros, `0..31`   |
| `0x2B`           | `BGEUI`   | `unsigned32(Ra) >= imm` | Con ceros, `0..31`   |

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

## 3. Identificadores adicionales para GPU

### `GETLANE` y `GETWARP`

| Opcode propuesto | Mnemónico    | Resultado                                        |
|------------------|--------------|--------------------------------------------------|
| `0x34`           | `GETLANE Rd` | Índice de lane dentro del warp: `0..warp_size-1` |
| `0x35`           | `GETWARP Rd` | Slot de warp dentro del SM                       |

Ambas usan I-Type: `X = Rd`, `Y = 0`, `imm16 = 0`. Los campos reservados no
nulos producen `ERROR_INVALID_ENCODING`. Solo escriben las lanes activas;
una escritura a `R0` se descarta. El soporte inicial propuesto es GPU; cualquier
incorporación a MiniCPU deberá fijar explícitamente sus resultados escalares.

`GETTID` conserva su semántica de thread residente:
`warp_id * warp_size + lane_id`. Estos identificadores no representan por sí
solos un índice global de trabajo independiente de la ubicación física.

### `GETWID`: identificador lógico configurable

| Opcode propuesto | Mnemónico  | Resultado                                     |
|------------------|------------|-----------------------------------------------|
| `0x36`          | `GETWID Rd` | Los 32 bits de `warp_user_id` del warp actual |

Encoding: `X = Rd`, `Y = 0`, `imm16 = 0`. El valor es igual para todas las lanes
del warp y solo escriben las activas. En MiniCPU se propone devolver cero.

Cada slot de warp guarda un `warp_user_id` de 32 bits: 256 bits en una
configuración de ocho warps. El lanzador lo configura con la GPU detenida;
se conserva durante pausa/reanudación y vale cero tras reset de GPU.
La ventana MMIO está pendiente de asignación. No debe reutilizarse el cuarto
word del descriptor actual, que ya expone estado de solo lectura.

Es independiente de `workgroup_id`, usado por las barreras. No cambia el
scheduler, los tags de LSU ni `BAR`. No se exige unicidad: el programa puede
interpretarlo como tile, objeto, número de bloque o base de elementos. Al mover
un trabajo de slot o de SM, el lanzador debe conservar este valor.

```asm
GETWID  R1         ; si el lanzador proporciona una base de elementos
GETLANE R2
ADD     R3, R1, R2
```

Si el ID representa un número de bloque, el programa calcula
`warp_user_id * warp_size + lane_id`. `GETWID` no asigna trabajo automáticamente.

## 4. Incorporación de capabilities existentes a GPU

Esta sección es trabajo pendiente de backend, no nuevas asignaciones de opcode.
La 21 ya implementa estas operaciones en CPU; no se presupone que por ello estén
disponibles en MiniGPU.

| Capability vigente | Trabajo al incorporarla a GPU                                          |
|--------------------|------------------------------------------------------------------------|
| `calls`            | Enlace por lane, saltos indirectos y regla de uniformidad              |
| `subword_memory`   | Tamaño y extensión en LSU, máscaras de escritura y validación por lane |
| `shift_immediate`  | Bit 10 y selección de cantidad, conservando la máscara activa          |
| `alu_extended`     | Semántica signed/unsigned, división por cero y resultados por lane     |

### Llamadas y destinos indirectos

Se propone exigir que `JALR` y `JR` produzcan el mismo destino efectivo en todas
las lanes activas. La comparación se realiza después del cálculo y alineación
que define v0.1. Si difieren, se propone `ERROR_SIMT`; hay que asignar o confirmar
su código antes de implementar. No se selecciona silenciosamente una lane.

Debe fijarse también el estado observable del fallo, en particular si se
impiden todas las escrituras de enlace antes de detectar la divergencia. No se
declara soporte `calls` en GPU hasta cerrar y probar el contrato completo.
`JAL` conserva su offset16 relativo en palabras; `JALR`, su inmediato en palabras;
`JR`, su opcode propio. Serializar múltiples destinos queda fuera de este alcance.

### Accesos pequeños

Se conserva el contrato de v0.1: offset16 signed en bytes, little-endian,
alineación par para medias palabras y conservación de bytes vecinos.
Solo acceden las lanes activas; se valida el intervalo completo de cada acceso.

La interfaz SM↔LSU debe transportar el tamaño. Las respuestas conservan la
asociación con warp/lane y sus errores. Aceptar una petición no equivale a
completarla: `BAR` debe esperar también estos accesos. No se introducen atómicos,
orden entre escrituras solapadas de distintos warps ni una garantía nueva de
rollback global ante un fallo parcial.

El backend EBR necesita habilitaciones por byte; el de SDRAM debe usar máscaras
adecuadas al tamaño y a la posición del dato. Los detalles de transferencias y
ráfagas pertenecen a cada implementación, no al contrato de la instrucción.

## 5. Operaciones nuevas mediante `EXT`

### Operaciones y contratos

| Operación propuesta | Utilidad                         | Grado de definición                  |
|---------------------|----------------------------------|--------------------------------------|
| `MIN`, `MAX`        | Límites y recorte signed32       | Semántica definida en esta propuesta |
| `MINU`, `MAXU`      | Índices y profundidad unsigned32 | Semántica definida en esta propuesta |
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

### Encoding propuesto: `EXT` en `0x1E`

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
| `0x09–0x3F`       | Reservadas | —                | 55 suboperaciones disponibles     |

Un campo reservado a cero no es un operando leído. Los campos reservados no
nulos producen `ERROR_INVALID_ENCODING`; una función reservada o no soportada
produce `ERROR_INVALID_OPCODE`. Todas las operaciones respetan `R0=0`; en GPU
solo escriben las lanes activas y no modifican las máscaras SIMT.

## 6. Resumen y mapa resultante

### Qué añadiría el conjunto completo

Sobre v0.1 se proponen **18 operaciones nuevas**: seis branches inmediatos,
tres identificadores y nueve operaciones bajo `EXT`. Consumen **10 opcodes
principales nuevos**. Dos de las operaciones EXT tienen contrato numérico pendiente.

Las capabilities de llamadas, memoria pequeña, shifts y ALU existentes pueden
portarse a GPU sin consumir opcodes nuevos. `R0`, `JR`, las unidades de los
saltos y el resto de los encodings vigentes permanecen iguales.

### Mapa completo si se adoptan todas las propuestas

**Vigente** significa ya definido en v0.1, no disponible en todos los backends.
**Propuesto** no supone que exista implementación ni que el contrato esté cerrado.

| Opcode      | Instrucción o familia                                 | Estado       |
|-------------|-------------------------------------------------------|--------------|
| `0x00`      | `NOP`                                                 | Vigente      |
| `0x01`      | `ADD`                                                 | Vigente      |
| `0x02`      | `SUB`                                                 | Vigente      |
| `0x03`      | `MULFX`                                               | Vigente      |
| `0x04`      | `AND`                                                 | Vigente      |
| `0x05`      | `OR`                                                  | Vigente      |
| `0x06`      | `XOR`                                                 | Vigente      |
| `0x07`      | `SHL` / `SHLI`                                        | Vigente      |
| `0x08`      | `SHR` / `SHRI`                                        | Vigente      |
| `0x09`      | `SAR` / `SARI`                                        | Vigente      |
| `0x0A`      | `MUL`                                                 | Vigente      |
| `0x0B`      | `MULHI`                                               | Vigente      |
| `0x0C`      | `DIV`                                                 | Vigente      |
| `0x0D`      | `DIVU`                                                | Vigente      |
| `0x0E`      | `REM`                                                 | Vigente      |
| `0x0F`      | `REMU`                                                | Vigente      |
| `0x10`      | `MOVI`                                                | Vigente      |
| `0x11`      | `ADDI`                                                | Vigente      |
| `0x12`      | `ANDI`                                                | Vigente      |
| `0x13`      | `ORI`                                                 | Vigente      |
| `0x14`      | `XORI`                                                | Vigente      |
| `0x15`      | `LOAD`                                                | Vigente      |
| `0x16`      | `STORE`                                               | Vigente      |
| `0x17`      | `MOVHI`                                               | Vigente      |
| `0x18`      | `LOADB`                                               | Vigente      |
| `0x19`      | `LOADUB`                                              | Vigente      |
| `0x1A`      | `STOREB`                                              | Vigente      |
| `0x1B`      | `LOADH`                                               | Vigente      |
| `0x1C`      | `LOADUH`                                              | Vigente      |
| `0x1D`      | `STOREH`                                              | Vigente      |
| `0x1E`      | `EXT`: nueve suboperaciones, véase §5                 | Propuesto    |
| `0x1F`      | Sin asignar                                           | Libre        |
| `0x20`      | `BEQ`                                                 | Vigente      |
| `0x21`      | `BNE`                                                 | Vigente      |
| `0x22`      | `BLT`                                                 | Vigente      |
| `0x23`      | `BGE`                                                 | Vigente      |
| `0x24`      | `BLTU`                                                | Vigente      |
| `0x25`      | `BGEU`                                                | Vigente      |
| `0x26`      | `BEQI`                                                | Propuesto    |
| `0x27`      | `BNEI`                                                | Propuesto    |
| `0x28`      | `BLTI`                                                | Propuesto    |
| `0x29`      | `BGEI`                                                | Propuesto    |
| `0x2A`      | `BLTUI`                                               | Propuesto    |
| `0x2B`      | `BGEUI`                                               | Propuesto    |
| `0x2C`      | `JAL`                                                 | Vigente      |
| `0x2D`      | `JALR`                                                | Vigente      |
| `0x2E`      | `JR`                                                  | Vigente      |
| `0x2F`      | `BRA`                                                 | Vigente      |
| `0x30`      | `GETTID`                                              | Vigente      |
| `0x31`      | `SSY`                                                 | Vigente, GPU |
| `0x32`      | `BAR`                                                 | Vigente, GPU |
| `0x33`      | `EXIT`                                                | Vigente, GPU |
| `0x34`      | `GETLANE`                                             | Propuesto    |
| `0x35`      | `GETWARP`                                             | Propuesto    |
| `0x36`      | `GETWID`                                              | Propuesto    |
| `0x37–0x3D` | Sin asignar; posibles operaciones de voto/intercambio | Libres       |
| `0x3E`      | `TRAP`                                                | Vigente      |
| `0x3F`      | `HALT`                                                | Vigente      |

### Ocupación

| Familia                        | Ocupados en v0.1 | Libres en v0.1 | Nuevos propuestos | Libres resultantes |
|--------------------------------|-----------------:|---------------:|------------------:|-------------------:|
| ALU `0x00–0x0F`                |               16 |              0 |                 0 |                  0 |
| Inmediatos/memoria `0x10–0x1F` |               14 |              2 |                 1 |                  1 |
| Control `0x20–0x2F`            |               10 |              6 |                 6 |                  0 |
| Sistema/SIMT `0x30–0x3F`       |                6 |             10 |                 3 |                  7 |
| **Total**                      |           **46** |         **18** |            **10** |              **8** |

El conjunto completo ocuparía **56 de 64 opcodes**, con **8 libres** y
**55 suboperaciones EXT libres**. Control quedaría lleno; no se puede recuperar
`0x2E` sin romper compatibilidad. Si las nueve operaciones EXT consumieran un
opcode principal cada una, el mismo conjunto agotaría los 64 opcodes.

## 7. Capabilities propuestas y decisiones pendientes

Los nombres siguientes son **propuestas**, no entradas existentes del runner:

| Capability propuesta | Operaciones                  | Alcance inicial propuesto                  |
|----------------------|------------------------------|--------------------------------------------|
| `branch_immediate`   | Los seis branches inmediatos | CPU y GPU                                  |
| `gpu_ids`            | `GETLANE`, `GETWARP`         | GPU                                        |
| `warp_user_id`       | `GETWID` y su configuración  | GPU; resultado cero en CPU si se incorpora |
| `minmax`             | `MIN`, `MAX`, `MINU`, `MAXU` | CPU y GPU                                  |
| `select`             | `SEL`                        | CPU y GPU                                  |
| `macfx`              | `MACFX`                      | CPU y GPU                                  |
| `pack565`            | `PACK565`                    | CPU y GPU                                  |
| `rcpfx`              | `RCPFX`                      | Pendiente del contrato numérico            |
| `rsqrtfx`            | `RSQRTFX`                    | Pendiente del contrato numérico            |

No se propone una capability única que obligue a implementar todo `EXT`.
Compartir opcode no implica compartir disponibilidad: un backend puede ofrecer
`MIN/MAX` sin recíproco. El runner deberá admitir las capabilities portables en
CPU y GPU, y comprobar `requires` contra las declaraciones de cada backend.

Antes de implementar falta:

1. Aprobar las asignaciones nuevas y los nombres/grupos de capabilities.
2. Cerrar la uniformidad de llamadas GPU y el estado observable de sus errores.
3. Asignar MMIO a `warp_user_id` y definir su integración con lanzamiento y reset.
4. Cerrar los contratos numéricos de `RCPFX` y `RSQRTFX`.
5. Elegir qué operaciones se incorporan primero y a qué backends, con medidas
   reproducibles de instrucciones, ciclos, área y timing.

Quedan fuera de este alcance la eliminación de `JR`, los branches compactados
de v0.3, el cambio de unidades de `JALR`, rotaciones y las nuevas operaciones de
voto/intercambio (`BALLOT`, `ANY`, `ALL`, `SHFL`), que no reciben encoding aquí.
La idea de carga de datos relativa al PC se conserva en v0.3 como extensión futura.

## 8. Plan de implementación y validación

| Componente              | Trabajo pendiente                                                         |
|-------------------------|---------------------------------------------------------------------------|
| `1.isa/miniisa_asm.py`  | Nuevos mnemónicos y encodings, etiquetas y validación de operandos        |
| `2.cpu-sim-func`        | Referencia funcional de las operaciones nuevas adoptadas                  |
| `11.gpu-sim-func`       | Nuevas operaciones, capabilities portadas, máscaras y fallos              |
| CPU RTL basada en la 21 | Decodificación y datapaths de las capabilities elegidas                   |
| GPU RTL                 | Portar capabilities existentes y añadir las nuevas elegidas, incluida LSU |
| Monitor/lanzador        | Configuración de `warp_user_id` e identificación de backends              |
| `x.cpu-tests`           | Declaración de capabilities, `requires` y pruebas diferenciales           |
| `1.isa/isa.md`          | Incorporar contratos adoptados y disponibilidad verificada                |

No es necesario modificar todas las carpetas históricas para añadir una
capability. Cada backend debe declarar únicamente lo que implementa.

La validación debe cubrir:

- Branches: límites de `imm5` y `offset16`, extensión signed/unsigned, igualdad
  con `-1`, saltos tomados/no tomados y divergencia/reconvergencia en GPU.
- Identificadores: lanes/warps distintos, máscara activa, descarte en `R0`,
  reset, pausa/reanudación y traslado del ID lógico entre slots.
- Calls GPU: destinos efectivos uniformes y divergentes, registros coincidentes,
  enlace descartado en `R0`, alineación y efectos observables del fallo.
- Memoria GPU: tamaños, extensión, bytes vecinos, offsets negativos, límites,
  alineación, errores por lane y finalización antes de `BAR`.
- EXT: funciones no soportadas, campos reservados, operandos coincidentes,
  extremos signed/unsigned, equivalencia de `MACFX` a `MULFX`+`ADD` y colores RGB565.
- Aritmética portada a GPU: signos, overflow, división por cero y máscaras activas.
- Regresión: conservar los resultados y encodings de programas v0.1; medir
  rendimiento por separado de la equivalencia funcional.

Esta revisión organiza la propuesta documental. No implementa instrucciones,
no registra capabilities nuevas y no cambia la ISA vigente.
