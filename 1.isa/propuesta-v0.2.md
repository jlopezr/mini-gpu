# Propuesta de MiniISA v0.2

Borrador para discusión. Cubre ocho bloques:

1. Corrección documental del bloque SIMT (**aplicada**; ver §0).
2. Branches con inmediato.
3. Llamadas y saltos indirectos: `JAL`, `JALR`, `JR`.
4. Desplazamientos con inmediato y rotaciones.
5. Escrituras de 8 y 16 bits: `STOREB` y `STOREH`.
6. ID lógico de warp asignado por el lanzador.
7. Operaciones candidatas para 2D y 3D.
8. El mapa de opcodes resultante y lo que queda libre.

Nada de esto rompe programas existentes: todo son opcodes hoy reservados, salvo
la corrección del bloque SIMT, que alinea el documento con lo que ya se ejecuta.

---

## 0. Corrección documental del bloque SIMT — aplicada

**Aplicado:** `isa.md` ya refleja los opcodes y formatos usados por el
ensamblador, el simulador GPU y el RTL. Se conservan aquí las discrepancias
originales como contexto de la propuesta:

| Opcode | `isa.md` documentaba | Ensamblador y simuladores usan |
|--------|--------------------|--------------------------------|
| `0x31` | `GETLANE`          | **`SSY`**                      |
| `0x32` | `GETWARP`          | **`BAR`**                      |
| `0x33` | `BAR`              | **`EXIT`**                     |

`GETLANE` y `GETWARP` siguen sin implementarse; su incorporación en §1.2 es
una propuesta independiente. La corrección aplicada documenta `SSY` en `0x31`
con formato B-Type, `BAR` en `0x32` y `EXIT` en `0x33`, junto con sus operandos
y semántica actual. No modifica ensamblador, simuladores ni RTL.

---

## 1. Bloque SIMT

### 1.1 Documentar lo que ya existe — aplicado en §0

| Opcode | Mnemónico | Formato    | Operandos | Semántica                                              |
|--------|-----------|------------|-----------|--------------------------------------------------------|
| `0x30` | `GETTID`  | I-Type     | `Rd`      | Identificador lineal del work-item                     |
| `0x31` | `SSY`     | **B-Type** | `label`   | Abre una región de reconvergencia cuyo join es `label` |
| `0x32` | `BAR`     | I-Type     | —         | Barrera; exige que participen todas las lanes vivas    |
| `0x33` | `EXIT`    | I-Type     | —         | Retira la lane permanentemente                         |

`SSY` usa B-Type con `offset26` en palabras, exactamente igual que `BRA`. Este formato ya está recogido en `isa.md` tras la corrección de §0.

`BAR` con `active_mask != live_mask` produce `ERROR_BARRIER`. `EXIT` retira la
lane de `live_mask`; cuando `live_mask` llega a cero el warp termina y las pilas
REGION y PATH quedan vacías. Ambos comportamientos ya están cubiertos por tests.

### 1.2 Añadir las que faltan

Recuperar los dos mnemónicos que `isa.md` prometía, en opcodes libres:

| Opcode | Mnemónico | Formato | Operandos | Semántica                                        |
|--------|-----------|---------|-----------|--------------------------------------------------|
| `0x34` | `GETLANE` | I-Type  | `Rd`      | Índice de lane dentro del warp, `0..warp_size-1` |
| `0x35` | `GETWARP` | I-Type  | `Rd`      | Identificador de warp dentro del SM              |

Los tres `GET*` comparten encoding: `X = Rd`, `Y = 0`, `imm16 = 0`.

Con `GETTID`, `GETLANE` y `GETWARP` se puede escribir código que decida por
lane, por warp o por work-item sin tener que derivar unos de otros con
divisiones, que es justo lo que la ISA no tiene barato.

**Candidatas que NO propongo ahora**, pero que conviene tener anotadas antes de
repartir `0x37–0x3D`: operaciones de voto entre lanes (`BALLOT`, `ANY`, `ALL`)
y de intercambio (`SHFL`). Son el siguiente escalón natural de una ISA SIMT y
consumirán varios opcodes; reservar espacio ahora es más barato que buscarlo
después.

### 1.3 ID lógico del warp: `GETWID`

