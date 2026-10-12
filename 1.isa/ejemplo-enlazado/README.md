# Compilación separada y enlace con vlink

Un programa hecho con tres objetos: dos salen de C y uno de ensamblador. Se
enlazan con `vlink`, y el código que el programa no usa no llega al `.bin`.

```text
main.c ──mini-lcc──▶ main.s ──mini-asm --vobj──▶ main.o ─────────────┐
mates.c ─mini-lcc──▶ mates.s ─mini-asm --vobj──▶ mates.o ──┐          │
rutinas.asm ───────────────────mini-asm --vobj──▶ rutinas.o ┴─ar─▶ libejemplo.a
arranque.asm (crt0.s) ─────────mini-asm --vobj──▶ arranque.o ────────┤
                                                                     ▼
                                                    vlink ──▶ programa.bin
```

| Fichero | Define | Usa |
|---|---|---|
| `main.c` | `main` | `doble` |
| `mates.c` | `cuadrado`, `cubo` | nada de fuera |
| `rutinas.asm` | `doble`, `triple` | nada de fuera |
| `arranque.asm` | `_start` (el `crt0.s` de siempre) | `main` |

```bash
git submodule update --init w.vlink && build-vlink   # una vez
make            # programa.bin: sin mates.o
make todo       # programa-todo.bin: con todo, para comparar
make sim        # R1 = 42
```

Todo se genera en `_build/ejemplo-enlazado/`.

## Paso a paso

**1. Compilar.** `mini-lcc --no-crt` traduce cada `.c` a ensamblador por su
cuenta. Con `--no-crt` no mete el arranque, porque eso va en su propio objeto.

**2. Ensamblar a objeto.** `mini-asm fichero --vobj fichero.o` genera un objeto
VOBJ (el formato de vasm, que vlink entiende) en vez de una imagen. El objeto
guarda el código de cada sección empezando en 0, los símbolos que exporta
(`.globl`) y los que importa (`.extern`), y una *relocation* en cada
instrucción que nombra una dirección todavía desconocida. Si no se pasa `-o`,
no intenta escribir un `.bin`. No podría hacerlo, porque `main.o` llama a `doble`
y aún no se sabe dónde va a estar. `mini-objdump` lo enseña:

```text
$ mini-objdump _build/ejemplo-enlazado/main.o
  [ 1] main     LABSYM  flags=EXPORT  sec=1  value=0x00000000
  [ 3] doble    IMPORT                sec=0  value=0x00000000
  [ 1] .text    size=32 relocs=1
       reloc PC   off=0x0000000c bits=0:16 ... symbol=[3] doble
```

Es el `JAL R31, doble` de `main`. El desplazamiento se rellena al enlazar.

Hay un detalle con lcc. Declara `.extern` para los datos que usa sin definirlos,
pero no para las funciones, porque en `build-c` todas las unidades se ensamblan
juntas y nunca le hizo falta. Si se ensambla `main.s` tal cual, sale
`etiqueta no definida: doble`. El Makefile resuelve esto con un `main.ext.s`
que pone las declaraciones antes del código (la lista está en `MAIN_EXTERNS`):

```asm
    .extern doble
    .include "main.s"
```

**3. Biblioteca.** `ar rc libejemplo.a mates.o rutinas.o` mete los dos objetos
"de biblioteca" en un archivo. Un objeto que se le pasa suelto a vlink siempre
se enlaza. En cambio, de un archivo solo saca los objetos que definen algún
símbolo que todavía falta.

**4. Enlazar.**

```bash
vlink -brawbin1 -M -o programa.bin arranque.o main.o libejemplo.a
```

vlink lee `arranque.o` y `main.o`. Después de leerlos solo le falta `doble`.
Recorre la biblioteca, ve que `doble` la define `rutinas.o` y la mete:

```text
libejemplo.a (rutinas.o) needed due to doble
```

Nadie pide `cuadrado` ni `cubo`, así que `mates.o` se queda fuera. Luego coloca
las secciones una tras otra desde la dirección 0 (`arranque.o` va primero para
que `_start` quede en 0), parchea cada relocation con la dirección final y
escribe la imagen plana (`rawbin1`). `-M` escribe el mapa en `programa.map`.

## Qué se ha eliminado

Comparando `programa.map` con `programa-todo.map`:

```text
make (con la biblioteca)             make todo (los .o sueltos)
.text  (size 44)                     .text  (size 7c)
  00-10 arranque.o                     00-10 arranque.o
  10-30 main.o                         10-30 main.o
  30-44 rutinas.o                      30-68 mates.o      ◀ cuadrado, cubo
                                       68-7c rutinas.o
```

Son 56 bytes de código menos (14 instrucciones), y el programa da lo mismo:
`main` devuelve `doble(21)`, R1 = 42.

## El límite: se elimina el objeto entero, no la función

`triple` tampoco la usa nadie, pero sigue en `programa.bin`. Está en el mismo
`rutinas.o` que `doble`, y vlink decide objeto a objeto: si un objeto hace
falta, entra entero. Por eso las bibliotecas de C clásicas ponen una función
por fichero. Si `triple` estuviera en un `triple.asm` propio dentro de la
biblioteca, también desaparecería.

Para quitar funciones sueltas de dentro de un objeto harían falta dos cosas que
hoy no existen:

- **una sección por función** (`.text.doble`, `.text.triple`…, como
  `-ffunction-sections` en GCC). mini-asm solo conoce `.text`, `.rodata`,
  `.data` y `.bss`.
- **un linker que tire las secciones a las que nadie llega**. Eso es
  `-gc-all`, que vlink tiene desde la 0.16. El de `w.vlink` es la 0.15.

## Otras notas

- La `.bss` (los 8 KiB de pila de `crt0.s`) sale como ceros al final de la
  imagen `rawbin1`. Por eso los dos `.bin` ocupan unos 8 KiB.
- La extensión `.o` es solo un nombre. Por dentro el fichero es VOBJ, y vlink
  reconoce el formato por el contenido. `mini-objdump` también lo lee.
- Este flujo no lleva el runtime de GPU ni `mini-opt`. Para programas CPU+GPU
  completos se sigue usando `build-c`, que ensambla todo de una vez.
