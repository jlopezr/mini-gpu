# Backend `fpga-sys` (los casos GPU en la 36 y la 37)

Estado (2026-10-10): **fase 1 implementada** ([`backends/fpga_sys.py`](backends/fpga_sys.py),
registrada en `run_tests.py`; tests en `test_fpga_sys.py`). La fase 2 (ampliar GPU
SIMT DEBUG en el RTL de la 37) **sigue siendo diseño**. Las secciones 1 a 3 son el
diseño original; lo que cambia al implementarlo está al final, en «Resultado de la
fase 1».

## 1. Problema

Los casos de `cases-gpu/` solo corren en placa con `--backend fpga-gpu`, y ese
backend solo conoce las carpetas que `backend_from_rtl` clasifica como `gpu`
(12, 14, 22, 29: tienen `gpu_sm.v` o `gpu_system.v` y **no** `cpu.v`). La 36 y la
37 tienen `cpu.v`, así que se clasifican como `cpu`, y `-p 36` da «no es una
versión registrada para fpga-gpu». Es a propósito: ahí la GPU es un coprocesador
que lanza la CPU por MMIO (GPU CORE, `mmio.md` §14.1), y el monitor gobierna la
CPU, no la GPU.

Hoy la única prueba de la GPU real en esas dos placas es
`cases-cpu/gpu/launch-run` (y `launch-start` en la 37, que tiene el hito 2).

## 2. Hechos comprobados

- **El host llega al MMIO de la GPU por el monitor, sin programa de CPU.**
  Probado el 2026-10-10 en la 36 con `read_word`/`write_word`: `GPU_ID`=11,
  `GPU_CAPS`=0x808, `GPU_STATUS`=0x4 (IDLE), y el PC del descriptor del warp 0
  acepta escritura y se relee. (`top.v` de la 37 enlaza `mon_mmio_*` al mismo
  mux que la CPU.)
- **El kernel y los datos van en la SDRAM compartida** (`write_memory`, con la CPU
  parada), como en `fpga-gpu`.
- **Lo que el RTL deja observar** (`gpu_system.v` de la 37, §14.3/§14.4):
  `GPU_STATUS` (RUNNING/HALTED/IDLE/ERROR), `WARP_LIVE`, `WARP_DONE`,
  `FIRST_ERROR` y `FIRST_ERROR_PC`, `WARP_RETIRED` por warp (con `CONTEXT`) y el
  contador total de GPU PERFORMANCE (`+0x04`).
- **Lo que NO deja observar:**
  - el **PC de ejecución** de cada warp: `PC` en los descriptores es el
    descriptor (lo escrito), no el actual;
  - la **máscara de lanes viva** de cada warp;
  - los **registros** de cada lane: `gpu_system.v` ata `debug_register` a 0 y no
    saca `debug_data` ni `debug_pc` por MMIO. El `READ_REGISTER` del monitor de
    la 36/37 es el de la CPU.
- **Cuánto pesa eso en los casos** (barrido de `cases-gpu/**/test.json`, 78
  casos): **74 de 78** comprueban `pc`, `active_mask` o `registers` de algún
  warp; solo **3** no necesitan nada de eso. Por claves: `active_mask` 70,
  `registers` 67, `instr_por_warp` 58, `pc` 56, `fault` 38, `fault.address` 11.
  Todos usan además `memory_dumps`, `halted`, `error`, `error_code` o
  `instructions_executed` total, que sí se pueden leer.

La consecuencia es que un backend que solo use lo que el RTL expone corre ~3 de
78 casos. Para que valga la pena hace falta, además, una pequeña ampliación del
RTL (fase 2).

## 3. Diseño

### 3.1 Qué es y qué no toca

Un backend nuevo, `x.tests/backends/fpga_sys.py`, con nombre `fpga-sys` (y
`gpu-sys-both` contra el simulador GPU, como `gpu-both`). **No cambia**
`fpga-gpu`, `fpga-cpu`, `backend_from_rtl` ni la clasificación de la 36 y la 37:
estas siguen siendo `cpu` para los casos de CPU. Se selecciona por capacidad:
carpetas con `cpu.v` **y** capacidad `gpu_core` (`tools/capabilities.json`,
hoy 36 y 37). Las versiones salen de `version.json` (`cpugpu`, `mk2`), igual
que en los otros backends. Así no se rompe ningún prototipo anterior.

El monitor es el de la carpeta (`monitor.py` de la 36/37) y no hereda
`WarpMixin`: el backend escribe los descriptores él, por MMIO.

### 3.2 Flujo de un caso

1. `ensure_bitstream` (se reutiliza `board.py`) con la versión de monitor de la
   carpeta.
2. `halt_cpu`. **La CPU no se ejecuta nunca**: el host hace de CPU.
3. `write_memory(0, programa)` y las regiones de `initial_memory`.
4. `GPU_CONTROL.RESET` (0x82000018, bit 4): limpia errores y warps. En el hito 1
   (36) también borra los descriptores; da igual, se reescriben.
