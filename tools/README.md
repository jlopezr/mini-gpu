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

### Queries Python

Las preguntas reutilizables son funciones Python registradas, no comandos con
lógica duplicada ni un DSL propio:

```python
from tools.traceability import query

@query
def my_query(graph):
    ...

@query("related-to", arguments=("identity",))
def related_to(graph, identity):
    ...
```

El registro core se consulta y ejecuta desde CLI:

```bash
$ trace query list
$ trace query unimplemented
$ trace query unverified
$ trace query not-fully-verified
$ trace query unsatisfied
$ trace query implementations-of SPEC-DEVICE#identity-register
$ trace query verifications-of SPEC-DEVICE#identity-register --format json
```

`unverified` significa que no existe ninguna relación entrante `verifies`.
`not-fully-verified` exige al menos una relación con `coverage=complete`; varias
relaciones `partial` no se combinan implícitamente. Esta slice expone el registro
Python, pero todavía no carga módulos de queries arbitrarios desde el proyecto.

### Rules Python

Las rules son políticas verificables separadas de las queries. Se registran con
`@rule`, devuelven `RuleFinding` y se activan explícitamente en `trace.yaml`:

```yaml
rules:
  - accepted-requirements-satisfied
  - accepted-specifications-implemented
  - accepted-targets-fully-verified
```

`trace check` solo las ejecuta después de resolver un grafo válido. Los findings
`error` provocan exit code 1; los `warning` se muestran sin hacer fallar el
comando. `trace rule list` enumera el registro core. Una rule desconocida o una
configuración duplicada/inválida es un error explícito.

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

Todavía no se modela jerarquía interna de símbolos. El contenido situado dentro
de bloques `gendoc` se ignora al construir el modelo, para que el resultado
generado nunca se convierta accidentalmente en fuente autoritativa.

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

`trace coverage` ayuda a migrar documentación existente: compara los ficheros
que descubre `scan` con las identidades declaradas y resume por directorio
cuántos siguen sin marcar. No es una query porque esos ficheros aún no son
identidades del grafo.

```bash
trace coverage                      # resumen por directorio de primer nivel
trace coverage --depth 2 --files    # más detalle y lista de ficheros sin marcar
trace coverage 30.fpga-cpu-console  # solo una zona
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
> mini-asm ../x.tests/cases-gpu/demos/vector/vector.asm           # -> 1.isa/mini_asm.py
> cpusim ../x.tests/cases-gpu/demos/vector/vector.asm             # -> 2.cpu-sim-func/minicpu_sim.py
> gpusim ../x.tests/cases-gpu/demos/vector/vector.asm             # -> 11.gpu-sim-func/minigpu_sim.py
> gpusim-cycle ../x.tests/cases-gpu/demos/vector/vector.asm       # -> 25.gpu-sim-cycle-uarch/minigpu_cycle.py
```

Cada uno acepta los mismos argumentos que el script al que llama (pásale
`--help` para verlos).

Sin `-o`, `mini-asm` deja el binario en `_build/<nombre>.bin` junto al fuente
(carpeta ignorada por git), no al lado del `.asm`. `board-load` y `run-board`
ensamblan ahí mismo, así que `vector.asm` acaba en `vector/_build/vector.bin`.

`mini-asm` se llamaba `miniisa`, y el módulo `1.isa/mini_asm.py` se llamaba
`miniisa_asm.py`. `MiniISA` sigue siendo el nombre de la ISA: el rename fue solo
del ensamblador, para que quede junto a `mini-lcc`.

Para saber qué instrucción hay en una dirección concreta —el `pc` que reporta
`run-board` o un simulador— `mini-asm --listing` saca el listado PC / palabra /
fuente y la tabla de etiquetas. Ver [`1.isa/ensamblador.md`](../1.isa/ensamblador.md).

Los tres simuladores aceptan **`.asm`, `.bin` o `.hex`**, y ensamblan solos si
hace falta. La carga es `load_program_bytes()` de `1.isa/mini_asm.py`, una
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
| `--halt-after-swaps N` | Activa vídeo y para el simulador tras N intercambios |
| `--frame-output frame.bin` | Activa vídeo y guarda el framebuffer frontal RGB565 de 320×240 |
| `--console` | Activa vídeo con la consola de texto 80×30 de la 30: `CONFIG` (`+0x40`), paleta (`+0x1000`) y texto (`+0x6000`) dentro de la ventana de vídeo. `SWAP` pasa a ser `FRAME_COMMIT` de dos bits (swap y `STATE_COMMIT`) |
| `--console-output pantalla.txt` | Activa `--console` y vuelca la pantalla de texto (30 líneas, UTF-8) al terminar |
| `--console-image pantalla.png` | Activa `--console` y guarda la pantalla como PNG 640×480, dibujada con `--console-font` (nombre de `30.fpga-cpu-console/fonts` —`cpc464` por defecto, `pc`, `tamzen`— o ruta a un `.hex`). Compone la consola sobre el framebuffer si el programa lo usa (`VIDEO_CTRL` en scanout); el color 0 es transparente, como en el RTL, y sin framebuffer sale negro. `--frame-output` y `fb_window` solo muestran el framebuffer, sin la consola |
| `--serial` | Activa serie en `0x80000200` |
| `--serial-tty` | Activa serie y lo conecta al terminal: la salida del programa va a stdout y lo que se teclea entra por RX (sin eco ni Enter, como `run-board --interactive`). **Ctrl+C** sale. Combinable con `--window` (ventana para teclado y ratón, terminal para la UART). No vale en `mini-dbg`: la TUI ocupa el terminal |
| `--serial-input entrada.bin` | Activa serie y precarga los bytes de entrada |
| `--serial-output salida.bin` | Activa serie y recoge la salida durante toda la ejecución |
| `--window` | Abre una ventana con la pantalla (framebuffer, consola o ambos, según `VIDEO_CTRL` y `CONFIG`) y conecta su teclado y ratón a INPUT. Implica vídeo; `--console` y `--console-font` valen igual. **F12** o cerrar la ventana paran el simulador; al terminar el programa la última imagen se queda hasta cerrarla. En `mini-dbg` es la ventana de `fb screen` y F12 interrumpe la ejecución sin parar la máquina |
| `--keyboard` | Activa INPUT (teclado y ratón, `mmio.md` §25, en `0x80600000`) con un teclado presente desde el principio |
| `--mouse` | Activa INPUT con un ratón presente desde el principio |
| `--input-script entrada.txt` | Activa INPUT y carga un guion de entrada. El guion conecta lo que no pidan `--keyboard`/`--mouse`; se comprueba entero al cargar |

