# Catálogo de programas C en mini-gpu

Este documento describe todos los programas y bibliotecas escritas en C del repositorio `mini-gpu`,
organizados por categoría, con su método de construcción y dependencias.

---

## Resumen rápido

| Categoría | Directorio | Programas | Build principal |
|---|---|---|---|
| **Compilador** | `u.lcc/` | LCC (el compilador mismo) | `make` + `build-mini.{sh,ps1}` |
| **Interprete BASIC** | `28.basic/` | `basic.c`, `basic_builtins.c` (+ tests) | `Makefile` (`cc` / `mini-lcc`) |
| **Enlazador** | `w.vlink/` | w.vlink | `Makefile` (`cc`) |
| **Biblioteca TUI** | `v.tui/` | v.tui | `Makefile` (`cc`) |
| **Ejemplo enlazado** | `1.isa/ejemplo-enlazado/` | `main.c`, `mates.c`, `rutinas.asm`, `arranque.asm` | `Makefile` (`mini-lcc` + `mini-asm` + `vlink`) |
| **Demos CPU+GPU** | `t.tests/cases-cpu-gpu/race/*/` | life, blur, rotate, cube, plane | `tools/c-program.mk` + `tools/mini-cc` |
| **Demos CPU+GPU (asm)** | `t.tests/cases-cpu-gpu/render/*` | plasma (3 versiones, sin C) | `mini-asm` directamente |
| **Demos CPU+GPU (asm)** | `t.tests/cases-cpu-gpu/launch/` | launch (kernel mínimo, sin C) | `mini-asm` directamente |
| **Demos CPU+GPU** | `t.tests/cases-cpu-gpu/simt/diverge/` | diverge | `Makefile` (`tools/c-program.mk` + `tools/mini-cc`) |
| **Demos CPU+GPU** | `t.tests/cases-cpu-gpu/dma/*/` | memset, memcpy, fill_rect, blit | `Makefile` (`tools/c-program.mk` + `tools/mini-cc`) |
| **Scheduler GPU** | `t.tests/cases-cpu-gpu/gpu-scheduler/` | scheduler.c, test-scheduler.c, demo.c | `Makefile` (`mini-lcc` + `mini-opt` + `mini-asm`) |
| **Tests LCC** | `u.lcc/tst/` | array.c, cf.c, … (varios) | `u.lcc/makefile` (`cc`) |
| **Tests mini-lcc** | `u.lcc/mini-tst/` | 166+ archivos .c pequeños | `build-mini.{sh,ps1}` (`cc`) |
| **Probes auditoría** | `analysis/lcc-audit/probes/` | args8.c, arrays_escape.c, … (11) | `make` (`rcc` + `mini-opt` + `sim-sys`) |

---

## 1. u.lcc/ — Compilador LCC

**Qué es:** El compilador C LCC (Lightweight C Compiler) que es el núcleo del proyecto.
Escrito en C, genera ensamblador para la arquitectura MiniISA.

**Archivos C principales:**
- `src/alloc.c`, `src/bind.c`, `src/dag.c`, `src/decl.c`, `src/enode.c`, `src/error.c`,
  `src/expr.c`, `src/event.c`, `src/init.c`, `src/inits.c`, `src/input.c`, `src/lex.c`,
  `src/list.c`, `src/main.c`, `src/output.c`, `src/prof.c`, `src/profio.c`, `src/simp.c`,
  `src/stmt.c`, `src/string.c`, `src/sym.c`, `src/trace.c`, `src/tree.c`, `src/types.c`,
  `src/null.c`, `src/symbolic.c`, `src/gen.c`, `src/bytecode.c`, `src/stab.c`
- `src/dagcheck.c`, `src/alpha.c`, `src/mips.c`, `src/mini.c`, `src/sparc.c`, `src/x86.c`,
  `src/x86linux.c` (generados por `lburg` a partir de descripciones de máquina)