5. Por cada warp del modelo validado (se reutiliza `System(...).configure_warps`
   de `11.gpu-sim-func`, como `WarpMixin`): `write_word` de `PC` (+0x0),
   `ACTIVE` (+0x4), `WORKGROUP_ID` (+0x8) en `0x82010000 + 16·n`, y
   `LOGICAL_WARP_ID` (+0x200+4n) y `WARP_ARG` (+0x280+4n) si no son cero. Todo
   en palabras de 32 bits, que es lo que acepta `gpu_system.v`.
6. Lanzar. En la 36 los warps ya quedan vivos al escribir `ACTIVE` y se reanudan
   con `RUN`; en la 37 (hito 2) `RUN` copia los descriptores. Se escribe
   `GPU_CONTROL.RUN` (bit 0) en ambas; la diferencia no se gestiona en el
   backend.
7. Esperar: sondear `GPU_STATUS` hasta `IDLE` (bit 2) o `ERROR` (bit 3), con
   plazo de `timeout_seconds`. Si se agota, `GPU_CONTROL.HALT` y `TimeoutError`.
8. Observar (ver 3.3) y leer `memory_dumps` con `read_memory`.

### 3.3 Correspondencia con el resultado de `fpga-gpu`

El diccionario que devuelve `run()` es el mismo que el de `GpuFpgaBackend`, para
que `run_tests.py` compare sin cambios.

| Campo | De dónde | Fase |
|---|---|---|
| `halted` | `GPU_STATUS` IDLE o HALTED | 1 |
| `error`, `error_code` | `GPU_STATUS.ERROR` y `FIRST_ERROR[15:8]` | 1 |
| `instructions_executed` total | GPU PERFORMANCE `+0x04` | 1 |
| `warp[n].instructions_executed` | `CONTEXT=n·8`, `WARP_RETIRED` | 1 |
| `fault.pc`, `fault.warp_id`, `fault.core_id` | `FIRST_ERROR_PC`, `FIRST_ERROR` | 1 |
| `memory` | `read_memory` | 1 |
| `warp[n].pc` | **nuevo**: `DEBUG_PC` | 2 |
| `warp[n].active_mask` | **nuevo**: `DEBUG_LIVE` | 2 |
| `warp[n].lane[l].Rk` | **nuevo**: `DEBUG_REG` + `DEBUG_DATA` | 2 |
| `fault.address` | no disponible (ningún prototipo lo guarda) | — |

Los casos que piden algo no disponible se **omiten con motivo** antes de abrir el
puerto, como hace `fpga-gpu` con sus casos incompatibles; nunca se sustituye una
observación por el valor esperado.

Fuera de alcance al principio: los casos con `video`/`run_until` (la GPU de la 36
no es maestro de MMIO y el vídeo es de la CPU).

### 3.4 Fase 2: ampliar GPU SIMT DEBUG

Tres huecos que hoy dan `simt_bad` (`gpu_system.v`, `default` del `case`
de §14.3), sin tocar `monitor.v` (que tiene que ser idéntico en toda la
familia, ver `test_monitor_port`):

| Offset | Registro | Contenido |
|---:|---|---|
| `+0x14` | `DEBUG_PC` | `pc[debug_warp]` (el SM ya saca `debug_pc`) |
| `+0x18` | `DEBUG_LIVE` | máscara de lanes vivas de `debug_warp` (nuevo puerto del SM) |
| `+0x1C` | `DEBUG_REG` (RW) | número de registro, 5 bits; lo recibe `debug_register` |
| `+0x20` | `DEBUG_DATA` (R) | `debug_data` del carril de `debug_lane`, con la GPU parada |

`CONTEXT` ya elige warp y carril, y `§14.3` ya anuncia que «gobierna qué
registros devuelve el comando de lectura»: esto lo hace por MMIO. Con la GPU en
marcha esos registros leerían basura (la lectura usa el puerto del banco), igual
que hoy `READ_REGISTER` exige el núcleo parado. Una capacidad nueva
(`gpu_debug_state`, detectada del RTL como las demás) separa los casos
omitidos de los ejecutables.

Costo: unas pocas LUT en `gpu_system.v` y un puerto en `gpu_sm.v`. **Invalida
los bitstreams de la 37** y exige re-barrer semillas (ver la nota de bitstreams
STALE). Además, la 37 tiene ahora mismo un build en marcha de otra sesión
(`rf-distribuida`), así que habría que coordinarlo. Para la 36 sería un
backport; no se propone.

## 4. Pruebas sin placa

Un `FakeMonitorClient` en `test_fpga_sys.py` (igual que `test_fpga_gpu.py`) que
registre los accesos y compruebe: el orden RESET → descriptores → RUN → sondeo,
las direcciones y valores escritos, el plazo, el mapeo de `GPU_STATUS` a
`halted`/`error`, y que un caso con expectativas no disponibles se omite con
motivo sin abrir el puerto.

## 5. Incertidumbres (no verificadas)

