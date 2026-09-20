# tools/

Infraestructura común del repositorio: lanzadores que funcionan desde cualquier
directorio una vez `tools/` está en el `PATH`, y que reutilizan la lógica que ya
vive en cada prototipo (simuladores, backends de placa) en vez de duplicarla.
`build`/`build-sweep`/`prototype-report` son genéricos: no dependen de qué
prototipo es, solo de en qué carpeta corren.

```bash
export PATH="$PWD/tools:$PATH"
```

Todo lo de aquí abajo funciona igual si lo lanzas desde la raíz del repo, desde
`17.fpga-gpu-ram-v2/`, o desde `/tmp`: cada comando localiza la raíz del
repositorio solo (por `MINI_GPU_ROOT`, por su propia ruta, o buscando
`tools/` + `README.md`).

## Comprobar la trazabilidad documental

`trace check` construye un Project Model conforme al metamodelo v0.3. Un fichero
Markdown es un `RESOURCE`, no una identidad semántica. Los `ARTIFACT` se
declaran explícitamente mediante un comentario seguido de su heading:

```markdown
<!-- trace:artifact IMPL-MINIGPU
type: implementation
subjects: [isa, cpu, gpu]
implements:
  - SPEC-ISA
-->

# Implementación MiniGPU
```

El ID es global, sensible a mayúsculas y no deriva del `type`. Los headings
dentro del artifact crean `SECTION` locales como `SPEC-ISA#ssy`; una sección
que sea origen de relaciones necesita un ID formal `{#ssy}` y una directiva
`trace:relations`. Los enlaces Markdown ordinarios no crean relaciones.

El checker valida metadata YAML, tipos core, IDs únicos, atributos de relación,
targets exactos y relaciones duplicadas. Solo conserva las relaciones authored
en su dirección canónica; `trace show` calcula la vista inversa al consultar.

Este vertical slice implementa `RESOURCE`, `ARTIFACT`, `SECTION` y relaciones
Markdown. `trace.yaml` controla el discovery con patrones `scan` y `exclude`:

```yaml
project: minigpu
version: 1
scan:
  - "**/*.md"
exclude:
  - build/**
  - .git/**
```

La configuración es estricta: campos desconocidos, versiones no soportadas y
listas de patrones inválidas son errores. Una ruta explícita tampoco puede
saltar los límites de `scan`/`exclude`.

### Caché del grafo

Cada adapter produce un fragmento de modelo por `RESOURCE`, almacenado en
`.trace/cache-v1.json` (ignorado por Git). La caché conserva identidades,
relaciones pendientes, diagnósticos, localizaciones y dependencias:

- si `mtime_ns` y tamaño no cambian, no se abre el fichero;
- si cambia la metadata pero no el tamaño, se calcula SHA-256 y se reutiliza el
  fragmento cuando el contenido sigue siendo idéntico;
- si cambia el contenido o la versión del adapter, se vuelve a parsear;
- los resources borrados salen del grafo activo y conservan su último fragmento
  como tombstone para el análisis de impacto;
- un sidecar se invalida también cuando cambia, aparece o desaparece el recurso
  que describe.

El resolver reconstruye siempre el grafo global desde los fragmentos para que
duplicados y referencias reflejen el conjunto actual. `trace check --no-cache`
permite forzar una lectura completa; la salida normal informa hits y misses.

### Análisis de impacto

`trace impact` recorre en ambos sentidos únicamente las relaciones explícitas
del grafo y muestra una ruta mínima que explica cada resultado. Acepta una
identidad o un recurso; cuando se indica un recurso, todas las identidades que
proceden de él son puntos de partida:

```bash
$ trace impact SPEC-DEVICE#identity-register
$ trace impact tools/traceability/example/validation.py --depth 2
$ trace impact REQ-DEVICE-IDENTITY --json
```

La salida separa afectados directos y transitivos. `--depth N` limita el
recorrido y `--json` ofrece IDs, localizaciones, profundidad y cada salto de la
ruta para integraciones. El recorrido es una vista de conectividad: no añade
relaciones semánticas ni invierte su dirección canónica; cada salto indica si
se recorrió una relación en sentido `outgoing` o `incoming`.

Si un recurso desaparece después de haber sido cacheado,
`trace impact ruta/al/recurso` utiliza su tombstone y lo marca expresamente en
la salida. Esta posibilidad depende de la caché descartable: con `--no-cache`,
o si se borra `.trace/cache-v1.json`, no existe historial del recurso eliminado.

### Navegación del grafo

La API pública `Graph` construye una vez los índices por ID, tipo de elemento,
tipo de artifact, `kind` y `subject`, además de relaciones entrantes, salientes
y ownership estructural. Los comandos de consulta usan esos mismos índices:

```bash
$ trace list --type specification
$ trace list --kind capability --format json
$ trace incoming SPEC-DEVICE#identity-register --relation implements
$ trace outgoing IMPL-DEVICE-PROBE --relation implements
$ trace tree SPEC-DEVICE
$ trace path VER-DEVICE-IDENTITY::identity-read IMPL-DEVICE-PROBE::read-identity
```

