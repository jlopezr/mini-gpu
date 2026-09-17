# Plan de unificación del mapa de memoria y MMIO

Lista de trabajo para aplicar el **contrato objetivo** de
[`mapa-de-memoria.md`](mapa-de-memoria.md) §6 al RTL, a los monitores y a los
tests. Ese documento define *qué* debe quedar; este define *en qué orden* y *qué
hay que tocar en cada paso*.

Objetivo declarado: **que el mismo programa valga en varios prototipos**. El
criterio para ordenar la lista es ese, no la dificultad. Por eso la 22 va pronto
pese a ser la más difícil, y los contadores en CPU quedan fuera de la ronda.

## Estado al 17/09/2026

**Cerradas y verificadas en placa:** fases 0, 1, 2, 3, **3.4** (`READ_WORD` en
los diez prototipos con juego de comandos) y **4a parcial** (`SYS_ID` en las
cuatro GPU). La 22 responde monitor 2.6 y pasa 28 casos contra hardware.

El último punto de la fase 0 —un caso de vídeo que corra en las dos familias con
el mismo binario— **también está cerrado**, y resultó arrastrar cuatro cosas que
no estaban previstas: `architecture` como lista, la carpeta `cases-shared`, un
`VideoDevice` para el simulador funcional de GPU (no lo tenía) y un
`incompatibility` en el backend `gpu-simulator` (faltaba, y era un fallo: no
miraba el `requires` de los casos).

**Lo siguiente es la fase 3.5**, y conviene entrar en ella sabiendo que no toda
pesa lo mismo: `VIDEO_CTRL` en CPU desbloquea trabajo, y unificar las bases de FB
—34 ficheros en tres copias independientes— sólo iguala. La **4b** y la **fase 5**
no tienen hoy un consumidor que las pida.

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
- [x] **Resuelto el punto 10 del `TODO.md`** (`MONITOR_REGIONS = ()` en la familia
      HDMI). El vacío no era correcto, pero tampoco era un fallo visible, y las
      dos mitades importan:

      `MEMORY_REGIONS` solo filtra **bloques y transferencias**
      (`validate_block`/`validate_transfer`); los accesos byte a byte no pasan por
      ahí. Como todo el acceso a vídeo de la familia HDMI va byte a byte por
      `_read_register`, la lista podía estar vacía sin que nadie lo notara. Y
      `21/monitor.v` no tiene lista blanca en absoluto —el filtrado lo hace el
      adaptador—, así que tampoco había gemela que contradijera.

      Lo incoherente era contra la 22: allí un bloque de 28 bytes sobre el bloque
      de vídeo funciona (lo comprueba `gpu_monitor_regions_tb` desde la fase 3),
      y en 16/18/19/21 el cliente lo rechazaba antes de mandarlo aunque el RTL lo
      habría aceptado. Relleno con `(0x8000_0000, 0x8000_0018)` en las cuatro;
      llegará a `0x1c` cuando la fase 3.5 añada `VIDEO_CTRL`.

- [x] **Resuelta la ambigüedad del nombre `perf_counters`.** Era peor que una
      molestia de lectura: `perf_counters_from_rtl` en `rtl_facts.py` detecta el
      comando de monitor `CMD_GET_CYCLES` (`0x36`) y ponía
      `entry["perf_counters"] = True`, mientras que la capacidad homónima detecta
      el bloque MMIO `gpu_perf_counters.v`. **En la 22 daban valores opuestos
      para la misma carpeta**: su monitor tiene los 12 comandos base, así que el
      campo era `False` y la capacidad estaba presente.

      El mal nombre era el del backend —no describe un dispositivo, describe si
      el monitor entiende dos comandos, que es lo que §6.5 llama «+contadores»—,
      así que pasa a **`monitor_cycle_counters`** y la capacidad conserva el
      nombre del dispositivo que usa el contrato.

- [x] **Un caso de prueba de vídeo compartido entre familias.** Cerrado:
      [`x.tests/cases-shared/video/double-buffer`](../x.tests/cases-shared/video/double-buffer).
      Pasa en `cpu-simulator` y en `gpu-simulator` con **el mismo binario**.

      Lo que hizo falta, que fue más de lo previsto:

      1. **`architecture` admite una lista.** `case_architectures` sustituye a
         `case_architecture`, y `resolve_architecture` decide con cuál cargar el
         caso según el backend. La familia la elige el backend, no el caso.
      2. **Carpeta `cases-shared`.** Los casos de las dos familias viven
         aparte a propósito: mezclados con los de CPU, el día que uno dejara de
         correr como GPU no lo notaría nadie.
      3. **El programa no afirma ninguna dirección absoluta.** Las bases de
         encendido difieren entre familias —y la fase 3.5 planea cambiarlas—,
         así que comprueba *relaciones*: que escribir FB_BACK ignora los bits
         bajos, que tras SWAP las dos bases se intercambian, y que no hay
         underflow. El resultado va a memoria con la marca `0x5A5A` delante,
         porque un mapa de bits a secas confundiría «fallaron las cuatro» con
         «el programa no llegó a ejecutarse».
      4. **`VideoDevice` en el simulador funcional de GPU.** No existía: el
         modelo de GPU no tenía vídeo. Es un dispositivo propio, no una copia
         del de la CPU, porque el hardware no es el mismo —alineación a 16
         bytes, `HALT_AT` que lee cero, `VIDEO_CTRL` que sólo tiene la GPU—.
         Los offsets sí coinciden, que es justamente lo que el caso comprueba.
      5. **`incompatibility` en el backend `gpu-simulator`.** Faltaba, y era un
         fallo: era el único de los cuatro backends que no miraba el `requires`
         del caso, así que uno que pidiera un dispositivo ausente se ejecutaba
         igual y fallaba como si el programa estuviese mal, en vez de omitirse.
         No se había notado porque hasta ahora ningún caso de GPU declaraba una
         capacidad que al simulador le faltase.

      **Queda sin verificar en placa.** `gpu_fpga.run` ya lee los registros de
      vídeo con `READ_WORD`, pero eso no ha corrido contra la 22 todavía.

