# Tests de MiniCPU y MiniGPU

También incluye el backend funcional MiniGPU (`--backend sim-gpu`), con casos en
`cases-gpu`. Los casos CPU están en `cases-cpu` y el modo `both` sigue comparando
exclusivamente el simulador CPU con la FPGA. `cases-shared` tiene los que
declaran las dos arquitecturas.

## Dónde viven los programas

Todo `.asm` de prueba o de demostración vive aquí, una sola vez, y no dentro de
la carpeta de cada prototipo. Las carpetas de prototipo no tienen `examples/`
versionado: lo que sus testbenches Verilog leen de `generated/programs/*.hex` lo genera
`tools/stage_programs.py` desde estos fuentes (lo ejecuta `test`, y no se
versiona).

- `cases-*/<familia>/<caso>/` — casos con `test.json` y expectativas.
- `cases-cpu/demos/` y `cases-gpu/demos/` — las antiguas `examples/`. Cada
  programa tiene su carpeta, con `test.json` si es comprobable de forma barata.
  Las variantes para ISAs anteriores llevan `.legacy-<prototipos>.asm` y no se
  ejecutan: son para las placas viejas (16/18/19, 12/14/17).
- [`cases-cpu-gpu/`](cases-cpu-gpu/README.md) — las antiguas `examples/` del prototipo 32: programas que usan la
  CPU y la GPU a la vez, en ensamblador y en C, uno por carpeta con su README. No llevan `test.json`: no hay
  backend que corra CPU y GPU juntas por `run_tests.py`, y los comprueba `32.cpu-gpu-func-sim/test_cpu_gpu_sim.py`.
  `run_tests.py` no los descubre.
- [`unit/`](unit/README.md) — los tests de Python de la infraestructura (`test_*.py`), agrupados por tema. Los
  lanzadores (`run_tests.py`, `record_case.py`, `test`) se quedan en esta carpeta.

### Convertir una demo en un caso

Una demo que termina sola, o que se puede parar tras N intercambios de vídeo
(`run_until: {"swap": N}`), se convierte en caso sin teclear las expectativas:

```powershell
# 1. escribe test.json con nombre, program, requires, max_instructions y "expect": {}
# 2. grábalo desde el simulador; --tighten deja max_instructions en el doble de
#    lo observado, y --frame guarda el frame tras run_until.swap
python record_case.py cases-cpu/demos/swap-smoke/test.json --tighten --frame
```

Lo grabado es una instantánea del simulador, no un oráculo independiente: su
valor llega al ejecutarlo contra la placa (`--backend both` / `gpu-both`), donde
el RTL debe coincidir. Un caso de demo tiene que parar en cuanto ha hecho lo
mínimo para comprobarse (una demo que tarda decenas de segundos no es un test):
por eso `tear_demo` y `tear_demo_fast`, que necesitan ~65 s en el simulador
para tres intercambios, no son casos.

## MiniGPU: ejemplo completo de suma de vectores

Desde `x.tests`:

```powershell
python run_tests.py --backend sim-gpu
python run_tests.py cases-gpu/memory/vecsum/test.json --backend sim-gpu
python -m unittest unit.runner.test_gpu_runner -v
```

El runner ensambla `vecsum.asm`, carga `a.hex` en 0x100 y `b.hex` en 0x140,
aplica `warps.json` y compara las 16 palabras de C en 0x180 con `expected.hex`.
No hace falta construir `memoria.bin` ni volcar resultados manualmente. El caso
comprueba también 16 instrucciones totales, PC=0x20 y 8 instrucciones por warp,
registros de varios hilos y que el warp 2 no haya ejecutado nada.

Los casos GPU requieren `architecture: "gpu"` y `warp_config`, una ruta relativa al `test.json`, y usan
los mismos campos `program`, `initial_memory` y `expect.memory_dumps` de CPU.
`expect.instructions_executed` cuenta instrucciones de warp completadas.
Para observar estado privado se usa, por ejemplo:

```json
{
  "warps": {
    "1": {
      "pc": "0x38",
      "active_mask": 0,
      "instructions_executed": 14,
      "registers": {
        "7": {"R1": 15, "R8": 115}
      }
    }
  }
}
```

Este fragmento va dentro de `expect`; las claves son ID de warp e ID local de
hilo. Solo se comparan las observaciones solicitadas. No existe un `expect.pc`
ni un banco `expect.registers` global para GPU. Un caso CPU enviado al backend
GPU, o uno GPU enviado a CPU/FPGA, se rechaza. Cada ejecución GPU crea memoria
nueva y admite programas de hasta 32 MiB; usa `max_instructions` como límite,
no `timeout_seconds`. `--version current` selecciona el simulador actual.

Este directorio contiene casos que pueden ejecutarse sobre el simulador
funcional, la FPGA o ambos. Cada backend produce el mismo estado observable:
estado de parada, error, PC, registros solicitados y regiones de memoria.

## Ejecución

Hay siete combinaciones principales de backend y versión. Cada una ejecuta la
suite entera de su arquitectura; el runner omite por su cuenta los casos de la
otra, y los que piden capacidades que ese backend no tiene.

### Casos C generados por mini-lcc

El submodulo [`../y.lcc`](../y.lcc) contiene tests C del backend MiniISA de
lcc. Para aprovecharlos desde esta infraestructura sin duplicar manifiestos
derivados en git:

```powershell
python run-mini-lcc-tests.py --backend sim-cpu
```

El adaptador ejecuta `y.lcc/run-mini-tst.py`, reutiliza los `.bin`, `.json` y
dumps esperados generados en `y.lcc/mini-tst-out/`, y crea casos temporales en
`x.tests/generated/mini-lcc/`. Esa carpeta esta ignorada porque se regenera a
partir de los `.c`.

Para pasar opcionalmente el ensamblador generado por `mini-opt` antes de crear
los casos de `x.tests`:

```powershell
python run-mini-lcc-tests.py --backend sim-cpu --optimize
```

`--compare-optimizer` conserva y ensambla las dos formas, muestra el recuento
antes/después y hace que `x.tests` valide la optimizada. Si se combina con
`--simulate-lcc`, el runner propio de Mini-LCC simula y comprueba también ambas:

```powershell
python run-mini-lcc-tests.py --backend sim-cpu --compare-optimizer --simulate-lcc
```