**Build:**
```bash
# Linux/Mac
./build-mini.sh        # compila build/rcc
./build-mini.sh clean  # borra artefactos

# Windows
.\build-mini.ps1       # compila build/rcc.exe con MSVC (vcvars32)
.\build-mini.ps1 clean

# O directamente con make
make rcc               # compila rcc
make lcc               # compila lcc
make all               # compila todo (rcc, lburg, cpp, lcc, bprint, liblcc)
```

**Herramientas que produce:**
- `build/rcc` — preprocesador de C
- `build/lcc` — compilador C (mini-lcc)
- `build/lburg` — generador de tablas de parsing
- `build/cpp` — preprocesador C
- `build/bprint` — generador de bitcodes

---

## 2. 28.basic/ — Interprete BASIC

**Qué es:** Un interprete de BASIC escrito en C, con tests unitarios y una versión para la placa.

**Archivos C principales:**
| Archivo | Descripción |
|---|---|
| `basic.c` | Núcleo del interprete |
| `basic_builtins.c` | Funciones builtin del BASIC |
| `basic_main.c` | Punto de entrada |
| `basic_platform.h` | Interfaz de plataforma |
| `basic_platform_host.c` | Implementación para host |
| `basic_platform_console.c` | Implementación para placa |
| `basic_mini_console.c` | Versión para placa con consola |

**Tests unitarios (se compilan con `cc` del host):**
`test_basic_store.c`, `test_expr.c`, `test_run.c`, `test_console.c`, `test_repl.c`,
`test_strings.c`, `test_input.c`, `test_arrays.c`, `test_logic.c`, `test_step.c`

**Build:**
```bash
# Tests unitarios (host)
make test_basic_store   # basic.c + basic_builtins.c + test_basic_store.c
make test_expr          # etc.

# Interprete para host
make basic_host         # basic.c + basic_builtins.c + basic_main.c + basic_platform_host.c

# Interprete para placa (usa mini-lcc)
make basic_console      # basic_mini_console.c + basic_platform_console.c + ... -> basic_console.asm
```

---

## 3. w.vlink/ — Enlazador ELF (w.vlink)

**Qué es:** El enlazador de objetos VOBJ/ELF del proyecto.

**Build:**
```bash
make                    # compila con cc
```

---

## 4. v.tui/ — Biblioteca de interfaz de texto

**Qué es:** Biblioteca de interfaz de usuario por texto para la placa.

**Build:**
```bash
make                    # compila con cc
```

---

## 5. 1.isa/ejemplo-enlazado/ — Ejemplo de compilación separada y enlace

**Qué es:** Ejemplo didáctico que muestra el flujo completo: C → mini-lcc → mini-asm → objeto → vlink → binario.

**Archivos C:**
| Archivo | Descripción |
|---|---|
| `main.c` | `main()`, llama a `doble` |
| `mates.c` | Define `cuadrado`, `cubo` |

**Archivos de ensamblador:**
| Archivo | Descripción |
|---|---|
| `rutinas.asm` | Define `doble`, `triple` |
| `arranque.asm` (crt0.s) | `_start` |

**Build:**
```bash
# Necesario primero
git submodule update --init w.vlink
# Luego
make                    # programa.bin (sin mates.o, code-size optimization)
make todo               # programa-todo.bin (con todo)
make sim                # ejecuta en simulador
```

**Flujo de construcción:**
```
main.c       ──mini-lcc──▶ main.s       ──mini-asm --vobj──▶ main.o  ┐
mates.c      ──mini-lcc──▶ mates.s     ──mini-asm --vobj──▶ mates.o  ┐
rutinas.asm  ─────────────mini-asm──▶── rutinas.o     ──ar──▶ libejemplo.a ┐
arranque.asm ─────────────mini-asm──▶── arranque.o   ─────────────────────┤
                                                                          ▼
                                                                   vlink ──▶ programa.bin
```

---

## 6. t.tests/cases-cpu-gpu/race/*/ — Demos CPU+GPU (race)