`tree` recorre estructura (`owner` y `parent-facet`), no relaciones semánticas.
`path` recorre relaciones explícitas en ambos sentidos y devuelve el camino más
corto, indicando en cada salto si utilizó la dirección canónica o su vista
inversa. `show`, `list`, `incoming`, `outgoing`, `tree`, `path` e `impact`
aceptan `--format text|json`; `impact --json` se conserva como alias.

Una `FACET` se declara dentro de un artifact y se asocia a una sección formal
con el mismo ID local:

```markdown
<!-- trace:facet calls
kind: capability
-->

## Function calls {#calls}
```

Esto crea `SPEC-ISA@calls` y `SPEC-ISA#calls`. Su subtree determina el alcance;
las facets anidadas conservan `parent-facet` y cada sección guarda únicamente
su facet inmediata. Una frontera de artifact termina cualquier facet activa.

Todavía no se interpretan sidecars, otros lenguajes de código, jerarquía de
símbolos ni generación `gendoc`; únicamente se ignora correctamente el
contenido situado dentro de bloques `gendoc` al construir el modelo.

### Anotaciones SystemVerilog

El adapter SystemVerilog ofrece nivel 1–2: enlaza grupos de comentarios al
siguiente `module` y reconoce artifacts, módulos nombrados y símbolos formales.

```systemverilog
// @artifact IMPL-MINIGPU type=implementation
// @implements SPEC-ISA
module minigpu (...);

// update-mask @implements SPEC-SIMT#active-mask
module mask_writer (...);
```

En el primer grupo las relaciones salen del ARTIFACT. En el segundo, el ID
formal produce `IMPL-MINIGPU::update-mask`. También se admite `@id local-id`
como anotación separada. Whitespace y comentarios normales no rompen el grupo;
otro elemento sintáctico sí lo rompe y produce un diagnóstico.

Python y ensamblador MiniISA reutilizan exactamente la misma gramática. Python
asocia los grupos al siguiente `class`, `def` o `async def` (admite decoradores
entre ambos); ASM los asocia al siguiente label. Sus comentarios son `#` y `;`
respectivamente. Como en SystemVerilog, el código no anotado permanece como
RESOURCE y no genera un inventario de SYMBOLs.

### Sidecars

Un fichero `<basename>.trace.yaml` aporta metadata a un recurso que no conviene
modificar. Puede declarar cualquier tipo de ARTIFACT; no implica `source` por
sí mismo.

```yaml
artifact: SRC-W9825G6KH-DATASHEET
type: source
kind: datasheet
resource:
  file: w9825g6kh.pdf
  revision: "Rev. A"
  sha256: "..."
```

`resource.file` se resuelve respecto al sidecar y no puede salir de la raíz.
Debe existir. Si se proporciona `sha256`, `trace check` valida su formato y el
contenido. La metadata desconocida es un error y el artifact puede declarar
las mismas relaciones core que una representación Markdown.

```bash
trace check                         # todos los Markdown del repositorio
trace check README.md docs/         # solo observaciones de esas rutas
trace check --root /ruta/mini-gpu   # raíz explícita para CI
trace show REQ-DEVICE-IDENTITY      # declaración y relaciones de una identidad
```

Al seleccionar rutas se siguen indexando las identidades de todo el repositorio,
de modo que sus enlaces pueden resolverse fuera del subconjunto. El comando
devuelve 0 si todo resuelve, 1 si encuentra diagnósticos y 2 si el uso o una
ruta de entrada no son válidos.

Hay un [ejemplo autocontenido](traceability/example/README.md) con requisito,
decisión, especificación, implementación y verificación. Sirve como recorrido
mínimo y especificación ejecutable del adapter Markdown.

## Windows: un `.ps1` por cada lanzador

Un fichero sin extensión no se puede ejecutar directamente en Windows (no hay
shebang), así que cada lanzador de `tools/` tiene un `.ps1` homónimo. Todos
son adaptadores finos que reenvían tal cual a python (`@args`); no hay lógica
propia en PowerShell en ninguno, así que las opciones son siempre las del
script Python correspondiente: `--prototype`/`-p`, doble guion.

## Resolver un prototipo

Los comandos Python que aceptan `--prototype` también aceptan `-p` (equivalen
al mismo argumento: `-p 17` y `--prototype 17` son intercambiables).

Entienden cuatro formas equivalentes de identificar un prototipo, y resuelven
un número ambiguo o inexistente con un error explícito en vez de adivinar:

```bash
$ list-prototypes | grep -m1 17
PROTOTYPE               TITLE
...
17.fpga-gpu-ram-v2      MiniGPU con SDRAM v2: 8 warps × 8 lanes             sí     no    sí     no

$ python3 tools/prototype.py 17
/Users/tú/mini-gpu/17.fpga-gpu-ram-v2

$ python3 tools/prototype.py 17.fpga-gpu-ram-v2   # nombre completo, mismo resultado
$ python3 tools/prototype.py ./17.fpga-gpu-ram-v2 # ruta relativa
$ python3 tools/prototype.py 99
error: No existe ningún prototipo para '99'. Disponibles: 0.mandelbrot, 1.isa, ...
```