Por defecto no se invoca el optimizador. Tanto el `.s` original como el
`.opt.s` se conservan bajo `y.lcc/mini-tst-out/`. Fuera de un checkout de
Mini-GPU se puede indicar el ejecutable con `--mini-opt RUTA`.

Por defecto se omiten los `xfail` conocidos de `mini-lcc` que generan
manifiesto, ya que `x.tests` no tiene semantica de fallo esperado. Para
investigarlos como fallos normales:

```powershell
python run-mini-lcc-tests.py --backend sim-cpu --include-xfail
```

Desde `x.tests`. `--port` es opcional: sin él, detecta el primer adaptador
FTDI conectado; solo hace falta si hay varios o para forzar uno en concreto
(por ejemplo, en Windows con "COM3"):

```powershell
# 1. CPU sobre el simulador funcional
python run_tests.py --backend sim-cpu

# 2. CPU sobre FPGA, versión EBR
python run_tests.py --backend fpga-cpu --version ebr --port COM3

# 3. CPU sobre FPGA, versión SDRAM
python run_tests.py --backend fpga-cpu --version sdram --port COM3

# 4. CPU sobre FPGA, versión con vídeo, sub-palabra y llamadas
python run_tests.py --backend fpga-cpu --version subword --port COM3

# 4b. CPU sobre FPGA, además con la ALU completa, shifts inmediatos y R0 a cero
python run_tests.py --backend fpga-cpu -p 21 --port COM3

# 5. GPU sobre el simulador funcional
python run_tests.py --backend sim-gpu

# 6. GPU sobre FPGA, versión BRAM
python run_tests.py --backend fpga-gpu --version bram --port COM3
```

En los backends FPGA, `-p`/`--prototype` permite seleccionar la versión por
número, nombre completo o ruta del prototipo. Por ejemplo, `-p 21` equivale a
`--version alu`. Ambas opciones son alternativas y no se pueden combinar.

Qué necesita y qué ejecuta cada una:

| # | Backend y versión | Bitstream | Monitor | Casos |
|---:|---|---|---:|---|
| 1 | `sim-cpu` | ninguno | — | todos los de `cases-cpu/` y `cases-shared/` |
| 2 | `fpga-cpu --version ebr` | [6.fpga-cpu](../6.fpga-cpu/) | 1.16 | 13; 21 omitidos por capacidades |
| 3 | `fpga-cpu --version sdram` | [10.fpga-cpu-ram](../10.fpga-cpu-ram/) | 1.17 | 12; 22 omitidos. Sin `mul_div`: ver abajo |
| 4 | `fpga-cpu --version subword` | [19.fpga-cpu-hdmi-ls](../19.fpga-cpu-hdmi-ls/) | 1.20 | 28; 10 omitidos por capacidades |
| 4b | `fpga-cpu --version alu` | [21.fpga-cpu-hdmi-alu](../21.fpga-cpu-hdmi-alu/) | 1.15 | todos los de `cases-cpu/` y `cases-shared/` |
| 4c | `sim-sys` | ninguno | — | los de `cases-cpu/` y `cases-shared/` más `cases-cpu/gpu/` (los que piden `gpu_core`) |
| 5 | `sim-gpu` | ninguno | — | los 34 de `cases-gpu/` |
| 6 | `fpga-gpu --version bram` | [12.fpga-gpu](../12.fpga-gpu/) | 2.3 | 26 compatibles; 8 omitidos con motivo |
| 7 | `fpga-sys --version cpugpu` (o `mk2`) | [36.fpga-cpu-gpu](../36.fpga-cpu-gpu/) (o la 37) | 5.36 (5.37) | la GPU de una CPU+GPU: pocos casos, ver abajo |

**La 36 y la 37 son CPU y GPU a la vez.** Como CPU se prueban con `fpga-cpu`
(`--version cpugpu` o `mk2`) y no han dejado de serlo. Su GPU la lanza la CPU por
MMIO (GPU CORE) y el monitor gobierna la CPU, no la GPU, así que `fpga-gpu` no
las conoce; las prueba `fpga-sys`, que hace de CPU desde el host (escribe los
descriptores y `GPU_CONTROL` por `write_word` con la CPU parada). `test-board -p 37`
lanza las dos, una tras otra (`--family cpu|gpu` elige una). De los 78 casos de
`cases-gpu/` solo corren los que no piden el PC, la máscara de lanes ni los
registros de los warps, porque el RTL no los expone por MMIO: hoy dos más los
compartidos que no dependen de ello. Los demás salen como `SKIP` con motivo. El
diseño, qué falta y cómo desbloquearlos: [backend-fpga-sys.md](backend-fpga-sys.md).
`--measure` todavía no admite `fpga-sys`.

`ebr`, `sdram`, `hdmi`, `bl8`, `subword` y `alu` son versiones del backend
**CPU**; `bram` lo es del backend **GPU**. No hay ninguna versión `ebr` de GPU.
Solo `sim-cpu` y `fpga-cpu --version alu` ejecutan los 38 casos: son los
dos únicos que tienen las ocho capacidades.

**`sdram` no tiene `mul_div`, y esa capacidad es distinta de las demás.**
`10.fpga-cpu-ram` no implementa `MUL`, `MULFX` ni `DIV`, que son instrucciones
**base** de la MiniISA, no extensiones. Salió al correr el diferencial contra esa
placa por primera vez. Se probó el port —copiar el `cpu.v` de la 6, que resultó
ser un superconjunto estricto— y funciona, pero deja el diseño en una de ocho
semillas al +2,4 %; el detalle está en
[`10.fpga-cpu-ram/cpu.v`](../10.fpga-cpu-ram/cpu.v).

`mul_div` es por tanto la única capacidad que significa «a este backend le
**falta** algo de la base» en vez de «tiene algo **de más**». Conviene no leer su
`SKIP` como «aquí no hace falta»: ahí falta algo que la ISA exige. El día que la
10 implemente las tres, la capacidad desaparece entera en lugar de extenderse a
más backends.

La selección automática para `fpga-gpu` y `gpu-both` omite con un mensaje
`SKIP` los casos que requieren capacidades no implementadas:

- Cuatro casos de `simt/capacity` fijan profundidades mediante `simulator_options`.
- Mandelbrot original y los dos casos de memoria fuera de rango usan direcciones
  o dumps fuera de los 128 KiB de BRAM. Mandelbrot packed sí es compatible.
