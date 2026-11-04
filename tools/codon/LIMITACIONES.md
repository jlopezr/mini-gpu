# Limitaciones de Codon que condicionan el código de los simuladores

Los núcleos de los simuladores (`2.cpu-sim-func/minicpu_core.py`,
`11.gpu-sim-func/minigpu_core.py` y `32.cpu-gpu-func-sim/cpu_gpu_core.py`) se
escriben para que **el mismo fichero** funcione en Python y compile con Codon: el
backend `--backend codon` los copia tal cual ([README.md](README.md)). Codon no es
Python: compila un subconjunto con tipos estáticos, y algunas construcciones
normales en Python no las admite. Este documento recoge cada una, el rodeo que
lleva el código por su culpa y qué se puede deshacer cuando Codon la resuelva.

Comprobado con **Codon 0.20.5** (la última versión publicada el 2026-10-31), en
macOS ARM64.

## Cómo saber si alguna se ha resuelto

Cada limitación tiene un programa mínimo en [`limitations/`](limitations/), válido
en Python, que imprime `OK`. Con 0.20.5 ninguno compila en Codon o da `OK`.
Después de actualizar Codon:

```sh
python3 tools/codon/limitations/check.py            # o --codon /ruta/a/codon
```

Por cada caso dice `sigue` o `RESUELTA`, y termina con error si alguno ha
cambiado, para que no pase desapercibido. El docstring de cada `lNN_*.py` repite
el rodeo y lo que hay que deshacer. Al quitar un rodeo, vuelve a pasar las pruebas
de los prototipos 2, 11, 23, 24, 25 y 32, `t.tests/run_tests.py` con los backends
`sim-*` y las de Codon (`RUN_CODON=1`).

## Limitaciones con rodeo en el código

| | Limitación (0.20.5) | Rodeo | Al resolverse |
|---|---|---|---|
| l01 | No hay módulo `struct`. | `load_u32`/`store_u32` de `tools/codon_compat` (con `struct` en Python). | Borrarlas de `codon_compat.py` y `.codon`; volver a `struct`. |
| l02 | No hay `int.from_bytes` ni `int.to_bytes`. | `load_le`/`store_le` de `tools/codon_compat`. | Igual que l01. |
| l03 | No hay módulo `dataclasses` (`@dataclass` sí, incorporado). | `from tools.codon_compat import dataclass`: la real en Python, la identidad en Codon. | Importar de `dataclasses`. |
| l04 | `@dataclass(frozen=True)` no se admite. | `Fault`, `SimtRegion` y `SimtPath` sin `frozen` (nunca se modificaban). | Volver a `frozen=True`. |
| l05 | No existe `frozenset`. | `set` en `LOAD_OPCODES`. | Volver a `frozenset`. |
| l06 | `"X \| None"` entre comillas es el tipo `str`. | Anotaciones sin comillas en los constructores. | Nada obligatorio. |
| l07 | Una anotación no puede nombrar una clase definida más abajo. | En la GPU, la lane (`CPU`) va antes que `Warp`, y `_step_warp` no anota `warp`. | Se puede volver al orden de arriba abajo (System, SM, Warp, lane). |
| l08 | Dos clases no pueden apuntarse mutuamente. | Nadie guarda a su padre: `System → SM → Warp → lane` solo hacia abajo, y `system` (y `warp`, para `GETID`) bajan como argumento. Afecta a las firmas de `Warp.step`, `reconverge`, `release_barriers`, `_step_warp` y los métodos de la lane, y a sus llamadas en 23, 24, 25 y 32. | Opcional: podrían volver `self.sm`/`self.warp`. |
| l09 | Un atributo de clase (`BASE = …`, `profile = None`, `ClassVar`) desactiva la inferencia de campos desde `__init__`. | Campos declarados en la clase (`SysIdDevice`); `CPU.profile` pasa a `__init__`. | Las declaraciones pueden quedarse. |
| l10 | Solo se infieren los campos asignados en el propio `__init__`, no en un `reset()` al que llama. | Campos declarados en `Warp` y en la lane. | Las declaraciones pueden quedarse. |
| l11 | Sin tipado pato: una tupla o un retorno de clases distintas no tiene tipo. | Base común `tools/mmio_device.MmioDevice`; `CPU._device` y `System.device_for` miran los dispositivos uno por uno y los devuelven como `MmioDevice \| None`. `BASE`/`SIZE` son campos de la instancia: una constante de la subclase no se ve a través de la base. | Volver al bucle sobre `(video, serial, input, sysid)`. |
| l12 | Una excepción sin campos declarados es genérica; `except` no conoce sus tipos (en el simulador, no la capturaba y abortaba). | `code` y `address` declarados en `ExecutionFault`. | Las declaraciones pueden quedarse. |
| l13 | Los imports se resuelven al compilar: `try/except ImportError` no los evita. | Gemelos `X.py`/`X.codon`: Codon prefiere el `.codon` (`tools/codon_compat`, `tools/sim_devices`, `gpu_trace`...). | Nada por sí sola; ver l01–l03. |
| l14 | `sys.path` no existe (tampoco con `--auto-python`). | Cada núcleo es un módulo sin CLI ni `sys.path` (`*_core.py`); el fichero de siempre añade la CLI y lo reexporta. El backend copia las fuentes, sin cambios, a un directorio con `tools/` al lado. | El núcleo podría volver al fichero de la CLI. |
| l15 | `from __future__ import annotations` no se admite. | Los núcleos y `tools/mmio_map.py` no lo llevan. Sin él, PyPy 3.11 evalúa las anotaciones al definir: por eso importa l07. | Se puede volver a poner. |
| l16 | Un `X \| None` no se convierte a su base al hacer `append` en una `list[Base]` (devolverlo desde una función anotada, o pasarlo a un parámetro `Base \| None`, sí funciona). | Ninguno hace falta hoy: los núcleos miran los dispositivos uno por uno y el bus guarda puertos. | Se podría volver a una lista de dispositivos. |
| l17 | Una subclase no puede reasignar en su `__init__` un campo heredado: lo toma por una declaración nueva. | `_GpuSystem` y `_SystemCpu` declaran sus campos (`bus: MmioBus`). | Las declaraciones pueden quedarse. |
| l18 | `from paquete import módulo` no funciona, y `tools.x` importado desde dentro de `tools/` se busca desde esa carpeta. | `import tools.mmio_map as mm`; import relativo (`from .mmio_device import ...`) dentro de `tools/`. | Volver a `from tools import ...`. |
| l19 | Una clase con los campos inferidos es genérica: no se puede heredar de ella (aserción interna del compilador) ni usarla como tipo de un campo declarado. | Campos declarados en `CPU` (minicpu), `System` y `StreamingMultiprocessor` (minigpu), `_Port` y `MmioBus`. Los dispositivos de control sacan sus constantes al módulo para seguir infiriendo. Por la misma razón, en la GPU las clases van lane, `Warp`, SM, `System` y los métodos reciben `system` sin anotar (l07). | Las declaraciones pueden quedarse. |
| l20 | `A if c else B` con dos tuplas de distinta longitud no tiene tipo. | `x in A if c else x in B` (`GpuCoreDevice.validate`). | Volver a `x in (A if c else B)`. |
| l21 | Un `bool` no se puede desplazar (`(x is not None) << 6`). | `int(...) << n` en los dispositivos de control. | Quitar el `int(...)`. |
| l22 | (Rendimiento) Un literal `{...}` en una condición se construye en cada evaluación; Python lo convierte en constante. En la CPU costaba 20 veces el tiempo. | Tuplas en `valid_encoding` y `IMPLEMENTED_OPCODES` como constante del módulo. | Nada: el código actual es igual de rápido en Python. |

