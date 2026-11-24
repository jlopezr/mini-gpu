# Herramientas del repositorio: inventario, inconsistencias y propuestas

Este documento cataloga lo que hay en [tools/](../tools/) (y los lanzadores de
`tools/` que apuntan a otras carpetas), agrupado por tema. Para cada herramienta
da su propósito y sus argumentos. Después recoge las inconsistencias de nombre,
de parámetros y de forma de funcionar, y termina con una lista de propuestas de
mejora, unificación y simplificación.

Para los detalles de uso y los ejemplos, el manual sigue siendo
[tools/README.md](../tools/README.md). Este documento es un mapa y un análisis, no
lo sustituye.

**Cómo se ha hecho.** Los argumentos salen de leer el código (`argparse` y los
lanzadores), no de ejecutar `--help`. Si algún valor por defecto ha cambiado en
una versión posterior, manda el código. Las herramientas que viven fuera de
`tools/` (`mini-asm`, `sim-*`, `t.tests/run_tests.py`) se han revisado solo en sus
banderas, no en su comportamiento.

---

## 1. Cómo está montado

Cada herramienta pública tiene hasta tres piezas:

| Pieza                  | Ejemplo                 | Papel                                                                                               |
|------------------------|-------------------------|-----------------------------------------------------------------------------------------------------|
| Lanzador sin extensión | `tools/build-sweep`     | El comando que se escribe. Puede ser `bash`, `python3` con `sys.path` o `runpy` hacia otra carpeta. |
| Lanzador Windows       | `tools/build-sweep.ps1` | Busca `.venv\Scripts\python.exe` y reenvía los argumentos.                                          |
| Módulo Python          | `tools/build_runner.py` | La lógica. Se nombra en `snake_case`; los lanzadores, en `kebab-case`.                              |

Hay tres familias de lanzador sin extensión:

1. **Bash que llama a `python -m tools.<módulo> <subcomando>`**: `build`, `test`,
   `build-sweep`, `build-compare`, `phase-sweep`, `lint`, `check`, `run-board`.
2. **Python con `sys.path.insert` + `from tools.x import main`**: la mayoría
   (`build-list`, `trace`, `perf-report`, `generate-*`...).
3. **Python con `runpy` hacia un script de otra carpeta**: `mini-asm`, `mini-dis`,
   `mini-objdump`, `sim-cpu`, `sim-gpu`, `sim-sys`, `sim-gpu-cycle`.

Varias herramientas contienen su propia lógica en el fichero sin extensión, sin
módulo: `asm-sizes`, `capture-frames`, `capture-frame-sim`, `check-vobj`,
`demo-no-cpu`, `image-to-framebuffer`, `list-prototypes`, `make-framebuffer`,
`measure-demo`, `mini-lcc`, `run-tests`, `setup`.

### Opciones que casi todas comparten

| Opción              | Significado habitual                                                      |
|---------------------|---------------------------------------------------------------------------|
| `-p`, `--prototype` | Prototipo (número o nombre de carpeta). Lo resuelve `tools/prototype.py`. |
| `--port`            | Puerto serie; por defecto detecta el primer FTDI.                         |
| `--serial-timeout`  | Segundos de espera del puerto serie.                                      |
| `-y`, `--yes`       | No preguntar (sobre todo antes de reprogramar la placa).                  |
| `--root`            | Raíz del repositorio (casi solo para pruebas).                            |
| `--label`           | Etiqueta de un build o de una medida.                                     |
| `--json`            | Salida en JSON (ver las inconsistencias: no siempre significa lo mismo).  |

---

## 2. Mapa por temas

| Tema                                   | Herramientas                                                                                                                                                                                |
|----------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| A. Entorno y repositorio               | `setup`, `list-prototypes`, `prototype-report`, `generate-docs`, `generate-mmio`, `generate-sysid`, `trace`, `check-links`, `get-documents`, `module-diagram`                               |
| B. Cadena de compilación               | `mini-lcc`, `mini-cc`, `mini-opt`, `mini-asm`, `mini-dis`, `mini-objdump`, `asm-sizes`, `check-vobj`, `build-vlink`, `mini-lcc-test`                                                        |
| C. Simuladores y depuración            | `sim-cpu`, `sim-gpu`, `sim-gpu-cycle`, `sim-sys`, `mini-dbg`                                                                                                                                |
| D. Síntesis, timing y verificación RTL | `build`, `build-list`, `build-status`, `build-log`, `build-stop`, `build-clean`, `build-sweep`, `build-compare`, `build-diamond`, `test`, `lint`, `check`, `timing-wall`, `fixtures-report` |
| E. Suites de tests de software         | `run-tests`, `test-all`, `test-board`, `test-timings`                                                                                                                                       |
| F. Placa real                          | `board-info`, `board-upload`, `board-load`, `run-board`, `phase-sweep`, `usb-power-monitor`, `font-patch`                                                                                   |
| G. Vídeo y framebuffer                 | `make-framebuffer`, `image-to-framebuffer`, `frame-to-image.py`, `compare-frames.py`, `capture-frames`, `capture-frame-sim`, `demo-no-cpu`, `measure-demo`                                  |
| H. Medidas y rendimiento               | `bench-all`, `measure-compare`, `perf-report`, `test-timings`                                                                                                                               |

