# TODO

Por orden de prioridad.

## 1. Optimizar LSU

El codigo es muy inocente y es lo que hace que hayamos bajado de 120Mhz a 32Mhz.

## 2. Revisar los inmediatos de la ISA en conjunto

Los inmediatos en desplazamientos, `AND`, `OR`, etc. pueden ahorrar bastantes instrucciones. La revisión debe ser global, no instrucción a instrucción.

`SHLI`/`SHRI`/`SARI` ya se añadieron (capability `shift_immediate` en
`21.fpga-cpu-hdmi-alu`, `isa.md` §3, opcodes `0x07–0x09` bit 10). No está
claro si fue como parte de esta revisión global o una decisión aparte —
revisar si el resto de inmediatos (`AND`, `OR`...) sigue pendiente o si ya
no aplica.

## 3. Mejoras al controlador de SDRAM

¿Qué mejoras podemos hacer? ¿Qué hacía supuestamente el de `7.fpga-ram`, que no funciona?

## 4. Ejecución paso a paso o N pasos

Avanzar una instrucción de warp, inspeccionar registros y memoria, y detenerse
en un PC o un warp concreto. `TextTrace` ya hace el trabajo sucio.

Debe ser una herramienta **aparte**, no una opción de `run_tests.py`: el
runner responde pasa/falla y un depurador interactivo es otro oficio.

Prioridad baja a propósito: no encuentra fallos, ayuda a entenderlos una vez
encontrados, y con las expectativas actuales `--trace-detail` ya cubre casi
todos los casos.

**Parcial.** `monitor.py step` ya existe (un paso de CPU en placa real), pero
es el primitivo de bajo nivel, no la herramienta descrita aquí: no inspecciona
registros/memoria automáticamente ni para en un PC/warp concreto. Sigue
pendiente como herramienta aparte.

## 5. Snapshots de ejecución

Guardar y restaurar memoria, PC, registros, máscaras y estado del scheduler.
Extensión del fichero de lanzamiento, con un propósito distinto.

Es lo de mayor impacto de la lista: `mandelbrot` son ~100 s y supone el 99,8 %
del tiempo de la suite GPU; reproducir un fallo tardío pasaría de minutos a un
instante. Además permitiría comparar simulador y FPGA **en un punto intermedio**,
no solo al final.

**Pero va el último a propósito.** Un snapshot tiene que serializar
`region_stack` y `path_stack`, que es justo lo que está en diseño activo. Congelar
ese formato ahora obliga a migrar snapshots cada vez que se toque la semántica
de `SSY`. Hacerlo cuando `SSY` esté cerrado.

## 6. Buscar inexactitudes entre doc y código

## 7. Consistencia de documentación por prototipo RTL

`cycles.md` ya es uniforme en toda la familia CPU (6, 10, 16, 18, 19, 21).
Falta en GPU (12, 14, 17). `optimizacion.md` solo existe en 17 — no está
claro si debería generalizarse o si es específico de esa carpeta (fue la que
subió el fmax de la 14).

## 8. Revisar divergencias innecesarias entre versiones

Una optimización en una versión sí y en otra no. `MULX` no está en CPU pero
sí en GPU... Y que los ciclos de cada versión de CPU/GPU sean consistentes
entre sí (ligado al punto 7).

## 9. `apio lint` falla en prototipos con `sdram_model.v`

En `21.fpga-cpu-hdmi-alu` (y probablemente cualquier otro con SDRAM + testbenches
de simulación), `apio lint` pasa `-DSYNTHESIZE`, pero `sdram_model.v` envuelve
`module sdram_model` en `` `ifndef SYNTHESIZE ``. Como `apio lint` también barre
los `*_tb.v` (p.ej. `cpu_burst_system_tb.v`, que instancia `sdram_model`), el
módulo queda excluido y Verilator falla con `Can't resolve module reference:
'sdram_model'`. No es una regresión de RTL: es que `apio lint` mezcla ficheros
de síntesis y de simulación en el mismo comando con `-DSYNTHESIZE` puesto.
Revisar si hay que excluir `*_tb.v` del lint, o separar `sdram_model.v` del
guard de síntesis.

## 10. Revisar `MONITOR_REGIONS` — HECHO

El vacío de la familia HDMI (16/18/19/21) no era correcto, pero tampoco era un
fallo visible. `MEMORY_REGIONS` solo filtra **bloques y transferencias**
(`validate_block`/`validate_transfer`); los accesos byte a byte no pasan por ahí,
y todo el acceso a vídeo de esa familia va byte a byte por `_read_register` de
`x.tests/backends/fpga.py`. Por eso la lista podía estar vacía sin que se notara.
Además `21/monitor.v` no tiene lista blanca propia —el filtrado lo hace
`monitor_mem_adapter_128.v`—, así que no había gemela que la contradijera.

La incoherencia era contra la 22, donde un bloque de 28 bytes sobre el bloque de
vídeo sí funciona. Relleno con `(0x8000_0000, 0x8000_0018)` en las cuatro; llega
a `0x1c` cuando se añada `VIDEO_CTRL` a la CPU (fase 3.5 de
`docs/unificacion-mmio.md`).

Comprobado en simulación: `cpu_video_tb.v` recorre ahora los 24 bytes del bloque
de vídeo seguidos contra el adaptador real y verifica que se recomponen en los
mismos valores que las lecturas por palabra. Es lo que hace un `READ_BLOCK` a
nivel de bus —el monitor transfiere el bloque como lecturas de byte consecutivas
sobre ese puerto—, y `mon_read` aborta en cuanto una devuelve error, así que
valida el rango entero y no solo su primera dirección.

## 12. Tests de capacidad pendientes en `x.tests`

**En marcha.** El mecanismo de capacidades ya existía para GPU
(`requires: ["atomic_warp_faults"]`); se extendió a CPU con `video` y
`frame_capture`. El primero subido con esto fue `cases/video/band`.

Lo que queda por subir, por orden de lo que más cubriría:

- Los cuatro `swap_demo` / `tear_demo` de la 16 y la 18, que hoy solo se
  miran a ojo. Necesitan que el modelo de referencia sepa mover la banda,
  o un `run_until` que pare siempre en el mismo punto del ciclo.
- `examples/fpga_smoke_test.asm`, que está duplicado en 6, 10, 16 y 18.
- Los bancos de `memory-test` del monitor, que son un caso de conformidad
  disfrazado de comando.

## 12.5. Unificar el mapa de memoria y MMIO entre prototipos

Aplicar al RTL el contrato objetivo de `docs/mapa-de-memoria.md` §6, para que el
mismo programa valga en varias versiones. Plan por fases con la lista completa
de ficheros a tocar: **[`docs/unificacion-mmio.md`](docs/unificacion-mmio.md)**.

Los movimientos reales son solo dos —warps de `0x80000000` a `0x80001000`, y el
vídeo de la 22 de `0x80000200` a `0x80000000`— pero arrastran el bloque de
identificación, la política de dirección inexistente y la renumeración de las
versiones de monitor.

Numerado 12.5 provisionalmente; probablemente merece subir en la lista.

## 13. Herramienta para testear solo un component a nivel de RTL, p.e la LSU

## 13. Herramienta similar para generar diagrama de bloques. como se conecta LSU con el resto de componentes, y como se conecta el resto de componentes entre si.
## 14. VVP que ejecuta? El RTL?