Por ejemplo, las mismas opciones sirven con cualquiera de los tres lanzadores:

```powershell
.\tools\cpusim.ps1 programa.asm --serial-input entrada.bin --serial-output salida.bin
.\tools\gpusim-cycle.ps1 dibujo.asm --video --halt-after-swaps 2 --frame-output frame.bin
.\tools\cpusim.ps1 leer_teclas.asm --input-script entrada.txt --serial-output salida.bin
```

#### Ventana (`--window`)

```powershell
.\tools\cpusim.ps1 2.cpu-sim-func\examples\input_paint.asm --window --run-limit 2000000000
```

El pintor de `2.cpu-sim-func/examples/input_paint.asm` dibuja con el ratón
(botón izquierdo), cambia de color con cualquier tecla y borra con la barra
espaciadora. La ventana es un proceso aparte (`tools/screen_window.py`, Tk y
PIL) y el simulador la refresca unas 15 veces por segundo solo si la pantalla
cambió; no hay ritmo de tiempo real, el simulador corre tan deprisa como puede.

Las teclas viajan como **teclas físicas** (`tools/host_input.py`): `MapVirtualKey`
da el scancode y de ahí el Usage ID, así que no dependen del layout. Los
modificadores se leen del sistema y AltGr no deja pulsado un Control. Mantener
una tecla no repite pulsaciones: el contrato no define typematic, es del
software. Los movimientos del ratón se funden en un evento por muestreo
(10 ms) y el puntero solo cuenta mientras está sobre la ventana. Perder el
foco suelta todo.

#### Guiones de entrada (`--input-script`)

Una acción por línea, con el instante en instrucciones completadas (de CPU o
de warp): `@N` es absoluto y `+N` relativo a la línea anterior. `@0` se aplica
al cargar, antes de la primera instrucción.

```text
@0    keyboard connect               # o `keyboard connect A LSHIFT` con teclas ya pulsadas
+100  key press H                    # down y up, dos reports
+10   type "Hola\n"                  # teclado US; las mayúsculas llevan LSHIFT
+50   key down LSHIFT A              # varias teclas = un solo report
+50   key up LSHIFT A
@500  mouse connect
+10   mouse move 12 -5
+10   mouse button left click        # left, right, middle o 0..31; down, up o click
+10   mouse report 0b101 3 4         # bitmap de botones y movimiento en un report
+10   keyboard disconnect            # libera lo pulsado y deja STATE a cero
```

Las teclas son nombres de `tools/hid_keys.py` (`A`, `ENTER`, `LSHIFT`, `F1`,
`UP`...) o Usage IDs literales (`0x2C`); un dígito suelto es la tecla del
dígito, no el Usage ID. El simulador reproduce INPUT, no USB: aplica los
reports con el orden de eventos, el overflow y las reglas de
conexión/desconexión de §25, así que un guion que lanza más de 16 eventos sin
que el programa los lea los pierde igual que la FPGA.

`SYS_ID` siempre está disponible, también mediante LOAD en la 25. Vídeo y serie
son opcionales en la API (`video=VideoDevice()`, `serial=SerialDevice()`). El
runner `x.tests` conecta serie en los tres modelos y vídeo cuando lo pide el
caso; los tres declaran `video`, `frame_capture` y `serial`.

El contrato funcional de vídeo incluye `SWAP_COUNT`, `HALT_AT` y `VIDEO_CTRL`.
Las bases arrancan a cero y las configura el programa; se alinean a 4 bytes en
los tres modelos. Una escritura a `SWAP` pide intercambio, incluso con valor
cero. Para portabilidad al RTL GPU, alinear bases a 16 y escribir 1 a `SWAP`.
`HALT_AT` cuenta intercambios completados desde que se arma (mmio.md §9.6) y
`HALT_TARGET` dice a quién para: el bit 0 a la CPU y el 1 a la GPU, y cada modelo
solo hace caso al suyo. El RTL GPU no gana serie por esta unificación de
simuladores.

El frame se mide en instrucciones CPU o de warp, no en ciclos del pipeline.
Los puntos de avance y el orden entre warps dependen del motor: no se promete
el mismo PC al capturar. No se simulan desgarro, underflow ni tiempo físico de
UART/HDMI. `--frame-output` vuelca RAM desde `FB_FRONT`, no renderiza PATTERN ni
BLANK. Los accesos MMIO requieren palabras alineadas de 32 bits.

## Depurador interactivo (`mini-dbg`)

Un solo depurador que se **conecta** a dos sitios: el simulador funcional o la
placa por el monitor serie. Mismos comandos, misma interfaz, mismo núcleo.

```bash
> mini-dbg programa.asm                  # simulador funcional (2.cpu-sim-func)
> mini-dbg --board --prototype 21        # placa real, por monitor.py
> mini-dbg --board -p 21 programa.asm    # placa, con el fuente para el listado
```

El programa hace dos cosas: se carga en el simulador y sirve de mapa
`PC -> fuente`. Con `--board` no se carga nada —de eso ya se ocupa
`board-load`— pero el `.asm` sigue valiendo para ver el código tal como se
escribió en vez de palabras en crudo. El mapa no es un desensamblador: lo
construye `mini_asm.first_pass`, como `mini-asm --listing`, así que conserva
comentarios, etiquetas y macros. Con un `.bin` o un `.hex` se ven `.word`.

La TUI son cuatro paneles —código con el PC centrado, registros, memoria y
consola— y una línea de comandos. Cada tecla hace exactamente lo mismo que
escribir el comando, ni más ni menos:

| Comando | Tecla | Qué hace |
|---|---|---|
| `step [N]` | `s` | Ejecuta N instrucciones (1 por defecto). No para en breakpoints |
| `over` | `n` | Un paso, saltando entera la llamada si es `JAL`/`JALR` |
| `finish` | `o` | Ejecuta hasta salir de la función actual |
| `run [N]` | `c` | Hasta breakpoint, `HALT`, error, `F12` o `Esc`; con N, como máximo N instrucciones |
| `until X` | `u` | Hasta la dirección, etiqueta o línea marcada por el cursor |
| `break [X]` | `b` | Breakpoint en X (o en el PC con la tecla); sin argumento los lista |
| `delete [X]` | — | Borra el breakpoint X, o todos |
| `regs [Rn]` | — | Los registros, o uno |
| `set X V` | — | `set R5 0x10`, `set pc bucle` |
| `mem [X N]` | — | Vuelca N bytes desde X y mueve el panel de memoria |
| `write X V` | — | Escribe la palabra V en la dirección X |
| `fb [X]` | `v` | Ventana de framebuffer: `front` (por defecto), `back`, `both`, `off`. `fb screen` abre la pantalla del simulador (framebuffer, consola o ambos) con teclado y ratón hacia INPUT; `--window` la abre al arrancar |
| `input` | — | Estado de INPUT: presencia, teclas pulsadas, botones del ratón y la cola de eventos, sin consumirlos. Solo si hay INPUT (`--keyboard`, `--mouse`, `--window` o `--input-script`) |
| `frame` | `f` | Ejecuta hasta que se completa el siguiente intercambio de framebuffer |
| `reset` | `R` | PC, registros y contadores a cero sin borrar la memoria |

Durante `run`, `until`, `over`, `finish` o `frame`, `F12` (o `Esc` en la TUI) solicita
la parada y devuelve el control a la TUI. En las ventanas **solo** `F12`: `Esc` es una
tecla más del programa que se depura. Código y memoria aceptan también `PageUp`, `PageDown` y
`Home`; `Home` lleva al inicio del programa o a `0x00000000`, respectivamente.
`Ctrl+C` hace lo mismo durante la ejecución; con la máquina ya parada, sale del
depurador limpiamente.
`run` sin argumento no tiene límite interno, pensado también para programas
gráficos con bucle principal permanente. `run N` o `--run-limit N` permiten
pedir expresamente un máximo.
Después de ejecutar, el cursor de código vuelve al PC y el siguiente
`↑`/`↓` parte de la instrucción actual.
Con el foco en código, registros o memoria, `/` abre una búsqueda en ese panel.
En memoria busca bytes hexadecimales (`DE AD BE EF`) o texto dentro de la
ventana mostrada. `a` repite la última búsqueda en el mismo panel.
Los comentarios clicables usan cian para destinos de código, magenta para RAM
y amarillo para MMIO (`0x80000000` en adelante). La dirección efectiva de un
acceso se calcula con la instantánea actual de los registros: es exacta cuando
el PC está en esa instrucción y orientativa al inspeccionar código futuro.

El pie muestra únicamente acciones disponibles. `v` y `f` no aparecen si el
objetivo no ofrece vídeo; al cambiar el foco añade las teclas propias del panel:
`↑`/`↓`, `/`, `a`, `p`, `b` y `u` en código, `↑`/`↓`, `/` y `a` en registros, y
`↑`/`↓`, `/`, `a` y `h` en memoria.

### Ver el framebuffer mientras se depura

`v` (o `fb`) abre una **ventana** aparte con el framebuffer, en tkinter —de la
biblioteca estándar, no hace falta pygame ni nada nuevo—. `fb both` enseña los
dos buffers lado a lado, `+`/`-` amplían y `F12` detiene la ejecución en curso
sin cerrar la ventana. La X (o `fb off`) sí la cierra.
Mientras la ventana de vídeo tiene el foco, sus teclas de depuración se
reenvían como si estuviera seleccionado el panel de código: `s`, `n`, `o`,
`c`, `f`, `R`, cursores, `PageUp`/`PageDown`, `Home`, `p`, `b`, `u`, `/` y
`a`. El zoom conserva `+`/`-`.

Los dos buffers no enseñan lo mismo, y esa es la gracia:

- **front** es el frame estable, el que estaría saliendo por HDMI.
- **back** es sobre el que el programa está dibujando *ahora*, así que con la
  máquina parada a mitad de dibujo se ve a medias. Eso no es un fallo de la
  captura: es ver exactamente hasta dónde había llegado. Es justo lo contrario
  de `capture-frames`, que para en el swap para que la captura salga
  entera y determinista — las dos herramientas quieren cosas distintas.

En el simulador la ventana se repinta **después de cada comando**, así que se
ve el dibujo avanzar paso a paso. En la placa no: son ~1,5 s por buffer a
1 Mbaud (el número está medido en `tools/capture-frames`), así que se refresca
cuando se pide con `fb`. `fb auto on|off` cambia ese comportamiento si en algún
caso concreto interesa lo contrario.
Durante una ejecución larga, el título con `PC` e `instr` se actualiza unas
diez veces por segundo aunque no haya un frame nuevo; este refresco no lee ni
transfiere los píxeles.
Cada frame viaja íntegramente en memoria por la tubería, codificado en Base64;
no se crean archivos temporales ni interviene el bloqueo de ficheros de
Windows. La ventana agrupa los frames que llegan más deprisa de lo que puede
pintarlos. Si Pillow falla igualmente,
el error aparece en rojo en la consola de la TUI en vez de quedar oculto bajo
el repintado del terminal.

Las bases no se cablean: `FB_FRONT` y `FB_BACK` se releen en cada refresco
porque el swap las intercambia. En el simulador se le preguntan al dispositivo;
en la placa se leen de la ventana de vídeo de MMIO v2 (`0x80200000`), pero sólo
después de comprobar el magic de SYS_ID y el bit de vídeo de `DEVICES`. Sin
magic no se lee nada: en v2 `0x80000000` es SYSTEM, así que leer ahí a ciegas
devolvería el propio magic con pinta de dirección de framebuffer.

Los programas de vídeo escriben sus propias bases `FB_FRONT` y `FB_BACK`; el
depurador no las prepara desde fuera. Hay que habilitar el dispositivo con
`--video`. Si un fuente usa símbolos `MMIO_VIDEO_*` sin esa opción, `mini-dbg`
y `cpusim` muestran un aviso antes de ejecutarlo:

```bash
> mini-dbg x.tests/cases-cpu/video/fire/fire.asm --video -x "run 400000"
```

Direcciones y valores aceptan etiquetas del programa, `0x...`, decimal y `pc`.
Los `.include` se buscan en `x.tests/inc` siempre —es donde vive `mmio.inc`—
más lo que se añada con `-I`.
Para tuberías, `ssh` o una máquina sin `textual`, `--no-tui` da el mismo
depurador en modo línea. Se puede arrancar con trabajo hecho:
`mini-dbg programa.asm --break bucle -x run`.