**Qué son:** Cada demo tiene tres versiones (CPU, GPU inocente, GPU buena) y comparten código.
Incluyen `test.json` para el runner automático.

**Programas:**

| Carpeta | Programa | Archivos C | Descripción |
|---|---|---|---|
| `race/life/` | life | `life.c`, `life_ptr.c`, `life_standalone.c` | Game of Life |
| `race/blur/` | blur | `blur.c`, `blur_standalone.c` | Filtro de desenfoque |
| `race/rotate/` | rotate | `rotate.c`, `rotate_standalone.c` | Rotación de imagen |
| `race/cube/` | cube | `cube.c` | Cubo 3D |
| `race/plane/` | plane | `plane.c`, `plane_test.c` | Plano con texturas |

**Build (todos iguales):**
```bash
# Desde cualquier carpeta race/*/
make              # compila con mini-cc (mini-lcc + mini-opt + mini-asm)
make sim          # ejecuta en simulador
make debug        # depura con mini-dbg
make compare      # compara con modelo Python
make run          # ejecuta en placa
make case         # genera dumps de memoria esperados (para test.json)
make clean
```

**Framework de build compartido:** `tools/c-program.mk` + `tools/mini_cc.py`. Los Makefile de `life`, `blur` y
`rotate` construyen los `*_standalone.c` (los que lanzan la GPU con `GPU_RUN`); `blur.c`, `life.c` y `life_ptr.c`
solo definen los kernels y los compila `compare_race.py`, sin el runtime de la GPU.

---

## 7. t.tests/cases-cpu-gpu/render/* — Plasma (3 versiones)

**Qué es:** Un programa gráfico que pinta un plasma. Tres versiones que producen la misma imagen.

| Versión | Carpeta | Descripción |
|---|---|---|
| v1 | `render/render/` | Un hilo por fila de celdas (asm) |
| v2 | `render-v2/render_v2/` | Escrituras coalescidas (asm) |
| CPU | `render-cpu/render_cpu/` | Solo CPU, referencia (asm) |

**Nota:** Las versiones de render son programas en ensamblador (`.asm`), no en C.
No tienen Makefile propio; se ensamblan directamente con `mini-asm`.

**Build:**
```bash
# Desde la carpeta correspondente
mini-asm render.asm -o render.bin   # ensambla directamente
sim-sys render.asm --window         # ejecuta en simulador
```

---

## 8. t.tests/cases-cpu-gpu/launch/ — Kernel mínimo

**Qué es:** El ejemplo más pequeño que lanza un kernel GPU. CPU y kernel en un solo fichero.

**Build:** Se ensambla directamente con `mini-asm` (no tiene Makefile propio).

---

## 9. t.tests/cases-cpu-gpu/simt/diverge/ — Divergencia de lanes

**Qué es:** Kernels en C cuyas lanes divergen, para probar el comportamiento SIMT.

**Archivo C:** `diverge.c`

**Build:**
```bash
make              # compila con mini-cc (mini-lcc + mini-opt + mini-asm)
make sim          # ejecuta en simulador
make compare      # compara con modelo Python
make case         # genera dump esperado
```

---

## 10. t.tests/cases-cpu-gpu/dma/*/ — Kernels de sistema

**Qué son:** Kernels DMA (memset, memcpy, fill_rect, blit) y sus benchmarks.

| Carpeta | Programa | Descripción |
|---|---|---|
| `dma/memset/` | memset | Kernel memset |
| `dma/memcpy/` | memcpy | Kernel memcpy |
| `dma/fill_rect/` | fill_rect | Llenado de rectángulo |
| `dma/blit/` | blit | Block image transfer |
| `dma/bench-dma/` | benchmark | Benchmark de kernels DMA |
| `dma/lat-exp/` | latencia | Experimento de latencia |
| `dma/poll-exp/` | polling | Experimento de polling |
| `dma/rect/` | rect | Rectángulo |
| `dma/harness/` | arnés | Arnés de tests |