---

## 3. Inventario por tema

### A. Entorno y repositorio

| Herramienta          | Qué hace                                                           | Argumentos                                                                                                                                                                                                                                                                                                 |
|----------------------|--------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `setup`              | Instala `requirements.txt` y, si hay `uv`, PyPy para el simulador. | Ninguno. Sin `.ps1`.                                                                                                                                                                                                                                                                                       |
| `list-prototypes`    | Lista los prototipos y sus características.                        | `--root`, `--json`                                                                                                                                                                                                                                                                                         |
| `prototype-report`   | Informe de un prototipo.                                           | `-p` (obligatorio), `--root`, `--json`                                                                                                                                                                                                                                                                     |
| `generate-docs`      | Regenera las secciones generadas de los `.md`.                     | `--root`, `--check`, `--list-generators`                                                                                                                                                                                                                                                                   |
| `generate-mmio`      | Regenera las constantes del mapa MMIO.                             | `--check`                                                                                                                                                                                                                                                                                                  |
| `generate-sysid`     | Regenera el identificador de sistema.                              | `--check`                                                                                                                                                                                                                                                                                                  |
| `trace`              | Modelo de trazabilidad documental.                                 | Subcomandos `check`, `show`, `impact`, `coverage`, `dedupe`, `list`, `tree`, `path`, `query`, `rule`, más comandos de relaciones. Comunes: `--root`, `--no-cache`, `--format` (`text` o `json`); además `--depth`, `--json`, `--relation`, `--apply`, `--ext`, `--files`, `--type`, `--kind`, `--subject`. |
| `check-links.py`     | Comprueba enlaces entre `.md`.                                     | Posicionales; sin `argparse`. Sin lanzador ni `.ps1`.                                                                                                                                                                                                                                                      |
| `get-documents.ps1`  | Lista los `.md` del repo.                                          | Ninguno. Solo Windows.                                                                                                                                                                                                                                                                                     |
| `module-diagram.ps1` | SVG de un módulo Verilog con yosys + netlistsvg.                   | `-VerilogPath`, `-TopModule`, `-ExtraFiles`, `-Inside`. Se declara experimental y «fuera del sistema de lanzadores».                                                                                                                                                                                       |

### B. Cadena de compilación

| Herramienta     | Qué hace                                                           | Argumentos                                                                                                                                                                                                                                                                       |
|-----------------|--------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `mini-lcc`      | C a ensamblador MiniISA con `u.lcc`.                               | `source`, `-o`, `--keep-i`, `-I`, `-D`, `--no-crt`, `--fp32`, `--no-alias`, `--allocator`                                                                                                                                                                                        |
| `mini-cc`       | C completo (varios `.c`) a imagen, opcionalmente cargada en placa. | `program`, `otro...`, `-o/--output`, `--outdir`, `-I`, `-D`, `--data ETIQUETA=FICHERO`, `--board`, `--load [PROTOTIPO]`, `--no-run`, `--fp32`, `--far-calls`, `--opt-stats`, y las de `mini-opt` (`--assume-noalias`, `--extern-refs`, `--whole-program`, `--passes`, `--stats`) |
| `mini-opt`      | Optimizador del ensamblador.                                       | `-o/--output`, `--passes`, `--ssy-all`, `--assume-noalias`, `--extern-refs`, `--whole-program`, `--stats`, `--list-passes`                                                                                                                                                       |
| `mini-asm`      | Ensamblador (`1.isa/asm2/mini-asm.py`).                            | `input`, `-o`, `--hex`, `--vobj`, `--json`, `-I/--include-dir`, `-D/--define`, `--listing [FICHERO]`                                                                                                                                                                             |
| `mini-dis`      | Desensamblador.                                                    | `input`, `-f/--format`, `--start-pc`, `--no-addresses`, `--no-words`                                                                                                                                                                                                             |
| `mini-objdump`  | Volcado de un objeto.                                              | `input`, `-d/--disassemble`, `--json`                                                                                                                                                                                                                                            |
| `asm-sizes`     | Tamaño por función y dato a partir de un `.lst`.                   | `listing`, `--top` (25), `--all`, `--datos`                                                                                                                                                                                                                                      |
| `check-vobj`    | Valida la salida VOBJ con `vlink`.                                 | `input`, `--vlink`, `--keep`                                                                                                                                                                                                                                                     |
| `build-vlink`   | Compila el submódulo `w.vlink`.                                    | Ninguno. Solo bash.                                                                                                                                                                                                                                                              |
| `mini-lcc-test` | Suite del submódulo `u.lcc`.                                       | Se reenvía a `run-mini-tst.py`.                                                                                                                                                                                                                                                  |