`list-prototypes` es el punto de partida cuando no te acuerdas del nombre
exacto de una carpeta: lista todo en orden numérico (1, 2, ..., 10, 11, no
alfabético) con el título de su `README.md`, el backend detectado en el RTL
(`cpu`/`gpu`/`—`) y si tiene `apio.ini` (si lo tiene, `build`/`test`/`lint`/
`build-sweep` funcionan ahí sin más).

## Ensamblar y simular un programa

Lanzadores finos: ejecutan el script real de la carpeta correspondiente, no
una reimplementación.

```bash
> miniisa examples/vector.asm            # -> 1.isa/miniisa_asm.py
> cpusim examples/vector.asm             # -> 2.cpu-sim-func/minicpu_sim.py
> gpusim examples/vector.asm             # -> 11.gpu-sim-func/minigpu_sim.py
> gpusim-cycle examples/vector.asm       # -> 25.gpu-sim-cycle-uarch/minigpu_cycle.py
```

Cada uno acepta los mismos argumentos que el script al que llama (pásale
`--help` para verlos).

Los tres simuladores aceptan **`.asm`, `.bin` o `.hex`**, y ensamblan solos si
hace falta. La carga es `load_program_bytes()` de `1.isa/miniisa_asm.py`, una
sola para los tres: antes cada simulador hacía lo suyo, y estos ejemplos con
`.asm` solo funcionaban en `gpusim-cycle` — los otros dos leían el fichero como
binario y morían con «el programa debe contener instrucciones completas», que
es el síntoma (el texto fuente no mide un múltiplo de 4) y no la causa.

Ojo con los casos de `x.tests`: muchos traen un `warps.json` que hay que pasar
con `--config`, o el simulador lanza los 8 warps por defecto en vez de los que
el caso espera.

```bash
$ gpusim x.tests/cases-gpu/memory/memory-copy/program.asm \
         --config x.tests/cases-gpu/memory/memory-copy/warps.json --trace
```

El modelo 25 ejecuta la futura microarquitectura S/F/I/D/X/W. Acepta
`--trace ciclos.jsonl`, `--report perfil.json`, latencias parametrizables y
`--imem-lines 0` para fetch ideal. Tests: `test --prototype 25 --quick`.
Los casos existentes también se ejecutan con
`python x.tests/run_tests.py --backend gpusim --version cycle x.tests/cases-gpu`.

### Periféricos comunes de los tres simuladores

`cpusim`, `gpusim` y `gpusim-cycle` comparten `tools/sim_devices.py` y las
opciones de `tools/sim_peripherals.py`:

| Opción | Efecto |
|---|---|
| `--video` | Activa registros de vídeo en `0x80000000` |
| `--frame-instructions N` | Periodo sintético del frame, 1000 por defecto; debe ser positivo |
| `--halt-after-swaps N` | Activa vídeo y arma `HALT_AT` para parar tras N swaps |
| `--frame-output frame.bin` | Activa vídeo y guarda el framebuffer frontal RGB565 de 320×240 |
| `--serial` | Activa serie en `0x80000200` |
| `--serial-input entrada.bin` | Activa serie y precarga los bytes de entrada |
| `--serial-output salida.bin` | Activa serie y recoge la salida durante toda la ejecución |

Por ejemplo, las mismas opciones sirven con cualquiera de los tres lanzadores:

```powershell
.\tools\cpusim.ps1 programa.asm --serial-input entrada.bin --serial-output salida.bin
.\tools\gpusim-cycle.ps1 dibujo.asm --video --halt-after-swaps 2 --frame-output frame.bin
```

`SYS_ID` siempre está disponible, también mediante LOAD en la 25. Vídeo y serie
son opcionales en la API (`video=VideoDevice()`, `serial=SerialDevice()`). El
runner `x.tests` conecta serie en los tres modelos y vídeo cuando lo pide el
caso; los tres declaran `video`, `frame_capture` y `serial`.

El contrato funcional de vídeo incluye `SWAP_COUNT`, `HALT_AT` y `VIDEO_CTRL`.
Las bases arrancan a cero y las configura el programa; se alinean a 4 bytes en
los tres modelos. Una escritura a `SWAP` pide intercambio, incluso con valor
cero. Para portabilidad al RTL GPU, alinear bases a 16 y escribir 1 a `SWAP`.
El RTL GPU no gana serie ni `HALT_AT` por esta unificación de simuladores.

El frame se mide en instrucciones CPU o de warp, no en ciclos del pipeline.
Los puntos de avance y el orden entre warps dependen del motor: no se promete
el mismo PC al capturar. No se simulan desgarro, underflow ni tiempo físico de
UART/HDMI. `--frame-output` vuelca RAM desde `FB_FRONT`, no renderiza PATTERN ni
BLANK. Los accesos MMIO requieren palabras alineadas de 32 bits.

