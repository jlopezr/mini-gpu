<!-- trace:artifact SPEC-MINIISA-ASSEMBLER
type: specification
kind: component
subjects:
  - assembler
-->

# El ensamblador MiniISA

Este documento define la sintaxis y el comportamiento del ensamblador MiniISA, incluyendo sus interfaces de uso, sistema de símbolos, directivas y generación de la imagen binaria.

La arquitectura, el repertorio de instrucciones y sus codificaciones están definidos en [`isa.md`](isa.md). El ensamblador transforma el código fuente conforme a esas definiciones y resuelve antes de la emisión los elementos propios de la herramienta, como directivas, inclusiones y etiquetas locales.

La salida es una **imagen plana** little-endian que se carga en `0x00000000`. No existe formato objeto, relocations ni linker: los símbolos se resuelven a direcciones absolutas dentro de la imagen.

## Interfaces de uso

### Línea de órdenes

```bash
python 1.isa/mini_asm.py programa.asm                  # -> programa.bin
python 1.isa/mini_asm.py programa.asm -o otro.bin
python 1.isa/mini_asm.py programa.asm --hex salida.hex
python 1.isa/mini_asm.py programa.asm -I x.tests/inc   # dónde buscar .include
python 1.isa/mini_asm.py programa.asm --listing        # listado por pantalla
python 1.isa/mini_asm.py programa.asm --listing p.lst  # listado a fichero
```

`-I` puede repetirse. Los directorios se consultan en el orden indicado.

Los lanzadores del repositorio (`run-board`, `capture-frame-sim`, `run_tests.py`) ya incluyen `x.tests/inc`, por lo que los `.asm` ejecutados mediante ellos no necesitan añadirlo explícitamente.

### API de Python

El ensamblador también puede utilizarse directamente como módulo Python. Los simuladores y los tests emplean esta interfaz para ensamblar código sin pasar por la línea de órdenes.

```python
from mini_asm import assemble, assemble_bytes

assemble("MOVI R1, 1\nHALT")                       # -> [palabra, palabra]
assemble_bytes(fuente, base_dir, nombre, (inc,))   # -> bytes
```

`base_dir`, `origin` e `include_dirs` solo son necesarios cuando el fuente utiliza `.include`. Al ensamblar directamente una cadena sin información de fichero, los diagnósticos utilizan `línea N` en lugar de `fichero:N`.

## Proceso de ensamblado

El ensamblador transforma el fuente en una imagen binaria mediante tres fases. Este proceso determina la resolución de inclusiones y símbolos, la disposición de las secciones y la información mostrada por el listado.

Las construcciones propias del ensamblador se resuelven antes de la emisión y no alteran el modelo de ejecución; por ejemplo, una etiqueta local y su expansión manual producen la misma imagen binaria.

1. **Expansión.** Se resuelven los `.include` y se produce una secuencia plana de `(fichero, número, línea)`. Cada línea conserva su ubicación original para poder producir diagnósticos referidos al fuente correspondiente.

2. **Pasada 1.** Se determinan los tamaños y se asignan las direcciones de las etiquetas. En esta fase también se transforman las etiquetas locales `@nombre` en sus nombres internos compuestos.

3. **Pasada 2.** Se emiten instrucciones y datos resolviendo las referencias a etiquetas como direcciones absolutas.

Las secciones se ordenan entre la primera y la segunda pasada, cuando ya se conoce el tamaño de cada una.

## Listado (`--listing`)

El listado relaciona cada línea del fuente, una vez expandidos los `.include`, con el PC asignado durante la primera pasada y con la palabra emitida durante la segunda:

```text
00000038  43800002  MOVI  R28, MMIO_VIDEO_MODE_SCANOUT
0000003c  5b820000  STORE R28, R2, MMIO_VIDEO_CTRL_OFF
00000040            forever:
00000040  bfffffff  BRA forever

Etiquetas:
  00000040  forever
```

Su uso principal es identificar qué código corresponde al `pc` reportado por la placa o por un simulador. Para este propósito proporciona información equivalente a un desensamblado del programa fuente sin requerir una segunda tabla de decodificación paralela a `OPCODES`.

El listado no desensambla un `.bin` independiente: necesita el código fuente utilizado para producirlo.

Las constantes definidas mediante `.equ` no aparecen en la tabla de etiquetas. Aunque constantes y etiquetas comparten espacio de nombres, las constantes no representan posiciones del programa; incluirlas asociaría innecesariamente a los PC nombres procedentes, por ejemplo, de `mmio.inc`.

## Sintaxis

- Registros `R0`–`R31`, sin distinguir mayúsculas.
- Operandos separados por comas.
- Enteros con sintaxis de Python: `123`, `-4`, `0xFF`, `0b1010`, `1_000`.
- Comentarios con `;` o con `#`, hasta el final de línea. Dentro de comillas dobles no tienen efecto: en `.string "a ; b"` el `;` forma parte del literal.
- Una etiqueta puede aparecer en una línea propia o delante de una instrucción.