**Qué se puede hacer en cada sitio.** No todo objetivo soporta todo, y el que
no, lo dice en vez de fingirlo:

| Operación | Simulador | Placa |
|---|---|---|
| Paso, breakpoints, leer registros y memoria | sí | sí |
| Escribir memoria, `reset` | sí | sí |
| `set Rn` / `set pc` | sí | **no** — pide comandos nuevos en `monitor.v` (punto 11 del TODO) |
| `run` sin breakpoints | paso a paso (ya es rápido) | `RUN` del monitor, no miles de `STEP` por el serie |

Un `run` **con** breakpoints en la placa sí va instrucción a instrucción por el
puerto serie, porque el hardware no tiene comparador de PC: es correcto pero
lento, así que conviene acercarse con `until` y afinar desde ahí.

**Dónde está.** `tools/debug_core.py` es el depurador entero —comandos,
ejecución, breakpoints— y no pinta nada; `tools/debug_tui.py` solo coloca en
paneles lo que el núcleo devuelve. En medio, `tools/debug_target.py` define qué
necesita el depurador de la máquina que depura, con una implementación para el
simulador y otra (`tools/debug_board.py`) para el monitor. Añadir la MiniGPU
—warps y carriles— es escribir un tercer objetivo, no tocar la interfaz.
Suite: `python -m unittest discover -s x.tests -p test_debugger.py`.

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

### Informe de tiempos de todas las suites (`test-timings`)

`test-timings` ejecuta y ordena de mayor a menor todos los tests unitarios
Python del repositorio (por método y con subtotal por carpeta), los bancos RTL de un prototipo (por banco) y los casos de
`x.tests` para `cpusim`, `gpusim` y `gpusim-cycle`. Escribe por defecto
`reports/test-timings.md`. Usa `--jobs 1` por defecto para que el total y los
tiempos individuales no se solapen:

```powershell
.\tools\test-timings.ps1                                  # todo; usa la placa si la detecta
.\tools\test-timings.ps1 --prototype 30                   # solo este RTL
.\tools\test-timings.ps1 --prototype 30 --prototype 29     # RTL CPU y GPU
.\tools\test-timings.ps1 --prototype 30 --cpu-prototype 30 --gpu-prototype 29
.\tools\test-timings.ps1 --skip-hardware                    # no detectar ni modificar la placa
.\tools\test-timings.ps1 --full --json reports/test-timings.json
```

Por defecto detecta un único FTDI: si está conectado, elige el prototipo
registrado de número más alto de cada familia y acepta cargar primero su
bitstream CPU y después el GPU; si no encuentra ninguno, omite hardware sin
fallar. `--skip-hardware` evita incluso la detección y garantiza que no toca la
placa. Al indicar `--cpu-prototype`/`--gpu-prototype` manualmente no carga nada
(`--no-upload`). `--cases RUTA` (repetible) limita los casos, y `--skip-python`,
`--skip-rtl` y `--skip-x-tests` permiten medir una parte. Los bancos marcados
`TEST-LENTO` solo entran con `--full`.

Los casos cuyo `test.json` declara `"slow": "motivo"` se omiten por defecto
en `gpusim` y `gpusim-cycle`: hoy son las dos imágenes completas, `mandelbrot`
y `mandelbrot-packed`, que dominan el tiempo del informe y ocultan el coste del
resto de la suite. `--full-x-tests` los incluye. Esta
exclusión no se aplica a las placas CPU/GPU, cuyo coste y comportamiento interesa
medir por separado. El runner general ofrece también `--exclude-case RUTA`
(repetible) para excluir un caso o una carpeta en cualquier ejecución, y
`--skip-slow` para respetar la marca declarativa.

No incluye síntesis, lint ni checks de documentación: son validaciones, pero no
tests de ejecución comparables. Tampoco incluye la suite propia opcional de
`y.lcc` ni `13.hdmi/check_timing.ps1`; ambas son proyectos/pruebas independientes
y requieren dependencias o entornos distintos.

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

`--archive-only` archiva los resultados existentes sin volver a sintetizar.
Por defecto se reutiliza el último informe detallado si sus hashes coinciden
con el RTL, constraints y opciones actuales. Si no coinciden, ejecuta PNR
detallado y guarda el log completo. `--no-incremental` fuerza siempre un PNR
detallado nuevo; `--incremental` fuerza una ejecución usando la caché interna
de Apio y no pide el progreso detallado de routing.
Funciona igual sin `--background` (bloquea hasta terminar, con la misma
salida por pantalla).

Para reconstruir todos los prototipos que declaran un proyecto Apio:

```powershell
.\tools\build.ps1 --all
```