El obstáculo de fondo que tenía apuntado, y cómo se resolvió: **un caso CPU y
uno GPU no son el mismo programa**, porque el de GPU reparte trabajo con
`GETTID` entre 64 hilos. La salida no fue meter una guarda en el programa sino
quitarle el reparto **desde fuera**: el `warps.json` del caso deja
`active_mask: 1`, un único hilo activo, así que no hace falta ninguna guarda y
el código puede ser literalmente el mismo. `SSY`/`BAR` ya no estorban desde que
son no-op en la MiniCPU.

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
- [x] Sintetizar y verificar en placa. Síntesis: 34,93 MHz contra 25 de
      restricción, +136 LUTs. Placa (ULX3S 85F, COM3): monitor 2.3 y **26 casos,
      0 fallos**. Cada caso configura warps, así que valida de una vez la lista
      blanca, `MONITOR_REGIONS`, la ventana en `0x80001000` y la depuración.

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
- [x] Sintetizar y verificar en placa. 14: 32,65 MHz contra 25, +47 LUTs, y
      **27 casos, 0 fallos**. 17: 38,18 MHz, sintetiza y responde, pero
      `test-board` no la acepta porque **no tiene `version.json`** y por tanto no
      es un target de test soportado — es preexistente y deliberado, está
      documentado en `prototype_report.py`. Verificada a mano: `warp-status` lee
      los ocho descriptores desde `0x80001000`, y `0x80000000` **se rechaza**,
      que es lo correcto porque la 17 no tiene vídeo y el slot compartido está
      vacío.

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
- [x] **Verificado en placa** (ULX3S 85F, COM3). Síntesis: 35,67 MHz de SDRAM
      contra 25 de restricción, `clk_pix` 71,92 y `clk_pix_5x` 227,01, todos con
      holgura; **+452 LUTs (+1,3 %)**, bastante más que los +47 de la 14 — la 22
      lleva además el vídeo movido, el bit 1 de `STATUS`, `HALT_AT` y el término
      `mux_gpu_page` en el camino que comparten host y GPU. No está desglosado.

      Suite: **27 casos, 0 fallos**. Pero la suite **no prueba el vídeo**, porque
      los casos de vídeo son de arquitectura CPU y se omiten. La prueba de verdad
      fue correr los kernels y leer el bloque:

      | Registro | Tras `plasma.asm` | |
      |---|---|---|
      | `FB_FRONT` `+0x00` | `0x00100000` | lo escribe el kernel |
      | `FB_BACK` `+0x04` | `0x00140000` | lo escribe el kernel |
      | `STATUS` `+0x0C` | `0x329a0000` | 12954 frames, underflow 0 |
      | `SWAP_COUNT` `+0x10` | `4` | **cuatro intercambios completados** |
      | `HALT_AT` `+0x14` | `0` | lee cero, no levanta `bad` |
      | `VIDEO_CTRL` `+0x18` | `2` = SCANOUT | lo escribe el kernel |

      Es la validación completa: el kernel configuró los dos buffers en los
      offsets del contrato, pidió intercambios por `SWAP` en `+0x08` y el
      hardware completó cuatro, sin underflow.
- [x] Documentar que **los programas alinean las bases de framebuffer a 16
      bytes**. El alineamiento no se unifica: 4 B en CPU y 16 B en GPU conviven
      si los programas respetan el más estricto. Escribir una base no alineada a
      16 no da error en la 22, se truncan los bits bajos en silencio.

### Criterio de salida de la fase 3

El mismo `.asm` de vídeo, con las mismas constantes, corre en 21 y en 22. Si eso
no se cumple, la fase no está terminada aunque todo sintetice.

**Cumplido en hardware**, ver arriba.

### El caso de `SYS_ID`, reproducido en vivo

Con la 17 flasheada, **`board-upload -p 22` no sube nada** y da el bitstream por
bueno: comprueba la identidad por versión de monitor, y 14, 17 y 22 responden las
tres **2.4**. `mmio_selftest.asm` fallaba entonces con `error_code=0x02` al
escribir `VIDEO_CTRL`, porque corría sobre la 17, que no tiene vídeo. Con
`--rebuild` pasa.

Es exactamente lo que [`mapa-de-memoria.md`](mapa-de-memoria.md) §6.5 predice
—«con `--version sdram` contra una placa con la 22 flasheada, la comprobación de
bitstream pasa y se miden prestaciones del hardware equivocado»— y el argumento
práctico para la fase 4a. Hasta que exista `SYS_ID`, **conviene usar
`--rebuild`** al cambiar entre 14, 17 y 22.