### C. Simuladores y depuración

| Herramienta     | Destino                                   | Argumentos                                                                                                                                                                                                                                                                 |
|-----------------|-------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `sim-cpu`       | `2.cpu-sim-func/minicpu_sim.py`           | `program`, `--run-limit` (100 M), `--memory-size`, `--dump`                                                                                                                                                                                                                |
| `sim-gpu`       | `11.gpu-sim-func/minigpu_sim.py`          | `program`, `--run-limit` (100 M), `--memory-size` (32 MiB), `--num-warps` (8), `--warp-size`, `--simt-region-depth`, `--simt-path-depth`, `--config`, `--dump ADDR SIZE FILE`, `--trace`, `--trace-detail`, `--trace-limit`, `--trace-file`                                |
| `sim-gpu-cycle` | `25.gpu-sim-cycle-uarch/minigpu_cycle.py` | `--num-warps`/`--warps`, `--warp-size`/`--lanes`, `--config`, `--warp-config`, `--memory-size`, `--run-limit`, `--max-cycles`, `--dump`, `--dump-memory`, `--trace*`, `--cycle-trace*`, `--pipeline-trace*`, `--pipeline-from`, `--pipeline-cycles`, `--report`, `--state` |
| `sim-sys`       | `32.cpu-gpu-func-sim/cpu_gpu_sim.py`      | `program`, `--backend`, `--run-limit`, `--cpu-run-limit`, `--gpu-run-limit`, `--memory-size`, `--num-warps` (8), `--warp-size` (8), `--cpu-steps`, `--gpu-steps`, `--dump`, `--trace`, `--trace-limit`, `--trace-file`                                                     |
| `mini-dbg`      | `tools/debug_cli.py` (TUI Textual)        | `program`, `--board`, `-p`, `--port`, `--serial-timeout` (2.0), `--memory-size`, `--load-address`, `-I/--include`, `--gpu`, `--num-warps`, `--warp-size`, `--cpu-steps`, `--gpu-steps`, `--run-limit`, `--break`, `-x/--command`, `--no-tui`                               |

### D. Síntesis, timing y verificación RTL

Los siete comandos `build*` y `test` son subcomandos de `tools/build_runner.py`;
cada uno tiene su propio lanzador.

| Herramienta       | Subcomando                 | Argumentos                                                                                                                                                                                        |
|-------------------|----------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `build`           | `build`                    | `-p` o `--all` (excluyentes), `--label`, `--root`, `--archive-only`, `--incremental/--no-incremental`, `--background`                                                                             |
| `build-status`    | `status`                   | `-p`, `--id`, `--root`                                                                                                                                                                            |
| `build-log`       | `log`                      | `-p`, `--id`, `--root`, `--lines` (20), `--follow`                                                                                                                                                |
| `build-list`      | `list`                     | `-p`, `--root`, `--prototypes`                                                                                                                                                                    |
| `build-stop`      | `stop`                     | `-p`, `--id`, `--root`                                                                                                                                                                            |
| `build-clean`     | `clean`                    | `-p`, `--root`, `--keep` (10), `--keep-reports` (2), `--full`, `--older-than`, `--max-size`, `--dry-run`, `--yes`                                                                                 |
| `build-sweep`     | `sweep`                    | `-p` (o `--last`), `--label`, `--root`, `--seeds N...`, `--report-dir`, `--live`, `--compare`, `--list`, `--show`, `--promote [SEMILLA]`, `--from`, `--nextpnr-options`, `--jobs`, `--background` |
| `test`            | `test`                     | `-p` (obligatorio), `--label`, `--root`, `--quick`, `--full/--slow`, `--lint`, `--lint-only`, `--verbose`, `--jobs`, `--background`                                                               |
| `lint`            | `test --lint-only`         | Las de `test`.                                                                                                                                                                                    |
| `check`           | `test` + `lint` + `build`  | Solo `--prototype`.                                                                                                                                                                               |
| `build-compare`   | `tools/build_compare.py`   | `-p/--prototype` (repetible)                                                                                                                                                                      |
| `build-diamond`   | `tools/diamond_runner.py`  | `--prototype`, `--synth`, `--diamond`, `--strategy`, `--env`, `--tcl-only`, `--keep`. Solo existe el `.ps1`.                                                                                      |
| `timing-wall`     | `tools/timing_wall.py`     | `source`, `-p`, `--sweep`, `--seed`, `--compare`, `--clock`, `--top` (20), `--cross`, `--path`, `--by-register`, `--netlist`, `--filter`, `--stages`, `--stage-matrix`, `--ports`                 |
| `fixtures-report` | `tools/fixtures_report.py` | `-p` (opcional)                                                                                                                                                                                   |

