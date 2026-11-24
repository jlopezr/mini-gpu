# Herramientas del repositorio: inventario, inconsistencias y propuestas

Este documento cataloga lo que hay en [tools/](../tools/) (y los lanzadores de
`tools/` que apuntan a otras carpetas), agrupado por tema. Para cada herramienta
da su propósito y sus argumentos. Después recoge las inconsistencias de nombre,
de parámetros y de forma de funcionar, y termina con una lista de propuestas de
mejora, unificación y simplificación.

Para los detalles de uso y los ejemplos, el manual sigue siendo
[tools/README.md](../tools/README.md). Este documento es un mapa y un análisis, no
lo sustituye.

**Actualizado** tras añadir `--bitstream` y `--toolchain` a `test-board` y tras
cambiar `_sources_changed` (commit `b196f98`); el resto del inventario es de la
primera versión.

**Aplicadas las propuestas 1 a 16 y la 16b** (secciones 5.1 y 5.2). Las secciones 3 y 4 describen el
estado *anterior* a ese cambio; donde difiere, manda 5.1 y el código.

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
| `mini-cc`       | C completo (varios `.c`) a imagen, opcionalmente cargada en placa. | `program`, `otro...`, `-o/--output`, `--output-dir`, `-I`, `-D`, `--data ETIQUETA=FICHERO`, `-p`, `--load`, `--no-run`, `--fp32`, `--far-calls`, `--opt-stats`, y las de `mini-opt` (`--assume-noalias`, `--extern-refs`, `--whole-program`, `--passes`, `--stats`) |
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
| `run-tests`    | `t.tests/run_tests.py` contra simuladores.                          | `--quick`, `--verbose`, `--hardware`, `--`; el resto se reenvía. *(Ahora con `argparse`, propuesta 19.)*                                                                                                                                                  |
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

**Qué bitstream hay en la placa.** `board-upload` y `test-board` pueden programar
un build archivado de `reports/` (apio o Diamond) en vez del de `_build/default`:

| Orden | Qué programa |
|---|---|
| `board-upload -p N --bitstream RUTA` | El `hardware.bit` de esa ruta o carpeta. No sella la subida. |
| `test-board -p N --bitstream RUTA` | Lo mismo, y después lanza la suite con `--no-upload` (retira `-y`). |
| `test-board -p N --toolchain apio\|diamond` | El build más nuevo de esa herramienta con `hardware.bit`, `exit_code` 0 y fuentes iguales a las actuales (`board_record.find_latest_build`). Si no hay ninguno, falla y dice por qué sin tocar la placa. |
| `test-board -p N` (sin ninguna) | Lo que haya en la placa; con `-y`, si cree que está desfasado, sube el de apio de `_build/default` y recompila si hace falta. |