`GETTID` identifica actualmente al thread residente (`warp_id * warp_size +
lane_id`), y `GETWARP` propuesto en §1.2 identifica el slot de warp dentro del
SM. Hace falta un valor independiente de esa ubicación física, asignado por
la CPU o por el monitor al preparar el lanzamiento.

| Opcode propuesto | Mnemónico | Formato | Operandos | Semántica |
|---|---|---|---|---|
| `0x36` | `GETWID` | I-Type | `Rd` | `Rd = warp_user_id` del warp actual |

Encoding: `X = Rd`, `Y = 0`, `imm16 = 0`. Devuelve los 32 bits sin extensión
ni interpretación de signo, iguales para todas las lanes del warp. Solo las
lanes activas escriben su registro destino.

Cada slot guarda un `warp_user_id` configurable de 32 bits: 256 bits para los
ocho warps actuales, además de la lógica de acceso. El lanzador lo escribe con
la GPU detenida, se conserva durante halt/resume y vale cero tras reset de GPU.
La dirección MMIO se decidirá al implementar; no se debe reutilizar sin más el
cuarto word del descriptor actual, que ya expone estado de solo lectura.

Es un dato del trabajo, distinto de `workgroup_id` (agrupación para barreras).
No afecta al scheduler, los tags de LSU ni a `BAR`. El hardware no exige IDs
únicos: el programa puede usarlo como número de tile, bloque, objeto o base.
Mover el trabajo a otro slot o SM debe conservar este valor al cargar su contexto.

```asm
GETWID  R1          ; ejemplo: base de elementos asignada por la CPU
GETLANE R2          ; 0..7, cuando se implemente §1.2
ADD     R3, R1, R2  ; índice del elemento de esta lane
```

Si el programa interpreta el ID como número de bloque de ocho elementos,
calcula `warp_user_id * 8 + lane_id`; si lo interpreta como base, lo suma
directamente. `GETWID` no impone ninguna de las dos fórmulas, no asigna trabajo
por sí solo ni equivale a un `GETGID` automático. No se cambia la semántica de
`GETTID`. En MiniCPU se propone devolver cero, como `GETTID`, al no haber warp.

---

## 2. Branches con inmediato

### 2.1 Por qué

Medido sobre los 228 `MOVI` del repositorio: **56 existen solo para fabricar la
constante de una comparación**, la categoría más numerosa con diferencia. Cada
uno cuesta una instrucción y ocupa un registro:

```asm
MOVI R2, 4
BLT  R1, R2, low        ; en vez de   BLTI R1, 4, low
```

### 2.2 Cuántos bits caben

I-Type ofrece 26 bits de operandos. `Ra` (5) más `offset16` (16) gastan 21, así
que **quedan exactamente 5 bits**, que es justo el campo `Y`. No hace falta
inventar formato:

```text
31          26 25    21 20    16 15                         0
┌─────────────┬────────┬────────┬─────────────────────────────┐
│   opcode    │   Ra   │  imm5  │          offset16           │
└─────────────┴────────┴────────┴─────────────────────────────┘
```

¿Bastan 5 bits? De las 56 constantes medidas:

- **55 de 56 (98 %) caben.**
- La más repetida es `4`, con 26 apariciones; luego `2`, `3`, `6`, `5`.
- Todas son `≤ 8` salvo una, `128`, que seguiría usando `MOVI` + `BGE`.

### 2.3 Propuesta

| Opcode | Mnemónico | Condición             |
|--------|-----------|-----------------------|
| `0x26` | `BEQI`    | `Ra == imm`           |
| `0x27` | `BNEI`    | `Ra != imm`           |
| `0x28` | `BLTI`    | `signed(Ra) < imm`    |
| `0x29` | `BGEI`    | `signed(Ra) >= imm`   |
| `0x2A` | `BLTUI`   | `Ra < imm`, unsigned  |
| `0x2B` | `BGEUI`   | `Ra >= imm`, unsigned |

**Extensión del inmediato**, que hay que fijar explícitamente porque es donde se
cometen los errores:

- En las variantes con signo (`BEQI`, `BNEI`, `BLTI`, `BGEI`) el `imm5` se
  **extiende con signo**: rango `-16..15`. Permite comparar contra cero y contra
  negativos pequeños, que es el caso del test de signo.