Los recorre en orden numérico y de forma secuencial, crea una entrada de
`build-list` por prototipo, continúa si alguno falla y muestra un resumen al
final. `--all` no admite `--background`, para no lanzar varias síntesis FPGA
simultáneas accidentalmente.

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
$ build-list --prototypes                  # una fila de estado por prototipo RTL
$ build-stop --prototype 17                # SIGTERM al build activo
```

`build-list --prototypes` cruza el último intento registrado con el bitstream
local y el informe archivado. Distingue `CURRENT`, `STALE` y `MISSING` del
estado del último build (`SUCCESS`, `FAILED`, `TIMING_FAIL`, `RUNNING`,
`INTERRUPTED` o `NEVER`), y muestra timing, Fmax requerida/alcanzada del reloj limitante,
la semilla fija de NextPNR (o `-` si no hay ninguna), duración, fecha y
etiqueta. Es una consulta: no lanza ni detiene builds.
Cuando el build produjo un resultado válido pero no alcanzó la frecuencia
requerida, `LAST BUILD` muestra `TIMING_FAIL` en amarillo y la columna
`TIMING` conserva `FAIL` en rojo; `FAILED` queda reservado para errores sin
un informe de timing válido.
La fecha se convierte a la zona horaria local del ordenador.
En una terminal colorea los estados (`CURRENT`/`SUCCESS`/`PASS` en verde,
obsoletos o interrumpidos en amarillo, fallos o ausencias en rojo y builds
activos en cian); al redirigir la salida no emite secuencias ANSI. Si hay algún
build activo, lo anuncia sobre la tabla y marca su fila con `*`. La variable
de entorno `NO_COLOR` desactiva también el color interactivo.

`--background` devuelve el control enseguida: crea `status.json` de inmediato
y sigue el proceso en segundo plano de verdad (grupo/sesión propios), no
bloquea la terminal que lo lanzó. Si lo paras con `build-stop`, el estado
queda en `stopped`, no en `failed`.

Al consultar el historial, un registro que siga marcado como `running` pero
cuyo PID ya no exista se corrige y persiste como `interrupted`. Esto recupera
los estados que quedan huérfanos tras cerrar una terminal, reiniciar el equipo
o terminar externamente el proceso de seguimiento.

Los backends de placa usan este mismo camino cuando necesitan reconstruir un
bitstream antes de programarlo. Esa síntesis automática aparece por tanto en
`build-list`, con etiqueta `auto-upload`, y genera el mismo archivo de timing
que un `build --prototype N` explícito.

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
fixtures, `test_*.py` propios o `apio.ini`:

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

Orden de pasos: fixtures (si algún banco del prototipo incluye `fixtures/count.vh`,
las genera `tools/make_rtl_fixtures.py --prototype N`, ver
[Fixtures diferenciales de RTL](#fixtures-diferenciales-de-rtl-make_rtl_fixtures-y-fixtures-report);
si no, el `make_fixtures.py` propio, si existe) → `test_*.py` propios por
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

Con `--jobs 1`, un prototipo sin ningún banco marcado hace una sola llamada a
`apio test`, y el recorrido por bancos sueltos solo se usa cuando hay algo que
excluir. Con el valor por defecto (`--jobs 2`) los bancos se reparten como se
explica abajo.

Al marcar uno, deja cubierto lo mismo por otro lado. `gpu_plasma_tb` tiene a
`gpu_plasma4_tb`, que corre el mismo camino con 24 filas en vez de 240 (~50 s).

### Bancos en paralelo (`--jobs`)

`test` reparte los bancos RTL en `--jobs N` grupos (por defecto 2) que corren a
la vez. Cada grupo es **una** invocación de `apio test` sobre su **propia copia**
de la carpeta del prototipo, y no sobre la real: apio/scons guardan estado en el
proyecto y dos `apio test` sobre la misma carpeta se pisarían. Las copias son
hermanas de la carpeta (`_tmp_test_<k>_<prototipo>`, para que rutas como
`..\x.tests\inc` sigan valiendo), no llevan `reports/` ni `_build/`, y se borran
al terminar, también si algo falla.

- El reparto es por turnos, sin más. Sirve cuando un banco pesa más que todos los
  demás juntos, como `video_fullframe_tb` en la 30 (unos 40 s de simulación
  frente a ~10 s del resto): la suite tarda lo que ese banco y los demás corren
  a su lado. Más grupos no lo bajan.
- Los ficheros que un banco escribe en su carpeta (`frame_full.hex/.bin`) se
  copian de vuelta a la carpeta real, como con una sola invocación.
- `--jobs 1` es el comportamiento anterior, sin copias.
- La salida de cada grupo se imprime entera al terminar, no mientras corre.

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

## Fixtures diferenciales de RTL (`make_rtl_fixtures` y `fixtures-report`)

`gpu_system_tb.v` (y `gpu_system_bl8_tb.v` en 22 y 29) compara el estado completo del RTL con el del
simulador funcional, programa a programa. Lo que lee está en `<prototipo>/fixtures/` (`NN.program.hex`,
`NN.regs.hex`, `NN.memory.hex`, `NN.config.hex`, `NN.counts.hex`, `NN.state.hex`, `manifest.json` y
`count.vh`). **No se versiona**: lo genera un único script para los cinco prototipos de GPU (12, 14, 17,
22 y 29), a partir de los casos de `x.tests/cases-gpu`.

```bash
python tools/make_rtl_fixtures.py --prototype 22        # escribe 22.fpga-gpu-bl8/fixtures/
python tools/make_rtl_fixtures.py -p 12 --out /tmp/f    # a otro sitio, para comparar
```

`test --prototype N` ya lo ejecuta como primer paso (un prototipo cuyo banco incluye `fixtures/count.vh`
lo usa; si no, su `make_fixtures.py` propio, si lo tiene), así que a mano solo hace falta para el banco
suelto: `apio test -p 22.fpga-gpu-bl8 gpu_system_tb.v` necesita las fixtures ya generadas.

Qué casos entran y por qué lo decide el propio caso, en su `test.json`
(ver [x.tests/README.md](../x.tests/README.md#casos-para-el-diferencial-de-rtl)). Un caso entra en un
prototipo solo si todo su `requires` está entre las capacidades que `rtl_facts` lee de su RTL; los
casos van por ruta ordenada, así que el `NN` de un caso puede ser distinto en cada prototipo.

`fixtures-report` dice cuál es cuál:

```text
$ fixtures-report
caso                                       12   14   17   22   29
alu/random-arithmetic                      01   01   01   01   01
...
Omisiones:
  <caso> en 12: falta video

Sin problemas.