## Ejecutar la suite de tests

`x.tests` (backends de placa/simulador, casos, runner) tiene su propio
`./test` local; `run-tests` es el mismo script accesible desde cualquier sitio:

```bash
$ run-tests
== Tests unitarios de infraestructura ==
...
== Suite de casos (run_tests.py) ==
...

$ run-tests --quick              # solo los test_*.py, sin simular casos (rápido)
$ run-tests --hardware           # casos contra placa real, backend gpu-fpga
$ run-tests -- --backend cpu-fpga               # passthrough directo a run_tests.py; detecta el puerto FTDI si no pasas --port
```

## Compilador C experimental (`mini-lcc`)

El fork de lcc con backend MiniISA se integra como submodulo en
`y.lcc`, no dentro de `tools/`: `tools/` conserva solo los lanzadores y la
infraestructura propia del repo. Para inicializarlo:

```bash
$ git submodule update --init --recursive y.lcc
```

La validacion propia del compilador se puede lanzar directamente:

```bash
$ mkdir -p y.lcc/build
$ python3 y.lcc/run-mini-tst.py --simulate
```

O mediante el wrapper global:

```bash
$ mini-lcc-test
```

Para compilar un programa C a ensamblador MiniISA:

```bash
$ mini-lcc programa.c -o programa.s
```

Por ahora esta validacion comprueba compilacion y simulacion dentro de
`mini-lcc`. El siguiente paso sera usarlo para producir `.asm`, `.bin` o
manifiestos `.json` desde programas C y alimentar con ellos los simuladores y
las suites de `x.tests`.

## Build con historial de timing, en segundo plano, estado, logs

`tools/build` (con `tools/build_report.py`) es común a cualquier prototipo con
`apio.ini` — no hace falta copiar nada a su carpeta. Sintetiza con apio,
resume Fmax/LUT/FF/camino crítico y archiva un historial reproducible en
`<prototipo>/reports/`:

```bash
$ build --prototype 17 --label synth --background
Using prototype: 17.fpga-gpu-ram-v2
Started build: 20260915-001203-synth
Status: .../reports/20260915-001203-synth/status.json
Log: .../reports/20260915-001203-synth/build.log
```

`--archive-only` archiva los resultados existentes sin volver a sintetizar;
`--incremental` usa la caché normal de apio (sin progreso de PNR en vivo).
Funciona igual sin `--background` (bloquea hasta terminar, con la misma
salida por pantalla).

Desde otra terminal (o desde otro directorio: `build-status` también acepta
`--prototype` para encontrarlo sin tener que estar dentro de la carpeta):

```bash
$ build-status --prototype 17
Prototype: 17.fpga-gpu-ram-v2
Label: synth
State: running
PID: 47021
Elapsed: 02:14
Recent output:
...

$ build-log --prototype 17 --lines 50
$ build-log --prototype 17 --follow        # como tail -f / Get-Content -Wait
$ build-list --prototype 17                # builds anteriores, más nuevo primero
$ build-stop --prototype 17                # SIGTERM al build activo
```

`--background` devuelve el control enseguida: crea `status.json` de inmediato
y sigue el proceso en segundo plano de verdad (grupo/sesión propios), no
bloquea la terminal que lo lanzó. Si lo paras con `build-stop`, el estado
queda en `stopped`, no en `failed`.

Cuando ya no necesitas builds antiguos:

```bash
$ build-clean-logs --dry-run              # qué borraría, sin borrar nada
$ build-clean-logs --prototype 17 --keep 5 --yes
```

Por defecto conserva los 10 builds más recientes, los de los últimos 30 días,
cualquier build `running`, y el último `success` — nunca borra sin `--yes`.

## Suite de un prototipo (`test`)

Igual que `build`: común a cualquier prototipo, sin copiar nada a su carpeta.
Cada paso se salta con claridad si no aplica — no todos los prototipos tienen
`make_fixtures.py`, `test_*.py` propios o `apio.ini`:

```bash
$ test --prototype 21
Using prototype: 21.fpga-cpu-hdmi-alu
== tests Python
...
== regresión RTL (apio test)
...
OK

$ test --prototype 6 --quick          # solo fixtures + tests Python, sin apio test
$ test --prototype 21 --lint          # añade apio lint
$ test --prototype 22 --full          # incluye los bancos lentos (alias: --slow)
$ test --prototype 17 --background    # se sigue con build-status/build-log, igual que build
```

Orden de pasos: `make_fixtures.py` (si existe) → `test_*.py` propios por
`unittest discover` (si hay alguno) → `apio test` (regresión RTL contra los
testbenches del `apio.ini`, salvo `--quick`) → `apio lint` (solo con
`--lint`). Un prototipo sin nada de eso —`test_*.py` ni `apio.ini`— avisa y
sale en `OK` en vez de fingir que probó algo.

### Bancos lentos (`TEST-LENTO`)

