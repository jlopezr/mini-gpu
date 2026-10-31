# Rendimiento de los simuladores: qué queda por mirar

Lo que se sabe que se puede mejorar en el motor Codon (`sim-sys --backend codon`)
y en los núcleos Python que compila. Cada punto dice qué cuesta, por qué y por
dónde empezar. Al resolver uno, muévelo a «Hecho» con las medidas.

## Cómo medir

Dos cargas, con el motor ya compilado (la primera vez tarda unos 15 s más):

```sh
B=40.mini-gl/build/minigpu/3d/boxes.bin              # sobre todo CPU, GPU ociosa
D=t.tests/cases-cpu-gpu/dma/bench-dma/bench_dma.asm  # CPU y GPU, 15,9 M instrucciones de warp
/usr/bin/time -p python3 tools/sim-sys $B --backend codon --halt-after-swaps 12 \
    --run-limit 1000000000 --frame-output /tmp/boxes.bin
/usr/bin/time -p python3 tools/sim-sys $D --backend codon --run-limit 100000000
```

Sin `--backend codon` y con PyPy (`uv python find pypy`) se mide el motor Python.
Compara además el framebuffer (`cmp`) y la salida con las de antes del cambio, y
pasa las pruebas de los prototipos 11, 23, 24, 25 y 32, con
`RUN_SLOW=1 RUN_CODON=1 tools/test --prototype 32 --full`, que comparan con
Python el estado completo.

Medidas actuales (2026-10-31, macOS ARM64, Codon 0.20.5, PyPy 3.11):

| Carga | PyPy | Codon |
|---|---:|---:|
| `boxes.bin`, 12 swaps | 2,5 s | 0,57 s |
| `dma-bench` | 8,3 s | 1,4 s |

## Cómo perfilar el motor

`codon build -release` no deja símbolos, y `-o x.o` sí, pero con el prefijo
`l_`, que el enlazador de macOS descarta. Se compila a objeto, se enlaza a mano y
las direcciones se traducen con el desplazamiento de `__text`:

```sh
D=$(python3 -c "from tools.codon_backend import prepare; print(prepare()[0].parent)")
export CODON_PYTHON=$(python3 -c "from tools.codon_backend import library; print(library())")
L=$PWD/_build/codon-sdk/lib/codon
_build/codon-sdk/bin/codon build -release -o _build/codon-prof/engine.o $D/src/engine.codon
clang _build/codon-prof/engine.o -L$L -lcodonrt -lomp -Wl,-rpath,$L -o _build/codon-prof/engine-prof
otool -l _build/codon-prof/engine-prof | grep -A2 "sectname __text"   # addr 0x1000006e8
```

Se lanza `engine-prof` con el entorno de `prepare()` y se muestrea con
`sample <pid> 4`. Cada dirección de «Sort by top of stack», menos el desplazamiento
de `__text` (0x6e8), se busca en `nm -n engine.o`. Codon mete mucho en línea:
lo que sale como `main` es sobre todo el bucle de `run` con el paso de la CPU.

## Pendiente

### 1. El bucle de la CPU: unos 135 M instrucciones/s

Ya por encima de los unos 120 M del generador que reescribía los simuladores por
AST (ya borrado). Perfil actual de `boxes` (2026-10-31):

| Función | Muestras |
|---|---:|
| `main` (bucle de `run` y paso de la CPU, en línea) | 71 % |
| `CPU.read_u32` (sobre todo leer la instrucción) | 24 % |
| `list.__getitem__` (registros) | 5 % |

Pistas:

- Leer la instrucción directamente de la RAM cuando el PC está por debajo de
  `MMIO_SYSTEM_BASE`, sin pasar por `_device`, no se notó (1,58–1,63 s frente a
  1,60 s con 60 swaps), y se descartó. El 24 % puede ser la espera de la propia
  carga de memoria más que el código de alrededor.
- `list.__getitem__` es la comprobación de límites de `self.regs[r]`. Los
  índices salen de campos de 5 bits, así que nunca falla, pero Codon no lo sabe.
  Quitarla exigiría algo propio de Codon en los núcleos, que tienen que seguir
  siendo Python.

### 2. Llamadas de los proxies a Python en cada acceso MMIO

Con el reloj por lotes en el sistema, un `read` de vídeo, serie o entrada cuesta
una llamada a CPython (más un `advance` si había ticks pendientes), y un `write`,
además, las de `devices_changed` (`ticks_until_event()` de cada periférico). Un
programa que sondea en bucle un registro de estado paga una llamada por
iteración. No se ha medido: `boxes` y `dma-bench` apenas sondean. Haría falta un
caso que sondee (por ejemplo, esperar `VSYNC` en bucle) para saber si importa.
Una idea es copiar al proxy (`tools/sim_devices.codon`) los registros de estado
que no tienen efectos al leerse.