Hay además un subcomando `run` (ejecuta y registra un comando arbitrario) y uno
`_track` (interno) que no tienen lanzador propio. Fuera de `build_runner` hay
generadores sin lanzador: `make_rtl_fixtures.py`, `gen_input_vectors.py`,
`gen_fp32_convert_vectors.py`, `stage_programs.py`.

### E. Suites de tests de software

| Herramienta    | Qué hace                                                            | Argumentos                                                                                                                                                                                                                                               |
|----------------|---------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `run-tests`    | `t.tests/run_tests.py` contra simuladores.                          | `--quick`, `--verbose`, `--hardware`, `--`; el resto se reenvía. Sin `argparse`: recorre `argv` a mano.                                                                                                                                                  |
| `test-board`   | La misma suite contra la placa, infiriendo `--backend`/`--version`. | `-p` (obligatorio), `--port`, `--family cpu\|gpu\|all` (por defecto `all`), `--no-record`, `--bitstream RUTA` o `--toolchain apio\|diamond` (excluyentes: programan ese build archivado y prueban con `--no-upload`); el resto va a `run_tests.py`.                                                                                                                                 |
| `test-all`     | `test-board` sobre varios prototipos.                               | `--family cpu\|gpu` (por defecto `gpu`), `-p N` (repetible, entero), `-y`, `--list`, `-o`, `cases...`                                                                                                                                                    |
| `test-timings` | Cronometra la suite entera.                                         | `--prototype` (repetible, sin `-p`), `--cpu-prototype`, `--gpu-prototype`, `--skip-hardware`, `--cases`, `--jobs` (1), `--full`, `--full-x-tests`, `--skip-python`, `--skip-rtl`, `--skip-x-tests`, `--quiet`, `--verbose`, `--output`, `--json FICHERO` |

Opciones propias de `t.tests/run_tests.py` (a las que llegan los reenvíos):
`TEST_JSON...`, `--backend`, `--version`, `-p`, `--port`, `--serial-timeout`
(1.0), `-y`, `--no-upload`, `--exclude-case`, `--skip-slow`, `--trace`,
`--trace-detail`, `--trace-limit`, `--trace-file`, `--measure [FICHERO]`,
`--measure-label`, `-j/--jobs` (0), `--durations`, `--timings-json`,
`--results-json`.

### F. Placa real

`board-info`, `board-upload`, `board-load` y `test-board` son cuatro puntos de
entrada de `tools/run_board.py` (`main_info`, `main_upload`, `main_load`,
`main_test`). `run-board` es el `main` clásico, que hace todo a la vez.

| Herramienta | Argumentos |
|---|---|
| `board-info` | `-p` (obligatorio), `--port`, `--serial-timeout` (1.0) |
| `board-upload` | Las comunes más `--rebuild`, `--no-upload`, `-y`, `--bitstream RUTA` (`--bitstream` es incompatible con `--rebuild` y con `--no-upload`) |
| `board-load` | Las comunes más `--program` (obligatorio), `--no-run`, `--verbose` |
| `run-board` | Las comunes más `--program`, `--rebuild`, `--upload/--no-upload`, `-y`, `--reset`, `--no-run`, `--interactive`, `--verbose` |
| `phase-sweep` | `--bitstream [NOMBRE=]RUTA` (repetible, obligatorio), `-p`, `--port`, `--output`, `--address` (`0x100000`), `--length` (`0x10000`), `--repetitions` (2), `--phases`, `--restore-phase`, `--serial-timeout` (2.0), `--yes`, `--dry-run` |
| `usb-power-monitor` | `--interval` (1.0), `--duration` (minutos) y una opción de dispositivo |
| `font-patch` | `-p` (obligatorio), `font`, `--upload` |

### G. Vídeo y framebuffer

| Herramienta | Qué hace | Argumentos |
|---|---|---|
| `make-framebuffer` | Genera un patrón RGB565 de 320x240. | `pattern`, `output` |
| `image-to-framebuffer` | Convierte una imagen a RGB565, opcionalmente la sube. | `entrada`, `salida`, `--tamano`, `--ajuste recortar\|encajar\|estirar`, `--fondo`, `--upload`, `-p`, `--direccion`, `--port` |
| `frame-to-image.py` | Framebuffer a imagen. | `--tamano`, `--escala` |
| `compare-frames.py` | Compara dos framebuffers. | `--rgb565`, `--tolerancia`, `--diff`, `--max-listados` |
| `capture-frames` | Captura N frames de la placa. | `-p` (obligatorio), `program`, `--frames` (3), `--desde` (3), `--prefijo`, `--port` |
| `capture-frame-sim` | Captura un frame en el simulador de CPU. | `program`, `salida`, `--swap N` o `--instrucciones N`, `--max-instrucciones` |
| `demo-no-cpu` | Patrón de diagnóstico sin CPU. | `-p` (obligatorio), `--pattern`, `--port`, `--address` |
| `measure-demo` | Fotogramas por segundo de una demo. | `-p` (obligatorio), `--port`, `--samples` (3), `--window` (1.0) |

### H. Medidas y rendimiento

