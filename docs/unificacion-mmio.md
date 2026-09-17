# Plan de unificación del mapa de memoria y MMIO

Lista de trabajo para aplicar el **contrato objetivo** de
[`mapa-de-memoria.md`](mapa-de-memoria.md) §6 al RTL, a los monitores y a los
tests. Ese documento define *qué* debe quedar; este define *en qué orden* y *qué
hay que tocar en cada paso*.

Objetivo declarado: **que el mismo programa valga en varios prototipos**. El
criterio para ordenar la lista es ese, no la dificultad. Por eso la 22 va pronto
pese a ser la más difícil, y los contadores en CPU quedan fuera de la ronda.

## Lo que ya está hecho

No hay que tocar nada de esto, y conviene saberlo antes de empezar:

- **19 y 21 ya son conformes.** Su troceado en 16 slots de 256 B es la base del
  contrato, precisamente para no tener que moverlas.
- **Ningún core de CPU cambia de dirección** en todo el plan.
- **Depuración SIMT y contadores de rendimiento ya están en su slot** definitivo
  (`0x80000100` y `0x80000300`). Coincidencia, pero aprovechable.

Los movimientos reales son solo dos: warps `0x80000000` → `0x80001000`, y el
vídeo de la 22 `0x80000200` → `0x80000000`.

---

## Fase 0 — Preparar las fuentes de verdad

No toca RTL. Desbloquea el bitmap de dispositivos y la lista blanca derivada,
que son dos consumidores de la misma tabla.

- [x] **Permitir que `architecture` y `file` sean listas.** Prerrequisito que no
      estaba previsto: `parse_requires` en `run_tests.py` rechazaba un `requires`
      cuya arquitectura no fuese *exactamente* la del caso, y `architecture` era
      un único valor. Mientras `video` fuese solo `cpu`, un caso GPU **no podía
      declararlo aunque la placa tuviera el dispositivo** — el bloqueo estructural
      justo para lo que persigue este plan. Ahora `CAPABILITIES` guarda una tupla
      y `capability_files`/`capability_architectures` normalizan ambos campos.
- [x] **Añadir entradas GPU a [`tools/capabilities.json`](../tools/capabilities.json):**
      `warp_config` y `simt_debug` (patrones `cfg_region` y `debug_warp` sobre
      `gpu_system_bl8.v`/`gpu_system.v`, en ese orden porque la 22 conserva un
      `gpu_system.v` que su top **no instancia**) y `perf_counters`
      (`gpu_perf_counters.v`).
- [x] **Arreglar la detección de `video` para GPU.** `video` pasa a
      `"architecture": ["cpu", "gpu"]` con `file` alternativo
      `["video_registers.v", "gpu_video_regs.v"]`.
- [x] **Regenerar la tabla** con `generate-docs`. Resultado: 12/14/17 declaran
      `warp_config, simt_debug`; la 22, `video, warp_config, simt_debug,
      perf_counters`; ninguna CPU cambia.

      Aviso para las próximas regeneraciones: `generate-docs` también reescribió
      `synthesis-report.md` con cifras de `_build/video-mux` en vez del informe
      archivado, porque la 22 no tiene `reports/*/summary.json` y
      `_build_snapshot` cae a lo último que haya en `_build/`. Es dato local no
      versionado; se revirtió. Revisar ese fichero antes de dar por bueno un
      `generate-docs`.
- [ ] Revisar de paso el punto 10 del `TODO.md` (`MONITOR_REGIONS = ()` en la
      familia HDMI): la fase 4 va a necesitar que esa lista sea coherente.

Dos cosas quedaron abiertas y conviene decidirlas antes de la fase 4:

- [ ] **Ambigüedad del nombre `perf_counters`.** Ya existía
      `perf_counters_from_rtl` en `rtl_facts.py`, que detecta algo **distinto**:
      el comando de monitor `CMD_GET_CYCLES` (`0x36`) de la 18, y pone
      `entry["perf_counters"] = True` en las VERSIONS de `backends/fpga.py`. No
      chocan funcionalmente —son claves distintas del mismo dict— pero ahora hay
      dos `perf_counters` que significan cosas diferentes en el mismo informe.
      Decidir si se renombra uno de los dos.