### 3. Lo que cuesta el código común en Python

Escribir los núcleos para que compilen con Codon hizo `boxes` con PyPy un 4 % más
lento (de 4,58 a 4,74–4,82 s, medido durante la migración), probablemente por la
llamada a `codon_compat` en cada acceso a memoria. Lo pagan Windows y quien no
tiene Codon. Probar si PyPy va mejor con otra implementación en `codon_compat.py`
(`memoryview.cast("I")`, `struct.Struct.unpack_from` precompilado), sin tocar los
núcleos.

### 4. Compilar el motor tarda unos 15 s

Solo una vez por cada cambio en las fuentes (queda en caché en
`_build/codon-engine/`), pero lo nota quien itera sobre los núcleos con
`--backend codon`. Probar sin `-release` para desarrollo, o ver qué módulo se lleva
el tiempo.

## Hecho

### Sin llamadas a Python por frame, límites por lotes y RAM por puntero (2026-10-31)

- **Fronteras de frame ociosas** (`tools/sim_devices.py`): sin intercambio ni
  cambio de configuración pendientes, el vídeo no tiene evento
  (`ticks_until_event` da `NEVER`) y `advance(n)` cuenta de una vez los frames
  que pasan. Antes, `boxes` llamaba a Python dos veces cada 1000 instrucciones,
  y eran esas llamadas las que hacían trabajar al recolector de Codon.
- **Límites por lotes** (`CpuGpuSystem._check_limits`): un margen,
  `_limit_slack`, cuenta cuántas instrucciones pueden retirarse antes de que un
  límite pueda alcanzarse, y la comprobación solo se hace cuando llega a cero.
  Comprobar en cada instrucción costaba casi un 20 %.
- **`load_u32`/`store_u32` por puntero** en `tools/codon_compat.codon`: una sola
  lectura de 32 bits, sin comprobar límites, porque quien llama ya lo ha hecho.

`boxes.bin` hasta 60 swaps con Codon: de 2,6 a 1,6 s (de 85 a 135 M
instrucciones/s). Hasta 12 swaps, de 0,75 a 0,57 s; `dma-bench`, de 1,6 a 1,4 s.
En PyPy no se nota.

### El planificador de `CpuGpuSystem` (2026-10-31)

Tres cambios en `32.cpu-gpu-func-sim/cpu_gpu_core.py`, sin cambiar el resultado:

- **Reloj por lotes en el sistema.** `tick_devices` solo cuenta; los periféricos
  avanzan de una vez (`advance(n)`) en el primer tick en que alguno tiene un
  evento (`ticks_until_event`), y antes de cada acceso del bus a uno de ellos
  (`_Port` llama a `MachineHooks.sync_devices`). Fuera de `run`, tick a tick, como
  antes. Los proxies de Codon ya no cuentan ticks; solo reenvían.
- **GPU ociosa.** Con la GPU detenida, `step_round` hace una comprobación de
  límites en vez de `gpu_steps` pasos que no harían nada.
- **Límites sin `Optional`.** `NO_LIMIT` en vez de `None`, y la comparación
  primero.

`boxes.bin` hasta 60 swaps (219 M instrucciones de CPU) con Codon: de 3,9 a
2,6 s. Hasta 12 swaps, de 1,0 a 0,75 s; `dma-bench`, de 1,7 a 1,6 s. En PyPy no se
nota.

### El paso del warp de la GPU ya no reserva memoria por lane (2026-10-31)

`Warp.step` en `11.gpu-sim-func/minigpu_core.py` hacía, por cada lane activa y cada
instrucción, una copia de los 32 registros, un `LaneResult` con su tupla de
`store`, una entrada en una lista de resultados, un `set` con los `next_pc` y otra
copia de los registros al confirmar. Ahora `CPU.evaluate` no escribe registros y
deja el resultado en campos de la lane (`rd`, `value`, `next_pc`, `halted`,
`store_*`). El warp mira si los PC coinciden recorriendo las lanes y escribe
`regs[rd]` al confirmar. Se sigue cumpliendo que un fallo en una lane no deja a
las otras a medias, porque nada se escribe hasta que han evaluado todas.

| Carga | PyPy antes | PyPy después | Codon antes | Codon después |
|---|---:|---:|---:|---:|
| `dma-bench` | 12,8 s | 8,2 s | 9,2 s | 1,7 s |
| `boxes.bin`, 12 swaps | 2,6 s | 2,6 s | 1,0 s | 1,0 s |

Salida y framebuffer idénticos. `boxes` no cambia porque con la GPU ociosa todo el
tiempo es de la CPU.