| Herramienta | Qué hace | Argumentos |
|---|---|---|
| `bench-all` | Lanza `--measure` en varios prototipos y genera informe. | `--family cpu\|gpu\|all` (por defecto `all`), `-p N` (repetible), `--label` (`bench`), `-y`, `--list`, `--report-only`, `--no-report`, `--history` (5), `measure_args...` |
| `measure-compare` | Compara dos medidas archivadas. | `MEDIDA...`, `-p` |
| `perf-report` | Informe de rendimiento acumulado. | `--label`, `--history` (5), `-o`, `--stdout` |

---

## 4. Inconsistencias detectadas

Están ordenadas por lo que más molesta en el uso diario. Cada una lleva el
ejemplo concreto.

### 4.1 Nombres de herramientas

1. **Los verbos de «probar» se solapan.** `test` (verificación RTL con apio),
   `run-tests` (suite de software en simuladores), `test-board` (esa misma suite
   en placa), `test-all` (`test-board` en varios prototipos), `test-timings`
   (cronometra todo) y `mini-lcc-test`. Los nombres no dicen cuál es cuál.
2. **`mini-lcc` frente a `mini-cc`.** La diferencia (una unidad frente a un
   programa entero con enlace, optimización y carga) no se ve en el nombre.
3. **`build-*` mezcla dos ideas.** `build-list/status/log/stop/clean/sweep` son
   gestión de builds de apio. `build-diamond` es otra cadena de síntesis,
   `build-compare` compara las dos cadenas y `build-vlink` compila una
   herramienta C y no tiene nada que ver con síntesis.
4. **Cuatro palabras para medir:** `measure-demo`, `measure-compare`,
   `perf-report` y `bench-all`, más `test-timings` y `timing-wall`. `timing-wall`
   trata el timing de síntesis y `test-timings` el tiempo de ejecución de los
   tests; ambos dicen «timing».
5. **`sim-gpu-cycle` lleva fijo el prototipo 25** y su lanzador está escrito
   distinto de los demás (`"""Thin launcher for prototype 25."""`, en inglés,
   sin `sys.path`).
6. **Dos `list`:** `build-list --prototypes` y `list-prototypes` hacen cosas
   parecidas.
7. **Tres ficheros ejecutables con `.py` y guion en el nombre**
   (`check-links.py`, `compare-frames.py`, `frame-to-image.py`), sin lanzador ni
   `.ps1`. El resto de herramientas no lleva extensión. Además, un nombre con
   guion no se puede importar como módulo.
8. **`generate-docs`, `generate-mmio` y `generate-sysid`** son tres comandos para
   «regenerar un derivado»; los tres admiten `--check`, pero solo `generate-docs`
   admite `--root` y `--list-generators`.

### 4.2 Parámetros con el mismo significado y distinta forma

| Concepto | Variantes encontradas |
|---|---|
| Prototipo | `-p/--prototype` casi siempre. Pero `test-timings` solo tiene `--prototype`; `build_runner` lo trata como texto; `bench-all` y `test-all` lo exigen entero; `build run` tiene el valor por defecto `"17"`. |
| Obligatoriedad de `-p` | Opcional en `status/log/list/stop/clean/timing-wall/fixtures-report`; obligatorio en `test/prototype-report/board-*/font-patch/demo-no-cpu`; en `build`, excluyente con `--all`. |
| Confirmar | `-y/--yes` en la mayoría; `build-clean` y `phase-sweep` solo tienen `--yes`. |
| Salida | `-o/--output` en `mini-*` y `perf-report`; solo `--output` en `phase-sweep` y `test-timings`; posicional `salida`/`output` en los de framebuffer; `--report-dir` en `build-sweep`. |
| JSON | `--json` booleano (`list-prototypes`, `prototype-report`, `trace impact`); `--json FICHERO` en `test-timings` y en `run_tests.py` como `--results-json`; `--format` (`text` o `json`) en `trace`; `mini-asm --json FICHERO`. |
| Dirección | `--address` (`demo-no-cpu`, `phase-sweep`) frente a `--direccion` (`image-to-framebuffer`) y `--load-address` (`mini-dbg`). |
| Tamaño | `--tamano` (framebuffer) frente a `--memory-size`, `--length`. |
| Límite de ejecución | `--run-limit` (simuladores, `mini-dbg`), `--max-instrucciones` (`capture-frame-sim`), `--max-cycles` (`sim-gpu-cycle`). |
| Inclusiones | `-I/--include-dir` (`mini-asm`), `-I/--include` (`mini-dbg`), `-I` sin forma larga (`mini-lcc`, `mini-cc`). |
| Listar | Subcomando `build list`, bandera `--list` (`test-all`, `bench-all`, `build-sweep`), `--list-generators`, `--list-passes`. |
| Tests lentos | `--full/--slow` (`test`), `--full` (`test-timings`), `--skip-slow` (`run_tests`). Son tres vocabularios para lo mismo. |
| Verbosidad | `--verbose` en casi todas; `-v` y `--quiet` en `test_runner`/`test-timings`. |
| Familia CPU/GPU | `--family` con valores por defecto distintos: `all` en `test-board` y `bench-all`, `gpu` en `test-all`. |
| Paralelismo | `--jobs`: por defecto `None` (`build_runner`), `0` (`run_tests`), `1` (`test-timings`); y `-j` solo en `run_tests`. |
| Espera serie | `--serial-timeout`: 1.0 en `board-*`, `test-board`, `run_tests`; 2.0 en `mini-dbg` y `phase-sweep`. |
| Etiqueta | `--label`: por defecto `build`, `test`, `sweep`, `bench`, `medida` (`--measure-label` en `run_tests`). |