```asm
start:
    MOVI R1, 10
loop:
    ADDI R1, R1, -1
    BNE  R1, R0, loop
    HALT
```

La sintaxis de memoria expone directamente los tres campos del encoding:

```asm
LOAD  Rd, Ra, offset
STORE Rs, Ra, offset
```

`SHLI`, `SHRI` y `SARI` no son opcodes independientes: corresponden a `SHL`, `SHR` y `SAR` con el bit de cantidad inmediata activado. La cantidad válida está entre 0 y 31; cualquier otro valor se rechaza en lugar de truncarse.

`RET` es un alias de `JR R31`.

`LA Rd, etiqueta` carga una dirección absoluta de 32 bits. Es una pseudoinstrucción de dos palabras (`MOVHI` + `ORI`), al igual que `LI`, pero expresa que el operando se utiliza como dirección.

Admite aritmética sencilla de símbolos, por ejemplo:

```asm
LA R3, tabla+8
```

## Símbolos y etiquetas

Una etiqueta utilizada como inmediato representa su dirección. Por ejemplo, puede emplearse para cargar el puntero de una tabla:

```asm
    MOVI R3, vertices        ; solo mientras quepa en el signed16 de MOVI
```

Para direcciones que no caben en el inmediato de `MOVI` debe utilizarse `MOVHI` + `ORI`. El ensamblador rechaza el valor en lugar de truncarlo.

Se admite aritmética sencilla de símbolos:

```text
tabla+8
fin-inicio
```

### Etiquetas locales: `@nombre`

Una etiqueta cuyo nombre comienza por `@` pertenece a la última etiqueta global. Internamente se transforma en un nombre compuesto `global@local`:

```asm
drawline:
    ...
@loop:                       ; internamente `drawline@loop`
    BNE R9, R11, @loop

putpixel:
@loop:                       ; otro `@loop`, sin conflicto
    BRA @loop
```

Las etiquetas locales permiten que un fichero incluido exponga únicamente los símbolos que forman parte de su interfaz y mantenga locales los utilizados para su control interno.

Se aplican las siguientes reglas:

- **Una etiqueta local no abre un nuevo ámbito.** Tras `@a:`, una etiqueta `@b:` sigue perteneciendo a la última etiqueta global.
- `@` solo se admite al principio de un nombre. El nombre compuesto `drawline@loop` no puede escribirse directamente en el código fuente, evitando colisiones con la representación interna.
- Una referencia `@x` sin una etiqueta global anterior es un error.
- Los diagnósticos conservan la forma escrita en el fuente. Por ejemplo: `etiqueta no definida: @loop (local de drawline)`.

Se utiliza `@` para distinguir estas etiquetas tanto de las directivas, que comienzan por `.`, como de nombres globales habituales que comienzan por `_`, entre ellos `_start`.

Las etiquetas `L.xxx` generadas por `y.lcc` son globales y se mantienen como tales. `genlabel()` ya garantiza su unicidad y algunas identifican datos de `.rodata` o `.bss`, como literales de cadena o datos estáticos, que pueden ser referenciados desde distintas funciones.

## Directivas

### Datos

| Directiva               | Qué emite                                                                            |
|-------------------------|--------------------------------------------------------------------------------------|
| `.word v, …`            | 32 bits por valor. Acepta etiquetas, lo que permite construir tablas de direcciones |
| `.half v, …`            | 16 bits por valor                                                                    |
| `.byte v, …`            | 8 bits por valor                                                                     |
| `.string "…"`           | Bytes del literal, **NUL final** y relleno hasta múltiplo de 4                      |
| `.incbin "ruta"`        | Inserta un `.bin` literalmente o un `.hex` de palabras de 32 bits por línea         |
| `.space n` / `.zero n`  | `n` bytes a cero                                                                     |
| `.align n`              | Rellena hasta múltiplo de `n`                                                        |
| `.comm sim, tam[, ali]` | Reserva `tam` bytes en `.bss` bajo ese símbolo                                       |

Los escapes admitidos en `.string` son:

```text
\n  \r  \t  \0  \\  \"
```

Las rutas de `.incbin` se buscan con las mismas reglas que `.include`: primero junto al fichero que contiene la directiva y después en cada directorio indicado mediante `-I`.

Un `.bin` se copia byte a byte. Un `.hex` utiliza el mismo formato que `--hex`: una palabra hexadecimal de hasta 32 bits por línea, emitida en little-endian.

`.incbin` no introduce alineación adicional. El relleno final de la imagen continúa realizándose hasta un múltiplo de cuatro bytes.

El tamaño emitido por cada directiva debe calcularse de forma idéntica durante la primera y la segunda pasada. Una diferencia desplazaría las etiquetas posteriores y produciría direcciones incorrectas.

