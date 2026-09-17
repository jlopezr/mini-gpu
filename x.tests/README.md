# Tests de MiniCPU y MiniGPU

También incluye el backend funcional MiniGPU (`--backend gpusim`), con casos en
`cases-gpu`. Los casos CPU siguen en `cases` y el modo `both` sigue comparando
exclusivamente el simulador CPU con la FPGA.

## MiniGPU: ejemplo completo de suma de vectores

Desde `x.tests`:

```powershell
python run_tests.py --backend gpusim
python run_tests.py cases-gpu/memory/vecsum/test.json --backend gpusim
python -m unittest discover -s . -p test_gpu_runner.py -v
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
python run-mini-lcc-tests.py --backend cpusim
```

El adaptador ejecuta `y.lcc/run-mini-tst.py`, reutiliza los `.bin`, `.json` y
dumps esperados generados en `y.lcc/mini-tst-out/`, y crea casos temporales en
`x.tests/generated/mini-lcc/`. Esa carpeta esta ignorada porque se regenera a
partir de los `.c`.

Por defecto se omiten los `xfail` conocidos de `mini-lcc` que generan
manifiesto, ya que `x.tests` no tiene semantica de fallo esperado. Para
investigarlos como fallos normales:

```powershell
python run-mini-lcc-tests.py --backend cpusim --include-xfail
```

Desde `x.tests`. `--port` es opcional: sin él, detecta el primer adaptador
FTDI conectado; solo hace falta si hay varios o para forzar uno en concreto
(por ejemplo, en Windows con "COM3"):

```powershell
# 1. CPU sobre el simulador funcional
python run_tests.py --backend cpusim

# 2. CPU sobre FPGA, versión EBR
python run_tests.py --backend cpu-fpga --version ebr --port COM3

# 3. CPU sobre FPGA, versión SDRAM
python run_tests.py --backend cpu-fpga --version sdram --port COM3

# 4. CPU sobre FPGA, versión con vídeo, sub-palabra y llamadas
python run_tests.py --backend cpu-fpga --version subword --port COM3

# 4b. CPU sobre FPGA, además con la ALU completa, shifts inmediatos y R0 a cero
python run_tests.py --backend cpu-fpga --version alu --port COM3

# 5. GPU sobre el simulador funcional
python run_tests.py --backend gpusim

# 6. GPU sobre FPGA, versión BRAM
python run_tests.py --backend gpu-fpga --version bram --port COM3
```

Qué necesita y qué ejecuta cada una:

| # | Backend y versión | Bitstream | Monitor | Casos |
|---:|---|---|---:|---|
| 1 | `cpusim` | ninguno | — | los 38 de `cases/` |
| 2 | `cpu-fpga --version ebr` | [6.fpga-cpu](../6.fpga-cpu/) | 1.16 | 13; 21 omitidos por capacidades |
| 3 | `cpu-fpga --version sdram` | [10.fpga-cpu-ram](../10.fpga-cpu-ram/) | 1.17 | 12; 22 omitidos. Sin `mul_div`: ver abajo |
| 4 | `cpu-fpga --version subword` | [19.fpga-cpu-hdmi-ls](../19.fpga-cpu-hdmi-ls/) | 1.20 | 28; 10 omitidos por capacidades |
| 4b | `cpu-fpga --version alu` | [21.fpga-cpu-hdmi-alu](../21.fpga-cpu-hdmi-alu/) | 1.15 | los 38 de `cases/` |
| 5 | `gpusim` | ninguno | — | los 34 de `cases-gpu/` |
| 6 | `gpu-fpga --version bram` | [12.fpga-gpu](../12.fpga-gpu/) | 2.3 | 26 compatibles; 8 omitidos con motivo |

`ebr`, `sdram`, `hdmi`, `bl8`, `subword` y `alu` son versiones del backend
**CPU**; `bram` lo es del backend **GPU**. No hay ninguna versión `ebr` de GPU.
Solo `cpusim` y `cpu-fpga --version alu` ejecutan los 38 casos: son los
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

La selección automática para `gpu-fpga` y `gpu-both` omite con un mensaje
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

Desde la raíz del repositorio, para actualizar una placa con monitor 2.0 y
probar todos los casos compatibles:

```powershell
.\.venv\Scripts\python.exe .\x.tests\run_tests.py --backend gpu-fpga --version bram --port COM3 --yes --durations
```