$ fixtures-report --prototype 22     # una sola columna
```

La matriz lleva el `NN` de cada caso o `-` si el prototipo lo omite, con el motivo debajo. Después
comprueba tres cosas y sale con 1 si alguna falla:

1. un banco pide `generated/programs/X.hex` y no hay `X.asm` en `x.tests` (el banco no tendría programa);
2. un caso marcado `rtl.differential` que ningún prototipo usa (marca que no hace nada);
3. un programa que un banco pide por nombre y que ni un caso (que lo ejecute) ni un README de su
   carpeta documentan: corre en la regresión sin que nadie diga qué prueba.

Los bancos que piden su programa por nombre (`gpu_smoke_tb`, `gpu_plasma_tb`, `gpu_bench_tb`...) no
usan `fixtures/`: los resuelve `stage_programs.py` desde `x.tests`, y `fixtures-report` solo los vigila.

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

Cada semilla queda en `reports/<build>/sweep-<fecha>/seed-N/`, con
`results.json` y `medians.json` en la carpeta del barrido. Al final imprime
cuántas cumplen, el rango, la mediana y la semilla con más margen. Hay dos
usos distintos, y cada uno tiene su opción:

- **Fijar semilla porque vamos justos** (`--apply`): escribe `--seed N`, la de
  más margen, en el `nextpnr-extra-options` del `apio.ini` (solo si alguna
  cumple timing; conserva comentarios y saltos de línea). Es opt-in: las
  carpetas GPU no fijan semilla a propósito, ahí no se usa. Deja el bitstream
  en STALE hasta que se reconstruya con la semilla nueva. Los párrafos de
  números del `apio.ini` se siguen apuntando a mano.
- **Saber si un cambio de RTL mejora o empeora** (`--compare`): no fijes una
  semilla, que mezcla el efecto del cambio con el ruido del placement. Barre
  las mismas semillas antes y después, y compara:

  ```bash
  $ build-sweep --prototype 17 --seeds 1 2 3 4 5 6 7 8      # antes del cambio
  # ... cambio de RTL ...
  $ build --prototype 17
  $ build-sweep --prototype 17 --seeds 1 2 3 4 5 6 7 8 \
        --compare 17.fpga-gpu-ram-v2/reports/<build-antiguo>/sweep-<fecha>
  ```

  Por reloj imprime mediana, peor caso y rango de los dos barridos, y un
  veredicto: `MEJORA`, `EMPEORA` o «dentro del ruido» cuando el cambio de
  mediana no supera dos veces el error típico de la diferencia entre los dos
  conjuntos (desviación / √n de cada uno). El rango de las semillas no vale
  para esto: con ocho es tan ancho que tapaba una mejora de +6 MHz. Exige exactamente las mismas
  semillas que el barrido de referencia y se niega antes de barrer si no
  coinciden. Es una heurística, no una prueba estadística.

**Probar opciones de nextpnr** (`--nextpnr-options`): antes de tocar el
`apio.ini`, se mide con el mismo barrido sobre el mismo build archivado. Las
opciones van **sin guiones** y con `=` para el valor, para que no dependan de
cómo cite cada shell:

```bash
$ build-sweep --prototype 30 --seeds 1 2 3 4 5 6 7 8 --nextpnr-options tmg-ripup placer-heap-timingweight=120 \
      --compare 30.fpga-cpu-console/reports/<build>/sweep-<base>
```

Quedan anotadas en el barrido (`--list` las muestra en la columna OPCIONES) y
con `--apply` se escriben en el `apio.ini` **junto con la semilla**: una semilla
solo vale con las opciones con las que se midió. No admite `seed`, `json`,
`report`, `lpf`, `textcfg`, `package`, `speed` ni `force`, que ya pone el
barrido. Hay que comparar siempre contra un barrido base **con las mismas
semillas y el mismo build**.

Lo medido en la 30 (ocho semillas, mismo netlist, mediana de `sdram_clk`, 80
MHz exigidos): `tmg-ripup` y `placer-heap-timingweight` de 60 a 250 suben la
mediana y hacen que algunas semillas cumplan; `--router router2` la baja 13 MHz;
`placer-heap-critexp`, `placer-heap-beta` y `freq` dan exactamente lo mismo que
sin ellas, y `placer static` empeora. `tmg-ripup` alarga el rutado (unos 4-5
minutos por semilla en la 30).

**Consultar barridos ya hechos** (no lanza nada ni crea registro en `reports/`):

```bash
$ build-sweep --prototype 6 --list            # una fila por barrido y reloj
$ build-sweep --prototype 6 --show latest     # detalle por semilla del último
$ build-sweep --prototype 6 --show 20260920-1334   # o un trozo del nombre (ver --list)
```

`build-sweep --last` (sin `--prototype`) hace lo mismo para todos los prototipos
a la vez: una fila por reloj del **último** barrido de cada prototipo que tenga
alguno, con el margen del peor caso sobre lo exigido.

En terminal (y sin `NO_COLOR`), `--last`, `--list`, `--show`, `--compare` y el
resumen del propio barrido colorean los valores: peor / mediana / mejor y el
margen en verde si llegan a lo exigido y en rojo si no; `CUMPLEN` en verde si
cumplen todas las semillas, amarillo si algunas y rojo si ninguna; y el
veredicto de `--compare` (`MEJORA` verde, `EMPEORA` rojo, ruido amarillo). Al
redirigir a un fichero o al log no se escribe ningún código de color.

`--list` enseña, de todos los builds archivados, cuántas semillas cumplieron y
el peor / mediana / mejor de cada reloj frente al exigido; `2/3` en SEEDS
significa que una semilla pedida no llegó a dar informe. `--show` añade el
margen en % por semilla y marca las que no dieron informe. Acepta `latest`, un
trozo único del nombre del barrido o su ruta.

**Cuándo fijar semilla y qué Fmax declarar.** Se fija (`--apply`) cuando el
margen se mide en unidades, como en las carpetas de CPU: ahí la semilla decide
si el diseño cumple. En las de GPU (12, 14, 17, 22) el margen se mide en
decenas por ciento, la semilla no decide nada, y fijarla solo daría un número
reproducible a costa de rebarrer con cada cambio de RTL: no se fija. En ese
caso el Fmax que vale es el **peor** del barrido, no el de un build suelto, que
es optimista y no reproducible. Para una medición reproducible concreta sí se
puede fijar la semilla, pero no representa el peor caso del barrido.

`build-sweep` no sintetiza: re-ruta el `hardware.json` del último build
archivado. Si el RTL ha cambiado desde entonces devuelve ocho números
plausibles y falsos, así que ejecuta `build` justo antes.

Antes reemplazaba a `tools/seed-sweep.ps1` (retirado): ese trabajaba directo
sobre `_build/<env>/` sin pasar por el archivo de `reports/`; `build-sweep`
pide un build archivado primero, pero a cambio verifica que ese build pasó
timing y queda constancia de qué fuentes se barrieron.

## El muro de caminos casi críticos (`timing-wall`)

Un build que cierra con poca holgura casi nunca tiene **un** camino malo: tiene
cientos casi igual de malos, y arreglar el peor solo descubre el siguiente.
`timing-wall` enseña ese muro —qué registros de destino llegan tarde, de qué
módulos son y cuántos— y compara dos builds para ver si un cambio baja el muro o
solo el primer camino:

```bash
$ timing-wall -p 30                                   # último build (o, si no trae detalle, el último barrido)
$ timing-wall -p 30 --sweep latest --seed 5           # una semilla concreta de un barrido
$ timing-wall <barrido> --compare <otro-barrido>      # antes y después de un cambio de RTL
$ timing-wall informe.pnr --clock sdram --top 30
```

Acepta un `hardware.pnr`, una carpeta `seed-N` o un barrido entero (se toma su
mejor semilla). Por defecto mira el reloj de menos margen. La `LLEGADA` es el
tiempo acumulado hasta el registro de destino desde el flanco de reloj, como el
último número de un camino crítico; `HOLGURA = periodo − llegada`, y las columnas
`>=80 %` y `>=90 %` cuentan destinos por encima de esa fracción del periodo. Sale
además el resumen por módulo, que suele decir más que la lista de registros.

Ejemplo real (la 30, sdram_clk a 80 MHz): del mejor build sin opciones de
nextpnr al que está en la placa, los destinos a ≥ 80 % del periodo bajan de 675 a
293 y los de ≥ 90 % de 223 a 11. Antes de arreglar nada, el 80 % del muro eran
registros anchos de `dmem_adapter_i` (`wb_data`, de 128 bits, y sus máscaras).

Necesita el informe detallado de nextpnr (`--detailed-timing-report`): **todas las
semillas de `build-sweep` lo llevan**, pero un `build` normal no, salvo que el
`apio.ini` lo pida. Solo se miran los destinos del reloj elegido, sin las rutas
hasta los pines. Es una lectura de un solo netlist y una sola semilla: la
colocación mueve las cifras, así que conviene comparar semillas de un mismo
barrido y no una contra otra suelta.

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
actualizado: docs/resumen-prototipos.md
actualizado: docs/synthesis-report.md

$ generate-docs --check     # no escribe nada; exit code 1 si algo cambiaría (para CI)
$ generate-docs --list-generators
```

