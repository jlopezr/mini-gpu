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
| `boxes.bin`, 12 swaps | 2,6 s | 1,0 s |
| `dma-bench` | 8,2 s | 1,7 s |

## Pendiente

### 1. El motor va a la mitad que el generador que había antes

Con la CPU hace unos 60 M instrucciones/s; el generador que reescribía los
simuladores por AST (ya borrado) llegaba a unos 120 M con su bucle propio. No se
ha perfilado. Sospechosos:

- `load_u32`/`store_u32` de `tools/codon_compat` en cada acceso a memoria;
- `device_for`, que mira los dispositivos MMIO uno por uno en cada LOAD/STORE
  (l11 en [LIMITACIONES.md](LIMITACIONES.md));
- `CpuGpuSystem.run` comprueba límites y llama a `tick_devices` (y por tanto a
  los proxies) en cada instrucción.

Por dónde empezar: perfilar con Instruments (macOS) o `perf` (Linux) el binario
`_build/codon-engine/<hash>/sim-sys-codon` con `boxes.bin`. Para lanzarlo a mano
necesita el entorno que monta `tools/codon_backend.prepare`.

### 2. Llamadas de los proxies a Python en cada acceso MMIO

[`tools/sim_devices.codon`](../sim_devices.codon): el reloj por lotes evita casi
todas las llamadas por tick, pero cada `read`/`write`/`validate` de vídeo, serie o
entrada hace `sync()` y además pregunta `ticks_until_event()` a Python. Un programa
que sondea en bucle un registro de estado paga dos llamadas a CPython por
iteración. No se ha medido: `boxes` y `dma-bench` apenas sondean. Haría falta un
caso que sondee (por ejemplo, esperar `VSYNC` en bucle) para saber si importa.
Ideas: no preguntar `ticks_until_event()` tras un `read` si `pending` era 0, o
copiar al proxy los registros de estado que no tienen efectos al leerse.

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