Un banco que lleve `TEST-LENTO` en un comentario queda **fuera de la pasada
normal**; `--full` (o `--slow`) lo mete de vuelta. Sirve para los bancos que
simulan una carga realista entera y cuestan minutos: hoy solo
`22.fpga-gpu-bl8/gpu_plasma_tb.v`, con 463 s, la mitad de la suite del
prototipo.

La marca va **dentro del banco, con el motivo al lado**, no en una lista
aparte: una lista se desincroniza en cuanto alguien renombra o borra un banco y
el filtro deja de filtrar sin que nadie se entere. Al omitir alguno, `test`
dice cuál y cómo pedirlo.

Un prototipo sin ningún banco marcado se comporta exactamente como antes: una
sola llamada a `apio test`. El recorrido por bancos sueltos solo se usa cuando
hay algo que excluir.

Al marcar uno, deja cubierto lo mismo por otro lado. `gpu_plasma_tb` tiene a
`gpu_plasma4_tb`, que corre el mismo camino con 24 filas en vez de 240 (~50 s).

### Solo lint (`lint`)

`test --lint` añade `apio lint` a la suite completa, pero sigue ejecutando
fixtures/tests Python si el prototipo los tiene. Para *solo* lint, sin nada
más:

```bash
$ lint --prototype 12
Using prototype: 12.fpga-gpu
== lint (apio lint)
...
OK
```

`lint` es `test --lint-only`: nunca toca fixtures, tests Python ni la
regresión RTL, aunque el prototipo los tenga.

## Barrido de semillas de placement (`build-sweep`)

Igual que `build`: común a cualquier prototipo con `apio.ini`, sin copiar
nada. Necesita un build archivado con timing correcto (`build --prototype N`
primero) y `oss-cad-suite` instalado (lo gestiona `apio`). Lee la placa/paquete
del propio `scons.params` archivado — no asume qué FPGA es:

```bash
$ build --prototype 17 --label base
$ build-sweep --prototype 17 --seeds 1 2 3 4 5     # usa el último build archivado
$ build-sweep --prototype 17 --seeds 1 2 3 --report-dir 17.fpga-gpu-ram-v2/reports/20260915-001203-base
$ build-sweep --prototype 17 --seeds 1 2 3 4 5 --background   # se sigue con build-status/build-log
```

Antes reemplazaba a `tools/seed-sweep.ps1` (retirado): ese trabajaba directo
sobre `_build/<env>/` sin pasar por el archivo de `reports/`; `build-sweep`
pide un build archivado primero, pero a cambio verifica que ese build pasó
timing y queda constancia de qué fuentes se barrieron.

## Encadenar todo (`check`)

`test` → `lint` → `build`, en ese
orden, parando en el primer fallo. Solo reenvía `--prototype` — cada paso
tiene opciones propias incompatibles entre sí (`--quick`, `--archive-only`...),
así que para combinaciones concretas usa cada comando por separado:

```bash
$ check --prototype 12
Using prototype: 12.fpga-gpu
== tests Python
...
== lint (apio lint)
...
== regresión RTL (apio test)
...
OK
```

## Informe de un prototipo

Sin necesidad de placa: cruza el título del `README.md`, el último commit que
tocó la carpeta, el mapa de memoria que declara `monitor.py`
(`ARCHITECTURAL_REGIONS`/`MONITOR_REGIONS`, leído sin importar el módulo), y
el último `reports/*/summary.json` archivado si existe. La identidad
—backend, versión de monitor, reloj, capacidades— se lee **directamente del
RTL**, no de una copia a mano en ningún sitio:

- CPU o GPU: presencia de `cpu.v` vs `gpu_sm.v`/`gpu_system.v`.
- Versión de monitor: `localparam VERSION_MAJOR`/`VERSION_MINOR` en `monitor.v`.
- Reloj: atributo `FREQUENCY_PIN_CLKOP` del fichero del PLL.
- Capacidades: `tools/capabilities.json` — un mapa capacidad→señal (fichero,
  y opcionalmente un patrón a buscar dentro). Añadir una capacidad nueva es
  una entrada ahí, no hay que tocar cada prototipo ni el código de
  `prototype-report`.

```bash
$ prototype-report --prototype 21
Prototype: 21.fpga-cpu-hdmi-alu
Title: MiniCPU con la familia ALU completa, desplazamientos inmediatos y `R0` a cero
Last commit: d99ca1d (2026-09-14) 10 does not have MUL/DIV
Backend: cpu — alu (monitor 4.21)
Clock: 80.0 MHz
Capabilities: mul_div, subword_memory, calls, shift_immediate, alu_extended, video, frame_capture, serial
Memory map:
  ARCHITECTURAL_REGIONS:
    0x00000000-0x02000000 (33,554,432 bytes)
Synthesis: (sin reports/*/summary.json; ejecuta ./build --report)

$ prototype-report --prototype 21 --json | jq .capabilities
```