- **El PC final de un warp** que da el simulador al terminar (`EXIT`) puede no
  coincidir con `pc[w]` del SM. **Sigue sin saberse**: ningún caso aceptado en la
  fase 1 lee el PC, así que `gpu-sys-both` no lo ha podido contrastar. Es lo
  primero que dirá la fase 2.
- **Hito 1 vs 2**: el hito 1 (36) hace `live = ACTIVE` al escribir el
  descriptor. Comprobado en la 36 el 2026-10-10: la secuencia de `launch-run`
  (RESET, descriptores con ACTIVE al final, RUN, esperar `WARP_DONE`) funciona
  tal cual desde el host.
- **Latencia de MMIO por el monitor**: cada `write_word`/`read_word` son unos
  milisegundos de serie. Un caso con 8 warps son ~40 escrituras; despreciable,
  pero el sondeo de `GPU_STATUS` conviene espaciarlo.
- **Lectura de registros con la GPU parada**: `debug_register` se usa en
  `read_address_a` solo con `halted`; falta comprobar que `halted` está a 1 tras
  terminar todos los warps (el comentario del SM dice que mezcla «pausada» con
  «terminada»).

## 6. Resultado de la fase 1

**Cómo se usa** (la 36 y la 37 son CPU **y** GPU; `fpga-sys` es *además* de
`fpga-cpu`, no en su lugar):

```powershell
python run_tests.py --backend fpga-sys -p 36 --port COM3     # solo la GPU
python run_tests.py --backend gpu-sys-both -p 36             # contra el simulador
test-board -p 37 -y                                           # CPU y GPU, una tras otra
test-board -p 37 --family gpu -y                              # solo la GPU
test-all --family gpu -y                                      # 12, 14, 22, 29, 36 y 37
```

**Qué cambió respecto al diseño:**

- `backend_from_rtl` **no cambia**: la 36 y la 37 siguen siendo `cpu` para
  `fpga-cpu`, el SYS_ID y los informes. `rtl_facts.backends_from_rtl` es la nueva,
  y devuelve `("cpu", "gpu")` para ellas; la usan `fpga-sys`, `test-board`,
  `test-all` y `prototype-report`.
- Las **capacidades** de la GPU se detectan solo en los ficheros `gpu_*.v`
  (`gpu_core.gpu_capabilities`). Con la detección normal, `alu_extended`, `calls`
  o `subword_memory` se habrían atribuido a la GPU al casar en `cpu.v`. El vídeo,
  el puerto serie y el INPUT no son capacidades de esta GPU (no es maestro de MMIO).
- `fpga-sys` **no admite `--measure`** todavía.

**Qué se comprobó en la placa** (2026-10-10):

| | `fpga-sys` | diferencial `gpu-sys-both` |
|---|---|---|
| 36 (bitstream actual) | 6 casos, 0 fallos | 6 casos, 0 fallos |
| 37 con el bitstream `isa-ext` | 13 casos, 1 fallo (ver abajo) | — |

De los 78 casos de `cases-gpu` solo **2** son comprobables hoy
(`demo-warp-lane-bands` y `gpu-mandelbrot-packed`), más los casos compartidos que
no dependen del estado de los warps. Un test lo fija
(`test_los_casos_de_gpu_que_se_aceptan_son_pocos_y_se_conocen`): si ese número
sube es que se ha expuesto algo del RTL y hay que anotarlo aquí. `mandelbrot-packed`
tarda 5 s en la placa y 100 s en el simulador.

**La 37 no tiene ahora un bitstream de su RTL actual.** Todos los builds
posteriores a `isa-ext` (8 oct) fallaron y dejaron el mismo `hardware.bit`
(el de `isa-ext`, que no cerró timing: 67,1/80 MHz). El backend declara las
capacidades del RTL *actual*, así que con ese bitstream:

- con `base` (cerró timing, pero es anterior a la ISA extendida): fallan los 7
  casos de `alu_extended`, `calls`, `compare` y `shift_immediate`
  (código 1 y 5, instrucción inválida);
- con `isa-ext`: pasan todos salvo `shared-shift-immediate-shli-shri-sari`
  (código 5): el `gpu_lane.v` de ese build no tiene los desplazamientos
  inmediatos, que se añadieron después. Tampoco pasa `gpu-launch-start`
  (`fpga-cpu`): WARP_START es del hito 2.

Ningún fallo viene del backend. Hay que repetir la 37 cuando exista un bitstream
del RTL actual.

## 7. Orden de trabajo propuesto

1. Fase 1: `fpga_sys.py` + registro en `run_tests.py` + `test_fpga_sys.py`.
   Valida el flujo con los 3 casos sin observaciones de estado y `launch-run`.
2. Fase 2 en la 37 (RTL + `mmio.md` §14.3 + `capabilities.json`), re-barrido de
   semillas y primera pasada con `gpu-sys-both` para descubrir diferencias.
3. Decidir qué hacer con los casos de vídeo y la 36.