Coste medido en Python: con PyPy, `boxes.bin` hasta 12 swaps pasa de 4,58 a
4,74–4,82 s (≈ 4 %), probablemente por la llamada a `codon_compat` en cada acceso a
memoria. Instrucciones y framebuffer idénticos.

Otros cambios de diseño que pidió Codon, sin limitación propia: la GPU avisa al
sistema con `MachineHooks.on_retire` (`tools/mmio_device.py`) y no con una función
guardada en un campo; el perfil de la CPU se lleva desde la CLI
(`minicpu_sim.run_profiled`) y no desde `CPU.run`; `_Port` pregunta
`gpu_may_read` al dispositivo en vez de `getattr(device, "gpu_readable", None)`.

## Lo que se queda en Python por diseño

No son carencias que se espere que Codon resuelva, sino consecuencia de que
compila con tipos estáticos:

- **Ganchos dinámicos**: la traza (`system.trace`, `TraceEvent` con una tupla de
  longitud variable) y el perfil (`cpu.profile`) son `None` o un objeto Python. Con
  ellos, `sim-sys` usa el motor Python (con un aviso si se pidió `--backend codon`).
- **Validación de configuración**: `configure_warps` valida JSON con `isinstance`
  sobre objetos arbitrarios.
- **Periféricos y anfitrión**: vídeo, serie y entrada (con ventana Tk, terminal,
  ctypes), la CLI (`argparse`, `pathlib`) y los informes. Codon los ve como
  objetos Python.

## Diferencias de semántica a vigilar

- `int` en Codon es de 64 bits con signo; en Python no tiene límite. Los núcleos
  enmascaran a 32 bits (`u32`, `& MASK32`) y un producto de 32 × 32 bits cabe, pero
  un valor intermedio de más de 64 bits daría otro resultado sin avisar. Las
  pruebas diferenciales (`RUN_CODON=1`) son las que lo detectarían.

## Cómo resuelve Codon los imports (para el backend)

Comprobado con 0.20.5, útil para montar la compilación:

- Busca junto al fichero que importa y en su biblioteca estándar. `CODON_PATH`
  no sirve para añadir módulos propios.
- Si existen `X.py` y `X.codon` en el mismo sitio, toma `X.codon`; dentro de un
  paquete (`tools/X.codon`) también.
- Sigue los enlaces simbólicos hasta el fichero real y busca los imports desde
  allí: hay que **copiar** las fuentes, no enlazarlas.
- `--auto-python` importa desde CPython lo que no encuentra (por ejemplo
  `argparse`), pero no hace que exista `sys.path`.

## Cómo se comprobó

Las pruebas `RUN_CODON=1` de `32.cpu-gpu-func-sim/test_codon_backend.py` comparan
el estado completo del motor compilado con el de Python. Durante la migración se
contrastaron además, con arneses en `_build/codon-b/`, 83 programas de
`cases-cpu`/`cases-shared` (CPU), 75 de `cases-gpu`/`cases-shared` (GPU) y los 13
de `cases-cpu-gpu` (sistema, con la RAM completa): todos idénticos.