- División por cero exige ausencia de efectos parciales en todas las lanes
  (`requires: ["atomic_warp_faults"]`); el RTL no garantiza ese comportamiento.

Si se pide explícitamente uno de esos casos, el runner falla antes de abrir
el puerto o cargar un bitstream. También valida el lanzamiento (8 lanes, PC,
máscaras y workgroup) y rechaza expectativas de dirección efectiva de fallo,
que este monitor no conserva. El simulador sigue ejecutando los 34 casos con
sus expectativas completas.

El backend FPGA lee PC, máscara activa y contador por warp, el contador total,
y PC/warp/lane del primer fallo. Solo lee los registros citados en las
expectativas para evitar 2048 transacciones UART por caso. Las observaciones
no disponibles nunca se sustituyen por valores esperados.

Desde la raíz del repositorio, para actualizar una placa con otro bitstream y
probar todos los casos compatibles:

```powershell
.\.venv\Scripts\python.exe .\x.tests\run_tests.py --backend fpga-gpu --version bram --port COM3 --yes --durations
```

El backend exige monitor **3.12** y ofrece cargar `12.fpga-gpu` si responde otra
versión o si el monitor no responde. `--yes` autoriza esa carga. No fuerza una
recarga si ya responde 3.12; para cargar otra compilación de la misma revisión:

```powershell
.\.venv\Scripts\apio.exe upload -p .\12.fpga-gpu
if ($LASTEXITCODE -ne 0) { throw "Falló la carga" }
.\.venv\Scripts\python.exe .\x.tests\run_tests.py --backend fpga-gpu --version bram --port COM3 --no-upload --durations
```

`apio` se busca junto al ejecutable de Python y, si no está allí, en PATH.
La carga recibe salida en vivo. Para comparar también con el simulador, usa
`--backend gpu-both --version fpga-gpu=bram`; se comparan estados, memoria y
observaciones exigidas por el caso, excluyendo la duración de ejecución.

