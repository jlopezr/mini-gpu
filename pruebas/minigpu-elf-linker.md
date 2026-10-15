# MiniGPU: ELF, relocations, linker y carga de programas

## 1. Objetivo

El objetivo es sustituir el uso de una imagen `.bin` completamente plana por una toolchain basada en ELF, sin rehacer el compilador ni depender de un linker grande como GNU `ld` o LLVM `lld`.

La situación de partida es:

- El backend de **LCC para MiniGPU ya está terminado**.
- El compilador genera ensamblador MiniGPU.
- La toolchain actual puede producir una imagen binaria raw.
- El problema del `.bin` es que representa una imagen plana de memoria:
  - los huecos entre regiones pueden ocupar espacio en el fichero;
  - la `.bss` no contiene datos útiles pero necesita aparecer como memoria inicializada a cero;
  - no existe información estructurada de símbolos, secciones, punto de entrada o regiones cargables.

La propuesta es mantener LCC y evolucionar únicamente la parte final de la toolchain:

```text
C
│
▼
LCC MiniGPU
│
▼
ASM MiniGPU
│
▼
Assembler MiniGPU
│
▼
ELF32 ET_REL (.o)
│
▼
Linker MiniGPU en Python
│
▼
ELF32 ET_EXEC
│
▼
Uploader
│
├── WRITE de los bytes reales
├── ZERO de la BSS
└── RUN en el entry point
```

---

## 2. Por qué ELF

ELF permite separar tres conceptos que en un `.bin` raw quedan mezclados:

1. **Lo que existe en el fichero.**
2. **Lo que debe existir en memoria.**
3. **Dónde debe cargarse.**

En particular, un segmento cargable ELF (`PT_LOAD`) contiene:

```text
p_offset   offset en el fichero
p_vaddr    dirección virtual
p_paddr    dirección física
p_filesz   bytes presentes en el fichero
p_memsz    bytes ocupados en memoria
```

Para una región que contiene `.data + .bss`:

```text
p_filesz = tamaño real de .data
p_memsz  = tamaño de .data + tamaño de .bss
```

Por tanto:

```text
BSS = p_memsz - p_filesz
```

El uploader no necesita transmitir esos ceros.

Puede hacer:

```text
WRITE p_paddr, p_filesz, <datos del ELF>
ZERO  p_paddr + p_filesz, p_memsz - p_filesz
```

Esto resuelve directamente el problema que motivó el cambio desde `.bin`.

---

## 3. Alcance propuesto

No se pretende implementar ELF completo ni un linker general de propósito universal.

Se define un subconjunto controlado por MiniGPU.

### Entrada del linker

```text
ELF32
Little endian
ET_REL
```

Secciones inicialmente necesarias:

```text
.text
.rodata
.data
.bss
.symtab
.strtab
.rela.text
.rela.rodata
.rela.data
```

Opcionalmente:

```text
COMMON / SHN_COMMON
```

### Salida del linker

```text
ELF32
Little endian
ET_EXEC
```

Con un número pequeño de segmentos `PT_LOAD`.

Una configuración inicial razonable sería:

```text
PT_LOAD RX   -> .text + .rodata
PT_LOAD RW   -> .data + .bss
```

También sería posible empezar con un único segmento si la plataforma no necesita permisos separados.

---

## 4. División de responsabilidades

### 4.1 LCC

LCC no cambia conceptualmente.

Continúa haciendo:

```text
C -> ASM MiniGPU
```

No necesita saber nada del ELF ejecutable final.

---

### 4.2 Assembler MiniGPU

El assembler pasa a producir objetos relocatables:

```text
foo.s -> foo.o
```

El `.o` será:

```text
ELF32 ET_REL
```

El assembler es responsable de:

- codificar instrucciones;
- crear secciones;
- crear la tabla de símbolos;
- resolver labels locales cuando sea posible;
- generar relocations cuando el valor final dependa del linker.

Ejemplo:

```asm
MOVHI r5, foo@hi
ORI   r5, r5, foo@lo
```

Si `foo` no se conoce todavía, el assembler deja el campo inmediato provisionalmente vacío y genera las relocations correspondientes.

---

## 5. Relocations mínimas

La ISA MiniGPU permite mantener un conjunto de relocations muy pequeño.

Propuesta inicial:

```c
enum {
    R_MINIGPU_NONE     = 0,
    R_MINIGPU_32       = 1,
    R_MINIGPU_HI16     = 2,
    R_MINIGPU_LO16     = 3,
    R_MINIGPU_PCREL16  = 4,
    R_MINIGPU_PCREL26  = 5,   /* reservado inicialmente */
};
```

El conjunto realmente necesario para una primera versión sería:

```text
R_MINIGPU_32
R_MINIGPU_HI16
R_MINIGPU_LO16
R_MINIGPU_PCREL16
```

`R_MINIGPU_PCREL26` puede reservarse y añadirse cuando aparezca un caso real.

---

## 6. Notación de relocations

Se usa la notación ELF habitual:

```text
S = dirección final del símbolo
A = addend
P = dirección del lugar que contiene la relocation
```

---

## 7. R_MINIGPU_32

Se usa para valores absolutos de 32 bits.

Fórmula:

```text
value = S + A
```

Ejemplo en C:

```c
int foo;
int *p = &foo;
```

La palabra almacenada en `.data` para inicializar `p` necesita contener la dirección final de `foo`.

La entrada de relocation sería conceptualmente:

```text
type   = R_MINIGPU_32
symbol = foo
addend = 0
```

El linker escribe:

```text
S + A
```

como una palabra de 32 bits.

También sirve para:

- tablas de punteros;
- tablas de punteros a función;
- estructuras con direcciones estáticas.

---

## 8. R_MINIGPU_HI16 y R_MINIGPU_LO16

Se utilizan para materializar una dirección de 32 bits mediante:

```asm
MOVHI rX, symbol@hi
ORI   rX, rX, symbol@lo
```

Para:

```text
V = S + A
```

se define:

```text
R_MINIGPU_HI16 = (V >> 16) & 0xffff
R_MINIGPU_LO16 = V & 0xffff
```

Una referencia a un global podría quedar como:

```asm
MOVHI r5, foo@hi
ORI   r5, r5, foo@lo
LOAD  r6, r5, 0
```

El assembler genera dos relocations sobre el mismo símbolo.

### Ventaja de MiniGPU

Si `ORI` usa un inmediato zero-extended, no hace falta ninguna corrección especial entre la parte alta y baja.

El cálculo es literalmente:

```text
HI = value >> 16
LO = value & 0xffff
```

No es necesario introducir la lógica de carry que aparece en algunas otras ISAs con pares HI/LO.

---

## 9. R_MINIGPU_PCREL16

Se utiliza para saltos o llamadas PC-relative cuyo destino no puede resolver el assembler.

El caso principal es una llamada a una función definida en otro objeto.

Ejemplo:

```asm
JAL r31, printf
```

Si la semántica de `JAL` es:

```text
target = PC + 4 + sign_extend(imm16) * 4
```

el linker calcula:

```text
delta = S + A - (P + 4)
```

y después:

```text
imm16 = delta >> 2
```

Antes de parchear debe comprobar:

```text
delta % 4 == 0
```

y:

```text
-32768 <= delta / 4 <= 32767
```

Si no cabe:

```text
relocation truncated: R_MINIGPU_PCREL16
```

La primera versión del linker no necesita implementar trampolines ni veneers.

---

## 10. R_MINIGPU_PCREL26

Puede reservarse para instrucciones con un desplazamiento PC-relative mayor, por ejemplo `BRA` o `SSY`, si en algún momento aparecen referencias entre objetos.

Fórmula conceptual:

```text
value = (S + A - (P + 4)) >> 2
```

Pero no es imprescindible en la primera versión si esas instrucciones sólo saltan a labels locales.

---

## 11. Qué NO necesita relocation

Una propiedad importante es que muchos saltos internos pueden resolverse completamente en el assembler.

Por ejemplo:

```asm
    BEQ r1, r2, .L23
    ...
.L23:
```

La distancia entre ambas instrucciones no cambia al recolocar la sección `.text`.

El assembler puede resolver el desplazamiento directamente.

Lo mismo puede ocurrir con:

```text
BNE
BLT
BGE
BRA
SSY
```

cuando el destino pertenece al mismo objeto y puede resolverse localmente.

Esto mantiene pequeño el conjunto de relocations del linker.

---

## 12. LOAD/STORE de globales

No hace falta una relocation específica para el inmediato de `LOAD` o `STORE`.

Una dirección global se materializa primero en un registro:

```asm
MOVHI r5, foo@hi
ORI   r5, r5, foo@lo
LOAD  r6, r5, 0
```

Por tanto, inicialmente no hacen falta relocations como:

```text
R_MINIGPU_ABS16
R_MINIGPU_GPREL16
```

Una futura ABI con `GP` y "small data" sí podría justificar algo como:

```text
R_MINIGPU_GPREL16
```

pero sería una optimización posterior.

---

## 13. Preferir RELA frente a REL

Para una arquitectura nueva es recomendable usar relocations ELF de tipo `RELA`.

Las entradas `RELA` contienen:

```c
r_offset
r_info
r_addend
```

El addend está almacenado explícitamente.

Esto hace que el linker pueda trabajar siempre con:

```text
S + A
```

o:

```text
S + A - P
```

sin tener que reconstruir `A` leyendo los bits ya codificados en la instrucción.

Ejemplo:

```asm
MOVHI r5, array+12@hi
ORI   r5, r5, array+12@lo
```

Las dos relocations pueden indicar:

```text
symbol = array
addend = 12
```

y el linker calcula directamente:

```text
S + 12
```

### Decisión recomendada

```text
.rela.text
.rela.data
.rela.rodata
```

en lugar de:

```text
.rel.text
.rel.data
.rel.rodata
```

---

## 14. Símbolos

El assembler debe generar una `.symtab` normal.

El linker necesita distinguir al menos:

```text
símbolos locales
símbolos globales definidos
símbolos globales undefined
```

Ejemplo:

```text
foo.o:
    foo      GLOBAL DEFINED
    printf   GLOBAL UNDEFINED

lib.o:
    printf   GLOBAL DEFINED
```

El linker construye una tabla global:

```text
foo      -> dirección final en foo.o
printf   -> dirección final en lib.o
```

Si queda un símbolo global undefined al final:

```text
undefined symbol: ...
```

---

## 15. COMMON

Hay que comprobar cómo representa actualmente LCC las definiciones tentativas.

Por ejemplo:

```c
int foo;
```

podría acabar como:

```asm
.bss
foo:
    .space 4
```

o como:

```asm
.comm foo,4
```

Si el assembler utiliza `.comm`, puede convertirlo a:

```text
SHN_COMMON
```

El linker debe entonces:

1. juntar todos los COMMON;
2. respetar tamaño y alineación;
3. reservar espacio al final de `.bss`;
4. asignarles dirección.

Si LCC ya termina materializándolos en `.bss`, este soporte puede posponerse.

---

## 16. Layout del ejecutable

La primera versión no necesita implementar linker scripts GNU.

Puede usar una política fija o una configuración pequeña.

Ejemplo:

```text
TEXT_BASE = 0x00100000
DATA_BASE = alineado después de .rodata
ENTRY     = _start
```

Layout:

```text
.text
.rodata
.data
.bss
```

o, si interesa separar código y datos:

```text
.text/.rodata  -> TEXT_BASE
.data/.bss     -> DATA_BASE
```

Una configuración externa mínima podría ser:

```text
TEXT = 0x00100000
DATA = 0x00200000
ENTRY = _start
```

No hace falta implementar el lenguaje completo de scripts de GNU `ld`.

---

## 17. Algoritmo del linker

Una primera versión del linker puede seguir este flujo:

```text
1. Leer todos los ELF ET_REL.

2. Leer:
      secciones
      símbolos
      relocations

3. Construir las secciones finales:
      .text
      .rodata
      .data
      .bss

4. Asignar offsets dentro de cada sección final.

5. Asignar direcciones virtuales/físicas.

6. Calcular la dirección final de cada símbolo.

7. Resolver símbolos globales.

8. Aplicar cada relocation.

9. Buscar el símbolo de entrada (_start).

10. Generar ELF ET_EXEC.

11. Generar los PT_LOAD.
```

---

## 18. Aplicación de relocations

Pseudo-Python:

```python
for rel in relocations:
    S = address_of(rel.symbol)
    A = rel.addend
    P = address_of_relocation(rel)

    if rel.type == R_MINIGPU_32:
        patch_u32(P, S + A)

    elif rel.type == R_MINIGPU_HI16:
        patch_imm16(P, ((S + A) >> 16) & 0xffff)

    elif rel.type == R_MINIGPU_LO16:
        patch_imm16(P, (S + A) & 0xffff)

    elif rel.type == R_MINIGPU_PCREL16:
        delta = S + A - (P + 4)

        if delta & 3:
            error("unaligned PC-relative relocation")

        value = delta >> 2

        if value < -32768 or value > 32767:
            error("PC-relative relocation out of range")

        patch_imm16(P, value & 0xffff)
```

La parte específica de MiniGPU es muy pequeña.

---

## 19. Implementación en Python

La propuesta es implementar el linker en Python.

### Lectura: pyelftools

`pyelftools` resulta adecuado para leer:

- headers ELF;
- section headers;
- `.symtab`;
- `.strtab`;
- `.rela.*`;
- contenido de secciones.

Esto evita tener que escribir un parser ELF robusto.

Arquitectura propuesta:

```text
ELF ET_REL
│
▼
pyelftools
│
▼
estructuras internas del linker
│
├── sections
├── symbols
└── relocations
```

---

## 20. Escritura del ELF final

Hay dos opciones.

### Opción A: writer ELF32 propio

Es la opción recomendada para mantener la toolchain pequeña.

El linker genera con `struct.pack` únicamente lo necesario:

```text
ELF header
Program headers
Section headers opcionales
segmentos PT_LOAD
payload de text/rodata/data
```

El ejecutable puede incluso prescindir inicialmente de `.symtab` si no se necesita debug.

Ventajas:

- dependencia mínima;
- formato totalmente controlado;
- fácil de depurar;
- código pequeño;
- comportamiento reproducible.

### Opción B: LIEF

LIEF permite:

- leer ELF;
- modificar ELF;
- crear secciones y segmentos;
- volver a escribir ELF.

Es más cómodo, pero introduce una dependencia binaria/C++ considerablemente mayor que `pyelftools`.

Para MiniGPU se prefiere inicialmente:

```text
pyelftools + writer ELF32 propio
```

---

## 21. ELF ejecutable mínimo

La salida mínima puede contener:

```text
ELF32 header
2 x Program Header
.text/.rodata
.data
```

Primer `PT_LOAD`:

```text
flags   = R | X
vaddr   = TEXT_BASE
filesz  = tamaño(text + rodata)
memsz   = filesz
```

Segundo `PT_LOAD`:

```text
flags   = R | W
vaddr   = DATA_BASE
filesz  = tamaño(data)
memsz   = tamaño(data + bss)
```

El punto de entrada:

```text
e_entry = address(_start)
```

---

## 22. Uploader

El uploader no necesita conocer secciones ni relocations.

Sólo necesita leer los `PT_LOAD`.

Pseudo-código:

```python
for segment in elf.load_segments():

    data = segment.file_data()

    write_memory(segment.p_paddr, data)

    zero_len = segment.p_memsz - segment.p_filesz

    if zero_len:
        zero_memory(
            segment.p_paddr + segment.p_filesz,
            zero_len
        )

run(elf.entry_point)
```

En el protocolo hacia la placa se pueden usar tres órdenes:

```text
WRITE address length data
ZERO  address length
RUN   address
```

o una versión equivalente binaria.

---

## 23. Ventaja frente a transmitir `.bin`

Supongamos:

```text
.text     32 KiB
.rodata    4 KiB
.data      8 KiB
.bss     256 KiB
```

La memoria ocupada es aproximadamente:

```text
300 KiB
```

Pero sólo es necesario transmitir:

```text
44 KiB
```

La BSS se representa estructuralmente mediante:

```text
p_memsz > p_filesz
```

y la placa la pone a cero sin recibir esos bytes por UART.

---

## 24. Evolución futura

La arquitectura deja abierta la posibilidad de añadir más adelante:

### Archives

```text
.a
```

y selección de objetos según símbolos undefined.

### Linker script más potente

Sólo si aparece una necesidad real.

### Debug symbols

Mantener `.symtab` y quizá DWARF.

### Nuevas relocations

Por ejemplo:

```text
R_MINIGPU_PCREL26
R_MINIGPU_GPREL16
```

### Trampolines

Para llamadas `PCREL16` fuera de rango.

Ninguna de estas funciones es necesaria para la primera versión.

---

## 25. Primera versión propuesta

La implementación inicial puede fijarse deliberadamente a:

```text
Entradas:
    ELF32 ET_REL little-endian

Secciones:
    .text
    .rodata
    .data
    .bss

Símbolos:
    LOCAL
    GLOBAL
    UNDEFINED

Relocations:
    R_MINIGPU_32
    R_MINIGPU_HI16
    R_MINIGPU_LO16
    R_MINIGPU_PCREL16

Relocations:
    formato RELA

Layout:
    fijo/configuración MiniGPU simple

Entry:
    _start

Salida:
    ELF32 ET_EXEC

Segmentos:
    PT_LOAD RX
    PT_LOAD RW

BSS:
    p_memsz > p_filesz
```

Esto cubre el caso normal de programas C enlazados estáticamente sin convertir el proyecto en una reimplementación de GNU `ld`.

---

## 26. Resumen de diseño

La propuesta final es:

```text
LCC se mantiene sin cambios conceptuales.

El assembler MiniGPU pasa a emitir objetos ELF ET_REL.

Los objetos contienen símbolos y unas pocas relocations MiniGPU.

El linker es un programa pequeño en Python.

pyelftools se utiliza para leer los objetos.

La salida ELF ET_EXEC se escribe con un writer ELF32 mínimo.

El ejecutable usa PT_LOAD.

La BSS se representa mediante p_memsz > p_filesz.

El uploader transmite únicamente los bytes reales y ordena a la placa
poner a cero el resto.

Finalmente arranca en e_entry.
```

El punto clave es que MiniGPU no necesita un linker ELF general.

Necesita un linker **suficientemente completo para C estático en MiniGPU**, con un ABI y un conjunto de relocations deliberadamente pequeños.