Una prueba con `--bitstream`/`--toolchain` deja su `board-tests.json` en la carpeta
de ese build, porque el registro se asocia por el hash del `.bit` (es lo que rellena
la columna BOARD de `build-list --prototypes`). Para decidir si el RTL «ha cambiado»,
`run_tests` ya no mira solo el bitstream de apio: si lo último que se programó es un
build archivado de este prototipo con las fuentes actuales, lo da por bueno
(`_sources_changed` en `t.tests/backends/board.py`). La comparación ignora
`diamond-constraints.txt`: un cambio solo de restricciones no invalida un build.

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
| Elegir el bitstream | `--bitstream RUTA` en `board-upload` y `test-board`; `--bitstream [NOMBRE=]RUTA` repetible y obligatorio en `phase-sweep`; `--toolchain apio\|diamond` solo en `test-board`; `board-upload`, `run-board` y `test-all` no la tienen. *(Resuelto con la 16b: ahora `-b/--bitstream` y `-t/--toolchain` en todas.)* |

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
   `parse_known_args` y reenvían el resto; `run-tests` también (antes recorría
   `argv` a mano, propuesta 19), y además acepta `--` como separador. Los tres
   reenvían a `run_tests.py` lo que no reconocen. Además, `test-board` ya no es un reenvío puro: con
   `--bitstream`/`--toolchain` lee `-y` de lo reenviado, lo retira y añade
   `--no-upload` (porque `run_tests` no admite `-y` y `--no-upload` a la vez).
   Es una regla implícita que no se ve en la línea de órdenes.
   `--bitstream`/`--toolchain` tampoco existen en `run-board` ni en `test-all`.
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
| 1 | **Hecho.** `tools/README.md` recoge ahora las nueve herramientas (sección «Otras herramientas») y enlaza este documento desde su cabecera y desde la sección de Windows. | S |
| 2 | **Hecho.** Quitados `--warps`, `--lanes` y `--dump-memory` (`sim-gpu-cycle`) y `--slow` (`test`, en `build_runner.py` y `test_runner.py`). Quedan `--num-warps`, `--warp-size`, `--dump`, `--full`. Pendiente: `--config`/`--warp-config`, que sigue siendo un alias en `sim-gpu-cycle`. | S |
| 3 | **Hecho.** `-y` en `build-clean` y `phase-sweep`; `-p` en `test-timings`. | S |
| 4 | **Hecho.** `build run -p` es obligatorio; ya no hay valor por defecto `"17"`. | S |
| 5 | **Hecho.** `setup.ps1` creado. `build-vlink` ya tenía `.ps1` (el inventario lo daba por solo bash). `build-diamond`, `module-diagram` y `get-documents` siguen siendo solo `.ps1` a propósito (Diamond y la ruta de `netlistsvg` son de Windows) y queda dicho en `tools/README.md`. | S |
| 6 | **Hecho.** `test-timings` usa `sys.path` + `from tools.test_timings import main`; su `.ps1` sigue el molde común (llama al lanzador sin extensión). | S |
| 7 | **Hecho, con 1,0 s.** Nuevo `tools/cli_common.py` con `DEFAULT_SERIAL_TIMEOUT` y `add_serial_timeout()`, usado por `run_board` (y con él `board-*`, `test-board`, `run-board`), `run_tests.py`, `mini-dbg`, `phase-sweep` y `debug_board.py`. Se eligió 1,0 (el de `board-*`, `test-board` y `run_tests`); `mini-dbg` y `phase-sweep` bajan desde 2,0, así que si alguna lectura larga de `phase-sweep` expira hay que subirlo con `--serial-timeout`. Es una constante. Es también el primer contenido de la propuesta 8. | S |

### 5.2 Unificación de parámetros