### Otros dos fallos que destapó la fase 0, y que no eran suyos

**Los `examples/*.bin` están versionados** y en la fase 3 se regeneraron los
`.hex` pero no los `.bin`: `mmio_selftest`, `plasma_1frame` y `plasma_small` se
quedaron desfasados respecto a su `.asm`. Al migrar kernels hay que regenerar
**los dos** formatos.

`run-board` abortaba en la 22 con «The FPGA rejected the command» al leer
`VIDEO_STATUS`. `run_board.py` hace esa comprobación de underflow **si el
prototipo declara `video`**, y hasta la fase 0 la 22 no lo declaraba, así que la
rama nunca se ejecutaba en GPU. Al activarse salió a la luz que da por hecho el
modelo de CPU: allí monitor y CPU se arbitran sobre el mismo bus MMIO y la
lectura vale en marcha —que es justo cuando interesa mirar el underflow de una
demo que no para—, mientras que **el puerto host de la GPU rechaza toda
transacción mientras corre** (`if(!halted) begin host_ready<=1; host_error<=1;
end` en `gpu_system_bl8.v`). Comprobado en placa: con `halted=False` se rechaza,
parada funciona. Arreglado saltando la comprobación solo en ese caso.

## Fase 3.4 — Acceso de 32 bits del monitor al MMIO

Prerrequisito de los contadores de la fase 3.5, y arregla por el camino una
clase de fallo latente que hoy existe en las dos familias.

**El problema.** El host llega a los registros MMIO **byte a byte**: en CPU solo
con `READ_BYTE`/`WRITE_BYTE` —los bloques a MMIO los rechaza el monitor—, y
`x.tests/backends/fpga.py` tiene `_read_register`/`_write_register`, que son
cuatro idas y vueltas por serie. Entre la primera y la cuarta pasa del orden de
un milisegundo, así que **un registro que siga vivo puede leerse partido**.

No es hipotético. `fpga.py` lee `VIDEO_STATUS` (`0x8000000C`) así y saca
`frames = estado >> 16`, que es `frame_count` — y `frame_count` incrementa con
`fill_start && fill_first` **sin condicionar a `cpu_halted`**; el propio
`video_registers.v` dice que «avanza aunque la CPU esté parada». A 60 Hz el
acarreo del byte bajo al alto cae cada ~4,3 s y la ventana vulnerable es ~1 ms:
del orden de una lectura de cada cuatro mil, con síntoma de 256 frames de más.
No está observado, es un razonamiento sobre el código. El simétrico existe en
escritura: el host actualiza `FB_FRONT` byte a byte y el scanout de la 22 sigue
vivo durante la escritura (usa `reset`, no `core_reset`), así que puede leer una
base mezclada durante un frame.

**Por qué sale barato.** La palabra de 32 bits **ya existe** donde hace falta, en
las dos familias: `monitor_mem_adapter_128.v` recibe `input wire [31:0]
mmio_read_data` y tira tres bytes, y `gpu_system_bl8` calcula `mmio_data` entera
y selecciona un byte. Una transacción de bus ya produce la palabra completa, así
que `READ_WORD` sería **atómico de verdad**, no solo cómodo — el valor no puede
salir partido por construcción, sin depender de ninguna invariante.

- [x] **`READ_WORD` (`0x12` → `0x92`) en la familia GPU.** Comparte los estados de
      dirección y de espera con `READ_BYTE` mediante un flag `word_access`, igual
      que `block_is_write` para los bloques, así que no hace falta máquina nueva
      —quedaban además solo dos huecos en el `state` de 5 bits. El armazón de
      respuesta ya servía hasta 7 bytes y devolver 5 cabe.

      **Exige dirección alineada a 4.** La memoria entrega la palabra que
      *contiene* la dirección, así que una no alineada devolvería una palabra
      distinta de la pedida: mejor rechazarla que mentir.

- [ ] **`WRITE_WORD` queda FUERA de esta fase.** El puerto host escribe con
      `expanded_data={4{write_data}}` más un strobe de byte, así que una escritura
      de 32 bits real obliga a llevar máscara de bytes hasta el puerto aux y hasta
      la RAM, en las dos familias. Y solo evita el desgarro de *escritura*, que ya
      se evita escribiendo con el núcleo parado. El de *lectura* no tiene esa
      salida, porque `frame_count` avanza con el núcleo parado. Se añadirá cuando
      haya un motivo concreto.

- [x] **Salida de 32 bits AL LADO, no ensanchada.** Se empezó ensanchando
      `host_read_data` a `[31:0]`, que es más limpio sobre el papel. Al propagarlo
      apareció que **dieciocho bancos** lo declaran `wire [7:0]`: Verilog habría
      truncado **sin un aviso**, y esos bancos habrían seguido pasando mientras
      leían el byte 0 en vez del byte pedido. Con `host_read_word` aparte,
      `READ_BYTE` y los bloques no se tocan y ningún banco cambia.