- [ ] **Un `test.json` sigue declarando una sola `architecture`.** Que `video`
      valga para las dos familias permite a un caso GPU *requerirlo*, pero no
      hace que un mismo caso corra en 21 y 22: GPU exige `warp_config` y CPU lo
      rechaza. Compartir el caso, y no solo la capacidad, es trabajo aparte — se
      decidirá con el criterio de salida de la fase 3 delante.

## Fase 1 — Ensayo del movimiento de warps en la 12

La 12 es la más barata para rodar la cadena completa: EBR en vez de SDRAM, sin
vídeo, sin contadores, ciclo de síntesis corto. El parche recorre las cuatro
capas que van a doler igual en la 22.

- [x] Mover la ventana de configuración de warps a `0x80001000–0x8000107F` en
      [`12.fpga-gpu/gpu_system.v`](../12.fpga-gpu/gpu_system.v). El prefijo pasa
      de `address[31:12]==20'h80000` a `address[31:13]==19'h40000`, y
      `address[12]` distingue la página compartida de la exclusiva. El resto de
      la página GPU responde `bad`, como cualquier hueco.
- [x] Actualizar la **lista blanca dentro de**
      [`12.fpga-gpu/monitor.v`](../12.fpga-gpu/monitor.v).
- [x] Actualizar `MONITOR_REGIONS` en
      [`12.fpga-gpu/monitor.py`](../12.fpga-gpu/monitor.py), la gemela a mano de
      la anterior. Se introdujo `WARP_CONFIG_BASE` para que la dirección deje de
      estar repetida por el fichero.
- [x] Pasar los tests de `x.tests` y los `*_tb.v`. **176 tests Python** y la
      regresión RTL completa de la 12 en verde.
- [ ] Sintetizar y verificar en placa que el lanzamiento de warps sigue vivo.

Cuatro testbenches daban por hecha la dirección vieja, y ninguno de forma
evidente: `gpu_control_tb.v` la tenía en la tarea `fresh` y en un caso suelto,
`gpu_regions_tb.v` en tres sitios, `gpu_system_tb.v` en el bucle de
configuración, y `gpu_uart_tb.v` **como bytes big-endian dentro de la trama
UART** (`80 00 00 30` → `80 00 10 30`), que es el único sitio donde la dirección
no se parece a una dirección. Conviene buscarla en esas cuatro formas al migrar
14, 17 y 22.

El backend compartido `x.tests/backends/gpu_fpga.py` también la tenía cableada,
y lo comparten las cuatro GPU. Ahora la lee del `monitor.py` del prototipo con
`warp_config_base()`, y las tres carpetas sin migrar declaran
`WARP_CONFIG_BASE = 0x8000_0000`: **en las fases 2 y 3 basta con cambiar esa
constante**, no hay que volver a tocar el backend.

## Fase 2 — Replicar en 14 y 17

12, 14, 17 y 22 comparten decodificador, y los `monitor.v` de 14 y 17 son byte a
byte idénticos entre sí. El parche de la fase 1 se replica casi literal.

- [x] Aplicar el mismo movimiento en
      [`14.fpga-gpu-ram/gpu_system.v`](../14.fpga-gpu-ram/gpu_system.v) y
      [`17.fpga-gpu-ram-v2/gpu_system.v`](../17.fpga-gpu-ram-v2/gpu_system.v),
      con sus `monitor.v`, `monitor.py`, testbenches, `test_monitor.py` y README.
      El parche de la 12 valió literal: los cuatro sitios eran los mismos, en las
      mismas cuatro formas.
- [x] Regresión RTL de **las tres en paralelo** (`Start-Job` en una sola
      llamada). Las tres en verde a la primera, y 176 tests Python.
- [x] Comprobar que 14 y 17 siguen respondiendo idénticas: sus `gpu_system.v`
      eran byte a byte iguales antes del parche y lo siguen siendo después.
- [ ] Sintetizar y verificar en placa (pendiente junto con el de la fase 1).

## Fase 3 — La 22, donde está el retorno

