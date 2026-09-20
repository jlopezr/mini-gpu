# El ensamblador MiniISA

Referencia de `miniisa_asm.py`: sintaxis, directivas y línea de órdenes.

**Esto no es la ISA.** [`isa.md`](isa.md) define la arquitectura —qué
instrucciones existen, qué hacen y cómo se codifican— y la cumple cualquier
implementación. Lo de aquí son decisiones de *esta herramienta*: las
directivas, los `.include` y las etiquetas locales no existen en el hardware,
se resuelven antes de emitir un solo bit. Un programa que use `@loop` y otro
que escriba las etiquetas a mano producen exactamente la misma imagen.

La salida es una **imagen plana** little-endian que se carga en
`0x00000000`. No hay formato objeto, relocations ni linker: los símbolos se
resuelven a direcciones absolutas dentro de esa imagen.

## Línea de órdenes

```bash
python 1.isa/miniisa_asm.py programa.asm                  # -> programa.bin
python 1.isa/miniisa_asm.py programa.asm -o otro.bin
python 1.isa/miniisa_asm.py programa.asm --hex salida.hex
python 1.isa/miniisa_asm.py programa.asm -I x.tests/inc   # dónde buscar .include
```

`-I` se puede repetir y se prueban en orden. Los lanzadores del repo
(`run-board`, `capture-frame-sim`, `run_tests.py`) ya pasan `x.tests/inc`, así
que desde un `.asm` del repo no hace falta.

## Sintaxis

- Registros `R0`–`R31`, sin distinguir mayúsculas.
- Operandos separados por comas.
- Enteros con sintaxis de Python: `123`, `-4`, `0xFF`, `0b1010`, `1_000`.
- Comentarios con `;` o con `#`, hasta el final de línea. Dentro de comillas
  dobles no cuentan: en `.string "a ; b"` el `;` es parte del mensaje.
- Una etiqueta puede ir en su línea o delante de una instrucción.

```asm
start:
    MOVI R1, 10
loop:
    ADDI R1, R1, -1
    BNE  R1, R0, loop
    HALT
```

La sintaxis de memoria expone los tres campos del encoding, sin azúcar:

```asm
LOAD  Rd, Ra, offset
STORE Rs, Ra, offset
```

`SHLI`, `SHRI` y `SARI` **no son opcodes**: son `SHL`, `SHR` y `SAR` con el bit
de cantidad inmediata puesto. La cantidad va de 0 a 31 y cualquier otra se
rechaza en vez de truncarse.

`RET` es un alias de `JR R31`.

## Etiquetas

Una etiqueta vale como inmediato, y entonces **es su dirección**. Es como se
carga el puntero de una tabla:

```asm
    MOVI R3, vertices        ; sólo mientras quepa en el signed16 de MOVI
```

Más allá de 32 KiB hay que usar `MOVHI` + `ORI`, y el ensamblador lo dice en
vez de truncar.

Se admite aritmética sencilla: `tabla+8`, `fin-inicio`.

### Etiquetas locales: `@nombre`

Una etiqueta que empieza por `@` pertenece a la **última etiqueta global**, y
por dentro pasa a llamarse `global@local`:

```asm
drawline:
    ...
@loop:                       ; internamente `drawline@loop`
    BNE R9, R11, @loop

putpixel:
@loop:                       ; otro `@loop`, y no chocan
    BRA @loop
```

Existen por los `.include`. Sin ellas, `drawline.inc` se apropiaba de **nueve**
nombres globales, ocho de los cuales son saltos internos que no le importan a
nadie; ahora reserva uno.

Detalles que conviene saber:

- **Una etiqueta local no abre ámbito.** Tras `@a:`, un `@b:` sigue
  perteneciendo a la global anterior, no a `@a`.
- `@` sólo se admite **al principio** de un nombre, así que el nombre compuesto
  `drawline@loop` no lo puede escribir nadie a mano: no hay forma de chocar.