| # | Propuesta | Esfuerzo |
|---|---|---|
| 8 | **Hecho (parcial).** `tools/cli_common.py` tiene `add_prototype`, `add_port`, `add_serial_timeout`, `add_yes`, `add_output`, `add_output_dir`, `add_json`, `add_verbosity`, `add_jobs`, `add_family` y `prototype_number`. Lo usan `run_board`, `phase_sweep`, `prototype_report`, `font_patch`, `test_all`, `bench_all`, `debug_cli`, `debug_board` y `run_tests`. Quedan sin migrar los `argparse` de `build_runner`, `test_runner`, `test_timings`, `trace`, los lanzadores sin módulo y los simuladores (viven en carpetas de prototipo y declaran sus propias opciones). | M |
| 9 | **Hecho (parcial).** `-p` pasa a texto resuelto por `prototype.py` en `bench-all` y `test-all` (`prototype_number`), y se añade `-p` a `build-diamond` y a `stage_programs`. `-y` en `phase-sweep` y `build-clean`. `--output-dir` solo donde es una salida: `--report-dir` de `build-sweep` era en realidad el build de origen y pasa a `--build-dir`; `--output` de `phase-sweep` era un prefijo y pasa a `--output-prefix`. `mini-cc --outdir` pasa a `--output-dir` en todos los usos, incluido `u.lcc/runtime/fuzz-softfloat.py` (submódulo: ese cambio hay que commitearlo dentro de `u.lcc`; además llamaba a `tools/build-c`, que ya no existe, y ahora llama a `mini-cc`). | M |
| 10 | **Hecho.** `trace --format json` es ahora `--json` (también en los tests, el README y `minitour.md`); `test-timings --json FICHERO` es `--output-json`; `run_tests --results-json`/`--timings-json` son `--output-results-json`/`--output-timings-json`. Pendiente: `mini-asm --json FICHERO` (vive en `1.isa/asm2`). | M |
| 11 | **Hecho.** Opciones y posicionales en inglés en `image-to-framebuffer`, `capture-frames`, `capture-frame-sim`, `frame-to-image.py`, `compare-frames.py` y `asm-sizes`: `--size`, `--scale`, `--fit` (valores `crop`/`fit`/`stretch`), `--background-color`, `--address`, `--first-swap`, `--prefix`, `--instructions`, `--tolerance`, `--max-listed`, `--data`, `input`/`output` y `expected`/`actual`. `--max-instrucciones` no pasa a `--max-instructions` sino a `--run-limit`, el nombre acordado en todo el repo para este límite. Pendiente: `--direcciones` de los `sdram_dq_matrix.py` de cada prototipo. | M |
| 12 | **Hecho (por la vía corta).** `--full` incluye lo lento en `test` y `test-timings`. `--skip-slow` de `run_tests` se queda como el inverso documentado: allí lo lento corre por defecto, y invertirlo cambiaría qué corre `test-board`. La ayuda ya lo explica. | S |
| 13 | **Hecho.** `--family` vale `all` por defecto en `test-all`, `test-board` y `bench-all`. Con `all`, la 36 y la 37 salen dos columnas en la matriz de `test-all` (CPU y GPU), tituladas `36 CPU` y `36 GPU`. | S |
| 14 | **Hecho.** `-j/--jobs` con `0` = automático en `test`, `build-sweep`, `run-tests` y `test-timings`. Los valores por defecto no cambian: `test-timings` sigue en 1 a propósito (tiempos comparables), `test` en 2 (`AUTO_JOBS`) y `build-sweep` en un tercio de los hilos. | S |
| 15 | **Hecho (lo que cambia el comportamiento sin riesgo).** `sim-sys` gana `--trace-detail`; las ayudas de `--num-warps`, `--warp-size` y `--run-limit` dicen el mismo valor por defecto en los cuatro. `--warp-size` queda en `None` en `sim-gpu` y `mini-dbg` porque es el centinela de «no lo pedí» (con `--config` hay que comprobar que no choque, y `mini-dbg` rechaza opciones de GPU sin `--gpu`): el efectivo es 8 en todos. | M |
| 16 | **Hecho.** `mini-cc` no lleva el 36 cableado: `-p PROTOTIPO` compila para la placa de ese prototipo y `--load` (que exige `-p`) la sube. Desaparece `--board`. `tools/c-program.mk` pasa `-p $(PROTOTYPE)`. | S |
| 16b | **Hecho.** `-t/--toolchain apio\|diamond` y `-b/--bitstream RUTA` (formas cortas nuevas) en `board-upload`, `run-board` y `test-board`; `-t` en `test-all` (por prototipo; `-b` no tiene sentido con varios prototipos) y `-b [NOMBRE=]RUTA` + `-t` repetibles en `phase-sweep` (con `-t` hace falta `-p`, y la etiqueta es el nombre de la herramienta). Todas usan `board_record.find_latest_build` vía `run_board.archived_source`, y las definiciones están en `cli_common.add_bitstream`/`add_toolchain`/`add_archived_build`. `-b` y `-t` son excluyentes y no se combinan con `--rebuild` ni `--no-upload`. | S |

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
| 19 | **Hecho.** `run-tests` usa `argparse` con `parse_known_args` (`allow_abbrev=False`, para que `--ver` no se convierta en `--verbose`). Reenvía a `run_tests.py` lo que no reconoce, en orden, y todo lo que sigue a `--`, sin interpretarlo; `-h` ya da la ayuda de `argparse`. Test nuevo: `t.tests/unit/tools/test_run_tests_launcher.py`. | S |
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