- [x] `_read_register` de `fpga.py` usa `READ_WORD` donde lo hay.
      **Condicionado a la capacidad, no a la versión de monitor**, que es un
      cambio respecto a lo que decía este plan: la numeración **no es comparable
      entre familias** —la 6 va por 1.x y la 22 por 2.x— así que «versión ≥ N»
      no significa nada fuera de una carpeta. La capacidad `read_word` se
      detecta del RTL (patrón `CMD_READ_WORD` sobre `monitor.v`), igual que las
      demás. El camino de bytes se queda como respaldo, y un test comprueba que
      hoy ningún prototipo lo necesita.

      `_write_register` **no cambia**: `WRITE_WORD` sigue fuera de la fase.

- [x] **Al juego base y en todos los prototipos con MMIO.** Hecho en los diez
      que tienen juego de comandos: 6, 10, 16, 18, 19, 21, 12, 14, 17 y 22.

      **5, 8 y 9 quedan fuera, y no por pereza:** no son CPU ni GPU, son RAM sin
      MMIO. Allí `READ_WORD` ahorraría tres idas y vueltas pero **no sería
      atómico** —la garantía sólo existe donde hay un camino de 32 bits detrás—,
      así que daría un comando con el mismo nombre y otra promesa, que es peor
      que no tenerlo.

- [x] **`SYS_ID` en las cuatro GPU** (adelantado desde la fase 4a, ver allí).

**Verificado en placa** el 17/09/2026, sobre la 22 (`lsu2`, monitor 2.6):

- `SYS_ID` responde `0x4D47_0016` —`"MG"` y 22 en decimal—, `CONTRACT = 1`,
  `DEV_BITMAP = 0`, `ISA_PROFILE = 0x0b`. Leído con `READ_WORD`, así que las dos
  piezas se prueban a la vez.
- La suite completa de casos contra la placa: **28 casos, 0 fallos**.
- La síntesis de las cuatro GPU y las seis CPU pasa; la 12 queda en 35709
  TRELLIS_COMB / 9202 FF.

**Abrir el MMIO al monitor con el núcleo en marcha, igual en las dos familias.**
`READ_WORD` arregla que el valor salga entero; esto arregla que se pueda pedir
siquiera. Hacen falta las dos: de poco sirve una lectura atómica de
`VIDEO_STATUS` si para hacerla hay que parar la demo.

Va en dos casillas porque **las dos familias no están en el mismo punto**, y con
una sola se leía como pendiente en ambas:

- [x] **CPU: ya lo hace**, desde antes de este plan. No es un cambio a aplicar,
      es una propiedad que hay que *no romper* al unificar.
- [ ] **GPU: falta.** [`gpu_system_bl8.v`](../22.fpga-gpu-bl8/gpu_system_bl8.v)
      sigue rechazando en el puerto host con `if(!halted) begin host_ready<=1;
      host_error<=1; end`, antes de mirar a dónde iba la transacción.

      La regla que la CPU implementa hoy **no** es «el monitor solo puede con el
      núcleo parado», es **«MMIO siempre, RAM solo parada»**. En
      [`monitor_mem_adapter_128.v`](../21.fpga-cpu-hdmi-alu/monitor_mem_adapter_128.v)
      la rama `is_mmio` va *antes* de la comprobación de `cpu_halted`, y el
      rechazo por `!cpu_halted` cuelga solo del camino de SDRAM. Es deliberado y
      correcto: la RAM está detrás del búfer de combinación de escrituras y del
      controlador de ráfagas que la CPU está usando; los registros MMIO son
      registros y leerlos no molesta a nadie.

      Y el corte de la GPU es más bruto de lo necesario, porque el bloque MMIO
      de la 22 **ya sirve a dos amos**: el mux
      `gm_accept ? gm_addr : address` de `gpu_system_bl8.v` arbitra entre la GPU y
      el host, y existe porque `mmio_selftest.asm` necesita que la GPU lea sus
      propios contadores. La maquinaria de arbitrar ya está puesta; lo que falta
      es dejar de cortar en la puerta.

      Y hace falta de verdad, no solo por comodidad: **parar la GPU no congela
      `frame_count`**, porque el scanout cuelga de `reset` y no de `core_reset`.
      O sea que en la 22 hoy se juntan lo peor de las dos cosas —solo puedes leer
      parada, y estar parada no detiene el contador.

      Con esto el parche de `run_board.py` —saltarse la comprobación de underflow
      si el backend es GPU y está en marcha— **desaparece** en vez de quedarse
      como excepción permanente.

      Dos cosas que no conviene dar por sentadas:

      - **Solo lecturas.** Leer en marcha es inocuo; escribir `VIDEO_CTRL` o
        `FB_FRONT` mientras el kernel los toca es una carrera con el programa.
        Abrir lecturas y dejar las escrituras como están hasta tener un motivo.
      - **Prioridad, que hoy es asimétrica.** En la GPU `gm_accept` gana siempre:
        el núcleo tiene preferencia y el host espera. En la CPU se decidió lo
        contrario, y el comentario de [`top.v`](../19.fpga-cpu-hdmi-ls/top.v) de la
        19 lo razona: el monitor va primero para que un `SWAP` escrito desde el PC
        no se quede detrás de un programa que dibuja a toda velocidad. Al unificar
        hay que resolver esa diferencia a conciencia, no por omisión.

