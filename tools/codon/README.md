# Codon: backend opcional CPU+GPU

Qué no admite Codon, qué rodeos llevan por ello los núcleos de los simuladores y
cómo comprobar si una versión nueva los resuelve: [LIMITACIONES.md](LIMITACIONES.md).
Qué queda por mirar de rendimiento: [RENDIMIENTO.md](RENDIMIENTO.md).

## Motor CPU+GPU integrado

```sh
tools/sim-sys t.tests/cases-cpu-gpu/launch/launch.asm --backend codon
make -C 40.mini-gl sim-boxes SIM_ARGS="--backend codon"
RUN_CODON=1 PYTHON=python3 tools/test --prototype 32 --quick
RUN_SLOW=1 RUN_CODON=1 PYTHON=python3 tools/test --prototype 32 --full
```

Python sigue siendo el backend predeterminado. Codon es opcional: se busca en
`MINIGPU_CODON`, el PATH o `_build/codon-sdk/bin/codon`. Hace falta la biblioteca
compartida de CPython (se detecta sola, o `CODON_PYTHON=/ruta/a/libpython`). Se
puede lanzar también desde PyPy. No descarga nada. Traza y perfil usan el motor
Python, con un aviso.

### El mismo código en los dos lenguajes

El motor compila **los núcleos de los simuladores tal cual**:
`2.cpu-sim-func/minicpu_core.py`, `11.gpu-sim-func/minigpu_core.py` y
`32.cpu-gpu-func-sim/cpu_gpu_core.py`. Son Python normal escrito dentro del
subconjunto que Codon compila; cada rodeo que eso exige está anotado en el código
y explicado en [LIMITACIONES.md](LIMITACIONES.md). Los ficheros de siempre
(`minicpu_sim.py`, `minigpu_sim.py`, `cpu_gpu_sim.py`) añaden la línea de órdenes
y reexportan su núcleo, así que quien los importa no cambia nada.

Lo que se queda en Python tiene un gemelo `.codon` al lado del `.py`, y Codon lo
prefiere al importar:

| Gemelo | Qué es en el motor |
|---|---|
| `tools/codon_compat.codon` | Lo que le falta a Codon (`struct`, `int.from_bytes`, `dataclass`) |
| `tools/sim_devices.codon` | Proxies de los periféricos Python (vídeo, serie, entrada) |
| `11.gpu-sim-func/gpu_trace.codon`, `tools/sim_profile.codon`, `1.isa/asm2/minigpu_isa.codon` | Vacíos: traza, perfil y desensamblador no existen en el motor |

`tools/codon_backend.py` copia esas fuentes, sin cambiarlas, a
`_build/codon-engine/<hash>/src/` y compila `tools/codon/engine.codon` con
`-release` (unos 15 s la primera vez). La clave incluye todas las fuentes copiadas,
la versión y ruta del compilador y la libpython: un cambio en un núcleo recompila.

### Cómo se reparte el trabajo

- `tools/codon/engine.codon` construye el `CpuGpuSystem` nativo, lo ejecuta con
  su `run` (el mismo planificador, límites y detección de bloqueo que en Python)
  y al acabar copia su estado al espejo Python (`export`, la única lista de campos).
- `tools/codon/host.py` es el lado Python: parsea la línea de órdenes, construye
  con `cpu_gpu_sim.build_system` un sistema espejo (periféricos y programa), le da
  como RAM la del motor (una vista sin copia, que es lo que ve la ventana) y cierra
  con el mismo `finish_run` que el backend Python.
- Los proxies de `tools/sim_devices.codon` reenvían a Python cada `advance`, cada
  acceso MMIO y cada `ticks_until_event`. Llamadas por instrucción no hay: el
  sistema cuenta los ticks y avanza los periféricos solo en el primero que tiene
  un evento o antes de un acceso del bus (`CpuGpuSystem.tick_devices`, el reloj
  por lotes de `sim_devices.py`). Tras cada `advance` preguntan si se ha pedido
  parar (ventana, F12, Ctrl+C) y, si es así, llaman a `request_stop` del sistema
  nativo.

Las pruebas diferenciales (`RUN_CODON=1`) comparan con Python el estado
**completo** del sistema (todos los campos de CPU, GPU, warps y lanes, recorridos
con `vars`, más un SHA-256 de la RAM y el estado de los periféricos): repartos
CPU/GPU, errores y límites, SIMT y barreras, vídeo, serie, entrada con guion, DMA,
render por GPU y kernels C con divergencia. Una de ellas comprueba además que las
limitaciones documentadas siguen vigentes.

### Rendimiento (2026-10-31, macOS ARM64, Codon 0.20.5)

| Carga | PyPy 3.11 | Codon |
|---|---:|---:|
| `boxes.bin`, 12 swaps, 42 190 000 instrucciones CPU, GPU ociosa | 2,6 s | 0,75 s |
| `dma-bench`, 27,7 M instrucciones CPU y 15,9 M de warp | 8,4 s | 1,6 s |

Proceso completo, con el motor ya compilado; unos 0,23 s son arranque fijo
(CPython embebido y el anfitrión). Framebuffer y estado idénticos a Python.

Cómo medir, lo que queda por mejorar y lo ya hecho:
[RENDIMIENTO.md](RENDIMIENTO.md).