- En las variantes sin signo (`BLTUI`, `BGEUI`) se **extiende con ceros**: rango
  `0..31`. Comparar sin signo contra un negativo no tiene sentido.

`BEQI`/`BNEI` aparecen en ambas listas porque la igualdad no depende del signo;
se documentan como signo por coherencia con `BEQ`/`BNE`.

---

## 3. Llamadas y saltos indirectos

### 3.1 El problema del registro cero

MiniISA v0.1 dice que **los 32 registros son generales, incluido `R0`**. Eso
impide el truco de RISC-V, donde `jalr x0, ra, 0` sirve de retorno porque el
enlace se descarta en el registro cero.

Sin registro cero hacen falta **dos** instrucciones distintas: una que guarda el
enlace y otra que no. La alternativa es cablear `R0` a cero en v0.2, que es un
cambio mucho más invasivo y rompe cualquier programa que use `R0` como registro
general.

**Propongo no tocar `R0`** y pagar un opcode extra por `JR`. Es reversible: si
más adelante se decide cablear `R0`, `JR` se convierte en un alias.

### 3.2 Propuesta

| Opcode | Mnemónico | Formato | Operandos       | Semántica                         |
|--------|-----------|---------|-----------------|-----------------------------------|
| `0x2C` | `JAL`     | I-Type  | `Rd, label`     | `Rd = PC + 4`; salto relativo     |
| `0x2D` | `JALR`    | I-Type  | `Rd, Ra, imm16` | `Rd = PC + 4`; salto a `Ra + imm` |
| `0x2E` | `JR`      | I-Type  | `Ra`            | Salto a `Ra`, sin guardar enlace  |

Encodings:

```text
JAL   X = Rd,  Y = 0,   imm16 = offset relativo en palabras
JALR  X = Rd,  Y = Ra,  imm16 = desplazamiento en palabras
JR    X = 0,   Y = Ra,  imm16 = 0
```

Decisiones tomadas y por qué:

- **`JAL` es I-Type, no B-Type.** B-Type daría ±32 M palabras de alcance pero no
  tiene campo de registro, así que obligaría a un registro de enlace implícito.
  I-Type da `±32 768` palabras, o sea **±128 KiB**, muy por encima de cualquier
  programa que quepa en esta máquina, y deja el registro de enlace explícito.
- **El desplazamiento va en palabras**, como todo el control de flujo actual.
  Rompe la intuición de quien venga de RISC-V, donde `JALR` va en bytes, pero
  ser coherente dentro de la propia ISA vale más que parecerse a otra.
- **`RET` no es un opcode**, es un alias del ensamblador para `JR R31`.

### 3.3 Convención de llamada

No forma parte de la ISA, pero conviene fijarla en el ensamblador para que las
funciones sean interoperables:

| Registro | Uso |
|---|---|
| `R31` | Dirección de retorno (`link`) |
| `R30` | Puntero de pila, cuando exista |

Los accesos por byte y media palabra también sirven para datos empaquetados.
Las escrituras `STOREB` y `STOREH` se proponen en §4.4; las cargas de esos
tamaños quedan para una ampliación posterior. Una pila de palabras puede usar
los `LOAD`/`STORE` actuales.

### 3.4 Aviso serio: saltos indirectos y divergencia

Esto es lo que más cuidado requiere de toda la propuesta.

En una máquina SIMT, `JALR`/`JR` pueden producir **tantos destinos distintos
como lanes activas**. La maquinaria actual de `SSY` está construida para
divergencias de **dos** caminos: una `REGION` con un fall-through y una pila de
`PATH`. Un salto indirecto con 8 destinos distintos no encaja ahí.

Las tres salidas posibles:

1. **Exigir destino uniforme.** Si las lanes activas no calculan el mismo
   destino, `ERROR_SIMT`. Es lo más simple, se implementa comparando el destino
   de las lanes activas, y cubre el caso real de las llamadas a función, donde
   el destino suele ser uniforme.
2. Serializar por destinos distintos, como hace el hardware real. Es
   considerablemente más trabajo y toca el scheduler.
3. Definir `JALR` como instrucción **escalar por warp**, que lee el registro de
   una lane designada.