Los tres backends de FPGA comprueban la placa al arrancar y, si hace falta,
ofrecen cargar su bitstream; ver [Placa y bitstream](#placa-y-bitstream).

Además, `--backend both` ejecuta cada caso CPU en el simulador **y** en la FPGA
y compara los dos estados observados entre sí:

```powershell
python run_tests.py --backend both --version fpga-cpu=sdram --port COM3
```

Sin rutas explícitas se descubren todos los ficheros `cases-cpu/**/test.json`. Los
casos CPU se agrupan igual que los GPU:

| Grupo | Qué valida |
|---|---|
| [alu](cases-cpu/alu/) | Reglas de la ALU que la ISA fija explícitamente |
| [basics](cases-cpu/basics/) | Camino mínimo de ejecución y de memoria, y `R0` cableado a cero |
| [errors](cases-cpu/errors/) | Códigos de error y PC de la instrucción causante |
| [extensions](cases-cpu/extensions/) | Lo posterior a la v0.1: llamadas, accesos sub-palabra, consola serie, desplazamientos inmediatos y ALU extendida |
| [programs](cases-cpu/programs/) | Programas con bucles, como prueba de integración |
| [video](cases-cpu/video/) | Registros de vídeo, intercambio y frame capturado |

Los de `extensions` y `video` llevan `requires`, así que no corren en todos los
backends; ver [Capacidades](#capacidades).

También se puede ejecutar uno o varios casos concretos:

```powershell
python run_tests.py cases-cpu/basics/smoke/test.json --backend sim-cpu
```

Los casos GPU admiten traza del scheduler. `--trace-limit` limita los eventos
mostrados, pero no la ejecución ni las comprobaciones del caso; `--trace-file`
los guarda en vez de escribirlos en stderr:

```powershell
python run_tests.py cases-gpu/memory/vecsum/test.json --backend sim-gpu `
    --trace --trace-limit 100 --trace-file ejecucion.log
```

`--trace-detail` añade cambios de registros y accesos a memoria. Para
Mandelbrot conviene usar siempre un límite pequeño, porque una ejecución completa
produce millones de eventos aunque solo se quieran inspeccionar los primeros.

La salida indica siempre el tiempo total, y anota el de cada caso que pase de un
segundo. `--durations N` lista además las N ejecuciones más lentas al terminar
(10 si se omite el número):

```powershell
python run_tests.py --backend sim-gpu --durations 5
```

Es la forma de decidir un `timeout_seconds` con criterio en vez de a ojo. Los
tiempos son solo informativos: no forman parte de las expectativas de ningún
caso, porque volverían la suite intermitente.

`--version` selecciona la versión de cada backend. Con un único backend se
puede usar directamente `--version VERSION`; con varios se usa
`--version BACKEND=VERSION` y el parámetro puede repetirse:

```powershell
python run_tests.py --backend both `
    --version sim-cpu=current --version fpga-cpu=sdram --port COM3
```

Cada backend declara internamente todas sus versiones y cuál es la
predeterminada. Añadir una variante nueva solo requiere incorporarla al
registro `VERSIONS` del módulo correspondiente; el runner no contiene una
lista especial de versiones FPGA o del simulador.

## Placa y bitstream

Los backends de FPGA comprueban la versión física mediante `GET_VERSION`:

**La tabla de qué versión responde cada proyecto no se copia aquí**, porque se
genera sola a partir del RTL: está en
[`docs/resumen-prototipos.md`](../docs/resumen-prototipos.md). Una copia a mano
en este fichero se quedaría atrás en cuanto cambiara un `top.v`, que es
exactamente lo que le pasó a la que había.

Lo que sí conviene saber para leer esas respuestas:

```text
mayor   = juego de comandos     3  base + READ_WORD/WRITE_WORD
                                4  lo anterior + SEND_BYTES/RECV_BYTES
menor   = número de carpeta     3.6, 3.10, 3.12, 3.14, 3.16, 3.17,
                                3.18, 3.22, 4.19, 4.21
```

**Dos prototipos con el mismo juego de comandos responden distinto igualmente**,
y eso es deliberado. La 19 y la 18 tienen protocolos idénticos —las instrucciones
nuevas de la 19 viven enteras dentro de la CPU, no añaden ni un comando— pero
`GET_VERSION` es lo único que el runner puede preguntar antes de cargar un
programa: si las dos respondieran igual, daría por bueno un bitstream de la 18
para los casos de `extensions`, que pararían con error `0x01`.

Desde que el menor **es** el número de carpeta, esa unicidad ya no hay que
vigilarla a mano. Antes sí, y llegó a fallar: la 14 y la 17 compartieron número
siendo hardware distinto.

La versión predeterminada de `fpga-cpu` es `alu` (21, la más completa; antes
era `ebr`). La comprobación ocurre **una sola vez al construir el backend**,
antes de ejecutar ningún caso, y distingue tres situaciones:

| Situación | Qué significa | Qué hace el runner |
|---|---|---|
| No se abre el puerto | No hay placa, o la tiene abierta otro programa | Error, sin más. No hay nada que cargar |
| El puerto abre pero el monitor no contesta | La FPGA no tiene bitstream con monitor. El chip USB-serie de la placa enumera igual, tenga o no bitstream | Ofrece cargarlo |
| Contesta con otra versión | Está cargado el bitstream de otro proyecto | Ofrece cargar el que toca |

```powershell
python run_tests.py --backend fpga-cpu --port COM3              # pregunta
python run_tests.py --backend fpga-cpu --port COM3 --yes        # carga sin preguntar
python run_tests.py --backend fpga-cpu --port COM3 --no-upload  # nunca carga
```

La carga se hace con `apio upload` en el directorio del proyecto, y su salida se
ve en vivo, porque sintetizar puede tardar varios minutos y sin verla parece que
el runner se ha colgado.

Sin terminal interactiva y sin `--yes` el runner falla en vez de quedarse
esperando una respuesta que nadie va a dar; es el caso de CI o de una tubería.
`--yes` y `--no-upload` se excluyen entre sí.

Después de cargar vuelve a preguntar la versión: que `apio upload` termine con
éxito no garantiza que la placa quedara programada.

`RESET_CPU` permite ejecutar casos consecutivos sin reconfigurar la placa ni
borrar sus memorias.

## Formato

`test.schema.json` formaliza el JSON. Las rutas se resuelven respecto al
directorio que contiene cada `test.json`.

```json
{
  "architecture": "cpu",
  "name": "ejemplo",
  "program": "program.asm",
  "max_instructions": 1000,
  "timeout_seconds": 2.0,
  "initial_memory": [
    {
      "address": "0x00100300",
      "file": "input/data.bin"
    }
  ],
  "expect": {
    "halted": true,
    "error": false,
    "error_code": "0x00",
    "pc": "0x00000020",
    "registers": {
      "R1": "0x12345678"
    },
    "memory_dumps": [
      {
        "address": "0x00100400",
        "file": "expected/result.bin"
      }
    ]
  }
}
```

Los programas pueden ser `.asm`, `.bin` o `.hex`. El runner los convierte en
memoria a palabras little-endian sin generar artefactos intermedios.

La longitud de cada región se deduce del tamaño del fichero binario. La
comparación informa de la primera dirección y offset distintos.

Los ficheros de memoria inicial y los dumps esperados pueden ser binarios o
`.hex`. En un fichero `.hex`, cada línea representa una palabra de 32 bits que
se convierte a cuatro bytes little-endian; se admiten comentarios con `#`.

## Opciones del simulador

Un caso GPU puede fijar parámetros de construcción del simulador con la clave
opcional `simulator_options`:

```json
{
  "architecture": "gpu",
  "name": "ssy-path-overflow-depth4",
  "program": "program.asm",
  "warp_config": "warps.json",
  "simulator_options": {
    "simt_region_depth": 8,
    "simt_path_depth": 4
  },
  "expect": {}
}
```

Equivalen a `--simt-region-depth` y `--simt-path-depth` de `minigpu_sim.py` y
permiten provocar overflow de las pilas SIMT sin programas enormes. Como son
parámetros del simulador, la FPGA no puede reproducirlos: un caso que las use se
omite en el descubrimiento automático si el backend no es `sim-gpu`, y se
rechaza si se pide explícitamente. Los casos CPU no las admiten.

## Direcciones de datos

Los JSON, los programas, el simulador, la CPU y el monitor utilizan siempre
direcciones globales. El backend no suma ninguna base. Los casos compatibles
con ambas FPGA colocan el programa en `0x00000000–0x00003fff` y los datos en
`0x00100000–0x00103fff`; los casos que requieran otras direcciones deberán
seleccionar una versión con SDRAM.

## Resultado diferencial

El modo `both` realiza primero la comparación de cada backend contra los valores
esperados. Después comprueba que los estados observados del simulador y la FPGA
sean idénticos. Los valores esperados siguen siendo necesarios: dos
implementaciones podrían compartir el mismo error.

**Qué queda fuera de esa comparación, y por qué.** Un campo que es distinto por
construcción convierte el diferencial en un fallo fijo, y un fallo fijo se acaba
ignorando, que es la peor forma de perder una comprobación:

| Campo | Motivo |
|---|---|
| `cycles`, `clock_hz` | El simulador no modela el tiempo |
| `instructions` | Es arquitectónico y sí debe coincidir, pero se contrasta en `--measure`, que además sabe avisar con `¡discrepan!` |
| `video.frames` | Aquí un frame son N instrucciones; en la placa, 16,7 ms de barrido. Medido en `video-registers`: 1 contra 7068 |
| `pc`, **solo con `run_until`** | Esa parada es asíncrona y deja el PC donde pille a la CPU. Es el mismo motivo por el que `expect.pc` está prohibido junto a `run_until`. Medido en `video-bounce`: 196 contra 192, dos instrucciones del bucle de espera |

Del vídeo se sigue comparando todo lo demás, que es lo que de verdad dice si las
dos implementaciones hacen lo mismo: el frame capturado byte a byte, `swaps`
—anclado al intercambio, no al tiempo— y `fb_front`. Y `pc` sí se compara en los
casos sin `run_until`, donde la parada es determinista.

[`test_differential.py`](unit/runner/test_differential.py) fija este recorte. Hasta que se
aplicó, **los casos de vídeo fallaban siempre el diferencial** aunque
pasaran en los dos backends por separado.

## Medir: `--measure`

Los casos dicen si una versión está *bien*. `--measure` dice lo que *cuesta*:
ejecuta cada caso en cada versión aplicable y escribe una tabla en Markdown con
instrucciones, tiempo y CPI.

```bash
# Todas las versiones de placa, más el simulador
python run_tests.py --backend fpga-cpu --measure medidas.md --port COM3 cases

# Solo dos versiones, y sin nombre de fichero: solo se archiva en reports/
python run_tests.py --backend fpga-cpu --version hdmi --version bl8 \
    --measure --measure-label antes-de-segmentar --port COM3 cases-cpu/programs

# Sin placa: solo cuenta instrucciones, que es la mitad de la tabla
python run_tests.py --backend sim-cpu --version sim --measure cases
```

Cambiar de versión recarga el bitstream, así que el bucle exterior es la versión
y no el caso; con cuatro versiones son cuatro cargas, no cuatro por caso.

**La medida se archiva sola**, con o sin fichero, en
`<prototipo>/reports/<fecha>-medida-<etiqueta>/`: `measure.json` (datos de cada
caso, hash de las fuentes sintetizables y el Fmax del build de *esas* fuentes) y
`measure.md` (la tabla de esa versión). El CPI solo vale para el RTL con que se
midió, y un build que no coincide con las fuentes actuales no aporta Fmax: la
medida sale con `Fmax n/d`. `tools/measure-compare` pone dos medidas juntas; ver
`tools/README.md`.

**El tiempo no es el reloj de pared.** Entre arrancar y parar la CPU hay decenas
de vueltas de UART a 1 Mbaud, y eso enmascara por completo un programa de
milisegundos. Lo que se mide es el contador de ciclos de la placa, y el tiempo
sale de él y de la frecuencia del reloj.

**El CPI solo existe donde hay contadores.** Los añade la 18 con los comandos
`0x36` / `0x37` del monitor; la 6, la 10 y la 16 son hitos cerrados y no se
tocan, así que sus celdas dicen `sin contadores`. El simulador tampoco lo tiene,
porque no modela el tiempo: cuenta instrucciones y nada más.

**Las instrucciones sí salen de todas partes**, y ahí está el valor de mezclar
backends en la misma tabla: el número de instrucciones es arquitectónico y tiene
que coincidir. Cuando no coincide, la tabla lo marca con `¡discrepan!` y añade un
aviso, porque eso no es una versión lenta sino una CPU haciendo otra cosa.

Una medida solo cuenta si el programa terminó como el caso esperaba; los casos
de trampa se miden igual que los demás, porque terminar en error es lo suyo.

## Estado de error

Los errores detienen la CPU y hacen que el PC observable señale la instrucción
causante. Los códigos comunes son:

| Código | Significado                                             |
|-------:|---------------------------------------------------------|
| `0x01` | Opcode reservado, desconocido o todavía no implementado |
| `0x02` | Acceso de memoria inválido                              |
| `0x03` | Instrucción `TRAP` explícita                            |
| `0x04` | División por cero                                       |
| `0x05` | Opcode conocido con campos reservados inválidos         |

Los casos de `cases-cpu/errors` verifican por separado `TRAP`, opcode inválido y
encoding inválido sobre ambos backends.

## Programas de integración

`cases-cpu/programs` contiene cargas de trabajo pequeñas pero completas:

- `fibonacci`: bucle, aritmética y generación secuencial de un array;
- `array-sum`: entrada inicial, acumulación con wrap y resultado en memoria;
- `memory-copy`: dos punteros, `LOAD`, `STORE` y offset negativo;
- `shift-multiply`: multiplicación sin `MUL`, mediante sumas y shifts.

Estos casos complementan los tests unitarios de RTL comprobando el flujo entero
ensamblador, CPU, memoria, monitor y backend.

El más grande de todos no está ahí sino en
[`cases-cpu/extensions/serial/forth`](cases-cpu/extensions/serial/forth/), porque
necesita `serial`: ejecuta el [Forth de la carpeta 20](../20.forth/) entero
—1107 instrucciones, 26 opcodes— y le da una sesión que interpreta, compila una
palabra nueva con `:` y la llama. Es el único caso en el que el programa bajo
prueba es lo bastante grande como para que un fallo de una instrucción rara
salga a la luz, y el único cuyo veredicto es una transcripción de consola
comparada byte a byte entre simulador y placa.

Un detalle que condiciona su forma: **la cola de salida son 64 bytes y la
sesión escribe 74**, así que los dos backends la vacían mientras el programa
corre, no al parar. Si se deja llenar, `emit` se queda esperando hueco para
siempre y el caso muere por límite de instrucciones en vez de por lo que
estuviera probando. La entrada, en cambio, sí cabe entera en la cola antes de
arrancar, que es lo que mantiene el caso determinista.

## Casos GPU y diagnóstico de fallos

`cases-gpu` agrupa los casos por la propiedad que validan. Cada grupo y cada
caso tienen su propio `README.md`:

| Grupo | Qué valida |
|---|---|
| [simt/reconvergence](cases-gpu/simt/reconvergence/) | Divergir y volver a juntarse en el join |
| [simt/reuse](cases-gpu/simt/reuse/) | Reejecutar un `SSY` que ya está en el top |
| [simt/exit](cases-gpu/simt/exit/) | Lanes que mueren con estado SIMT abierto |
| [simt/capacity](cases-gpu/simt/capacity/) | Límites de las pilas REGION y PATH |
| [simt/barriers](cases-gpu/simt/barriers/) | Interacción de `BAR` con la divergencia |
| [faults](cases-gpu/faults/) | Diagnóstico y atomicidad de los fallos de ejecución |
| [memory](cases-gpu/memory/) | `LOAD`/`STORE` con varios warps y máscaras parciales |
| [scheduling](cases-gpu/scheduling/) | PC y contadores independientes por warp |
| [programs](cases-gpu/programs/) | Programas completos de integración |

El descubrimiento automático es recursivo, así que añadir un caso solo requiere
crear su carpeta dentro del grupo que le corresponda.

Los casos de fallo verifican que el siguiente warp se queda en su PC anterior:
no ejecuta otra instrucción tras el error global. Las pruebas del runner también
comprueban el orden round-robin `[0, 3, 0, 3, 3]` del caso de PC independientes,
los pasos después del fallo y la conservación del primer diagnóstico.

El campo opcional `expect.fault` comprueba el diagnóstico completo:

```json
"fault": {
  "pc": "0x1C",
  "warp_id": 0,
  "core_id": 3,
  "address": "0x02000000"
}
```

Se combina con `error: true` y `error_code` (el ejemplo corresponde a código 2).
El objeto exige los cuatro campos; `core_id: null` representa un fallo común
del warp y `address: null` un fallo sin dirección de acceso, como DIV o TRAP.
`fault: null` exige que no exista fallo. Si se omite `fault`, no se comprueban
estos detalles. Solo está disponible para casos GPU. Un campo ausente en el
resultado del backend nunca equivale a un `null` esperado.

## Casos para el diferencial de RTL

Los bancos `gpu_system_tb.v` / `gpu_system_bl8_tb.v` comparan el RTL con el simulador funcional. Sus
programas son casos de `cases-gpu` como cualquier otro, marcados en el `test.json`:

```json
"rtl": { "differential": true, "warp_config": "../../rtl-8-warps.json", "exclude": ["12"] }
```

- `differential`: el caso entra en las fixtures de RTL (`tools/make_rtl_fixtures.py`).
- `warp_config` (opcional): lanzamiento que usa el RTL, relativo al caso. El banco lanza **8 warps** y hay
  casos cuyo `warps.json` lanza 1 o 2 (`demos/vector`, `demos/simt`): sin esto el RTL perdería la
  cobertura multi-warp. `cases-gpu/rtl-8-warps.json` es el lanzamiento de 8 warps, todos en `pc = 0`.
- `exclude` (opcional): números de prototipo que no lo ejecutan. Solo para lo que `requires` no sepa
  decir; ahora no lo usa ningún caso.

La aplicabilidad por prototipo la da `requires`: un caso con `["mul_div"]` solo entra en los prototipos
cuyo RTL lo tiene. Una clave `rtl` desconocida es un error, no se ignora.

Qué sí y qué no marcar:

- Sí: programas deterministas que terminan con `HALT`/`EXIT` sin error y con contadores de instrucciones
  fijos, para los que el simulador es la referencia.
- No: casos con fallo esperado (`r0-load-still-faults`: el banco exige que el simulador no termine con
  error) ni con bucles de espera cuyo número de vueltas depende del planificador
  (`workgroup-barrier-isolation`: el diferencial compara contadores exactos).
- Un caso que necesite un modelo de referencia lo lleva en `reference.py`.

`fixtures-report` (ver [tools/README.md](../tools/README.md#fixtures-diferenciales-de-rtl-make_rtl_fixtures-y-fixtures-report))
muestra qué caso corre en qué prototipo y por qué se omite el que falte.

## Arquitectura y compatibilidad

Todos los casos declaran explícitamente `"architecture": "cpu"` o
`"architecture": "gpu"`. No se deduce la arquitectura del nombre del archivo
ni de su carpeta. GPU exige `warp_config`; CPU lo rechaza.

Los backends declaran `ARCHITECTURE`: `sim-cpu`, `sim-sys` y `fpga-cpu` son
CPU; `sim-gpu`, `sim-gpu-cycle`, `fpga-gpu` y `fpga-sys` son GPU. El
predeterminado de `run_tests.py` es `sim-gpu`. Las versiones se seleccionan,
por ejemplo, con `--version sim-gpu=current`.

Los nombres llevan la plataforma delante (`sim-` o `fpga-`) y detrás lo que se
ejecuta:

| Backend | Qué es | Pareja en placa |
|---|---|---|
| `sim-cpu` | [2.cpu-sim-func](../2.cpu-sim-func/) | `fpga-cpu` |
| `sim-gpu`, `sim-gpu-cycle` | [11.gpu-sim-func](../11.gpu-sim-func/) y [25.gpu-sim-cycle-uarch](../25.gpu-sim-cycle-uarch/) | `fpga-gpu` |
| `sim-sys` | [32.cpu-gpu-func-sim](../32.cpu-gpu-func-sim/): la CPU y la GPU sobre la misma RAM; ejecuta casos de CPU, con la capacidad `gpu_core` | `fpga-cpu` sobre la 36 o la 37 |
| `fpga-sys` | la GPU de la 36 o la 37, lanzada por el host con la CPU parada ([backend-fpga-sys.md](backend-fpga-sys.md)); ejecuta casos de GPU | `sim-gpu` (`gpu-sys-both`) |

Los lanzadores de `tools/` se llaman igual que los simuladores (`sim-cpu`,
`sim-gpu`, `sim-gpu-cycle`, `sim-sys`). Los diferenciales son `both`
(`sim-cpu` contra `fpga-cpu`), `sys-both` (`sim-sys` contra `fpga-cpu`),
`gpu-both` (`sim-gpu` contra `fpga-gpu`) y `gpu-sys-both` (`sim-gpu` contra
`fpga-sys`).

El descubrimiento automático omite casos de otra arquitectura y muestra cuántos.
Una ruta solicitada explícitamente con arquitectura incompatible produce código
2. Se valida la selección completa antes de construir los backends, ejecutar
programas o abrir conexiones FPGA; una selección mixta incompatible no ejecuta
parcialmente los casos válidos.

## Capacidades

La arquitectura no basta: dentro de «CPU» hay bitstreams muy distintos. El de
`6.fpga-cpu` no tiene vídeo; el de `16.fpga-cpu-hdmi` y los de las GPU `22` y
`29` sí tienen vídeo y pueden pararse tras un intercambio concreto. Un caso
declara lo que necesita:

```json
"requires": ["frame_capture"]
```

| Capacidad | Qué significa | Quién la tiene |
|---|---|---|
| `atomic_warp_faults` | Un fallo de warp no deja efectos parciales | solo el simulador GPU |
| `video` | Registros en `0x80000000` y un framebuffer que se muestra | `sim-cpu`, `sim-gpu`, `hdmi`, `bl8`, `subword`, `alu`, `console`, y las GPU `22` y `29` |
| `frame_capture` | Parar tras N intercambios y capturar el frame: hace falta `SWAP_COUNT` (se detecta de `video_registers.v` o `gpu_video_regs.v`), no `HALT_AT` | los mismos que `video` |
| `halt_on_swap` | `HALT_AT` cuenta intercambios: el arnés lo arma en vez de sondear. Implica `frame_capture`; un caso no lo pide, lo elige el backend | todas las que tienen vídeo: las CPU (`hdmi`, `bl8`, `subword`, `alu`, `console`) y las GPU 22 y 29 |
| `subword_memory` | `LOADB`/`LOADUB`/`STOREB`/`LOADH`/`LOADUH`/`STOREH`, opcodes `0x18–0x1D`. En una CPU se detecta en `cpu.v`; en una GPU, en `gpu_sm.v`, que es quien despacha la memoria | `sim-cpu`, `subword`, `alu`, `sim-gpu`, `sim-gpu-cycle` y la GPU 29 (`smpipe`) |
| `gpu_ids` | La familia `GETID` (`GETLANE`, `GETWARP`, `GETLWARP`, `GETARG`, opcode `0x30` con `type` 1 a 4) y los campos `logical_warp_id` y `arg` de cada warp en `warps.json` (`LOGICAL_WARP_ID[n]` y `WARP_ARG[n]`, `mmio.md` §14.2). Un caso que los use en `warps.json` **tiene que declararla**: el runner lo rechaza al cargarlo. Se detecta en `gpu_lane.v`; una GPU sin ella solo tiene `GETTID` y un `type` ≠ 0 para con `0x05`, así que sus casos se omiten allí | `sim-gpu`, `sim-gpu-cycle` y la GPU 29 (`smpipe`) |
| `calls` | `JAL`/`JALR`/`JR`, opcodes `0x2C–0x2E` | `sim-cpu`, `subword`, `alu` |
| `serial` | Puerto serie en `0x80000200`, y los comandos que lo alimentan | `sim-cpu`, `subword`, `alu` |
| `input` | INPUT, teclado y ratón (`mmio.md` §25, `0x80600000`). El caso lo alimenta con `"input": [líneas de guion]` (`tools/input_script.py`; `@N`/`+N` en instrucciones completadas), que se comprueba al cargar el caso. Es **que el arnés sabe alimentarlo**, no que el RTL lo tenga (eso es `input_device`): la placa recibe eventos del monitor, no tiempo en instrucciones, así que solo lo declaran los simuladores y en la placa el caso se omite | `sim-cpu`, `sim-gpu`, `sim-gpu-cycle` |
| `input_device` | El RTL tiene el bloque INPUT (`input_registers.v`), alimentado por `INPUT_EVENTS`/`INPUT_PRESENCE` del monitor. Da el bit INPUT de `DEVICES` (`mmio.md` §5.4). **No implica `input`**: tener el dispositivo no significa poder reproducir un guion con tiempo | `console` |
| `shift_immediate` | `SHLI`/`SHRI`/`SARI`: bit 10 de `SHL`/`SHR`/`SAR` | `sim-cpu`, `alu` |
| `alu_extended` | `MULHI`/`DIVU`/`REM`/`REMU`, opcodes `0x0B` y `0x0D–0x0F` | `sim-cpu`, `alu` |
| `mul_div` | `MUL`/`MULFX`/`DIV`: **base de la ISA**, no una extensión | todos menos `sdram` |
| `perf_counters` | `CYCLES` y `RETIRED` de CPU PERFORMANCE (`0x81010000`): dan el CPI de `--measure` | `hdmi`, `bl8`, `subword`, `alu`, `console` |
| `perf_stalls` | Además las ranuras 2 a 7 (`IMEM_HITS`, `IMEM_MISSES`, `MEM_TX`, `STALL_MEM`, `STALL_FETCH`, `STALL_MMIO`): `--measure` reparte los ciclos entre cálculo, búsqueda, datos y MMIO | `console` |

Las cuatro de ISA existen por la misma razón que las de vídeo: sin ellas, un
caso ejecutado en un bitstream anterior no fallaría con un diagnóstico útil,
sino con **error `0x01`, opcode inválido**, que es lo mismo que produce un
ensamblador roto o un salto a datos. Un `SKIP` dice dónde está el problema; un
`0x01` a media suite, no.

Están separadas porque son extensiones independientes. `subword_memory`, `calls`
y `serial` llegaron juntas en la 19 y `shift_immediate` y `alu_extended` juntas
en la 21, pero ocupan bloques distintos del mapa de opcodes y un backport no
tiene por qué traerlas todas a la vez. Ninguna implica a otra.

El simulador funcional las tiene todas, y eso es lo normal: va por delante del
RTL, que es donde se prueba primero una instrucción nueva.

**`shift_immediate` no se detecta por `0x01`**, y hay que saberlo antes de
escribir un caso: no añade opcodes, es el bit 10 de tres que ya existían. En un
bitstream sin ella ese bit sigue siendo reservado y el programa para con
**`0x05`, encoding inválido** —justo lo que produce un ensamblador roto—. El
`SKIP` ahorra exactamente esa confusión.

### `mul_div` va al revés que todas las demás

`alu_extended` **implica** `mul_div`, y es una implicación física: `MULHI` sale
del mismo multiplicador que `MUL`, y `REM` del mismo divisor que `DIV`. Un
backend con `MULHI` pero sin `MUL` no puede existir, así que `alu` no la declara
—le llega sola—.

Y es la única capacidad que **encogerá** en vez de crecer. Las demás se extienden
según los bitstreams las van implementando; ésta desaparece entera el día que la
10 tenga multiplicador, porque ese día ya no habrá nada que distinguir.

### Dos cosas que NO son capacidades, por motivos opuestos

**`R0` cableado a cero** lo fue —se llamaba `zero_register`— mientras solo lo
tenía la 21. Ya no: con el backport aplicado lo cumplen las nueve
implementaciones, así que es una regla de la MiniISA y no algo que un backend
pueda tener o no. Su caso vive en `cases-cpu/basics/zero-register` y corre en todas
partes, sin `requires`.

Fue además la **única capacidad no aditiva** que ha tenido este runner, y eso es
lo que no podía quedarse así. Las demás se detectan solas: un bitstream que no
las tenga para con opcode inválido y se nota. Con `R0` general no hay parada,
hay otro resultado en silencio. Una capacidad sirve para omitir un caso con
criterio; no sirve para tapar una divergencia muda entre dos backends que el
diferencial compararía.

**El camino rápido de `MULHI`/`REM`/`REMU`** no lo fue nunca, por el motivo
contrario: es invisible para la arquitectura. Acierto y fallo dan el mismo
número y solo cambian los ciclos, que el diferencial ya excluye, así que ningún
caso puede depender de él. Lo que sí hay es un caso que fija el resultado de las
secuencias en las que **no** debe acertar, y ése vale igual contra el simulador,
que no lo modela.

### El simulador tiene vídeo, pero no tiene tiempo

`sim-cpu` declara las dos capacidades de video desde que `minicpu_sim.py` tiene un
`VideoDevice`, así que los casos de vídeo corren sin placa. **Conviene entender
qué significa un verde suyo y qué no.**

Lo que sí valida: **qué** dibuja un programa. La semántica de los registros,
cuándo se aplica un intercambio respecto a las escrituras, qué framebuffer queda
visible. Un programa que dibuja y sincroniza produce en el simulador exactamente
el mismo framebuffer que en la FPGA, byte a byte.

Lo que no valida, y no va a validar nunca: **cuándo**. Aquí no hay barrido
leyendo la memoria por su cuenta, ni ancho de banda, ni contienda por el bus.
De ahí salen tres huecos concretos:

- **`underflow` es siempre cero**, porque no hay nada que pueda llegar tarde.
  Una expectativa `underflow: false` pasa en el simulador **sin comprobar
  nada**. Sigue mereciendo la pena tenerla en el caso, porque en hardware sí
  significa algo, pero un verde de aquí no es haberla probado.
- **El desgarro no existe.** Un programa que dibuje sobre el buffer visible sin
  esperar al intercambio —los `tear_demo`— sale limpio aquí y partido en la
  placa. Es un fallo de programa que el simulador no puede encontrar.
- **El «frame» es sintético**: en la placa son 16,7 ms de barrido, aquí son N
  instrucciones ejecutadas.

Ese último punto parece que invalidaría la comparación, y no lo hace, por una
razón que merece explicarse: **para un programa que espera a que su intercambio
se aplique, el periodo da igual**. El programa nunca dibuja mientras hay un
intercambio pendiente, así que la secuencia de frames es idéntica sea cual sea
el periodo; lo único que cambia es cuántas vueltas da su bucle de espera. Los
cinco casos de `cases-cpu/video` sincronizan, y por eso el simulador puede declarar
`frame_capture` honestamente. `test_capabilities.py` lo comprueba con tres
periodos distintos.

Y lo que esto habilita, que es lo importante: **`--backend both`**. Un caso de
vídeo ejecutado en los dos sitios y comparado es la herramienta que encontró
que `MUL` estaba declarado pero no implementado —pasaba en el simulador y
fallaba en la FPGA—.

`frame_capture` implica `video`, así que un backend solo declara lo que de
verdad implementa.

Cada backend publica `incompatibility(case, version)`. Cuando falta algo, el
runner imprime `SKIP` y lo cuenta **aparte de los fallos**: un caso omitido por
no haber hardware no es un caso roto, y mezclarlos haría inútil el recuento.
El motivo dice dónde sí está:

```text
SKIP video-band [sim-cpu]: el simulador no tiene frame_capture:
    no hay barrido ni framebuffer, use --backend fpga-cpu --version bl8
```

Si el caso se pide **por ruta explícita**, en cambio, no se omite: se considera
un error. Pedir un caso concreto y que se salte en silencio sería peor.

### Casos de vídeo

Tres piezas más, y las tres solo se admiten con la capacidad declarada:

```json
{
  "requires": ["frame_capture"],
  "run_until": { "swap": 4 },
  "expect": {
    "video": { "underflow": false },
    "frame": { "file": "expected/frame.bin" }
  }
}
```

**`run_until.swap` se ancla al intercambio, no al contador de frames de vídeo.**
Parar cuando el contador de frames llega a N deja la CPU en un punto cualquiera
de su dibujo, con el buffer trasero a medias, y lo que se capture depende de la
velocidad relativa entre CPU y barrido: el caso saldría distinto cada vez. En el
N-ésimo intercambio completado el frame está entero por construcción.

**Cómo se para en placa.** Hay dos caminos, según lo que declare el RTL:

- **`halt_on_swap`** (todo lo que tiene vídeo: las CPU 16, 18, 19, 21 y 30 y las
  GPU 22 y 29). `HALT_AT` cuenta intercambios completados desde que se arma
  (mmio.md §9.6), así que el backend escribe `HALT_TARGET` (bit de CPU o de GPU
  según la familia) y `HALT_AT = N` antes de arrancar, y el núcleo se para solo
  al completarse el intercambio N. En la CPU es exacto al ciclo; en la GPU el SM
  termina la instrucción en vuelo, como con cualquier parada.
- **Sin ella**, que hoy no le toca a ninguna placa con vídeo. El host sondea
  `SWAP_COUNT` mientras el programa corre y manda parar al llegar a N. Es lo que
  hace `backends/frame_capture.py`, y queda como respaldo para una versión nueva
  que tuviera `SWAP_COUNT` pero no la alarma.

El sondeo llega tarde lo que tarda el viaje por el puerto serie, y la alarma de
hardware unos ciclos. En ese hueco el programa puede pedir otro intercambio, así
que en los dos caminos se comprueba cuántos hubo de más tras parar:

| Intercambios de más | Qué se hace |
|---|---|
| 0 | se captura `FB_FRONT` |
| 1 | se captura `FB_BACK`: el buffer buscado pasó a ser el trasero |
| 2 o más | `ParadaImprecisa`: el buffer ya se repintó; el caso se repite hasta 3 veces |

Con la CPU y la GPU de placa, un caso que no sale limpio a la tercera falla con
ese error en lugar de dar un frame que difiere en un píxel y parece ruido. Medido
en la 21 con `cube-solid`, 50 ejecuciones: siempre exactamente N.

**Con `run_until` no se puede declarar `expect.pc`**, y el runner lo rechaza al
cargar. La parada es asíncrona, así que el PC queda donde pille a la CPU;
aceptarlo daría un caso que pasa o falla según lo rápido que vaya ese día. En
GPU lo mismo vale para `expect.warps` y `instructions_executed`: solo se
comprueban `halted`, `error` y el frame. `record_case.py` ya no los graba.

**`expect.frame` no lleva dirección** a propósito. Tras el intercambio N,
`FB_FRONT` alterna entre los dos buffers según la paridad: si el caso tuviera
que decir la dirección, la mitad apuntarían al buffer que no es. El backend lee
`FB_FRONT` y vuelca desde ahí.

Y el fichero de `frame` tiene que salir de un **modelo**, no de una captura de
la propia placa. Si el esperado se genera capturando, el caso solo comprueba que
la placa sigue haciendo lo que hacía, incluido lo que haga mal.
[`cases-cpu/video/band/reference.py`](cases-cpu/video/band/reference.py) es el ejemplo.
Para ver dónde difieren dos frames, [`../tools/compare-frames.py`](../tools/compare-frames.py).