El nombre corto de versión (`alu`, `ebr`, `sdram`...) es lo único que sigue
viniendo de `x.tests/backends/{fpga,gpu_fpga}.py` — es una etiqueta elegida a
mano, no algo verificable en el RTL. Si un prototipo no está registrado ahí
(como le pasaba a `17.fpga-gpu-ram-v2`), cae al nombre de la carpeta en vez
de dejar todo en blanco.

## Las constantes del mapa MMIO

```bash
$ generate-mmio
escrito: x.tests/inc/mmio.inc
escrito: tools/mmio_map.py

$ generate-mmio --check     # no escribe; exit code 1 si algo cambiaría (para CI)
```

La fuente única es [`1.isa/mmio_map.vh`](../1.isa/mmio_map.vh), que pide
[`1.isa/mmio.md`](../1.isa/mmio.md) §20: sólo `define`, nombre y constante, sin
una sola expresión. De ahí salen el include del ensamblador y el módulo Python
que usan el monitor y los simuladores. **No edites lo generado**: toca el `.vh`
y vuelve a ejecutar esto.

El include se usa así, y `x.tests/inc` ya va en el `-I` tanto de
`run_tests.py` como de `tools/run_board.py`, así que no hay que pasar nada:

```asm
.include "mmio.inc"
    LI    R2, MMIO_VIDEO_BASE
    STORE R3, R2, 0                  ; CTRL
    LI    R4, MMIO_VIDEO_FB_FRONT_ADDR
```

Cada `_OFF` del `.vh` sale también como `_ADDR` con su base ya sumada. A qué
bloque pertenece se deduce del prefijo del nombre, así que **un `_OFF` tiene
que llamarse igual que su `_BASE`** — `MMIO_GPU_WARPS_PC_OFF` cuelga de
`MMIO_GPU_WARPS_BASE`, y escribirlo sin la S lo colgaría de `MMIO_GPU_BASE`.
El generador comprueba que no haya dos registros en la misma dirección y falla
si los hay, que es como se caza ese error.

`x.tests/test_mmio_map.py` comprueba tres cosas distintas: que lo generado está
al día, que las direcciones son las que dice el contrato (con los números
escritos a mano, para que un `.vh` mal editado no pase), y que el generador
rechaza lo que no debe aceptar.

## Mantener la documentación generada al día

```bash
$ generate-docs
escrito: docs/synthesis-report.md
actualizado: resumen-prototipos.md
actualizado: resumen-prototipos.md
actualizado: resumen-prototipos.md

$ generate-docs --check     # no escribe nada; exit code 1 si algo cambiaría (para CI)
```

`docs/synthesis-report.md` se regenera por completo en cada ejecución (no lo
edites a mano). `docs/resumen-prototipos.md` está escrito a mano, así que
`generate-docs` **solo** toca lo que haya entre marcadores. Hay tres bloques,
los tres en ese mismo fichero:

```markdown
<!-- BEGIN GENERATED: cpu-matrix -->        matriz CPU
<!-- BEGIN GENERATED: gpu-matrix -->        matriz GPU
<!-- BEGIN GENERATED: prototype-summary --> tabla plana de los diez prototipos
```

Si esos marcadores no existen en el archivo, no lo toca — hay que añadirlos a
mano una vez, donde tenga sentido insertar la tabla generada.

Las matrices llevan una columna por simulador además de las de bitstream. Las
capacidades del RTL se detectan leyendo los `.v`; las de los simuladores se leen
del `VERSIONS` de `x.tests/backends/{simulator,gpu_simulator}.py`, que es donde
están declaradas y lo que usa `incompatibility()` para decidir qué casos corren.
Fmax y LUT/FF salen del `summary.json` archivado en `reports/` y, si esa carpeta
no tiene ninguno, del `_build/*/hardware.pnr` local.

## Dependencias externas

- Python 3.10+
- Apio (`.venv/bin/apio` en macOS/Linux, `.venv/Scripts/apio.exe` en Windows)
- oss-cad-suite (Yosys, nextpnr...), que instala `apio` en
  `~/.apio/packages/oss-cad-suite`
- Icarus o Verilator para los testbenches Verilog/SystemVerilog
- pyserial para hablar con la placa (`board.py`, `monitor.py` de cada
  prototipo; los lanzadores de `tools/` que no tocan placa, como
  `prototype-report`, no lo necesitan)

## Diagnosticar desconexiones USB del FTDI (Windows)

`usb-power-monitor` registra los cambios de presencia y estado del FTDI y de
toda su cadena de hubs. Tambien guarda los indicadores de suspension selectiva
y de reposo de cada dispositivo. Es una herramienta de solo lectura: no cambia
la configuracion de energia. Comprueba el estado cada segundo, pero solo escribe
una nueva linea cuando detecta algun cambio, por lo que el registro permanece
pequeno. Cada evento se escribe, se fuerza a disco y se cierra inmediatamente;
el fichero queda util aunque el proceso o el dispositivo se interrumpan despues.