**Alias dentro de una misma herramienta.** `sim-gpu-cycle` acepta
`--num-warps`/`--warps` y `--warp-size`/`--lanes`; `sim-gpu-cycle` también tiene
`--dump` y `--dump-memory`; `test` acepta `--full` y `--slow`. Esto contradice la
decisión ya tomada de no tener alias (ver la memoria del proyecto).

**Idioma de las opciones.** La mayoría de las opciones están en inglés, pero hay
un bloque en español que casi todo el mundo desconoce: `--tamano`, `--escala`,
`--ajuste`, `--fondo`, `--direccion`, `--desde`, `--prefijo`, `--instrucciones`,
`--max-instrucciones`, `--tolerancia`, `--max-listados`, `--datos`, y los
posicionales `entrada`/`salida`. Todo ello en las herramientas de vídeo.

**Valores por defecto con nombres distintos para lo mismo en los simuladores.**
`--num-warps` vale 8 en `sim-gpu` y `sim-sys` pero `None` en `mini-dbg`;
`--warp-size` vale `None` en `sim-gpu` y 8 en `sim-sys`. `--trace-detail`
existe en `sim-gpu` y `run_tests.py` pero no en `sim-sys`. `--dump` toma
`ADDR SIZE FILE` en los simuladores de GPU y de sistema; en `sim-cpu` el texto
de ayuda debería comprobarse.

**Prototipo 36 cableado.** `mini-cc --board` dice «para la placa 36» y `--load`
tiene por defecto `"36"`. El resto de herramientas de placa usa `-p`.

### 4.3 Forma de funcionar

1. **Tres formas de reenviar argumentos.** `build_runner` y `run_board` usan
   `argparse` con subcomandos; `test-board` y `test-all` usan
   `parse_known_args` y reenvían el resto; `run-tests` recorre `argv` a mano, con
   `--` como separador. No hay una regla común sobre cómo pasar opciones a
   `run_tests.py`.
2. **Los lanzadores que necesitan `pyserial` se «re-ejecutan bajo el venv» de
   formas distintas.** `board-*`, `bench-all`, `font-patch` y `test-board`
   re-ejecutan Python; `run-board`, `build` y `test` (bash) eligen el intérprete
   antes; los `.ps1` lo eligen cada uno. El resultado es que el mismo módulo
   funciona o no según por qué lanzador entres.
3. **Los `.ps1` tienen tres estilos.** Unos fijan `PYTHONPATH` y llaman con
   `-m tools.<módulo>` (`build.ps1`, `test.ps1`, `build-diamond.ps1`); otros
   llaman al lanzador sin extensión con el Python del venv (`capture-frames.ps1`,
   `run-tests.ps1`); y `test-timings.ps1` busca el venv con otra ruta
   (`..\.venv\Scripts`), no fija `$ErrorActionPreference` y llama directo a
   `test_timings.py`.
4. **Huecos de plataforma.** `setup` no tiene `.ps1`. `build-diamond`,
   `get-documents` y `module-diagram` existen solo como `.ps1` (no hay forma de
   usarlos en Linux/macOS), y `build-vlink` solo como bash.
5. **`test-timings` importa `from test_timings import main`**, sin `tools.`, a
   diferencia de todos los demás lanzadores; funciona porque Python pone la
   carpeta del script en `sys.path`.
6. **Subcomandos frente a comandos sueltos.** `trace`, `build_runner` y
   `measure_archive` usan subcomandos; el resto de herramientas relacionadas
   usan un comando por acción (`build-list`, `build-log`...). Aun así hay
   subcomandos sin lanzador (`run`) y lanzadores que fijan el subcomando
   (`measure-compare` fuerza `compare`).
7. **Modos que cambian la semántica según una bandera.** `build-sweep` mezcla
   cinco usos (lanzar, `--list`, `--show`, `--compare`, `--promote`); `timing-wall`
   tiene catorce banderas de análisis; `image-to-framebuffer` convierte y sube;
   `mini-cc` compila, optimiza, enlaza y carga.
8. **Dos jerarquías de estado.** `build_runner` guarda estado, log y segundo plano
   (`--background`); ninguna herramienta de placa lo hace, ni siquiera
   `phase-sweep` o `bench-all`, que pueden durar mucho. `--background` solo existe
   en `build_runner`.