**La regla que queda escrita**, valga o no `READ_WORD`: *todo registro de 32 bits
que el host lea byte a byte tiene que estar congelado mientras el núcleo está
parado, o su valor puede salir partido.* Los contadores de rendimiento la cumplen
por diseño —avanzan solo con el núcleo corriendo, y §4 explica que eso es el
punto—; `frame_count` es la excepción conocida.

## Fase 3.5 — Alinear la CPU con el mismo contrato

Hasta aquí el contrato se aplicó moviendo **solo** la GPU, a propósito: así
ningún programa de CPU cambiaba. Esta fase va en la otra dirección y por eso
rompe binarios de CPU existentes; va después de que la 22 esté verificada en
placa.

Diferencias entre la implementación de CPU y el contrato, medidas en el RTL:

| | Contrato (§6) | CPU real (16/18/19/21) |
|---|---|---|
| `VIDEO_CTRL` `+0x18` | «solo GPU, por ahora» | **no existe**; el scanout está siempre encendido |
| Bases tras reset | no lo fija | `0x01000000`/`0x01025800` cableadas, iguales en los cuatro |
| Alineamiento de bases | 4 B en CPU, 16 B en GPU | 4 B, coincide |
| Contadores de rendimiento | slot `0x80000300` | **fuera del MMIO**: `cpu_cycles`/`cpu_instructions` en `top.v`, servidos por comandos `0x36`/`0x37` |
| Bloque de identificación | `0x80000F00` | no existe (fase 4) |

- [ ] **Añadir `VIDEO_CTRL` a la CPU** con el modo tras reset acordado. Es el
      cambio que habilita todo lo demás: sin control de modo no se puede arrancar
      sin scanout.
- [ ] **Mover los contadores de CPU al MMIO `0x80000300`.** Hoy `cpu_cycles` y
      `cpu_instructions` son dos registros en [`top.v`](../21.fpga-cpu-hdmi-alu/top.v)
      cableados a `monitor.v`, y **solo los lee el host**: para saber cuántos
      ciclos tardó un bucle hay que parar la CPU y preguntar por serie. En MMIO,
      el programa se mide a sí mismo, que es el argumento que §4 ya hace para la
      GPU.

      Encaja sin inventar nada: en la GPU `+0x00` es `CYCLES` y `+0x04` es
      `RETIRED`, justo los dos que tiene la CPU, así que el bloque de CPU es un
      **prefijo** del de GPU. §6 ya reserva el slot como «GPU, ampliable a CPU»,
      y `mmio_decoder.v` reserva los slots 3..15, así que añadir
      `DEV_PERF = 4'd3` son tres líneas.

      Dos cosas a reconciliar: la CPU **satura** (`cpu_cycles != 32'hffff_ffff`)
      y la GPU **da la vuelta** — y a 80 MHz, 2³² ciclos son **53 segundos**, así
      que un programa de un minuto satura el contador de CPU y deja de medir
      nada; unificar en dar la vuelta, que hace correctas las diferencias. Y
      escribir es fault en GPU e ignorado en CPU, misma decisión que la fase 4a.

      Aviso: leer `CYCLES` con un `LOAD` cuesta ciclos y retira una instrucción,
      y en la 21 además drena el búfer de escrituras, así que el programa
      perturba su propia medida. Se mide por deltas y se asume el sesgo; la GPU
      ya vive con eso.
- [ ] **Retirar `GET_CYCLES` (`0x36`) y `GET_INSTRUCTIONS` (`0x37`).** Con los
      contadores en MMIO se quedan sin razón de ser, y con ellos desaparece el
      juego «+contadores» entero: de tres juegos de comandos (12, 14 y 16) se
      pasa a dos, y ninguno es ya «el que tiene contadores», porque los contadores
      pasan a ser un dispositivo como los demás. Es el objetivo de la fase 5
      alcanzado por el camino de simplificar el bus en vez de por el de renumerar
      versiones.
- [ ] **Unificar las bases de reset en `0` / `0`.** Arrancar sin scanout elimina
      la única ventaja del valor cableado —que un programa funcionase sin
      configurar nada—, porque ahora tiene que escribir `VIDEO_CTRL` de todas
      formas. Y `0x01000000` no es válido en todos los mapas: en la 12, con
      128 KiB de EBR, esa dirección está fuera. Además [`mapa-de-memoria.md`](mapa-de-memoria.md)
      §2 ya dice que esas bases «no son reservas impuestas a todos los
      programas», cosa que cableadas en el reset sí son.

      **Es el punto de mayor alcance de todo el plan.** `0x01000000`/`0x01025800`
      aparecen en **34 ficheros** de diez carpetas. Se dividen en dos grupos y
      conviene no confundirlos:

      - **El valor de reset**, que tiene que cambiar: el parámetro
        `FB_FRONT_RESET`/`FB_BACK_RESET` en los cuatro `video_registers.v`, sus
        testbenches (`video_registers_tb`, `cpu_video_tb`, `subword_ls_tb`…), las
        constantes `FB_FRONT_RESET`/`FB_BACK_RESET` de
        `x.tests/backends/fpga.py`, y los valores por defecto de `VideoDevice` en
        `2.cpu-sim-func/minicpu_sim.py`. Son **tres copias independientes** del
        mismo dato —RTL, arnés de pruebas y simulador— y hay que moverlas juntas.
      - **La dirección elegida por un programa**, que puede quedarse: los
        `examples/`, `tools/make-framebuffer`, `20.forth` y los README siguen
        pudiendo poner su framebuffer en `0x01000000`. Lo que cambia es que ahora
        tienen que **escribirlo**, en vez de heredarlo del reset.

      El simulador ya usa los offsets del contrato (`FB_FRONT=0x00` …
      `HALT_AT=0x14`), así que ahí solo hay que tocar los valores por defecto y
      añadir `VIDEO_CTRL`.