```powershell
.\tools\usb-power-monitor.ps1
# o una prueba limitada a 20 minutos:
.\tools\usb-power-monitor.ps1 --duration 20 --output ftdi-prueba.jsonl
```

Deja que la pantalla se apague y, despues de reproducir el fallo, pulsa
`Ctrl+C`. El fichero JSONL solo contiene una instantanea inicial, los cambios
detectados y posibles errores; se puede compartir directamente para comparar
que elemento de la cadena desaparecio primero.

## Ejecutar un programa en una placa real (`run-board`)

Resuelve el prototipo, comprueba (y si hace falta sube) el bitstream
correcto, carga el programa y lo ejecuta. Reutiliza `x.tests/backends/board.py`
para todo lo que habla con la placa — no es un segundo sistema de
programación FPGA, es la composición de esas piezas con resolución de
prototipos:

```bash
$ run-board --prototype 6 --program fpga_smoke_test.asm --port COM3
Using prototype: 6.fpga-cpu
Bitstream correcto: monitor 3.6.
== cargando fpga_smoke_test.bin en 0x00000000
== arrancando
CPU halted=True error=False ...

$ run-board --prototype 6 --port COM3                    # solo comprueba identidad
$ run-board --prototype 6 --port COM3 --no-upload         # falla si el bitstream no es el correcto
$ run-board --prototype 6 --port COM3 --program demo.asm --no-run   # carga sin arrancar
$ run-board --prototype 21 --port COM3 --interactive      # deja una consola serie (solo con capacidad `serial`)
```

La identidad esperada del monitor se lee del RTL (`monitor.v`), igual que
`prototype-report` — no depende de que el prototipo esté registrado en
ningún sitio. `--rebuild` fuerza `apio upload` aunque la identidad ya
coincida.

`--program` acepta una ruta, o un nombre suelto: primero busca en el
directorio actual y en `examples/` del prototipo; si no aparece ahí, busca por
todo el repositorio (como hacía `run-demo.ps1`, ya retirado) y falla con una
lista si hay varias coincidencias.

Si no pasas `--port`, `run-board` detecta el primer adaptador FTDI conectado
(VID `0x0403`, el de la ULX3S y de la mayoría de placas de desarrollo FPGA).
En macOS/Linux no hay "COM3" que valga por defecto, así que esto evita tener
que buscarlo a mano cada vez; si hay varios o ninguno, lo dice explícitamente
en vez de adivinar.

### Detección de puerto compartida (`tools/serial_ports.py`)

Lo mismo vale ahora para los `monitor.py` de los prototipos y para
`22.fpga-gpu-bl8/profile.py`: todos importan `tools/serial_ports.py`, que es
el único sitio donde vive `detect_port()`/`available_ports()`.

Antes esa función estaba **copiada palabra por palabra en los trece
monitores** y devolvía el primer puerto del sistema. Con la placa
desenchufada eso cogía el puerto serie de la placa base o un enlace
Bluetooth, y el fallo salía mucho más tarde disfrazado de *write timeout* —
un síntoma que se parece a "la FPGA no tiene monitor" y no a "no has
enchufado la placa". Ahora `--port` sin valor detecta, y `available_ports()`
marca cuál es la placa:

```text
Available ports: COM3 (FTDI), COM1, COM6, COM8
```

`x.tests/backends/board.py` mantiene su propia copia a propósito: `x.tests`
no depende de `tools/` (la dependencia va en el otro sentido) y `board.py`
recibe el `monitor.py` del prototipo como módulo, así que importar desde el
monitor haría un ciclo. Son dos copias en vez de trece, y
`x.tests/test_monitor_port.py` comprueba que no divergen.

### Las tres operaciones por separado

`run-board` es la composición de tres pasos; cada uno también existe como
comando suelto, por si solo hace falta uno:

```bash
$ board-info --prototype 6 --port COM3
Using prototype: 6.fpga-cpu
OK: monitor 3.6 (versión ebr).                # o MISMATCH, sin subir nada nunca

$ board-upload --prototype 6 --port COM3 -y
Using prototype: 6.fpga-cpu
Bitstream correcto: monitor 3.6.

$ board-load --prototype 6 --port COM3 --program fpga_smoke_test.asm
Using prototype: 6.fpga-cpu
== cargando fpga_smoke_test.bin (32 bytes) en 0x00000000
== arrancando
CPU halted=True error=False ...
```

`board-info` nunca escribe nada en la placa (solo lee la versión del
monitor). `board-upload` es el mismo chequeo que hace `run-board` por
defecto, con `--rebuild`/`--no-upload`/`-y`. `board-load` **no comprueba la
identidad del bitstream** — asume que ya es el correcto y va directo a
ensamblar/cargar/ejecutar; combínalo con `board-upload` si no estás seguro.

### Suite de casos contra placa real (`test-board`)