**Recomiendo la opción 1** para v0.2, dejando la 2 como evolución. Y sobre todo:
que quede escrito en la ISA, porque un `JALR` divergente con semántica sin
definir es exactamente el tipo de agujero que aparece dos años después.

En MiniCPU no hay ningún problema: una sola lane, destino siempre uniforme.

---

## 4. Desplazamientos y rotaciones

### 4.1 Qué hay hoy

`SHL` (`0x07`), `SHR` (`0x08`) y `SAR` (`0x09`), todas R-Type, con la cantidad
en **los cinco bits bajos de `Rb`**.

**No hay rotaciones.** Ni `ROL` ni `ROR`.

### 4.2 Desplazamiento con inmediato

Medido: 12 sitios en el repositorio hacen `MOVI` + `SHL`. Menos que los
branches, pero el patrón es sistemático: casi siempre `MOVI Rk, 2` para
convertir un índice en desplazamiento de bytes.

Hay dos formas de darle inmediato, y la elección **no es de estilo**, es de
presupuesto de opcodes:

**Opción A — tres opcodes nuevos** (`SHLI`, `SHRI`, `SARI`) en `0x18–0x1A`.
Limpio y obvio. Pero la familia `0x10–0x1F` solo tiene 8 libres y ya hay cola:

| Pendiente | Opcodes |
|---|---:|
| `LOADB`, `LOADUB` (futuras), `STOREB` (§4.4) | 3 |
| `SHLI`, `SHRI`, `SARI` | 3 |
| `LOADH`, `LOADUH` (futuras), `STOREH` (§4.4) | 3 |
| **Total** | **9 sobre 8 disponibles** |

O sea que la opción A **no cabe** si además se quieren accesos de media palabra.

**Opción B — un bit en `extra`.** `SHL`/`SHR`/`SAR` son R-Type y su campo
`extra` son 11 bits que hoy deben valer cero. Basta un bit como "modo
inmediato", con la cantidad en el propio campo `Rb`, que ya es de 5 bits y ya se
usa como cantidad:

```text
31          26 25    21 20    16 15    11 10   9              0
┌─────────────┬────────┬────────┬────────┬───┬────────────────┐
│   opcode    │   Rd   │   Ra   │ Rb/imm │ I │       0        │
└─────────────┴────────┴────────┴────────┴───┴────────────────┘
                                            ↑ 1 = la cantidad es inmediata
```

Coste: **cero opcodes**. Contra: rompe la regla de que `extra` es siempre cero,
así que la comprobación de encoding pasa a ser distinta para esos tres opcodes,
y `ERROR_INVALID_ENCODING` deja de ser "todo `extra` a cero" para ellos.

**Recomiendo la opción B**, precisamente porque la familia de inmediatos es la
única con presión real y los accesos por bytes tienen más valor que la elegancia
del decodificador.

### 4.3 Rotaciones: no las añadiría

Uso medido en el repositorio: **cero**. Ni una rotación en `mandelbrot`, ni en
los kernels, ni en los tests.

Las rotaciones son valiosas en criptografía y hashing, que no es la carga de
trabajo de esta máquina. Y `ROR` se sintetiza con cuatro instrucciones, tres si
la cantidad es constante y se precalcula su complemento:

```asm
MOVI Rt, 32
SUB  Rt, Rt, Rn        ; 32 - n
SHL  Rt, Ra, Rt
SHR  Rd, Ra, Rn
OR   Rd, Rd, Rt        ; Rd = ROR(Ra, n)
```

Si algún día hacen falta rotaciones, necesitarán una suboperación adicional:
el bit de inmediato distingue registro/inmediato, no desplazamiento/rotación.
Podrían incorporarse a la extensión de §5.2. No se asignan ahora.

### 4.4 Escrituras de 8 y 16 bits

Añadir dos instrucciones para escribir elementos individuales de un framebuffer:
índices de paleta de 8 bits y píxeles RGB565 de 16 bits. También sirven para
texto y otros datos empaquetados; no tienen semántica específica de gráficos.

| Opcode propuesto | Mnemónico | Formato | Operandos | Operación |
|---|---|---|---|---|
| `0x1A` | `STOREB` | I-Type | `Rs, Ra, imm16` | Escribe `Rs[7:0]` |
| `0x1D` | `STOREH` | I-Type | `Rs, Ra, imm16` | Escribe `Rs[15:0]` |