- [x] **Estado de reset: `PATTERN`.** No hacía falta decidirlo: ya está resuelto
      en [`22.fpga-gpu-bl8/video-scanout.md`](../22.fpga-gpu-bl8/video-scanout.md),
      sección «Valor de reset: `PATTERN`, en todos los cores, sin parámetro»,
      que además cuenta que se planteó como parámetro con `SCANOUT` por defecto
      y se descartó por «escaquearse de la decisión».

      El criterio: *elegir el valor por defecto cuyo modo de fallo se explica
      solo*. Con `SCANOUT`, ver basura no dice si falla HDMI, el PLL, el cable,
      `fb_base` o el programa. Con `PATTERN`, verlo demuestra que la cadena hasta
      el monitor funciona y no verlo señala aguas arriba. `PATTERN` no es
      scanout: no lee SDRAM y no muestra basura, así que cumple «sin salida hasta
      que alguien la active» sin perder el diagnóstico.

      Ese documento ya evaluó el coste de migrar: las demos de 21 **ya** cargan
      la base del MMIO en un registro (`MOVHI R20, 0x8000`), así que encender el
      scanout es *un `STORE` más* en cada inicialización.
- [ ] Actualizar los programas de vídeo de CPU, que hoy dan por hechas las bases
      cableadas y el scanout siempre encendido: `swap_demo`, `tear_demo`,
      `bounce`, `band` y `examples/` de 16, 18, 19 y 21.
- [ ] **Ensanchar la ventana de la 16**, o aceptar que queda fuera del contrato.
      Decodifica `address[31:4]`, o sea 16 bytes: `+0x14` y `+0x18` caen fuera
      del MMIO y van a SDRAM. No leen cero, leen memoria. La 18 (`address[31:5]`,
      32 B) llega justo a `+0x18`; 19 y 21 tienen el slot de 256 B y no necesitan
      nada.

## Fase 4 — Descubrimiento en tiempo de ejecución

Va **después** de fijar los slots: hasta aquí el bitmap describiría un mapa a
punto de cambiar. Se parte en dos porque el coste de las dos mitades no se
parece: 4a son constantes escritas a mano y 4b necesita maquinaria nueva.

El bloque vive en `0x80000F00` y son cuatro palabras:

| Offset | Registro | Contenido | Fase |
|---|---|---|---|
| `+0x00` | `SYS_ID` | Magic + número de carpeta. Cero = prototipo antiguo | 4a |
| `+0x04` | `CONTRACT` | Versión del contrato de mapa de memoria | 4a |
| `+0x08` | `DEV_BITMAP` | Un bit por dispositivo presente | 4b |
| `+0x0C` | `ISA_PROFILE` | Perfil de ISA | 4a |

`CONTRACT` es **distinto** de la versión de monitor: el contrato de direcciones
cambia por otras razones y a otro ritmo, y mezclarlos reproduce el lío de los
diez números para cuatro juegos de comandos (§6.5).

### Fase 4a — `SYS_ID`, `CONTRACT` e `ISA_PROFILE`

Son constantes de solo lectura. Sin generador y sin registro central.

**Formato de `SYS_ID`: el número de la carpeta, con magic en la parte alta.**

```verilog
SYS_ID = {16'h4D47, 8'd0, 8'd22};  // 0x4D470016 en 22.fpga-gpu-bl8
//        magic      libre  carpeta
```

El número de carpeta ya existe, ya es único y ya lo resuelve
`resolve_prototype`, así que no hay nada que registrar al añadir un prototipo
—que es justo lo que `AGENTS.md` presume del repo— y no se puede olvidar ni
duplicar porque lo impone el nombre del directorio.

El magic no es adorno: sin él, el valor 0 sería ambiguo entre «prototipo
antiguo» y «prototipo 0», y `0.mandelbrot` existe. Y el byte libre se queda
**sin usar** a propósito: CPU-vs-GPU ya lo deriva `backend_from_rtl`, y las
capacidades son trabajo de `DEV_BITMAP` e `ISA_PROFILE`. `SYS_ID` es identidad
pura y así no se solapa con nadie.

Límite conocido: identifica **el prototipo**, no **el bitstream**. Dos síntesis
de la misma carpeta con parámetros distintos responden lo mismo, y `13.hdmi` no
encaja (no es un prototipo, es una prueba multi-entorno). Para el caso que duele
hoy —14, 17 y 22 respondiendo todas monitor 2.4 siendo hardware distinto— basta.

- [ ] **Decidir la política de dirección inexistente.** Hoy CPU lee cero y GPU
      levanta `bad`. El truco de compatibilidad —"leer cero en `0x80000F00` ya
      significa prototipo antiguo"— solo funciona donde una dirección vacía lee
      cero. Recomendación: **unificar solo dentro del slot de identificación** y
      mantener `bad` en el resto de la página, para no apagar el diagnóstico que
      convierte un error de programa GPU en un error visible del host. Es lo
      mismo que ya se hizo con `HALT_AT` en la 22 (fase 3).