9. **Documentación desigual.** `tools/README.md` no menciona `build-compare`,
   `build-diamond`, `check-links`, `compare-frames`, `generate-sysid`,
   `get-documents`, `mini-dis`, `module-diagram` ni `setup`.
10. **Herramientas huérfanas.** Hay módulos con `main` y sin lanzador
    (`make_rtl_fixtures`, `gen_input_vectors`, `gen_fp32_convert_vectors`,
    `stage_programs`), y el submódulo de `mini-opt` no se documenta como
    herramienta aparte aunque `mini-cc` reexpone todas sus banderas.

---

## 5. Propuestas

Se siguen dos reglas que ya se acordaron para este repo: **un solo nombre por
concepto y renombrarlo en todas partes** (sin alias de compatibilidad), y **no
tocar lo que otra persona tenga a medias** en el árbol. Cada propuesta indica
esfuerzo (S/M/L) y riesgo.

### 5.1 Rápidas y casi sin riesgo

| # | Propuesta | Esfuerzo |
|---|---|---|
| 1 | Añadir a `tools/README.md` las nueve herramientas que no figuran (ver 4.3.9) y enlazar este documento desde su cabecera. | S |
| 2 | Quitar los alias: `--warps`, `--lanes` y `--dump-memory` en `sim-gpu-cycle`, y `--slow` en `test`. Elegir `--num-warps`, `--warp-size`, `--dump`, `--full`. | S |
| 3 | Dar `-y` a `build-clean` y a `phase-sweep`, y `-p` a `test-timings`. | S |
| 4 | Corregir el valor por defecto `"17"` de `build run -p` (pedir `-p` explícito, como en `test`). | S |
| 5 | Dar a `setup` un `.ps1` y a `build-diamond`, `build-vlink` y `module-diagram` un lanzador bash o una nota explícita de «solo Windows/Linux». | S |
| 6 | Hacer que `test-timings` use el mismo molde de lanzador que los demás (`sys.path` + `from tools.test_timings import main`). | S |
| 7 | Unificar `--serial-timeout` en un solo valor por defecto (1.0 o 2.0) en un único sitio (`_add_common_args`) y reutilizarlo en `mini-dbg` y `phase-sweep`. | S |

### 5.2 Unificación de parámetros

| # | Propuesta | Esfuerzo |
|---|---|---|
| 8 | **Un módulo `tools/cli_common.py`** con funciones `add_prototype()`, `add_port()`, `add_serial_timeout()`, `add_yes()`, `add_output()`, `add_json()`, `add_verbosity()`. Cada herramienta las importa en vez de redeclararlas. Hoy hay `_add_common_args` en `run_board.py` y nada parecido en el resto. | M |
| 9 | Fijar la convención: `-p/--prototype` siempre texto resuelto por `prototype.py`; `-y/--yes` en todo lo que pregunte; `-o/--output` siempre fichero y `--output-dir` siempre carpeta. | M |
| 10 | Una sola política para JSON: `--json` booleano que escribe a stdout. Renombrar `test-timings --json FICHERO` a `--output-json` y `run_tests --results-json`/`--timings-json` a la misma familia; `trace --format json` pasa a `--json`. | M |
| 11 | Pasar a inglés las opciones en español de las herramientas de vídeo: `--tamano`→`--size`, `--escala`→`--scale`, `--ajuste`→`--fit`, `--fondo`→`--background-color`, `--direccion`→`--address`, `--desde`→`--first-swap`, `--prefijo`→`--prefix`, `--instrucciones`→`--instructions`, `--max-instrucciones`→`--max-instructions`, `--tolerancia`→`--tolerance`, `--max-listados`→`--max-listed`, `--datos`→`--data`. Los posicionales `entrada`/`salida` pasan a `input`/`output`. (Alternativa si prefieren castellano: traducir al revés, pero hacerlo en todo el repo.) | M |
| 12 | Un vocabulario para «lento»: `--full` para incluir lo lento, y quitar `--skip-slow` o dejarlo solo como inverso documentado. | S |
| 13 | Un único valor por defecto de `--family` (propongo `all`) y que `test-all` lo declare igual que `bench-all` y `test-board`. | S |
| 14 | `--jobs` con la misma semántica en todas partes (0 = automático) y `-j` como forma corta en todas. | S |
| 15 | Unificar los simuladores: mismas banderas de `--run-limit`, `--memory-size`, `--num-warps`, `--warp-size`, `--dump`, `--trace*` con los mismos valores por defecto (8 y 8) en `sim-gpu`, `sim-sys`, `sim-gpu-cycle` y `mini-dbg`. | M |
| 16 | Quitar el 36 cableado de `mini-cc`: `--board` y `--load` pasan a `-p/--prototype` + `--load`. | S |

### 5.3 Nombres de herramientas