**Build (todos iguales):**
```bash
make              # compila con mini-cc (mini-lcc + mini-opt + mini-asm)
make sim          # ejecuta en simulador
make compare      # compara con modelo Python
make case         # genera dump esperado
```

**Nota:** Algunos subdirectorios (`bench-dma`, `lat-exp`, `poll-exp`, `rect`, `harness`)
no tienen Makefile propio; se ensamblan con `mini-asm` directamente.

---

## 11. t.tests/cases-cpu-gpu/gpu-scheduler/ — Scheduler de jobs GPU

**Qué es:** Biblioteca C sin `main` que gestiona jobs de la GPU. Incluye tests y demo.

**Archivos C:**
| Archivo | Descripción |
|---|---|
| `scheduler.c` | Implementación del scheduler |
| `scheduler.h` | Cabecera |
| `test-scheduler.c` | Tests unitarios (C99, ASan, UBSan) |
| `demo.c` | Demo que lanza un job en la GPU del simulador |

**Build:**
```bash
make              # host (C89 check) + lcc (mini-lcc + mini-opt + mini-asm)
make host         # solo C89 check con cc del host
make lcc          # solo mini-lcc + mini-opt + mini-asm
make test         # test-scheduler.c en el host
make case         # test-scheduler.c + scheduler.c para MiniISA (mini-cc)
make sim          # ejecuta el binario case en simulador
make demo-sim     # demo.c en el simulador
make clean
```

**Nota:** No usa `tools/c-program.mk` porque es una biblioteca sin `main`: llama a `mini-cc` a mano con
`test-scheduler.c scheduler.c` (o `demo.c scheduler.c`). Tampoco pide el runtime de la GPU (`gpu.c`,
`gpu_runtime.inc`, `bench.inc`): el test no usa la GPU y la demo la programa por MMIO, así que cada imagen
ocupa la mitad (~33 KB menos, los de `__gpu_stack`).

---

## 12. u.lcc/tst/ — Tests de LCC

**Qué son:** Casos de prueba pequeños para el compilador LCC. Todos se construyen de la misma forma.

**Archivos C destacados:**
`array.c`, `cf.c`, `calls.c`, `control.c`, `leaf.c`, `locals.c`, `opt_patterns.c`,
`pressure.c`, `recursive.c`, `volatile.c`, `wide.c`, `args8.c`, `arrays_escape.c`

**Build:** Se compilan con `cc` (el compilador del host) desde `u.lcc/makefile`.

---

## 13. u.lcc/mini-tst/ — Tests mini-lcc

**Qué son:** 166+ casos de prueba pequeños para mini-lcc (el backend MiniISA de LCC).

**Build:**
```bash
# Linux/Mac
./build-mini.sh        # compila todos con cc

# Windows
.\build-mini.ps1       # compila todos con MSVC
```

---

## 14. analysis/lcc-audit/probes/ — Probes de auditoría de LCC

**Qué son:** 11 casos de prueba pequeños para auditar las optimizaciones de LCC.

**Archivos C:**
| Archivo | Descripción |
|---|---|
| `args8.c` | 8 argumentos |
| `arrays_escape.c` | Arrays que escapan |
| `calls.c` | Llamadas |
| `control.c` | Control flow |
| `leaf.c` | Función hoja |
| `locals.c` | Variables locales |
| `opt_patterns.c` | Patrones optimizables |
| `pressure.c` | Presión de registros |
| `recursive.c` | Recursión |
| `volatile.c` | Volátiles |
| `wide.c` | Operaciones wide |

**Build:** Se usan con `measure.py` que compila cada probe con `rcc`, lo ensambla,
lo pasa por `mini-opt` y lo ejecuta en el simulador.

---

## 15. Mini-Opt: El optimizador de ensamblador

**Dónde está:** `tools/mini-opt` (lanzador) y el paquete `tools/mini_opt/` (un fichero por pase en `passes/`)

**Qué es:** Un optimizador de ensamblador MiniISA que se ejecuta sobre el output de `mini-lcc`.