El backend exige monitor **2.3** y ofrece cargar `12.fpga-gpu` si responde otra
versión o si el monitor no responde. `--yes` autoriza esa carga. No fuerza una
recarga si ya responde 2.3; para cargar otra compilación de la misma revisión:

```powershell
.\.venv\Scripts\apio.exe upload -p .\12.fpga-gpu
if ($LASTEXITCODE -ne 0) { throw "Falló la carga" }
.\.venv\Scripts\python.exe .\x.tests\run_tests.py --backend gpu-fpga --version bram --port COM3 --no-upload --durations
```

`apio` se busca junto al ejecutable de Python y, si no está allí, en PATH.
La carga recibe salida en vivo. Para comparar también con el simulador, usa
`--backend gpu-both --version gpu-fpga=bram`; se comparan estados, memoria y
observaciones exigidas por el caso, excluyendo la duración de ejecución.

Los tres backends de FPGA comprueban la placa al arrancar y, si hace falta,
ofrecen cargar su bitstream; ver [Placa y bitstream](#placa-y-bitstream).

Además, `--backend both` ejecuta cada caso CPU en el simulador **y** en la FPGA
y compara los dos estados observados entre sí:

```powershell
python run_tests.py --backend both --version cpu-fpga=sdram --port COM3
```

Sin rutas explícitas se descubren todos los ficheros `cases/**/test.json`. Los
casos CPU se agrupan igual que los GPU:

| Grupo | Qué valida |
|---|---|
| [alu](cases/alu/) | Reglas de la ALU que la ISA fija explícitamente |
| [basics](cases/basics/) | Camino mínimo de ejecución y de memoria, y `R0` cableado a cero |
| [errors](cases/errors/) | Códigos de error y PC de la instrucción causante |
| [extensions](cases/extensions/) | Lo posterior a la v0.1: llamadas, accesos sub-palabra, consola serie, desplazamientos inmediatos y ALU extendida |
| [programs](cases/programs/) | Programas con bucles, como prueba de integración |
| [video](cases/video/) | Registros de vídeo, intercambio y frame capturado |

Los de `extensions` y `video` llevan `requires`, así que no corren en todos los
backends; ver [Capacidades](#capacidades).

También se puede ejecutar uno o varios casos concretos:

```powershell
python run_tests.py cases/basics/smoke/test.json --backend cpusim
```

Los casos GPU admiten traza del scheduler. `--trace-limit` limita los eventos
mostrados, pero no la ejecución ni las comprobaciones del caso; `--trace-file`
los guarda en vez de escribirlos en stderr:

```powershell
python run_tests.py cases-gpu/memory/vecsum/test.json --backend gpusim `
    --trace --trace-limit 100 --trace-file ejecucion.log
```

`--trace-detail` añade cambios de registros y accesos a memoria. Para
Mandelbrot conviene usar siempre un límite pequeño, porque una ejecución completa
produce millones de eventos aunque solo se quieran inspeccionar los primeros.

La salida indica siempre el tiempo total, y anota el de cada caso que pase de un
segundo. `--durations N` lista además las N ejecuciones más lentas al terminar
(10 si se omite el número):

```powershell
python run_tests.py --backend gpusim --durations 5
```

Es la forma de decidir un `timeout_seconds` con criterio en vez de a ojo. Los
tiempos son solo informativos: no forman parte de las expectativas de ningún
caso, porque volverían la suite intermitente.

`--version` selecciona la versión de cada backend. Con un único backend se
puede usar directamente `--version VERSION`; con varios se usa
`--version BACKEND=VERSION` y el parámetro puede repetirse:

```powershell
python run_tests.py --backend both `
    --version cpusim=current --version cpu-fpga=sdram --port COM3
```

Cada backend declara internamente todas sus versiones y cuál es la
predeterminada. Añadir una variante nueva solo requiere incorporarla al
registro `VERSIONS` del módulo correspondiente; el runner no contiene una
lista especial de versiones FPGA o del simulador.

## Placa y bitstream

Los backends de FPGA comprueban la versión física mediante `GET_VERSION`:

| Backend | Valor | Proyecto | Monitor | Memoria implementada |
|---|---|---|---:|---|
| `cpu-fpga` | `ebr` | `6.fpga-cpu` | 1.6 | `0x00000000–0x00003fff`, `0x00100000–0x00103fff` |
| `cpu-fpga` | `sdram` | `10.fpga-cpu-ram` | 1.5 | `0x00000000–0x01ffffff` |
| `cpu-fpga` | `hdmi` | `16.fpga-cpu-hdmi` | 1.10 | `0x00000000–0x01ffffff` |
| `cpu-fpga` | `bl8` | `18.fpga-cpu-hdmi-bl8` | 1.12 | `0x00000000–0x01ffffff` |
| `cpu-fpga` | `subword` | `19.fpga-cpu-hdmi-ls` | 1.13 | `0x00000000–0x01ffffff` |
| `gpu-fpga` | `bram` | `12.fpga-gpu` | 2.3 | 128 KiB de BRAM, 8 warps × 8 lanes |

**La 19 responde 1.13 aunque su protocolo sea idéntico al 1.12 de la 18.** No
añade ni un comando: las instrucciones nuevas viven enteras dentro de la CPU.
Sube igual porque `GET_VERSION` es lo único que el runner puede preguntar antes
de cargar un programa, y con las dos respondiendo 1.12 daría por bueno un
bitstream de la 18 para los casos de `extensions`, que pararían con error `0x01`.
Es el mismo motivo por el que 14 responde 2.2 compartiendo comandos con 12.

Para la tabla completa de qué tiene cada uno, ver
[Comparativa de versiones](../docs/resumen-prototipos.md).

La versión predeterminada de `cpu-fpga` es `alu` (21, la más completa; antes
era `ebr`). La comprobación ocurre **una sola vez al construir el backend**,
antes de ejecutar ningún caso, y distingue tres situaciones:

| Situación | Qué significa | Qué hace el runner |
|---|---|---|
| No se abre el puerto | No hay placa, o la tiene abierta otro programa | Error, sin más. No hay nada que cargar |
| El puerto abre pero el monitor no contesta | La FPGA no tiene bitstream con monitor. El chip USB-serie de la placa enumera igual, tenga o no bitstream | Ofrece cargarlo |
| Contesta con otra versión | Está cargado el bitstream de otro proyecto | Ofrece cargar el que toca |

```powershell
python run_tests.py --backend cpu-fpga --port COM3              # pregunta
python run_tests.py --backend cpu-fpga --port COM3 --yes        # carga sin preguntar
python run_tests.py --backend cpu-fpga --port COM3 --no-upload  # nunca carga
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
omite en el descubrimiento automático si el backend no es `gpusim`, y se
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

[`test_differential.py`](test_differential.py) fija este recorte. Hasta que se
aplicó, **los casos de vídeo fallaban siempre el diferencial** aunque
pasaran en los dos backends por separado.

## Medir: `--measure`

Los casos dicen si una versión está *bien*. `--measure` dice lo que *cuesta*:
ejecuta cada caso en cada versión aplicable y escribe una tabla en Markdown con
instrucciones, tiempo y CPI.

```bash
# Todas las versiones de placa, más el simulador
python run_tests.py --backend cpu-fpga --measure medidas.md --port COM3 cases

# Solo dos versiones, y sin nombre de fichero (sale en medidas.md)
python run_tests.py --backend cpu-fpga --version hdmi --version bl8 \
    --measure --port COM3 cases/programs

# Sin placa: solo cuenta instrucciones, que es la mitad de la tabla
python run_tests.py --backend cpusim --version sim --measure cases
```

Cambiar de versión recarga el bitstream, así que el bucle exterior es la versión
y no el caso; con cuatro versiones son cuatro cargas, no cuatro por caso.

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

Los casos de `cases/errors` verifican por separado `TRAP`, opcode inválido y
encoding inválido sobre ambos backends.

## Programas de integración

`cases/programs` contiene cargas de trabajo pequeñas pero completas:

- `fibonacci`: bucle, aritmética y generación secuencial de un array;
- `array-sum`: entrada inicial, acumulación con wrap y resultado en memoria;
- `memory-copy`: dos punteros, `LOAD`, `STORE` y offset negativo;
- `shift-multiply`: multiplicación sin `MUL`, mediante sumas y shifts.

Estos casos complementan los tests unitarios de RTL comprobando el flujo entero
ensamblador, CPU, memoria, monitor y backend.

El más grande de todos no está ahí sino en
[`cases/extensions/serial/forth`](cases/extensions/serial/forth/), porque
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

## Arquitectura y compatibilidad

Todos los casos declaran explícitamente `"architecture": "cpu"` o
`"architecture": "gpu"`. No se deduce la arquitectura del nombre del archivo
ni de su carpeta. GPU exige `warp_config`; CPU lo rechaza.

Los backends declaran `ARCHITECTURE`: `cpusim` y `cpu-fpga` son CPU;
`gpusim` es GPU y es el backend predeterminado de `run_tests.py`.
`both` sigue seleccionando los dos backends CPU. Las versiones se seleccionan,
por ejemplo, con `--version gpusim=current`.

El descubrimiento automático omite casos de otra arquitectura y muestra cuántos.
Una ruta solicitada explícitamente con arquitectura incompatible produce código
2. Se valida la selección completa antes de construir los backends, ejecutar
programas o abrir conexiones FPGA; una selección mixta incompatible no ejecuta
parcialmente los casos válidos.

## Capacidades

La arquitectura no basta: dentro de «CPU» hay bitstreams muy distintos. El de
`6.fpga-cpu` no tiene vídeo; el de `16.fpga-cpu-hdmi` sí, pero no puede pararse
en un frame concreto; el de `18.fpga-cpu-hdmi-bl8` puede las dos cosas. Un caso
declara lo que necesita:

```json
"requires": ["frame_capture"]
```

| Capacidad | Qué significa | Quién la tiene |
|---|---|---|
| `atomic_warp_faults` | Un fallo de warp no deja efectos parciales | solo el simulador GPU |
| `video` | Registros en `0x80000000` y un framebuffer que se muestra | `cpusim`, `hdmi`, `bl8`, `subword`, `alu` |
| `frame_capture` | Además `HALT_AT`, `SWAP_COUNT` y borrado de underflow | `cpusim`, `bl8`, `subword`, `alu` |
| `subword_memory` | `LOADB`/`LOADUB`/`STOREB`/`LOADH`/`LOADUH`/`STOREH`, opcodes `0x18–0x1D` | `cpusim`, `subword`, `alu` |
| `calls` | `JAL`/`JALR`/`JR`, opcodes `0x2C–0x2E` | `cpusim`, `subword`, `alu` |
| `serial` | Puerto serie en `0x80000200`, y los comandos que lo alimentan | `cpusim`, `subword`, `alu` |
| `shift_immediate` | `SHLI`/`SHRI`/`SARI`: bit 10 de `SHL`/`SHR`/`SAR` | `cpusim`, `alu` |
| `alu_extended` | `MULHI`/`DIVU`/`REM`/`REMU`, opcodes `0x0B` y `0x0D–0x0F` | `cpusim`, `alu` |
| `mul_div` | `MUL`/`MULFX`/`DIV`: **base de la ISA**, no una extensión | todos menos `sdram` |

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
pueda tener o no. Su caso vive en `cases/basics/zero-register` y corre en todas
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

`cpusim` declara las dos capacidades de video desde que `minicpu_sim.py` tiene un
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
cinco casos de `cases/video` sincronizan, y por eso el simulador puede declarar
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
SKIP video-band [cpusim]: el simulador no tiene frame_capture:
    no hay barrido ni framebuffer, use --backend cpu-fpga --version bl8
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

**Con `run_until` no se puede declarar `expect.pc`**, y el runner lo rechaza al
cargar. La parada es asíncrona, así que el PC queda donde pille a la CPU;
aceptarlo daría un caso que pasa o falla según lo rápido que vaya ese día.

**`expect.frame` no lleva dirección** a propósito. Tras el intercambio N,
`FB_FRONT` alterna entre los dos buffers según la paridad: si el caso tuviera
que decir la dirección, la mitad apuntarían al buffer que no es. El backend lee
`FB_FRONT` y vuelca desde ahí.

Y el fichero de `frame` tiene que salir de un **modelo**, no de una captura de
la propia placa. Si el esperado se genera capturando, el caso solo comprueba que
la placa sigue haciendo lo que hacía, incluido lo que haga mal.
[`cases/video/band/reference.py`](cases/video/band/reference.py) es el ejemplo.
Para ver dónde difieren dos frames, [`../tools/compare-frames.py`](../tools/compare-frames.py).