`x.tests/run_tests.py` necesita `--backend cpu-fpga`/`gpu-fpga` y `--version`
(el nombre corto de `x.tests/backends/{fpga,gpu_fpga}.py`), que hay que saber
a mano. `test-board` los infiere del mismo sitio que `board-info`/`run-board`
(el RTL, vía `_capabilities()`), detecta el puerto igual que el resto de
comandos de placa, y reenvía todo lo demás (`TEST_JSON`, `--trace`, `-y`,
`--measure`...) a `run_tests.py` sin tocarlo:

```bash
$ test-board --prototype 21 -y cases/basics
Puerto detectado: /dev/cu.usbserial-D00688 (ULX3S FPGA 85K v3.0.8)
Using prototype: 21.fpga-cpu-hdmi-alu
$ .../run_tests.py --backend cpu-fpga -p 21 --port /dev/... -y cases/basics
PASS smoke [cpu-fpga]
PASS zero-register [cpu-fpga]
2 caso(s), 0 fallo(s), 0 omitido(s) por arquitectura o capacidades, 1.7s
```

Si el prototipo no tiene identidad inferible (sin `cpu.v`/`gpu_sm.v`/
`gpu_system.v` + `monitor.v` con versión), falla con un mensaje claro en vez
de adivinar — en ese caso usa `x.tests/run_tests.py` directamente con
`--backend`/`--version` a mano.

## Herramientas de vídeo/HDMI (16, 18, 19, 21)

Comunes a los cuatro prototipos con framebuffer + HDMI, todas con `--prototype`/`-p`:

```bash
$ make-framebuffer bars fb.bin                                  # genera un patrón RGB565 320x240
$ capture-frames --prototype 21 swap_demo_fast --frames 4       # captura frames deterministas
$ measure-demo --prototype 21                                   # FPS de swap_demo/tear_demo (lee R21)
```

`make-framebuffer` no depende de ninguna versión concreta (mismo formato en
las cuatro carpetas). `capture-frames` y `measure-demo` sí hablan con una
placa real por el protocolo de vídeo compartido, reutilizando
`resolve_target`/`run_monitor_cli`/`detect_port` de `run_board.py`;
`measure-demo` en particular solo tiene sentido con las demos
`swap_demo`/`tear_demo`, no como medición de FPS general.

### Poner una imagen en la pantalla (`image-to-framebuffer`)

El camino contrario a `frame-to-image.py`: entra un JPG/PNG/BMP y sale el
`.bin` RGB565 de 320x240 —**153600 bytes**, el mismo formato que
`make-framebuffer`—, listo para `write-block`.

```bash
$ image-to-framebuffer foto.jpg foto_fb.bin                       # 153600 bytes en 0x01000000
$ image-to-framebuffer foto.jpg foto_fb.bin --ajuste encajar --fondo 0,0,64
$ image-to-framebuffer foto.jpg foto_fb.bin --upload --prototype 22
```

El framebuffer es de 320x240 y el scanout duplica cada píxel, así que lo que
entra sin deformarse es **4:3** (640x480, 1024x768...). Para el resto está
`--ajuste`: `recortar` (por defecto, llena y recorta el lado largo),
`encajar` (imagen entera con bandas de `--fondo`) y `estirar`.

Con `--upload --prototype N` no se queda en un fichero: resetea el núcleo,
escribe el framebuffer en SDRAM (~2 min a 250 kbaud), apunta `FB_FRONT` y
`FB_BACK` a esa dirección y pone `VIDEO_CTRL` en SCANOUT. No hace falta
programa cargado — el scanout lee SDRAM por su cuenta. `VIDEO_CTRL` solo
existe en la 22; en 16/18/19/21 el scanout está siempre encendido y la
herramienta lo dice al leerlo de vuelta en vez de fallar.

### Capturar un frame sin placa (`capture-frame-sim`)

Igual que `capture-frames`, pero contra el simulador funcional
(`2.cpu-sim-func/minicpu_sim.py`) en vez de hardware — no hace falta placa ni
`--prototype`, y es casi instantáneo. Dos formas de decidir cuándo capturar,
y el formato de salida lo decide la extensión (`.bin`, `.hex`, o cualquier
cosa que entienda Pillow vía `frame-to-image.py`):

```bash
$ capture-frame-sim cases/video/bounce/bounce.asm --swap 20 frame.png
$ capture-frame-sim cases/video/band/band.asm --instrucciones 500000 frame.bin
```

`--swap N` para en el N-ésimo intercambio completado desde el arranque.
`--instrucciones N` ejecuta N instrucciones sin condición de parada y captura
en el intercambio que ocurra después — útil para mirar el framebuffer en un
punto cualquiera del programa sin saber a qué intercambio corresponde.

## Qué no hay todavía

Nada pendiente en la infraestructura común. `prototype-report`/`run-board`
leen la identidad de un prototipo directamente del RTL (`cpu.v`/`gpu_sm.v`,
`monitor.v`, el PLL, `tools/capabilities.json`) en vez de depender de que
alguien la registre en ningún sitio — ver "Informe de un prototipo" arriba.

Para agentes trabajando en este repo: ver también [`../AGENTS.md`](../AGENTS.md).