`generate-docs` descubre los bloques declarativos en todos los Markdown que
forman parte del modelo. Tanto `docs/synthesis-report.md` como
`docs/resumen-prototipos.md` conservan el texto escrito a mano: la herramienta
**solo** toca lo que haya entre los marcadores de cada bloque. Por ejemplo:

```markdown
<!-- gendoc:begin cpu-capabilities
generator: cpu-matrix
-->

... contenido generado ...

<!-- gendoc:end cpu-capabilities -->
```

El nombre del bloque es local al documento y el campo `generator` selecciona
el generador registrado. El mismo mecanismo materializa queries del grafo:

```markdown
<!-- gendoc:begin identity-register-implementations
generator: trace.query
query: implementations-of
arguments:
  - SPEC-DEVICE#identity-register
-->

... tabla generada ...

<!-- gendoc:end identity-register-implementations -->
```

El generador llama directamente a `ModelBuilder`, `Graph` y `CORE_QUERIES`; no
duplica la semántica del CLI. `--check` comprueba también estos bloques sin
escribir. Como dogfood, `tools/generate_docs.py` declara el artifact
`IMPL-GENDOC` y símbolos formales para sus cuatro generadores.

Todos se despachan ahora mediante `GeneratorRegistry`: `synthesis-table`,
`cpu-matrix`, `gpu-matrix`, `prototype-summary` y `trace.query`. El decorador
`@generator` permite registrar otros generadores Python sin añadir ramas al
dispatcher. `--list-generators` muestra el inventario disponible. En cada
ejecución se recalculan todos los bloques encontrados; la
caché de `trace` conserva también qué recursos contienen bloques, por lo que
`generate-docs` solo vuelve a abrir esos Markdown y solo los escribe cuando el
texto renderizado cambia. Todavía no existe caché ni declaración de dependencias
específica por generador.

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

### Cambiar la fuente de la consola sin resintetizar (`font-patch`)

La fuente de `text_console.v` es contenido inicial de cuatro EBR: cambiarla no
cambia el netlist, así que no hace falta volver a sintetizar. `font-patch`
localiza esos EBR en `_build/default/hardware.config` por su contenido (detecta
cuál de las fuentes de `fonts/` lleva), los reescribe con la pedida y repaquea
con `ecppack`:

```bash
$ font-patch --prototype 30 pc               # deja _build/default/font-pc.bit
$ font-patch --prototype 30 cpc464 --upload  # y lo programa (SRAM) con fujprog
```

No toca `hardware.bit` ni el sello de subida. Tras `--upload` la CPU arranca
vacía: recarga el programa con `board-load`. Solo vale para el netlist con el
que se construyó el `.config`; si cambia el RTL hay que reconstruir, y entonces
la fuente entra por `FONT_FILE`. Parchear a la fuente por defecto da el mismo
bitstream, byte a byte, que una síntesis completa (comprobado en la 30).

### Suite de casos contra placa real (`test-board`)

`x.tests/run_tests.py` necesita `--backend cpu-fpga`/`gpu-fpga` y `--version`
(el nombre corto de `x.tests/backends/{fpga,gpu_fpga}.py`), que hay que saber
a mano. `test-board` los infiere del mismo sitio que `board-info`/`run-board`
(el RTL, vía `_capabilities()`), detecta el puerto igual que el resto de
comandos de placa, y reenvía todo lo demás (`TEST_JSON`, `--trace`, `-y`,
`--measure`...) a `run_tests.py` sin tocarlo:

```bash
$ test-board --prototype 21 -y cases-cpu/basics
Puerto detectado: /dev/cu.usbserial-D00688 (ULX3S FPGA 85K v3.0.8)
Using prototype: 21.fpga-cpu-hdmi-alu
$ .../run_tests.py --backend cpu-fpga -p 21 --port /dev/... -y cases-cpu/basics
PASS smoke [cpu-fpga]
PASS zero-register [cpu-fpga]
2 caso(s), 0 fallo(s), 0 omitido(s) por arquitectura o capacidades, 1.7s
```

Si el prototipo no tiene identidad inferible (sin `cpu.v`/`gpu_sm.v`/
`gpu_system.v` + `monitor.v` con versión), falla con un mensaje claro en vez
de adivinar — en ese caso usa `x.tests/run_tests.py` directamente con
`--backend`/`--version` a mano.

### CPI y reparto de los ciclos (`--measure`)