Es la única fase con trabajo no mecánico, y la primera que produce un programa
realmente portable entre familias. Los dos movimientos están acoplados: el vídeo
no puede ir a `0x80000000` mientras los warps estén ahí.

- [x] Mover warps a `0x80001000` en
      [`gpu_system_bl8.v`](../22.fpga-gpu-bl8/gpu_system_bl8.v) **y también en
      [`gpu_system.v`](../22.fpga-gpu-bl8/gpu_system.v)**. Ojo aquí: el `top_bl8`
      instancia `gpu_system_bl8`, pero `gpu_system` (la variante BL1) **no es
      código muerto** — lo usan `gpu_control_tb`, `gpu_system_tb`,
      `gpu_regions_tb` y `gpu_bench_base_tb`. Son dos decodificadores, no uno.
- [x] Mover el bloque de vídeo de `0x80000200` a `0x80000000`.
- [x] **`VIDEO_CTRL` de `+0x00` a `+0x18`**, dejando `FB_FRONT` en `+0x00`.
- [x] **Implementar el bit 1 de `STATUS` (`swap_pending`)** en
      [`gpu_video_regs.v`](../22.fpga-gpu-bl8/gpu_video_regs.v).
- [x] **`HALT_AT` (`+0x14`) lee cero** en vez de levantar `bad`. No estaba
      previsto y hacía falta: al ensanchar la lista blanca a `0x80000000–
      0x8000001C` para cubrir el bloque entero, una lectura en bloque de los 28
      bytes habría dado NACK en el byte 20. Leer cero es además lo que hace la
      CPU con un registro ausente del bloque. El **mecanismo** no se implementa:
      pararía el SM desde un registro de un periférico, y los kernels de la 22 ya
      terminan con `HALT`.
- [x] Actualizar lista blanca de `monitor.v` y `MONITOR_REGIONS` de `monitor.py`.
- [x] Revisar los kernels: `plasma.asm`, `plasma_small.asm`, `plasma_1frame.asm`,
      `plasma_static.asm`, `mmio_selftest.asm` y `plasma_nommio.asm` llevan las
      constantes dentro. **Y hay que reensamblar los `examples/*.hex`**, que están
      versionados y son los que leen los testbenches con `$readmemh`; conservar
      la convención de cada fichero (los `plasma*.hex` están en mayúsculas y el
      resto en minúsculas) para no ensuciar el diff.
- [x] Actualizar los testbenches afectados, incluido `gpu_lsu2_tb.v`, que usaba
      `0x80000204`/`0x80000208` como direcciones MMIO de ejemplo.
- [x] Añadir al `gpu_monitor_regions_tb.v` la lectura del **bloque de vídeo
      entero** (28 bytes). Con 4 bytes no se veía el hueco de `HALT_AT`.
- [ ] Verificar en placa que el arranque sigue en **PATTERN, no SCANOUT** — la
      SDRAM recién encendida contiene basura y arrancar en SCANOUT elegiría una
      salida indefinida por defecto.
- [x] Documentar que **los programas alinean las bases de framebuffer a 16
      bytes**. El alineamiento no se unifica: 4 B en CPU y 16 B en GPU conviven
      si los programas respetan el más estricto. Escribir una base no alineada a
      16 no da error en la 22, se truncan los bits bajos en silencio.

### Criterio de salida de la fase 3

El mismo `.asm` de vídeo, con las mismas constantes, corre en 21 y en 22. Si eso
no se cumple, la fase no está terminada aunque todo sintetice.

## Fase 4 — Descubrimiento en tiempo de ejecución

Va **después** de fijar los slots: hasta aquí el bitmap describiría un mapa a
punto de cambiar. Y arrastra una decisión previa que conviene tomar antes de
escribir un registro.

- [ ] **Decidir la política de dirección inexistente.** Hoy CPU lee cero y GPU
      levanta `bad`. El truco de compatibilidad de §6 —"leer cero en
      `0x80000F00` ya significa prototipo antiguo"— solo funciona en CPU: en GPU
      un binario que sondee el bloque no lee cero, revienta la transacción.
      Recomendación: **unificar solo dentro del slot de identificación**
      (`0x80000F00–0x80000FFF` lee cero en GPU) y mantener `bad` en el resto de
      la página. Pasar la página entera a "lee cero" apagaría el diagnóstico que
      hoy convierte un error de programa GPU en un error visible del host.