Se propone una familia de prefijos por tema. Los nombres actuales irían a la
columna izquierda y desaparecerían (sin alias); habría que actualizar `README`,
`AGENTS.md`, `Makefile`, `.ps1` y la memoria.

| Hoy | Propuesta | Motivo |
|---|---|---|
| `test` | `rtl-test` | Es la verificación RTL con apio. |
| `lint` | `rtl-lint` | Mismo grupo. |
| `check` | `rtl-check` | Test + lint + build. |
| `run-tests` | `sw-test` | Suite de software en simuladores. |
| `test-board` | `board-test` | Sigue el patrón `board-*`. |
| `test-all` | `board-test-all` | Idem. |
| `test-timings` | `test-profile` | Evita el choque con `timing-wall`. |
| `build-vlink` | `vlink-build` | No es una síntesis. |
| `measure-demo`, `measure-compare`, `perf-report`, `bench-all` | `measure-*` (`measure-demo`, `measure-compare`, `measure-report`, `measure-all`) | Un solo prefijo para medidas. |
| `compare-frames.py`, `frame-to-image.py`, `check-links.py` | `frame-compare`, `frame-to-image`, `check-links` (sin `.py`, con lanzador y `.ps1`) | Mismo molde que el resto. |
| `capture-frames`, `capture-frame-sim`, `make-framebuffer`, `image-to-framebuffer`, `demo-no-cpu` | prefijo `frame-` o `video-` | Un grupo, un prefijo. |

La renombración de `test`/`lint`/`check` es la de mayor impacto, porque aparece
en muchos documentos. Convendría hacerla con `generate-docs --check` y
`check-links` en verde como criterio de aceptación.

### 5.4 Forma de funcionar y mantenimiento

| # | Propuesta | Esfuerzo |
|---|---|---|
| 17 | **Un único lanzador genérico.** Hoy hay unos 60 ficheros sin extensión y unos 60 `.ps1` casi idénticos. Un solo `tools/_launch.py` (que elija el intérprete, el venv y el módulo) más una tabla `tools/commands.toml` (nombre → módulo o script) permitiría generar los lanzadores o sustituirlos por un solo punto de entrada (`tools/mgpu <comando>`). Es lo que más reduce el volumen de ficheros. | L |
| 18 | Si se prefiere no tocar los comandos, **generar** los lanzadores y los `.ps1` desde esa tabla con un comando `tools/gen-launchers` y comprobar en CI que están al día (igual que `generate-docs --check`). | M |
| 19 | Sustituir el `argv` manual de `run-tests` por `argparse` con `parse_known_args`, igual que `test-board`. | S |
| 20 | Hacer que todo lo que pueda durar más de unos minutos (`phase-sweep`, `bench-all`, `test-all`, `test-timings`) pueda correr con el mismo `--background` y el mismo `status/log/stop` que `build_runner`. | L |
| 21 | Partir `build-sweep` en `build-sweep run` y `build-sweep show/list/compare/promote` (o sacarlos a `sweep-*`), y `timing-wall` en modos con subcomandos. | M |
| 22 | Mover `mini_cc.py` y `mini_opt/` bajo una carpeta `tools/compiler/` junto a `mini-lcc`, y los `sim_*`, `debug_*`, `monitor_protocol` a `tools/sim/` y `tools/debug/`. Hoy `tools/` mezcla ~190 ficheros. | M |
| 23 | Añadir un test que recorra todos los lanzadores con `--help` y compruebe que: existe `.ps1` (o está en una lista de excepciones), el nombre usa `kebab-case` y las opciones comunes tienen el mismo nombre y valor por defecto. Evita que las inconsistencias vuelvan. | M |
| 24 | Generar de forma automática la tabla de la sección 3 desde `argparse` (como ya hacen los generadores de `generate-docs`), para que este documento no se desactualice. | M |

### 5.5 Orden sugerido

1. Propuestas 1 a 7 (un día, sin tocar nombres de comandos).
2. Propuestas 8 a 16 (convenciones de parámetros), de una en una y con los tests
   del repo en verde.
3. Propuestas 17 y 18 (lanzadores), antes de renombrar nada: así el cambio de
   nombres de 5.3 se hace en un solo sitio.
4. Los renombrados de comandos de 5.3, una sola vez y con búsqueda
   global en `.md`, `.ps1`, `Makefile` y la memoria del proyecto.
5. Propuestas 20 a 24.

---

## 6. Qué conviene verificar antes de actuar

- Los valores por defecto y las ayudas se han leído en el código. Conviene lanzar
  `--help` en las herramientas que se vayan a tocar.
- No se han inspeccionado `monitor.py` ni las herramientas propias de cada
  prototipo (`<prototipo>/monitor.py`, `Makefile`), que también forman parte de la
  experiencia de línea de órdenes.
- No se ha buscado qué documentos o scripts invocan cada herramienta por nombre.
  Antes de renombrar hay que hacer esa búsqueda.