### Constantes: `.equ`

```asm
.equ VIDEO_BASE,  0x80200000
.equ VIDEO_CTRL,  VIDEO_BASE+0x00
.equ VIDEO_FRONT, VIDEO_BASE+0x04

    LI   R2, VIDEO_BASE
    STORE R3, R2, 0          ; CTRL
```

`.equ nombre, valor`, con `.set` como alias, asigna un nombre a un valor. No emite bytes ni modifica las direcciones de las etiquetas posteriores.

Constantes y etiquetas comparten un único espacio de nombres. Un nombre definido como etiqueta no puede definirse como constante, ni a la inversa, y una segunda definición mediante `.equ` es un error.

El valor de una constante se resuelve en el punto donde aparece, utilizando enteros y constantes definidas previamente. No se admiten referencias hacia delante ni referencias a etiquetas:

```asm
.equ A, B+1      ; error: B todavía no existe
.equ B, 4

sitio:
.equ C, sitio    ; error: en la pasada 1 `sitio` aún no tiene dirección
```

Esta restricción es deliberada. Resolver referencias hacia delante requeriría resolver dependencias entre constantes, mientras que el uso principal de `.equ` —los includes de constantes MMIO generados a partir de [`mmio.md` §20](mmio.md#20-fuente-única-de-constantes)— requiere un formato sencillo y legible secuencialmente.

`MOVHI` solo admite enteros y no resuelve símbolos. Para cargar una constante simbólica de 32 bits debe utilizarse `LI Rd, expr32`.

`LI` emite dos palabras donde `MOVHI` emitía una; por tanto, sustituir `MOVHI Rn, 0x8000` por `LI Rn, BASE` aumenta el tamaño del programa y su cuenta de ciclos.

### Secciones

Se reconocen:

```text
.text
.rodata
.data
.bss
```

con los alias `.code` y `.rdata`, además de:

```text
.section nombre
```

Las secciones se emiten en el orden:

```text
.text
.rodata
.data
.bss
```

independientemente del orden en que aparezcan en el código fuente.

Su función es aceptar y reorganizar salida de compiladores. No representan segmentos de memoria independientes.

Las siguientes directivas se aceptan y se ignoran por compatibilidad con salida de compiladores:

```text
.globl
.global
.extern
.ent
.end
.type
.size
.file
.loc
.ident
```

### Inclusión

```asm
    .include "drawline.inc"
```

La búsqueda se realiza primero en el directorio del fichero que contiene el `.include` y después en los directorios indicados mediante `-I`, respetando su orden.

Esto permite que una dependencia situada junto al fichero que la incluye tenga prioridad sobre otra del mismo nombre disponible en un directorio compartido.

Cada fichero incluido resuelve a su vez sus propios `.include` tomando como primer directorio el suyo.

Se detectan ciclos de inclusión. La profundidad máxima es de 16 niveles; superar ese límite produce un error de ensamblado.

Las etiquetas globales de los ficheros incluidos pertenecen al mismo espacio de nombres que las del resto del programa. Una definición duplicada informa de ambos lugares:

```text
cube.asm:212: label duplicado: putpixel (ya definido en putpixel.inc:23)
```

### `.once`

La directiva `.once`, situada en un fichero incluido, evita que ese fichero se emita más de una vez:

```asm
; putpixel.inc
    .once

putpixel:
    ...
```

La propiedad se declara en el propio fichero incluido para que todos sus consumidores obtengan el mismo comportamiento. El modelo es equivalente al de `#pragma once`.

El comportamiento es opt-in. Sin `.once`, incluir el mismo fichero varias veces emite su contenido varias veces, lo que permite usos como la repetición deliberada de tablas.

En el fichero principal, `.once` no tiene efecto. De este modo un mismo `.asm` puede utilizarse directamente o ser incluido desde otro fuente.

Un fichero protegido mediante `.once` puede incluir a su vez otras dependencias protegidas del mismo modo. Por ejemplo, `drawline.inc` puede incluir `putpixel.inc` aunque el programa principal también lo incluya.

## Errores

Los errores de ensamblado se notifican mediante `AsmError`, que deriva de `ValueError`.

Esto permite a simuladores y otras herramientas consumidoras tratar un error del código fuente como una entrada inválida, diferenciándolo de un fallo interno del simulador o de la propia herramienta.

## Alcance y características no soportadas

El lenguaje de ensamblado se mantiene deliberadamente reducido.

No se soportan:

- macros;
- ensamblado condicional (`.if` / `.ifdef`);
- expresiones distintas de sumas y restas de etiquetas y constantes;
- formato objeto;
- linker.

La directiva `.once` cubre el caso habitual de las guardas de inclusión sin introducir ensamblado condicional, por lo que no se requiere un mecanismo basado en `.ifndef`.