Se mantiene el formato de `STORE`: `X = Rs`, `Y = Ra`, `imm16` es un
desplazamiento **en bytes**, con signo, de `-32768` a `32767`. La dirección
efectiva es `R[Ra] + sign_extend(imm16)`, con aritmética de 32 bits.
Los registros siguen siendo de 32 bits y los bits altos de `Rs` se ignoran.

- **`STOREB`** admite cualquier dirección de byte válida y modifica solo ese byte.
- **`STOREH`** exige dirección par. Escribe en little-endian: `Rs[7:0]` en
  `address` y `Rs[15:8]` en `address + 1`.
- Los bytes vecinos se conservan. Debe validarse el intervalo completo antes de
  emitir la escritura; un acceso fuera de rango o desalineado produce
  `ERROR_MEMORY_ACCESS`, igual que `STORE`.
- `STORE` (`0x16`) conserva su escritura de 32 bits y alineación de cuatro bytes.

```asm
STOREB R1, R2, 0     ; índice de paleta: un byte
STOREH R3, R4, 0     ; píxel RGB565: dos bytes, dirección par
```

En la GPU solo escriben las lanes activas. Se conservan los tags, los errores
por lane y la respuesta de finalización: aceptar la petición no equivale a
terminar el STORE. `BAR` debe esperar también estas escrituras. No se añaden
operaciones atómicas ni garantías de orden entre warps con escrituras solapadas.

La frontera SM↔LSU debe transportar el tamaño (8, 16 o 32 bits), común a la
instrucción del warp. En SDRAM, `STOREB` usa una transferencia de 16 bits con
una sola máscara de byte habilitada; `STOREH` usa una transferencia con ambas
habilitadas. Así se preservan los vecinos sin una lectura-modificación-escritura.
El backend EBR necesitará habilitaciones de escritura por byte equivalentes.

Las cargas de tamaño reducido se incluyen como candidatas en §5.1 y su espacio
se contabiliza en el mapa ampliado de §6. `PACK565` también se estudia allí como
operación separada: los stores escriben el valor ya empaquetado.

---

## 5. Operaciones candidatas para 2D y 3D

Estas operaciones son propuestas de evolución, no instrucciones implementadas.
El mapa siguiente contempla todas para comprobar capacidad de codificación;
no implica construir todas las unidades funcionales a la vez. Caber en la ISA
no garantiza caber en FPGA ni mejorar ciclos: se medirán kernels y timing.

### 5.1 Operaciones y utilidad

| Instrucción | Operación propuesta | Aplicación |
|---|---|---|
| `LOADB`, `LOADUB` | Leer 8 bits y extender con signo/ceros a 32 bits | Datos empaquetados, índices de textura y paleta |
| `LOADH`, `LOADUH` | Leer 16 bits y extender con signo/ceros a 32 bits | RGB565, coordenadas o profundidad empaquetada |
| `MIN`, `MAX` | Mínimo/máximo signed32 de dos registros | Recorte de coordenadas, cajas de triángulos, límites |
| `MINU`, `MAXU` | Mínimo/máximo unsigned32 | Colores, índices y profundidad sin signo |
| `SEL` | Elegir entre dos registros según un tercer registro | Selección sin bifurcación SIMT |
| `MACFX` | Acumular el producto Q16.16 de dos registros | Transformaciones, productos escalares e interpolación |
| `RCPFX` | Aproximación de `1/x` en Q16.16 | Perspectiva y reutilización de un divisor |
| `RSQRTFX` | Aproximación de `1/sqrt(x)` en Q16.16 | Normalización de vectores e iluminación |
| `PACK565` | Convertir `0x00RRGGBB` a RGB565 | Escritura de un color calculado en RGB888 |

Las cargas mantienen I-Type: `X = Rd`, `Y = Ra`, offset16 con signo en bytes.
`LOADB`/`LOADUB` admiten cualquier byte; `LOADH`/`LOADUH` exigen dirección par.
Debe validarse el intervalo completo; rango y alineación producen
`ERROR_MEMORY_ACCESS`, igual que las escrituras. `LOAD` de 32 bits no cambia.

