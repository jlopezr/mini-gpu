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

Una cosa sigue abierta, y se movió fuera de la fase 0 porque no es un ajuste
del runner sino un caso de prueba que escribir:

- [ ] **Un caso de prueba de vídeo compartido entre familias.** Que `video` valga
      para las dos permite a un caso GPU *requerirlo*, pero no hace que un mismo
      `test.json` corra en 21 y 22: [`run_tests.py:576`](../x.tests/run_tests.py#L576)
      exige `warp_config` en los casos GPU y lo prohíbe en los de CPU, y
      `validate_compatibility` pide que la arquitectura del caso sea exactamente
      la del backend.

      Pero el obstáculo de fondo no es ese código: **un caso CPU y uno GPU no son
      el mismo programa**, porque el de GPU reparte trabajo con `GETTID` entre 64
      hilos y usa `SSY`/`BAR`. Compartir el caso solo tiene sentido para un
      programa de **un solo hilo** — escribir `FB_FRONT`/`FB_BACK`, pedir `SWAP`,
      sondear el bit 1 de `STATUS`, comprobar `SWAP_COUNT`. Eso es literalmente
      idéntico en las dos familias desde la fase 3, y sería la prueba de que el
      contrato funciona.

      Va **después de verificar en placa**: escribir un test de conformidad sobre
      un mapa que todavía no ha corrido en hardware es construir sobre arena.

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
| Contadores de rendimiento | slot `0x80000300` | no existe |
| Bloque de identificación | `0x80000F00` | no existe (fase 4) |

- [ ] **Añadir `VIDEO_CTRL` a la CPU** con el modo tras reset acordado. Es el
      cambio que habilita todo lo demás: sin control de modo no se puede arrancar
      sin scanout.
- [ ] **Unificar las bases de reset en `0` / `0`.** Arrancar sin scanout elimina
      la única ventaja del valor cableado —que un programa funcionase sin
      configurar nada—, porque ahora tiene que escribir `VIDEO_CTRL` de todas
      formas. Y `0x01000000` no es válido en todos los mapas: en la 12, con
      128 KiB de EBR, esa dirección está fuera. Además [`mapa-de-memoria.md`](mapa-de-memoria.md)
      §2 ya dice que esas bases «no son reservas impuestas a todos los
      programas», cosa que cableadas en el reset sí son.
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
- [ ] Escribir `sysid.v`: cuatro constantes, ~25 líneas, igual para todos.
- [ ] Engancharlo a cada decodificador:
      - 19, 21: un `DEV_SYSID = 4'd15` en `mmio_decoder.v`, ~3 líneas.
      - 12, 14, 17: una rama `sysid_region` en `gpu_system.v`, ~6 líneas.
      - 22: lo mismo en **dos** decodificadores (`gpu_system.v` y
        `gpu_system_bl8.v`).
      - 16, 18: portar `mmio_decoder.v` y ensanchar el comparador del adaptador.
        **Ensanchar la ventana abarata el prefijo** (de `address[31:5]`, 27 bits,
        a `address[31:12]`, 20) y un dispositivo inexistente ya lee cero — el
        propio `mmio_decoder.v` lo documenta. Sin esto, 16 y 18 no llegan a
        `0x80000F00`: sus ventanas son de 16 y 32 bytes.
      - 2, 11: un `SysIdDevice` en Python al lado de `VideoDevice`/`SerialDevice`.
        Vale la pena: deja que un programa sepa que corre en simulador.
- [ ] **Un test que recorra las carpetas con MMIO** y falle si a alguna le falta
      el bloque o si su `SYS_ID` no coincide con el número de carpeta. Es lo que
      hace que «obligatorio» signifique algo dentro de seis meses, y con el ID
      derivado del nombre son cuatro líneas de Python.
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