- [x] **`sysid.v` escrito**, copia idéntica en las cuatro GPU, con `FOLDER`,
      `CONTRACT` e `ISA_PROFILE` por parámetro. `CONTRACT` = 1. `DEV_BITMAP` lee
      cero, que con `CONTRACT` = 1 significa «sin declarar» y no «ningún
      dispositivo».

      **`ISA_PROFILE`**: bit 0 `MUL`, bit 1 `DIV`, bit 2 subword, bit 3 SIMT. Las
      cuatro GPU dan `0x0b`. Lo que de verdad discrimina está en la familia CPU
      —a la 10 le faltan `MUL` y `DIV`— así que dentro de la GPU el campo no
      distingue nada; se declara para que el bloque signifique lo mismo en las dos
      familias.

      **Escrito a mano pero contrastado, no generado.** Un fichero generado se
      desincroniza en silencio si alguien toca el RTL y no regenera; un test que
      compara falla a gritos. Hay tres: `FOLDER` contra el nombre del directorio,
      `ISA_PROFILE` derivado del RTL, y `sysid.v` copia idéntica. Ojo con dónde
      vive cada rasgo: `SSY`/`BAR`/`EXIT` se decodifican en `gpu_sm.v` y **no** en
      `gpu_lane.v`.
- [x] Enganchado en 12, 14, 17 (una rama en `gpu_system.v`) y en la 22 en **dos**
      decodificadores (`gpu_system.v` y `gpu_system_bl8.v`). Hizo falta además una
      **quinta ranura de ventana** en `monitor.v`: la 22 ya usaba las cuatro.
      Es host-only, como los registros de depuración: un kernel no lo alcanza.

      **Comprobado en placa** el 17/09/2026 sobre la 22: `0x80000F00` responde
      `0x4D47_0016`, y los otros tres `1`, `0` y `0x0b`. Leído con `READ_WORD`.
- [x] Enganchado en 16, 18, 19 y 21, con `DEV_SYSID = 4'd15` en `mmio_decoder.v`
      —el **último** slot, no el primero libre, para que los dispositivos de
      verdad crezcan hacia arriba sin tropezárselo—. `FOLDER` e `ISA_PROFILE`
      van por parámetro desde cada `top.v`, así que `mmio_decoder.v` sigue
      siendo copia idéntica en las cuatro.

      En 16 y 18 hubo que **ensanchar la ventana** primero: eran de 16 y 32
      bytes y no llegaban a `0x80000F00` ni de lejos. Ensanchar **abarata** el
      prefijo (16 pasa de comparar 28 bits a 20; 18, de 27 a 20) y lo que se
      paga es un nivel de LUT en el mux de lectura, que crece con los
      dispositivos que *existen* y no con el tamaño del mapa.

      **`ISA_PROFILE` en CPU no se puede derivar con la regla de la GPU.** El
      patrón `OPCODE_SSY` ahora casa en las seis CPU, pero **como no-op**: se
      añadieron para compartir binarios con la GPU y no hay pila de
      reconvergencia detrás. Encender el bit 3 diría al host que el núcleo
      diverge y reconverge, que es falso. En CPU el bit 3 es cero siempre.
      Valores: 16 y 18 `0x03`; 19 y 21 `0x07`.

- [ ] 2 y 11: un `SysIdDevice` en Python al lado de `VideoDevice`/`SerialDevice`.
      Vale la pena: deja que un programa sepa que corre en simulador.

#### Por qué 6 y 10 se quedan fuera — **decisión provisional, a revisar**

No es un olvido, pero tampoco es una decisión firme: se toma para no abrir otro
frente a mitad de esta ronda, y **conviene volver a ella cuando lo demás esté
cerrado**.

Los tres datos que la sostienen hoy:

1. **Ninguno de los dos tiene ventana MMIO.** No es que les falte un
   dispositivo: es que no existe el concepto en su RTL. En el 6,
   [`memory_map.v`](../6.fpga-cpu/memory_map.v) tiene un solo eje —qué banco y
   qué peticionario— y todo lo que cae fuera de `address[31:15]==0` es error;
   añadir MMIO mete un segundo eje, *«¿esto es memoria siquiera?»*, en los tres
   caminos. En el 10 es más caro todavía: su `sdram_system_adapter.v` son 293
   líneas y el de la 16, que sí lo tiene, 477 — buena parte de esas 184 de
   diferencia **es justo el camino MMIO**.

2. **En la familia CPU la versión de monitor ya identifica la carpeta.** Son
   1.17, 1.18, 1.19, 1.20, 1.21 y 1.16: todas distintas. La ambigüedad que hizo
   nacer `SYS_ID` —14, 17 y 22 contestando las tres 2.4— es un problema de la
   GPU. En 6 y 10, `SYS_ID` aportaría **uniformidad, no capacidad**.

3. **El coste didáctico apunta en contra.** El 6 es el prototipo por el que se
   entra. Meterle MMIO allí presenta la entrada/salida mapeada en memoria **sin
   nada que mapear**, porque `SYS_ID` son cuatro constantes de sólo lectura. El
   concepto llega solo en la 16, empujado por el vídeo, que es cuando de verdad
   hace falta.

