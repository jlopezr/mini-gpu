# Simulador funcional MiniGPU

Implementa la MiniISA con un SM, varios warps y registros privados por hilo.
Cada warp tiene un único PC. El SM ejecuta una instrucción de un warp por paso,
alternando los warps activos en orden circular. No modela ciclos de hardware.

```powershell
python minigpu_sim.py ../1.isa/minimal.bin --num-warps 8 --warp-size 8
python -m unittest discover -s . -v
```

Desde la raíz del repositorio puede usarse `.venv/Scripts/python.exe`.

## Los programas de `examples/`

- **`vecsum.asm`** es el más sencillo que ejercita SIMT de verdad: cada lane
  suma un elemento de dos vectores de 16 palabras y guarda el resultado. La
  dirección sale de `GETTID` y un desplazamiento, así que las 16 lanes escriben
  en sitios distintos sin coordinarse. Los vectores viven en `0x0100` y
  `0x0140`, y el resultado en `0x0180`.
- **`simt_demo.asm`** ejercita divergencia anidada y `BAR`. Es el que usa la
  sección de extensiones SIMT, más abajo.
- **`divzero.asm`** está **vacío**, 0 bytes. El nombre sugiere que iba a probar
  la división por cero y nunca se escribió.

### De dónde sale `memoria.bin`

`run.bat` ejecuta `memoria.bin`, que no es un programa distinto sino **la imagen
de memoria completa de `vecsum`**: sus 56 bytes de código en `0x0000`, el vector
A en `0x0100` con los valores 0, 1, 2… y el vector B en `0x0140` con 100 en cada
posición. Por eso `run.bat` vuelca precisamente `0x0180`, que es donde `vecsum`
deja la suma.

No hay un fuente que lo genere: se armó a mano y se versionó ya ensamblado. Se
puede reconstruir con `vecsum.asm` más las dos tablas de datos, si algún día
hace falta cambiarlo.

## Traza del scheduler

```powershell
python minigpu_sim.py memoria.bin --config warps.json --trace --trace-limit 100
python minigpu_sim.py memoria.bin --config warps.json --trace-detail --trace-file ejecucion.log
```

`--trace` muestra paso, warp elegido, PC inicial, máscara, instrucción y PC final.
El resultado indica `READY`, `WAIT_BAR`, `FINISHED` o el fallo. Los pasos son emisiones del
scheduler, no ciclos de hardware: un intento fallido aparece en la traza aunque
no incremente el contador de instrucciones completadas.

`--trace-detail` activa además cambios efectivos de registros y lecturas/escrituras
de memoria por hilo activo. Los resultados de una instrucción fallida no se
presentan como confirmados. La máscara mostrada es la anterior a ejecutar HALT.
La salida va a stderr; `--trace-file` la escribe en UTF-8 (reemplaza el archivo).
`--trace-limit N` muestra hasta N instrucciones, con sus detalles, sin detener la
ejecución. El resumen final se escribe siempre, incluso después de alcanzar ese
límite. Todas estas opciones activan la traza por sí mismas. Sin ellas no se
generan eventos ni se copian registros para logging.
La columna `LANES` resume las dos máscaras SIMT por lane, con lane 0 a la
izquierda: `A` está activa en la instrucción, `.` sigue viva pero espera por
divergencia y `F` ya ha terminado mediante `EXIT`. La columna hexadecimal `MASK`
se conserva como representación de `active_mask`.

Desde Python se puede asignar `system.trace = TextTrace(stream, detail=True)`
(`TextTrace` está en `gpu_trace.py`). La traza observa `System.step/run` a través
del scheduler; `Warp.step()` directo no genera eventos. `TraceEvent` separa los
datos del paso de su representación textual. El límite y numeración pertenecen
a la instancia de `TextTrace`; crear otra instancia inicia una nueva sesión.

## Ejecución y HALT

### Configuración inicial desde JSON

```powershell
python minigpu_sim.py memoria.bin --config launch.example.json
```

El binario/dump inicializa la memoria desde la dirección cero. El JSON configura
el lanzamiento independientemente del contenido de memoria. Véase
`launch.example.json`: habilita el warp 0 con ocho hilos en PC=0 y el warp 1 con
cuatro hilos en PC=0x100. El dump debe contener el código en esas direcciones.

Hay hasta ocho warps (ID 0..7). Los omitidos y los que tienen `enabled: false`
quedan deshabilitados. `warps: []` es válido y no ejecuta instrucciones.
Cada entrada exige `id`; los valores por defecto son `enabled: true`, `pc: 0`
y una máscara con todos los hilos activos. El bit 0 corresponde al hilo 0.
`warp_size` vale 8 si se omite. Los enteros admiten números JSON o cadenas
decimales/hexadecimales; `enabled` exige un booleano JSON.

Se rechazan IDs duplicados o fuera de rango, campos desconocidos, PC no alineado
o fuera de memoria y máscaras que excedan el tamaño del warp. Un warp habilitado
debe tener al menos un hilo activo. También se validan los campos proporcionados
en warps deshabilitados. `--num-warps` permite reducir el número de slots; los
IDs deben caber en ellos. Si se proporciona `--warp-size` junto con `--config`,
ambos tamaños deben coincidir. Una configuración inválida devuelve código 2.

Desde Python: `load_program(data, launch=False)` carga sin activar hilos;
`configure_warps(config)` recibe el objeto JSON ya leído, reinicia registros,
contadores y fallo y aplica el lanzamiento sin cambiar memoria. Valida todo
antes de modificar estado. El tamaño del sistema debe coincidir con el JSON.
Sin `--config`, se conserva el lanzamiento de todos los warps desde PC=0.