Para `MACFX Rd, Ra, Rb`, la semántica propuesta es equivalente a multiplicar
con el `MULFX` actual y sumar al valor anterior de `Rd`, con wrap de 32 bits:

```text
product = signed64(signed32(Ra) * signed32(Rb))
Rd = u32(old_Rd + u32(product >> 16))   ; desplazamiento aritmético
```

No se introduce un acumulador oculto de 64 bits ni redondeo fusionado. Se leen
los valores anteriores de todos los operandos, también si coinciden registros.
El banco actual tiene dos puertos de lectura: `MACFX` y `SEL` requieren leer un
tercer valor mediante otro ciclo o una ampliación del banco. No se promete
latencia de un ciclo ni un multiplicador nuevo por lane.

`PACK565 Rd, Ra` produce los 16 bits bajos RGB565 y pone a cero los 16 altos:

```text
Rd = ((Ra >> 8) & 0xF800) | ((Ra >> 5) & 0x07E0) | ((Ra >> 3) & 0x001F)
```

`RCPFX` y `RSQRTFX` requieren todavía fijar rango, error máximo, redondeo,
saturación/desbordamiento y errores de dominio (cero y, para raíz, negativos).
Hasta cerrar esos contratos y sus referencias de prueba, se reserva su encoding
pero no se consideran listas para implementar. `DIV` entero no sustituye por sí
solo estas operaciones Q16.16. Una tabla más refinamiento es una posibilidad a medir.

Prioridad recomendada: cargas pequeñas y `MIN/MAX`, después `SEL`/`MACFX`;
recíproco, raíz inversa y empaquetado según perfiles de las demos. No se añaden
por ahora instrucciones de muestreo/filtrado de texturas, seno/coseno, productos
vectoriales completos ni mezcla de color empaquetado. Las tablas y las
instrucciones existentes permiten evaluar primero esas necesidades.

### 5.2 Codificación extendida propuesta: `EXT` en `0x1E`

Para evitar consumir un opcode principal por cada operación gráfica, se propone
un opcode de extensión `0x1E`, con formato de registros y suboperación. Es una
excepción explícita a la clasificación por los dos bits altos: el decodificador
no debe tratar toda la familia `01xxxx` como I-Type.

```text
31       26 25   21 20   16 15   11 10    6 5          0
+----------+-------+-------+-------+-------+------------+
| EXT=0x1E |  Rd   |  Ra   |  Rb   |  Rc   |   func6    |
+----------+-------+-------+-------+-------+------------+
```

Son 32 bits: 6 de opcode, cuatro campos de registro de 5 bits y 6 de función.
En el R-Type habitual, los once bits bajos se llaman `extra`; solo para `EXT`
se interpretan como `Rc + func6`. Las instrucciones existentes no cambian.
`EXT` es la familia de encoding; el ensamblador expone los mnemónicos siguientes:

| `func6` | Mnemónico | Operandos | Campos reservados / condición |
|---|---|---|---|
| `0x00` | `MIN` | `Rd, Ra, Rb` | `Rc = 0` |
| `0x01` | `MAX` | `Rd, Ra, Rb` | `Rc = 0` |
| `0x02` | `MINU` | `Rd, Ra, Rb` | `Rc = 0` |
| `0x03` | `MAXU` | `Rd, Ra, Rb` | `Rc = 0` |
| `0x04` | `SEL` | `Rd, Ra, Rb, Rc` | `Rd = (Rc != 0) ? Ra : Rb` |
| `0x05` | `MACFX` | `Rd, Ra, Rb` | `Rc = 0`; acumulador es el valor anterior de `Rd` |
| `0x06` | `RCPFX` | `Rd, Ra` | `Rb = Rc = 0`; contrato numérico pendiente |
| `0x07` | `RSQRTFX` | `Rd, Ra` | `Rb = Rc = 0`; contrato numérico pendiente |
| `0x08` | `PACK565` | `Rd, Ra` | `Rb = Rc = 0` |
| `0x09–0x3F` | Reservadas | — | 55 suboperaciones disponibles |

