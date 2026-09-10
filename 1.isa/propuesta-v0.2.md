# Propuesta de MiniISA v0.2

Borrador para discusión. Cubre cinco bloques:

1. Corregir el bloque SIMT, que hoy **no coincide con la implementación**.
2. Branches con inmediato.
3. Llamadas y saltos indirectos: `JAL`, `JALR`, `JR`.
4. Desplazamientos con inmediato y rotaciones.
5. El mapa de opcodes resultante y lo que queda libre.

Nada de esto rompe programas existentes: todo son opcodes hoy reservados, salvo
la corrección del bloque SIMT, que alinea el documento con lo que ya se ejecuta.

---

## 0. Punto de partida: `isa.md` miente en el bloque SIMT

`isa.md` dice, en §3, que debe tratarse como error cualquier discrepancia entre
el documento y el código. Hay tres:

| Opcode | `isa.md` documenta | Ensamblador y simuladores usan |
|--------|--------------------|--------------------------------|
| `0x31` | `GETLANE`          | **`SSY`**                      |
| `0x32` | `GETWARP`          | **`BAR`**                      |
| `0x33` | `BAR`              | **`EXIT`**                     |

`GETLANE` y `GETWARP` no existen en ninguna parte del repositorio. `BAR` está
documentada en el opcode equivocado. Quien implemente hardware leyendo `isa.md`
lo hará mal, y ya hay tests que dependen del comportamiento real: `BAR` en
`0x32` es lo que valida `simt/barriers/ssy-bar-partial-mask`.

**Esto hay que arreglarlo aunque se rechace todo lo demás de esta propuesta.**

---

## 1. Bloque SIMT

### 1.1 Documentar lo que ya existe

| Opcode | Mnemónico | Formato    | Operandos | Semántica                                              |
|--------|-----------|------------|-----------|--------------------------------------------------------|
| `0x30` | `GETTID`  | I-Type     | `Rd`      | Identificador lineal del work-item                     |
| `0x31` | `SSY`     | **B-Type** | `label`   | Abre una región de reconvergencia cuyo join es `label` |
| `0x32` | `BAR`     | I-Type     | —         | Barrera; exige que participen todas las lanes vivas    |
| `0x33` | `EXIT`    | I-Type     | —         | Retira la lane permanentemente                         |

`SSY` usa B-Type con `offset26` en palabras, exactamente igual que `BRA`. Es un
detalle que hoy no está escrito en ningún sitio y que sí está en el
ensamblador.

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
repartir `0x36–0x3D`: operaciones de voto entre lanes (`BALLOT`, `ANY`, `ALL`)
y de intercambio (`SHFL`). Son el siguiente escalón natural de una ISA SIMT y
consumirán varios opcodes; reservar espacio ahora es más barato que buscarlo
después.

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

La pila necesitará además `LOADB`/`STOREB` y probablemente accesos de media
palabra; eso ya está en el TODO y es independiente de esta propuesta.

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
| `LOADB`, `LOADUB`, `STOREB` (ya en el TODO) | 3 |
| `SHLI`, `SHRI`, `SARI` | 3 |
| Media palabra (`LOADH`, `LOADUH`, `STOREH`), si llega | 3 |
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

Si algún día hacen falta, el mismo bit de `extra` de la opción B da sitio a
`ROR`/`ROL` sin gastar opcodes, o quedan `0x1E`/`0x1F`. Anotarlo y seguir.

---

## 5. Mapa de opcodes resultante

### ALU y aritmética `0x00–0x0F`

Sin cambios. Sigue llena, con `MULHI`, `DIVU`, `REM` y `REMU` reservadas.

### Inmediatos y memoria `0x10–0x1F`

Sin cambios en esta propuesta. Quedan **8 libres** (`0x18–0x1F`) para los
accesos por byte y media palabra del TODO, gracias a resolver los
desplazamientos con la opción B.

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

| Opcode      | Antes (documentado) | Ahora (real y propuesto)                            |
|-------------|---------------------|-----------------------------------------------------|
| `0x30`      | `GETTID`            | `GETTID`                                            |
| `0x31`      | `GETLANE` ❌         | **`SSY`**                                           |
| `0x32`      | `GETWARP` ❌         | **`BAR`**                                           |
| `0x33`      | `BAR` ❌             | **`EXIT`**                                          |
| `0x34`      | libre               | `GETLANE`                                           |
| `0x35`      | libre               | `GETWARP`                                           |
| `0x36–0x3D` | libres              | libres, candidatas a voto e intercambio entre lanes |
| `0x3E`      | `TRAP`              | `TRAP`                                              |
| `0x3F`      | `HALT`              | `HALT`                                              |

Quedan **8 libres**.

### Recuento

| Familia                | Libres antes | Libres después |
|------------------------|-------------:|---------------:|
| ALU `0x00–0x0F`        |            0 |              0 |
| Inmediatos `0x10–0x1F` |            8 |              8 |
| Control `0x20–0x2F`    |            9 |          **0** |
| Sistema `0x30–0x3F`    |           10 |              8 |
| **Total**              |       **27** |         **16** |

---

## 6. Decisiones que hay que tomar

Ninguna de estas la puedo decidir yo:

1. **¿Se cablea `R0` a cero?** Afecta a `JR` y a toda la ISA. Decidirlo ahora
   evita arrastrar un opcode que luego sobra.
2. **Opción A o B para los desplazamientos inmediatos.** Es elegir entre un
   decodificador limpio y tres opcodes de la familia con más presión.
3. **Semántica de `JALR` divergente.** Recomiendo exigir destino uniforme, pero
   hay que escribirlo.
4. **¿Se reserva ya espacio para voto e intercambio entre lanes** en
   `0x36–0x3D`, o se reparte según haga falta?
5. **¿El desplazamiento de `JAL`/`JALR` va en palabras o en bytes?** Propongo
   palabras por coherencia interna.

---

## 7. Qué habría que tocar

| Componente                       | Trabajo                                                          |
|----------------------------------|------------------------------------------------------------------|
| `1.isa/isa.md`                   | Corregir el bloque SIMT y documentar lo nuevo                    |
| `1.isa/miniisa_asm.py`           | Mnemónicos, encodings, alias `RET`, validación de `imm5`         |
| `2.cpu-sim-func/minicpu_sim.py`  | Branches con inmediato, `JAL`/`JALR`/`JR`, shifts inmediatos     |
| `11.gpu-sim-func/minigpu_sim.py` | Lo mismo, más `GETLANE`/`GETWARP` y la regla de destino uniforme |
| `6.fpga-cpu`, `10.fpga-cpu-ram`  | Decodificador y control                                          |
| `12.fpga-gpu`                    | Decodificador, control y la comprobación de uniformidad          |
| `x.cpu-tests`                    | Un caso por instrucción nueva, con los valores frontera          |

La corrección del bloque SIMT (§0) es independiente del resto y **se puede hacer
hoy**: no cambia ni una línea de código, solo alinea el documento con lo que ya
se ejecuta y está cubierto por tests.