- Un `@x` sin ninguna etiqueta global antes es un error, no un símbolo suelto.
- Los errores lo muestran como se escribió: `etiqueta no definida: @loop (local
  de drawline)`, no el nombre compuesto que nadie escribió.

**Por qué `@` y no `.` ni `_`.** Con `.` —la convención de NASM— un `.loop:` se
lee como una directiva. Con `_` se choca con `_start`, que el backend MiniISA de
`y.lcc` emite como símbolo global; y además un `_` delante significa
históricamente lo contrario de local (era la decoración que los compiladores de
C añadían a los símbolos **globales**). `@` no lo usaba nadie y es la convención
de MASM.

Las etiquetas `L.xxx` que genera `y.lcc` **son globales y deben seguir
siéndolo**: `genlabel()` ya las hace únicas, y muchas son datos en `.rodata` o
`.bss` —literales de cadena, estáticas— referenciados desde cualquier función.
Un literal de cadena no tiene "función anterior" a la que pertenecer.

## Directivas

### Datos

| Directiva               | Qué emite                                                                           |
|-------------------------|-------------------------------------------------------------------------------------|
| `.word v, …`            | 32 bits por valor. Acepta etiquetas, que es lo que permite una tabla de direcciones |
| `.half v, …`            | 16 bits por valor                                                                   |
| `.byte v, …`            | 8 bits por valor                                                                    |
| `.string "…"`           | Los bytes del literal, **NUL final** y relleno hasta múltiplo de 4                  |
| `.space n` / `.zero n`  | `n` bytes a cero                                                                    |
| `.align n`              | Rellena hasta múltiplo de `n`                                                       |
| `.comm sim, tam[, ali]` | Reserva `tam` bytes en `.bss` bajo ese símbolo                                      |

Escapes en `.string`: `\n`, `\r`, `\t`, `\0`, `\\`, `\"`.

Contar cuatro bytes por línea pase lo que pase es el error clásico aquí: una
directiva de datos desplaza **todas** las etiquetas siguientes, y si la pasada 1
no la mide bien, nada se queja y el programa salta a sitios equivocados.

### Constantes: `.equ`

```asm
.equ VIDEO_BASE,  0x80200000
.equ VIDEO_CTRL,  VIDEO_BASE+0x00
.equ VIDEO_FRONT, VIDEO_BASE+0x04

    LI   R2, VIDEO_BASE
    STORE R3, R2, 0          ; CTRL
```

`.equ nombre, valor` (alias `.set`) da nombre a un valor. **No emite nada** y no
desplaza ninguna etiqueta.

Nombres y etiquetas comparten un **único espacio de nombres**: un nombre que ya
es etiqueta no puede ser constante, ni al revés, y repetir una `.equ` es error.
Un nombre que gana dos definiciones y se queda con la última es exactamente
cómo un programa acaba usando un mapa de direcciones y el hardware otro.

El valor se resuelve **en el sitio**, contra enteros y contra constantes ya
definidas más arriba. No admite referencias hacia delante ni etiquetas:

```asm
.equ A, B+1      ; error: B todavía no existe
.equ B, 4
sitio:
.equ C, sitio    ; error: en la pasada 1 `sitio` aún no tiene dirección
```