En la tabla, `Rc != 0` comprueba el contenido del registro, no su número.
El campo reservado `Rc = 0` no implica que el registro R0 esté cableado a cero:
simplemente no se lee ese operando. Los campos reservados no nulos producen
`ERROR_INVALID_ENCODING`; una función no implementada o reservada produce
`ERROR_INVALID_OPCODE`. Todas las operaciones respetan la máscara activa y no
alteran las máscaras SIMT. `SEL` selecciona datos, sin ejecutar un salto.

### 5.3 ¿Cabrían con opcodes independientes?

Sí, este conjunto concreto cabe, pero agotaría el espacio principal. Partiendo
del mapa con `STOREB`/`STOREH` había 14 libres: `GETWID` consume 1, las cuatro
cargas consumen 4 y las nueve operaciones de la tabla EXT consumen 9 si cada
una usa opcode propio. Resultado: **0 libres**, contando como ocupados los
opcodes ya reservados para aritmética, y sin espacio para voto/intercambio SIMT.

Con `EXT`, esas nueve operaciones consumen un solo opcode principal. Quedan
**8 opcodes principales y 55 suboperaciones EXT libres**. Este es el mapa
recomendado a continuación; no mezcla ambas alternativas de codificación.

---

## 6. Mapa de opcodes resultante

### ALU y aritmética `0x00–0x0F`

Sin cambios. Sigue llena, con `MULHI`, `DIVU`, `REM` y `REMU` reservadas.

### Inmediatos y memoria `0x10–0x1F`

| Opcode | Propuesta |
|---|---|
| `0x10–0x17` | Sin cambios, incluidos `LOAD` y `STORE` de 32 bits |
| `0x18` | `LOADB`, carga signed de 8 bits |
| `0x19` | `LOADUB`, carga unsigned de 8 bits |
| `0x1A` | **`STOREB`**, escritura de 8 bits |
| `0x1B` | `LOADH`, carga signed de 16 bits |
| `0x1C` | `LOADUH`, carga unsigned de 16 bits |
| `0x1D` | **`STOREH`**, escritura de 16 bits |
| `0x1E` | `EXT`, nueve suboperaciones propuestas en §5.2 |
| `0x1F` | Libre |

Queda **1 libre** (`0x1F`) al incluir todas las candidatas de §5. El mapa usa la opción B para los desplazamientos inmediatos; la
opción A entra en conflicto con `STOREB` en `0x1A`.

### Control de flujo `0x20–0x2F`

| Opcode      | Antes        | Ahora                                            |
|-------------|--------------|--------------------------------------------------|
| `0x20–0x25` | `BEQ`…`BGEU` | sin cambios                                      |
| `0x26–0x2B` | libres       | `BEQI`, `BNEI`, `BLTI`, `BGEI`, `BLTUI`, `BGEUI` |
| `0x2C`      | libre        | `JAL`                                            |
| `0x2D`      | libre        | `JALR`                                           |
| `0x2E`      | libre        | `JR`                                             |
| `0x2F`      | `BRA`        | sin cambios                                      |

**La familia queda completa.** Es la consecuencia más incómoda de la propuesta:
después de esto, cualquier instrucción de control de flujo nueva necesita
buscar hueco en otra familia o reorganizar el mapa.

Si preocupa, la palanca más barata es **posponer `JR`** y cablear `R0` a cero en
alguna versión futura, con lo que `JR Ra` sería `JALR R0, Ra, 0`. Deja `0x2E`
libre a cambio de un cambio incompatible más adelante.

### Sistema y SIMT `0x30–0x3F`

| Opcode      | Antes de corregir §0 | Ahora (real y propuesto)                            |
|-------------|---------------------|-----------------------------------------------------|
| `0x30`      | `GETTID`            | `GETTID`                                            |
| `0x31`      | `GETLANE` ❌         | **`SSY`**                                           |
| `0x32`      | `GETWARP` ❌         | **`BAR`**                                           |
| `0x33`      | `BAR` ❌             | **`EXIT`**                                          |
| `0x34`      | libre               | `GETLANE`                                           |
| `0x35`      | libre               | `GETWARP`                                           |
| `0x36` | libre | `GETWID`, ID lógico configurable del warp |
| `0x37–0x3D` | libres | libres, candidatas a voto e intercambio entre lanes |
| `0x3E`      | `TRAP`              | `TRAP`                                              |
| `0x3F`      | `HALT`              | `HALT`                                              |