`test-board --prototype 30 --measure medidas.md <casos>` ejecuta cada caso y
escribe una tabla en Markdown: instrucciones y CPI por versión, tiempo de CPU y,
**solo para las versiones con contadores de espera** (capacidad `perf_stalls`, hoy
la 30), una tercera tabla, «Reparto de los ciclos»: qué fracción de los ciclos de
cada caso es cálculo, espera a la búsqueda de instrucciones, espera a datos y
espera a MMIO, más la tasa de acierto del búfer de instrucciones y las peticiones
a memoria por instrucción. Los contadores son los de CPU PERFORMANCE
(`1.isa/mmio.md` §13.2); las versiones que solo tienen `CYCLES` y `RETIRED` salen
sin esa tabla, no con ceros.

Para mirar un programa suelto, o uno que ya está corriendo en la placa, el
`monitor.py` de la 30 tiene `perf`: `monitor.py perf` da lo acumulado y
`monitor.py perf 2` lo contado en una ventana de 2 s, que es lo correcto cuando
lleva minutos corriendo (los contadores dan la vuelta a los 53 s a 80 MHz).
Los dos usan `tools/perf_counters.py`, así que reparten los ciclos igual.

#### Archivo de medidas y comparación (`measure-compare`)

`--measure` archiva cada medida en `<prototipo>/reports/<fecha>-medida-<etiqueta>/`
(`measure.json` y `measure.md`), con o sin nombre de fichero. Guarda los datos de
cada caso, el hash de las fuentes sintetizables y el Fmax del build hecho con
*esas* fuentes; si no hay un build que coincida, el Fmax queda en `n/d`. Se pone
nombre con `--measure-label antes-de-segmentar`.

```bash
$ measure-compare -p 30                 # las dos medidas más recientes del prototipo
$ measure-compare A B                   # carpetas o measure.json, primero la de antes
```

Junta CPI y frecuencia en **ns por instrucción = CPI / Fmax**, para juzgar una
propuesta de subir Fmax que empeore el CPI. Es una **proyección**: el reloj real
está fijo (80 MHz, por el divisor de la UART) y nadie ha corrido a la Fmax del
build. El CPI global es ciclos totales entre instrucciones totales, sin los casos
de vídeo y UART, cuyas instrucciones dependen del reloj o del baudrate.

#### Probar todos los prototipos (`test-all`)

`test-all` ejecuta la suite completa en cada prototipo con placa, de uno en uno
(hay una sola placa), y escribe una matriz caso × prototipo en
`reports/pruebas/<fecha>-<familia>.md`: `PASS`, `FAIL` o `SKIP`, con una sección
que dice por qué se omitió cada caso y otra con el detalle de los fallos. Un
`SKIP` por capacidades no es un fallo; el código de salida es 0 solo sin `FAIL`
ni prototipos que no arrancan. Una pasada que termina con código distinto de cero
sin ningún `FAIL` (una excepción del arnés a mitad) sale como `INCOMPLETO` en la
columna Estado, con lo ya ejecutado en la matriz: antes salía como `OK` con medio
informe.

```bash
$ test-all --family gpu --yes          # 12, 14, 22 y 29
$ test-all --family cpu --yes
$ test-all -p 22 -p 29 --yes           # solo esos
$ test-all --list
```

#### Medir todos los prototipos y comparar (`bench-all`, `perf-report`)

`--measure` funciona con `--backend cpu-fpga` y con `--backend gpu-fpga`. En GPU
el CPI son ciclos por instrucción **de warp**, y solo salen ciclos donde el RTL
tiene el bloque GPU PERFORMANCE (22 y 29; en 12 y 14 sale `sin contadores`).

```bash
$ bench-all --list                      # qué prototipos mediría, sin tocar la placa
$ bench-all --yes                       # todos, CPU y GPU, y al final el informe
$ bench-all --family gpu -p 22 --yes    # solo la 22
$ perf-report                           # solo el informe, con lo ya archivado
$ perf-report --label bench --history 8
```

`bench-all` llama a `run_tests.py --measure -p N` por prototipo, así que cada uno
sube su bitstream (y lo sintetiza si sus fuentes cambiaron: la primera pasada
tarda). Un prototipo que falla no detiene a los demás. El informe va a
`reports/rendimiento/<fecha>-informe.md` y trae, por familia: un resumen por
prototipo (reloj, Fmax, CPI, ns/instr), y tablas de tiempo (ms), CPI y FPS donde
cada fila es un programa y cada columna un prototipo, más la evolución de cada
uno entre medidas y los casos cuyo CPI cambió un 1 % o más.

Tres cosas que el informe repite donde importan: el CPI del resumen es sobre los
casos que **todos** los prototipos de la tabla midieron (otro conjunto da otro
promedio); los programas de vídeo y UART llevan `*` porque su tiempo depende de
vsync o del baudrate; y los FPS son intercambios por segundo de la placa, que con
vsync a 60 Hz no pasan de 60 y solo se dan con 10 intercambios o más (con menos
sale `corto`: el arranque pesa más que el ritmo). Los prototipos sin contadores
(6, 10, 12 y 14) no entran en el CPI común, y la evolución compara cada medida con
la anterior solo sobre los casos que ambas tienen. Los casos de vídeo de GPU (`demo-plasma`)
corren en placa en la 22 y la 29: paran tras N intercambios sondeando
`SWAP_COUNT`, igual que los de CPU (`x.tests/backends/video_stop.py`).

## Herramientas de vídeo/HDMI

Comunes a los cuatro prototipos con framebuffer + HDMI, todas con `--prototype`/`-p`:

```bash
$ make-framebuffer bars fb.bin                                  # genera un patrón RGB565 320x240
$ demo-no-cpu --prototype 21 --pattern frame                    # lo muestra sin ejecutar CPU
$ capture-frames --prototype 21 swap_demo_fast --frames 4       # captura frames deterministas
$ measure-demo --prototype 21                                   # FPS de swap_demo/tear_demo (lee R21)
```

`make-framebuffer` no depende de ninguna versión concreta. `demo-no-cpu`
genera uno de sus patrones, para el núcleo, lo carga en SDRAM y configura el
scanout con el mapa MMIO común; acepta `--port` y detecta el FTDI si se omite.
`capture-frames` y `measure-demo` sí hablan con una
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
$ capture-frame-sim cases-cpu/video/bounce/bounce.asm --swap 20 frame.png
$ capture-frame-sim cases-cpu/video/band/band.asm --instrucciones 500000 frame.bin
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