Es una limitación deliberada. Resolver referencias hacia delante pediría un
solucionador de dependencias, y el uso para el que existe la directiva —el
include de constantes de MMIO generado desde
[`mmio.md` §20](mmio.md#20-fuente-única-de-constantes)— pide justo lo contrario:
una fuente tonta, legible de arriba abajo.

**`MOVHI` no resuelve símbolos**, sólo enteros. El vehículo para cargar una
constante de 32 bits es `LI Rd, expr32`, que sí los resuelve. Conviene recordar
que `LI` emite **dos** palabras donde `MOVHI` emitía una: cambiar un
`MOVHI Rn, 0x8000` por un `LI Rn, BASE` alarga el programa y su cuenta de
ciclos.

### Secciones

`.text`, `.rodata`, `.data`, `.bss` (con alias `.code` y `.rdata`), o
`.section nombre`. Se emiten **en ese orden**, independientemente de en qué
orden aparezcan en el fuente. Sólo sirven para aceptar salida de compiladores y
reordenarla; no hay segmentos de verdad.

Se ignoran, para tragar salida de compiladores: `.globl`, `.global`, `.extern`,
`.ent`, `.end`, `.type`, `.size`, `.file`, `.loc`, `.ident`.

### Inclusión

```asm
    .include "drawline.inc"
```

Se busca **primero en la carpeta del fichero que incluye** y después en las de
`-I`, en orden. Ese orden importa: un trozo local con el mismo nombre tiene que
ganar al compartido, o cambiar la biblioteca rompería programas ajenos en
silencio. Un fichero incluido resuelve *sus* `.include` desde su propia carpeta.

Se detectan los ciclos, y el anidamiento está limitado a 16 niveles para que una
cadena larga dé un error de ensamblado y no un `RecursionError` de Python.

**No hay espacios de nombres.** Las etiquetas globales de lo incluido lo son
para todo el programa. Un choque se denuncia diciendo los dos sitios:

```text
cube.asm:212: label duplicado: putpixel (ya definido en putpixel.inc:23)
```

### `.once`

Puesta **en el fichero incluido**, hace que no entre dos veces:

```asm
; putpixel.inc
    .once
putpixel:
    ...
```

Va en el incluido y no en quien incluye porque ser idempotente es una propiedad
suya: así no hay que acordarse en cada uno de los sitios que lo piden, y basta
que uno se olvide para romperlo. Es el modelo de `#pragma once`.

Es **opt-in**: sin `.once`, incluir dos veces emite el contenido dos veces, que
a veces es justo lo que se quiere (una tabla repetida). En el fichero principal
no hace nada, a propósito: un `.asm` puede querer ensamblarse suelto *y* ser
incluido por otro.

Con `.once`, un `.inc` puede arrastrar sus dependencias: `drawline.inc` incluye
`putpixel.inc` sin chocar con el programa que también lo incluya.

## Cómo funciona por dentro

Tres fases, y las dos primeras existen para que el resto no se entere de nada:

1. **Expansión.** Se resuelven los `.include` y se devuelve una lista plana de
   `(fichero, número, línea)`. A partir de aquí no hay ficheros, sólo líneas
   que recuerdan de dónde vinieron — que es lo que permite el mensaje de label
   duplicado con los dos sitios.
2. **Pasada 1.** Se miden los tamaños y se colocan las etiquetas. Aquí también
   se traducen las `@locales` a su nombre compuesto, así que el resto del
   ensamblador no sabe que existen.
3. **Pasada 2.** Se emite cada instrucción resolviendo las etiquetas a
   direcciones absolutas.

Las secciones se ordenan entre la 1 y la 2, que es cuando se conocen los
tamaños de cada una.

## API de Python

Los simuladores y los tests ensamblan sin pasar por la línea de órdenes:

```python
from miniisa_asm import assemble, assemble_bytes

assemble("MOVI R1, 1\nHALT")                       # -> [palabra, palabra]
assemble_bytes(fuente, base_dir, nombre, (inc,))   # -> bytes
```

`base_dir`, `origin` e `include_dirs` sólo hacen falta si el fuente usa
`.include`. Ensamblar una cadena suelta funciona sin ellos, y entonces los
errores dicen `línea N` en vez de `fichero:N`.

## Errores

`AsmError` hereda de `ValueError`, y no de `Exception`, para que los
simuladores lo presenten como lo que es —una entrada mala, no un fallo del
simulador— ya que los tres envuelven la carga en `except ValueError`.

## Qué no tiene

Ni macros, ni ensamblado condicional (`.if`/`.ifdef`), ni expresiones más allá
de sumas y restas de etiquetas y constantes, ni linker. `.once` cubre el caso de las guardas
de inclusión sin necesitar condicionales, que es la razón de que exista en esa
forma y no como `.ifndef`.