- [ ] **Definir los campos** del bloque `0x80000F00`:

      | Offset | Registro | Contenido |
      |---|---|---|
      | `+0x00` | `SYS_ID` | Magic + identificador de sistema. Cero = prototipo antiguo |
      | `+0x04` | `CONTRACT` | Versión del contrato de mapa de memoria |
      | `+0x08` | `DEV_BITMAP` | Un bit por dispositivo presente |
      | `+0x0C` | `ISA_PROFILE` | Perfil de ISA |

      Dos decisiones que importan: `SYS_ID` lleva **magic, no un contador**, o el
      valor 0 queda ambiguo entre "prototipo antiguo" y "prototipo 0". Y
      `CONTRACT` es **distinto** de la versión de monitor: el contrato de
      direcciones cambia por otras razones y a otro ritmo, y mezclarlos
      reproduce el lío de los diez números para cuatro juegos de comandos.
- [ ] **Generar `DEV_BITMAP` desde `capabilities.json`** (fase 0), no a mano.
- [ ] Implementarlo, empezando por 19/21 (que solo les falta esto para ser
      conformes) y siguiendo por las cuatro GPU.
- [ ] Actualizar la tabla de conformidad de `mapa-de-memoria.md` §6.

## Fase 5 — Consecuencias sobre el monitor

Orden tomado de §6.5. Hacerlo antes obliga a tocar el monitor dos veces.

- [ ] **Renumerar las versiones de monitor por juego de comandos**: de diez
      valores (1.15–1.20, 2.3–2.4) a cuatro. Hoy 6, 10 y 16 tienen el mismo juego
      y llevan 1.16/1.17/1.18; 19 y 21 tienen el mismo juego y llevan 1.20 y
      1.15. Y 14, 17 y 22 responden todos 2.4 siendo hardware distinto, con la
      consecuencia de que `--version sdram` pasa contra una 22 flasheada y se
      miden prestaciones del hardware equivocado.
- [ ] Conservar el número como **contrato de protocolo**, no como identidad. El
      caso que lo justifica es el backport de R0: mismos comandos, mismos
      dispositivos, misma lista de rangos, y un bitstream viejo no da error — da
      otro resultado. Un bitmap de dispositivos no detecta eso.
- [ ] **Unificar los `monitor.v` en uno parametrizado**, con los comandos
      opcionales por parámetro y la lista blanca **derivada** de qué dispositivos
      hay en vez de copiada. Con los slots fijos la derivación es directa.
- [ ] La única diferencia estructural que no se resuelve con parámetros es el
      cableado de `READ_REGISTER` y `RESET_CPU`, que van a sitios distintos en
      CPU y GPU. Tratarla explícitamente.

---

## Fuera de esta ronda, y por qué

- **Control de lanzamiento GPU por registros** (`0x80001080–0x80001FFF`). Hoy
  run/halt/step/reset llegan por señales del monitor. Convertirlos en registros
  choca de frente con que la interfaz host es byte a byte y solo funciona con la
  GPU parada. Es rediseño, no reubicación.
- **Contadores de rendimiento en CPU.** Función nueva, no condición para
  compartir programas.
- **Convivencia CPU+GPU en el mismo bitstream.** El contrato se diseña para no
  cerrarle la puerta —por eso lo exclusivo de la GPU se va a una segunda página
  en vez de a un slot libre de la primera— pero los siete puntos de "lo que falta
  por resolver" de §6 (arbitraje, dominios de reloj, orden de escrituras, quién
  pide los swaps) son otro proyecto.
- **Ventana MMIO en los simuladores.** 2 y 11 quedan fuera de contrato a
  propósito. Añadir una ventana MMIO al simulador funcional para que un programa
  no falle sería la peor manera de resolverlo; el patrón bueno ya existe y es
  `plasma_nommio.asm`.