El argumento **en contra** de esta decisión, que es real y por eso queda
escrito: con `SYS_ID` en todas, ninguna herramienta necesita un caso especial.
Lo que lo debilita hoy es que el caso especial no desaparecería igualmente —5, 8
y 9 seguirían fuera—, así que se pagaría un concepto en el prototipo didáctico a
cambio de *reducir* la excepción, no de eliminarla.

**La regla que se escribe, para que la omisión sea defendible y comprobable:**
*`SYS_ID` es obligatorio en toda carpeta que tenga ventana MMIO.* Así el test de
abajo tiene un criterio que exigir, y el 6 no queda como un descuido sino como
un prototipo que aún no tiene dispositivos. El día que tenga uno de verdad,
`SYS_ID` entra con él y el concepto llega motivado.

#### Vuelta a la lista

- [x] **Test de que `SYS_ID` coincide con el número de carpeta**, hecho para la
      familia GPU. Falta extenderlo para que *exija* el bloque en toda carpeta con
      ventana MMIO, que es lo que hace que «obligatorio» signifique algo dentro de
      seis meses.

- [x] **Arreglado un fallo que salió por el camino**, y que conviene no repetir.
      Al parametrizar `monitor.v` (fase 3 bis), `VERSION_MAJOR`/`MINOR` pasaron de
      ser *el valor* a ser el valor **por defecto**: el real lo pone el `top.v`.
      `monitor_version_from_rtl` seguía leyendo el localparam, así que las cuatro
      GPU reportaban 2.4 cuando eran 2.5, 2.6, 2.6 y 2.6, y ninguna suite lo
      detectó porque nada contrastaba ese dato. Al arreglarlo apareció un segundo:
      leyendo la instanciación cogía la del **banco de pruebas**, que va antes que
      `top.v` por orden alfabético y no es lo que se sintetiza. Ahora se excluyen
      los `*_tb.v` y el test de coherencia entre instancias cubre también los
      parámetros de versión.

      La lección general: **al mover un dato de sitio hay que mirar quién lo
      leía**. `AGENTS.md` dice que la identidad se lee del RTL, y eso convierte
      cualquier refactor de `monitor.v` en un cambio de interfaz para `rtl_facts`.
- [ ] Añadir a `AGENTS.md` que un prototipo con ventana MMIO expone el bloque.
- [ ] Actualizar la tabla de conformidad de `mapa-de-memoria.md` §6.

**Decisión abierta: 6 y 10.** No tienen ventana MMIO en absoluto, así que darles
`SYS_ID` significa inventarles una entera para meter dentro cuatro constantes. A
favor: son justo los que más falta hace distinguir, porque a la 10 le faltan
`MUL`/`DIV` y eso no se detecta de ninguna otra forma en ejecución — un
`ISA_PROFILE` ahí vale más que en la 21. En contra: son carpetas históricas y
estables, y tocarlas por algo que nada consume todavía se arrepiente uno. Por eso
la regla se escribe como **«un prototipo con ventana MMIO expone el bloque»**: no
bloquea a los otros ocho.

### Fase 4b — `DEV_BITMAP`

- [ ] **Generarlo desde `capabilities.json`** (fase 0), no a mano: escrito a mano
      en cada `monitor.v` sería una tercera gemela que mantener junto a la lista
      blanca y `MONITOR_REGIONS`, justo lo que §6.5 quiere quitar.
- [ ] Hace falta maquinaria que **no existe**: hay `.vh` generados, pero solo de
      fixtures de simulación, y `generate-docs` solo toca Markdown. No hay
      precedente de Verilog **sintetizable** generado ni de un test que compruebe
      que lo generado está al día.
- [ ] `capabilities.json` no tiene números de bit. Hay que añadirlos y
      comprometerse a no reutilizarlos nunca.
- [ ] Hacerlo **a la vez que la fase 5**: la unificación de los `monitor.v`
      quiere derivar la lista blanca de la misma tabla. Por separado se construye
      el generador dos veces.

## Fase 5 — Consecuencias sobre el monitor

Orden tomado de §6.5. Hacerlo antes obliga a tocar el monitor dos veces.

Las fases 3.4 y 3.5 **ya hacen la mitad del trabajo de esta**, y por el camino
bueno: 3.4 mete `READ_WORD`/`WRITE_WORD` en el juego base, y 3.5 retira
`GET_CYCLES`/`GET_INSTRUCTIONS` al pasar los contadores a MMIO. Resultado: los
tres juegos de comandos de hoy (12, 14 y 16) quedan en **dos** —base y
base+serie—, y ninguno es ya «el que tiene contadores». Lo que aquí queda es
renumerar y unificar, no rediseñar.

- [ ] **Renumerar las versiones de monitor por juego de comandos**: de diez
      valores (1.15–1.20, 2.3–2.4) a los que queden tras 3.4 y 3.5. Hoy 6, 10 y
      16 tienen el mismo juego y llevan 1.16/1.17/1.18; 19 y 21 tienen el mismo
      juego y llevan 1.20 y 1.15. Y 14, 17 y 22 responden todos 2.4 siendo
      hardware distinto, con la consecuencia de que `--version sdram` pasa contra
      una 22 flasheada y se miden prestaciones del hardware equivocado.
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