**Uso:**
```bash
python tools/mini-opt input.s -o output.s
python tools/mini-opt a.s b.s -o todo.s --whole-program --extern-refs 1.isa/runtime/crt0.s
```

Con varios `.s` los junta en ese orden (`merge.py`: renumera las `L.n` y `__sf.n` de los siguientes y da error si
dos definen el mismo símbolo) y optimiza la unión como un solo programa. `--extern-refs FICHERO` (repetible) son
los ficheros que se ensamblan aparte (arranque, `.inc`): los símbolos que nombran no se dan por privados.
`--whole-program` dice que la entrada es el programa entero y activa `deadfuncs`.

**Pases disponibles:**
- `deadfuncs` — con `--whole-program`, borra las funciones que no alcanza `main`, el arranque, lo que nombran los
  `--extern-refs`, un kernel (`__kernel_*`) ni un dato (`.word f`). Los datos no se tocan
- `intrinsics` — las variables `__gpu_*` pasan a `GETTID`/`GETLANE`/`GETWARP`/`GETLWARP`/`GETARG`/`BAR`
- `kernels` — `__kernel_*`: desplazamientos con registro, ISA de la GPU, entrada (pila de lane y parámetros desde
  `GETARG`) y `EXIT` en vez de `JR R31`
- `stackslots` — huecos de la pila de la lane que se leen en bucles, a registros libres
- `jumps` — `BRA` a una etiqueta que solo salta: salta al destino final; quita el `BRA` a la línea siguiente
- `boolean` — `Bcc ; MOVI r,1 ; BRA ; ...` pasa a `SLT`/`SLTU` (+ `XORI`)
- `forward` — `LOAD` de un hueco de pila cuyo valor ya está en un registro: copia (o sobra)
- `deadstores` — `STORE` a un hueco de argumentos entrantes que nadie lee: se borra
- `constprop` — constantes conocidas: a inmediato, redundantes, evaluar, identidades, `MUL`+`SHL`
- `copyprop` — propagación de copias (`ADD d, s, R0`)
- `dce` — borra instrucciones puras cuyo resultado no está vivo
- `branches` — saltos constantes o idénticos: siempre → `BRA`, nunca → se borra
- `unreachable` — borra bloques e instrucciones no alcanzables desde la entrada
- `argblock` — saca de los bucles de un kernel la lectura del bloque de argumentos (solo lectura por contrato)
- `strength` — reducción de fuerza: un puntero que avanza en vez de recalcular el índice de cada acceso
- `licm` — saca de los bucles lo que no cambia en ellos (constantes y cuentas con valores fijos)
- `noalias` — borra las marcas internas de `__noalias_mark` (ya las usó `licm`)
- `sharebase` — un `LI` base por símbolo y bloque: los `LOAD`/`STORE` suman el desplazamiento
- `deadsaves` — `STORE`/`LOAD` de R16..R29 que la función no usa: se borran
- `tailcalls` — `JAL` directo en posición final: restaura el frame y `BRA`
- `invert` — `Bcc a,b,L1 ; BRA L2 ; L1:` pasa a `B!cc a,b,L2 ; L1:`
- `ssy` — `SSY` delante de los saltos que pueden divergir (en bucles, antes del bucle)

`python tools/mini-opt --list-passes` da la lista al día; el orden por defecto está en `tools/mini_opt/registry.py`.

**Integración:** `mini-opt` se ejecuta automáticamente como parte del pipeline `mini-cc`, una sola vez con
todas las unidades `.c`:
```
.c ──mini-lcc──▶ .s ┐
.c ──mini-lcc──▶ .s ┴─mini-opt (une y optimiza)──▶ programa.opt.s ──mini-asm──▶ .bin
```

---

## Framework de build: tools/c-program.mk + tools/mini_cc.py

**Descripción:** Marco de build compartido para todos los programas CPU+GPU en C. `mini-cc` compila lo que se le
pide y nada más; lo único que pone solo es `crt0.s`, primero, cuando hay algún `.c`.