Quedan **7 libres** (`0x37–0x3D`).

### Recuento

| Familia                | Libres antes | Libres después |
|------------------------|-------------:|---------------:|
| ALU `0x00–0x0F`        |            0 |              0 |
| Inmediatos/extensión `0x10–0x1F` |     8 |              1 |
| Control `0x20–0x2F`    |            9 |          **0** |
| Sistema `0x30–0x3F`    |           10 |              7 |
| **Total**              |       **27** |          **8** |

---

## 7. Decisiones que hay que tomar

Decisiones de diseño pendientes de aprobación antes de implementar:

1. **¿Se cablea `R0` a cero?** Afecta a `JR` y a toda la ISA. Decidirlo ahora
   evita arrastrar un opcode que luego sobra.
2. **Opción A o B para los desplazamientos inmediatos.** Es elegir entre un
   decodificador limpio y tres opcodes de la familia con más presión.
3. **Semántica de `JALR` divergente.** Recomiendo exigir destino uniforme, pero
   hay que escribirlo.
4. **¿Se reserva ya espacio para voto e intercambio entre lanes** en
   `0x37–0x3D`, o se reparte según haga falta?
5. **¿El desplazamiento de `JAL`/`JALR` va en palabras o en bytes?** Propongo
   palabras por coherencia interna.
6. **Aprobar `EXT` y los contratos de §5.** En particular precisión y casos
   excepcionales de `RCPFX`/`RSQRTFX`, y coste del tercer operando.
7. **Asignar la ventana MMIO de `warp_user_id`.** Mantener los descriptores
   existentes compatibles y configurar el valor antes del lanzamiento.

---

## 8. Qué habría que tocar

| Componente                       | Trabajo                                                          |
|----------------------------------|------------------------------------------------------------------|
| `1.isa/isa.md`                   | Documentar lo nuevo; corrección SIMT ya aplicada                    |
| `1.isa/miniisa_asm.py`           | Mnemónicos, encodings, alias `RET`, validación de `imm5`         |
| `2.cpu-sim-func/minicpu_sim.py`  | Branches con inmediato, `JAL`/`JALR`/`JR`, shifts inmediatos     |
| `11.gpu-sim-func/minigpu_sim.py` | Lo mismo, más `GETLANE`/`GETWARP` y la regla de destino uniforme |
| `6.fpga-cpu`, `10.fpga-cpu-ram`  | Decodificador y control                                          |
| `12.fpga-gpu`                    | Decodificador, control y la comprobación de uniformidad          |
| `14.fpga-gpu-ram`                | Decodificar `STOREB`/`STOREH`, transportar tamaño SM↔LSU y emitir máscaras SDRAM |
| `x.cpu-tests`                    | Un caso por instrucción nueva, con los valores frontera          |

Para `STOREB`/`STOREH`, el ensamblador y ambos simuladores deben incorporar los
dos opcodes y su semántica. Los backends FPGA que los implementen deben adaptar
también las máscaras y la validación de direcciones. Las pruebas deben cubrir
bytes pares/impares, las dos mitades de una palabra, conservación de vecinos,
truncado de los bits altos, offsets negativos, límites de memoria, desalineación
de `STOREH`, máscaras de lanes y finalización antes de `BAR`.

Para `GETWID`: añadir configuración por warp en monitor/CPU y simulador,
almacenamiento en el SM, lectura por la instrucción y pruebas de reset,
halt/resume, valores de 32 bits, uniformidad entre lanes y cambio de slot
conservando el ID lógico. `GETTID` y las barreras deben mantener su comportamiento.

Para las operaciones de §5: extender ensamblador, validación de encoding,
simuladores y datapaths; adaptar LSU para tamaño y extensión de cargas. Probar
funciones EXT no implementadas, campos reservados, alias de registros, valores
con/sin signo, equivalencia de `MACFX` a `MULFX`+`ADD`, colores RGB565 y casos
numéricos límite. Medir ciclos y recursos antes/después: reducir instrucciones
no garantiza acelerar un kernel. Ninguna de estas ampliaciones se implementa
como parte de esta edición documental.

La corrección documental del bloque SIMT (§0) **ya está aplicada**. El resto
de las ampliaciones sigue siendo una propuesta; no se ha modificado código
para implementarlas.