- `load_program(data, address=0)` valida un programa no vacío, reinicia registros,
  contadores y fallo, coloca todos los PC en `address` y activa todos los hilos.
  Conserva la memoria fuera del rango cargado.

- `System.step()` ejecuta como máximo una instrucción de warp y devuelve si se
  completó. El fetch es único para todos los hilos activos.

- `instructions_executed` cuenta instrucciones **completadas por warp**: una ADD
  con ocho hilos cuenta una vez. HALT cuenta; una instrucción fallida no cuenta.
  El contador del sistema suma los contadores de los warps.

- `run(max_instructions)` usa un límite absoluto desde la última carga/reset.
  Se comprueba antes de emitir otra instrucción, también entre warps. Alcanzar
  HALT exactamente en el límite es correcto. Si se agota antes, lanza
  `InstructionLimitExceeded`; se puede continuar con un límite mayor.

- HALT retira todos los hilos activos del warp y avanza su PC a PC+4. El sistema
  está detenido cuando todos los warps terminan o existe un fallo global.
  Los pasos posteriores a una parada no modifican el estado.

- Un sistema recién construido o reiniciado no tiene trabajo y está detenido.
  `reset()` borra la memoria in situ y reinicia todos los registros y contadores.

## Fallos

`System.fault` es el único registro de fallo, inmutable, con `code`, `pc`,
`warp_id`, `core_id` y, para accesos inválidos, `address`. En fetch, decodificación
y TRAP, `core_id` es `None` porque el fallo corresponde al warp completo.
`error`, `error_code`, `error_pc` y `halted` son propiedades derivadas; no hay
banderas duplicadas en CPU, warp y SM que puedan desincronizarse.

Un fallo arquitectónico detiene toda la GPU inmediatamente y conserva siempre
el primer diagnóstico. Si varios hilos fallan, se informa del primero por orden
de hilo. El PC queda en la instrucción fallida. La instrucción se evalúa en todos
los hilos activos antes de confirmar resultados: un fallo no deja registros ni
escrituras de memoria parciales. Las instrucciones anteriores sí se conservan.
Las excepciones inesperadas de Python no se convierten en fallos de memoria.

La consola devuelve 0 en HALT normal, 1 en fallo arquitectónico y 2 para entradas
inválidas, problemas de archivos o limitaciones del simulador. `--dump ADDRESS
SIZE FILE` permite inspeccionar memoria tras HALT o fallo arquitectónico.

## Alcance del modelo

- `GETTID` devuelve `warp_id * warp_size + core_id`.

- Los saltos divergentes usan `SSY` y dos pilas SIMT (regiones y caminos); véase [opcodes.md](docs/opcodes.md).
  `EXIT` retira lanes permanentemente y `BAR` sincroniza un workgroup.

- La memoria es unificada. Los resultados de una instrucción se confirman en
  orden de hilo: si varios STORE escriben la misma palabra, gana el último hilo
  activo. Es una regla determinista del simulador, no una garantía de hardware
  para programas con carreras de memoria.

- `CPU` representa únicamente una lane: mantiene registros y evalúa resultados
  provisionales. La entrada de ejecución pública es `System.step/run`, no un
  paso individual de CPU. Este módulo no sustituye la API del simulador escalar
  de `2.cpu-sim-func`.

## Extensiones SIMT

El ensamblador compartido `../1.isa/miniisa_asm.py` acepta `SSY label`, `BAR` y
`EXIT`. Son extensiones del simulador GPU; no se implementan aquí en la CPU/FPGA.

Cada entrada JSON admite `workgroup_id` (entero no negativo, por defecto 0).
Sin configuración, todos los warps pertenecen al workgroup 0. Las máscaras de
lanzamiento inicializan tanto `active_mask` como `live_mask`.

Prueba de divergencia, reconvergencia y barrera entre dos warps:

```powershell
python ../1.isa/miniisa_asm.py examples/simt_demo.asm -o examples/simt_demo.bin
python minigpu_sim.py examples/simt_demo.bin --num-warps 2 --trace-detail
```

En cada warp, las lanes 0–3 terminan con R3=11 y las lanes 4–7 con R3=21.

### Regiones SIMT reutilizables

El simulador implementa la [semántica de regiones reutilizables](docs/ssy-reusable-regions-design.md).
Repetir el SSY de la región más interna conserva su máscara y sus caminos,
sin reservar otra región. Las salidas directas al join no reservan caminos.
Los dos Mandelbrot pueden conservar el SSY dentro de su bucle.
Las capacidades se configuran mediante la API Python:
`System(simt_region_depth=4, simt_path_depth=8)`. Por defecto son ocho y ocho.
También se pueden indicar por línea de comandos:

```powershell
python minigpu_sim.py examples/simt_demo.bin --simt-region-depth 4 --simt-path-depth 8
```

Ambos argumentos aceptan enteros positivos y valen 8 cuando se omiten.
El RTL de `12.fpga-gpu` aún usa la semántica anterior; ejecutar allí estos
patrones no tiene todavía las mismas garantías.
Ejecutar pruebas desde la raíz del repositorio:

```powershell
./.venv/Scripts/python.exe -m unittest discover -s 11.gpu-sim-func -v
```

`test_simt_regions.py` incluye regresiones de ambos Mandelbrot. Activar
`RUN_SLOW_SIMT=1` añade la comparación de los framebuffers completos.