```bash
mini-cc programa.c [otro.c|otro.s|otro.inc ...] [-o salida.bin] [--outdir DIR] [-I DIR]... [--data ETIQUETA=FICHERO]... [--board]
```

**Flujo de build:**
1. Para cada `.c`: `mini-lcc --no-crt` → `.s`
2. Una sola llamada a `mini-opt --whole-program` con todos los `.s` → `<programa>.opt.s`
3. Se genera un `.asm` con `crt0.s`, `<programa>.opt.s`, los ficheros a mano (`.s`, `.asm`, `.inc`, sin optimizar y
   en el orden de la línea de órdenes) y los `--data` (`.incbin`)
4. `mini-asm` → `.bin`

**El runtime de la GPU se pide explícitamente:** `gpu.c` (`gpu_launch` y `__gpu_stack`, 32 KB de pila de los
kernels), `gpu_runtime.inc` y `bench.inc`. `c-program.mk` los pasa con `$(GPU_RUNTIME)`, y los llamadores de Python
con `mini_cc.GPU_RUNTIME`. Un programa que no lanza la GPU desde C no los necesita.

**Variables que el Makefile del programa debe definir:**
- `PROGRAM` — nombre del programa
- `SOURCE` — archivo fuente C (default: `$(PROGRAM).c`)
- `BUILD_ARGS` — argumentos extra para `mini-cc` (ej: `--data`)
- `GPU_RUNTIME` — (opcional) los ficheros del runtime de la GPU; `GPU_RUNTIME :=` antes del `include` los quita
- `SIM_PROGRAM` — programa para sim-sys
- `COMPARE_COMMAND` — comando para comparar con modelo Python
- `BOARD_ARGS` — argumentos para build en placa

**Objetivos disponibles:**
| Objetivo | Descripción |
|---|---|
| `all` / `make` | Compila el programa |
| `sim` | Ejecuta en simulador |
| `debug` | Depura con mini-dbg |
| `compare` | Compara con modelo Python |
| `run` | Ejecuta en placa |
| `case` | Genera dumps esperados (para test.json) |
| `clean` | Borra artefactos |

---

## Programas que NO tienen C (solo referencia)

Los siguientes directorios contienen **solo ensamblador (`.asm`)** o **solo Python**:

| Directorio | Contenido |
|---|---|
| `t.tests/cases-cpu/*/` | Solo `.asm` (tests de CPU) |
| `t.tests/cases-gpu/*/` | Solo `.asm` (tests de GPU) |
| `t.tests/cases-shared/*/` | Solo `.asm` (tests compartidos) |
| `32.cpu-gpu-func-sim/` | Python (`test_cpu_gpu_sim.py`) |
| `t.tests/unit/*/` | Python (`test_*.py`) |
| `t.tests/runtime/gpu/gpu.c` | Runtime GPU en C (`gpu_launch` y `__gpu_stack`; se pasa a `mini-cc` con `GPU_RUNTIME`) |
| `1.isa/runtime/crt0.s` | Arranque en ensamblador |

---

## Diagrama de flujo de compilación general

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Flujo de compilación C                       │
└─────────────────────────────────────────────────────────────────────┘

  .c (programa)          .c (otras, y gpu.c si usa la GPU)
       │                                      │
       ▼                                      ▼
  mini-lcc ──no-crt──▶ .s               mini-lcc ──no-crt──▶ .s
       │                                      │
       └──────────┬───────────────────────────┘
                  ▼
     mini-opt --whole-program  (junta los .s, optimiza el programa entero,
                  │             borra las funciones que nadie alcanza)
                  ▼
          programa.opt.s
                  │
                  ▼
          mini-asm (crt0.s + programa.opt.s + [gpu_runtime.inc + bench.inc] + --data)
                  │
                  ▼
              programa.bin
                  │
           ┌──────┴──────┐
           ▼             ▼
       simulador      placa
       (sim-sys)    (run-board)
```
