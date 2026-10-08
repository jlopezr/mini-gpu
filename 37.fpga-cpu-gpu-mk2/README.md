# mk2: la 36 con más margen en el controlador y el hito 2 de GPU CORE

Copia de `36.fpga-cpu-gpu` (8 de octubre de 2026, el commit en que la 36 cumple
timing) para poder cambiar sin tocar una carpeta que ya cierra. Alias del
prototipo: `mk2`. Identificación de placa: monitor `5.37`.

## Qué es la 37 y qué se hace aquí

1. **Base.** RTL idéntico al de la 36, salvo el número de carpeta (`sysid_params.vh`)
   y la versión del monitor. Eso basta para cambiar el netlist: **la semilla de la
   36 no vale aquí** y hay que barrer de nuevo antes de fiarse de ningún número.
2. **Margen en el controlador SDRAM.** En la 36, `sdram_clk` cerró con +2,0 %;
   `timing-wall` ve 64 destinos por encima del 90 % del periodo.
3. **Hito 2 de GPU CORE**, en commits pequeños: `WARP_START`, `RESET` que conserva
   los descriptores, descriptores con la GPU en marcha, `WARP_LIVE` y `WARP_DONE`
   completos, registros de identidad. Más de ocho warps, solo si hace falta.
4. **Las instrucciones de la CPU que le faltaban a la GPU**: `SLT`, `SLTU`, `MULHI`,
   `DIVU`, `REM`, `REMU`, `JAL`, `JALR` y `JR` (hecho; ver «La GPU»).

Mientras no se diga otra cosa abajo, **lo que sigue describe la 36**, de la que
parte esta carpeta; los números de timing y de placa son los de la 36, no
medidos aquí.

# CPU que lanza una GPU de 8 carriles por MMIO, sobre el fabric FIFO de seis puertos

Prototipo derivado de `35.fpga-cpu-fifo-sdram2` (CPU, vídeo, monitor y SDRAM de
cuatro bancos en paralelo) y del núcleo de GPU de `29.fpga-gpu-sm-pipeline`. La
CPU de 80 MHz carga un kernel en la RAM compartida, configura los warps y arranca
la GPU escribiendo registros MMIO; la GPU, en su propio reloj, lee y escribe esa
misma RAM por dos puertos del fabric. Es el **hito 1** del plan de integración:
lo mínimo para que la CPU lance un kernel y espere a que acabe.

## Quién es quién

| Bloque | Reloj | Qué es |
|---|---|---|
| CPU, monitor, bus MMIO, vídeo (registros y consola) | `clk` 80 MHz | como en la 35 |
| SDRAM, fabric, controlador | `sdram_clk` 100 MHz | como en la 35 |
| GPU (`gpu_system`) | `clk_25mhz` 25 MHz | el oscilador de la placa, sin PLL |
| Píxel y TMDS | 25 MHz y 125 MHz | como en la 35 |

Puertos del fabric:

| Puerto | Master |
|---|---|
| 0 | datos de la CPU |
| 1 | instrucciones de la CPU |
| 2 | vídeo (scanout, urgente) |
| 3 | monitor |
| 4 | GPU: LSU vectorial (datos) |
| 5 | GPU: búsqueda de instrucciones |

Los puertos 4 y 5 cruzan del reloj de la GPU al de memoria con un puente
asíncrono cada uno (`fabric_fifo_bridge.v`), como los demás masters.

## La GPU

`gpu_sm.v` es el SM de la 29: 8 carriles, 8 warps, reconvergencia con pila SIMT,
barreras. Dos cambios respecto a la 29, ambos por area y por correctitud:

- **El sumador de direcciones es uno por carril.** `d_rf_a + {8{d_immediate}}`
  era un único sumador de 256 bits, y con un desplazamiento negativo el acarreo
  de un carril contaminaba al siguiente. Está arreglado también en la 29; el
  caso `x.tests/cases-gpu/memory/negative-offset` lo cubre.
- **Menos lógica de selección.** Comparadores de grupo (`same_group`) calculados
  una vez por pareja, `generation` de 1 bit, detección de reconvergencia por
  warp y elección del siguiente warp con una máscara de elegibilidad rotada:
  11.189 LUT4 en el SM contra 13.502 antes.

`gpu_system.v` envuelve el SM sin su fabric ni su vídeo y añade el bloque
**GPU CORE** (`mmio.md` §14.1): `GPU_CONTROL`, `GPU_STATUS`, `WARP_LIVE` y
`WARP_DONE`. La LSU y el buffer de instrucciones salen como los puertos 4 y 5.

### Instrucciones de la CPU en la GPU (37)

La lane ejecuta ahora lo mismo que la CPU: `SLT` y `SLTU` (reutilizan la resta y el
estado de comparación de los saltos), `MULHI` (el camino de `MULFX` con otra
ventana de salida), `DIVU`, `REM` y `REMU` (el camino de `DIV`, con operandos
crudos o con el resto como resultado) y `JAL`, `JALR` y `JR`. Un salto indirecto
sale de un registro por lane, así que el SM exige que **todas las lanes activas
coincidan**: si no, para con `ERROR_SIMT` (0x06) en lugar de serializar.
Bancos: `gpu_alu_tb.v` y `gpu_jump_tb.v`.

### Hito 2 de GPU CORE (37)

Las reglas están en `mmio.md` §14.1, «Reglas de lanzamiento». En el RTL:

- El SM guarda el **descriptor** de cada warp (`desc_pc`, `desc_active`,
  `desc_groups`) aparte de su estado de ejecución. `RUN` y `WARP_START` copian
  uno al otro (`launch`), así que leer un descriptor devuelve siempre lo escrito.
- `RESET` es un reset blando: descarta el estado de ejecución y conserva los
  descriptores, `LOGICAL_WARP_ID` y `WARP_ARG`. Solo el reset del sistema los borra.
- Un descriptor se escribe mientras **su** warp no esté vivo; con otros warps
  ejecutando es válido. `WARP_START` es todo o nada.
- Configurar ya no hace vivo a un warp: `WARP_LIVE` solo cambia al lanzarlo.
  Por eso, para depurar con `STEP`, se hace `HALT`, `WARP_START` y `STEP`.

Costo estimado: unos 70 FF por warp (los tres descriptores) y su mux de lectura.
Bancos: `gpu_core_tb.v` (siete bloques) y el caso `cases-cpu/gpu/launch-start`.

### Limitaciones

- La GPU **no es maestro de MMIO**: un warp que toque una dirección MMIO recibe
  error. La única ruta de MMIO va de la CPU a la GPU.
- Más de ocho warps no; `NUM_WARPS` aún no es un parámetro.
- No hay vídeo propio de la GPU: el único bloque VIDEO es el de la CPU. Tampoco
  hay todavía un registro de «ha terminado la parte gráfica» (`wait_graphics`),
  que dependerá del rasterizador.

## El bus MMIO

Todo el espacio MMIO empieza en `0x8000_0000` (`1.isa/mmio.md` v2). La CPU llega
por `cpu_dmem_adapter`, que vacía el buffer de escrituras antes de cualquier
acceso MMIO para conservar el orden. El monitor llega por su propio adaptador.
`mmio_mux` atiende a uno cada vez (el monitor primero) y `mmio_decoder` reparte
por bloque:

| Bloque | Dirección | Dispositivo |
|---|---|---|
| SYSTEM | `0x8000_0000` | identificación, memoria, versión |
| SERIAL | `0x8010_0000` | puerto serie del programa |
| VIDEO | `0x8020_0000` | registros de vídeo y consola de texto |
| INPUT | `0x8060_0000` | teclado y ratón (llegan del PC por el monitor) |
| CPU PERF | `0x8101_0000` | ocho contadores de rendimiento |
| GPU | `0x8200_0000..0x8203_FFFF` | CORE, WARPS, SIMT y PERF de la GPU |

El bus está segmentado en tres etapas (registro de la decodificación, registro de
la salida de cada dispositivo, mux de lectura) y un acceso tarda **4 ciclos**.
`mmio_mux` espera `EXTRA_CYCLES = 3`; el decodificador y el mux tienen que
cambiar a la vez. Los registros de la GPU viven en otro reloj, y `gpu_mmio_bridge`
los cruza con petición y confirmación por cambio de nivel, un acceso en vuelo:
`mmio_mux` espera su `done` con dirección, dato y tipo retenidos.

`mmio_bus_tb.v` monta mux, decodificador y todos los dispositivos con una GPU
simulada y comprueba 96 accesos (`sim/mmio_bus_expected.hex`).
`gpu_mmio_bridge_tb.v` ejercita el puente con 80 y 25 MHz sin relación de fase.

## La memoria

Es la de la 35: slot por banco con temporización independiente, página cerrada,
`ACTIVE` adelantados y `READ`/`WRITE` en orden de llegada. Ver el README de la 35
para el detalle y las cifras (8,19 ciclos por petición alternando bancos, 12,32 en
el mismo banco). Lo que cambia en la 36 es solo de timing:

- el candidato de `ACTIVE` se elige en paralelo por banco, con selección one-hot,
  en vez de una cadena de prioridad;
- el árbitro del fabric calcula la ronda con una función sin bucles;
- `issue_go` solo limpia `issue_valid` y el empuje a la cola `meta` y a los
  créditos ocurre un ciclo después (`go_q`).

## Timing

Síntesis con `-nowidelut` (quita `PFUMX` y `L6MUX21`: −11 % de LUT4) y nextpnr
**sin** `--tmg-ripup`, con `--placer-heap-timingweight 120` y semilla 7. Con
`--tmg-ripup`, `router1` repite el enrutado en rondas y no terminaba (2,5 h).

Build del 8 de octubre de 2026 (`reset-mem-copies`, 41 minutos de rutado):

| Reloj | Alcanzado | Exigido | Margen |
|---|---:|---:|---:|
| `sdram_clk` | 102,0 | 100 | +2,0 % |
| CPU `clk` | 83,9 | 80 | +4,9 % |
| `clk_pix_5x` | 174,2 | 125 | +39 % |
| `clk_25mhz` (GPU) | 35,6 | 25 | +42 % |
| `clk_pix` | 54,4 | 25 | +118 % |

Ocupación: 52.846 de 83.640 `TRELLIS_COMB` (63 %), 24.131 FF, 26 de 208 EBR y
38 de 156 multiplicadores.

Lo que hizo falta, en el orden en que apareció cada muro:

1. **Monitor.** La validación del bloque (rango, longitud) se calcula en un estado
   propio y se guarda en `block_ok`.
2. **Controlador y fabric.** Lo de arriba: selección de `ACTIVE` en paralelo,
   árbitro sin bucles, `go_q`.
3. **Consola de texto.** El sumador de `FONT_COUNT` ya no cuelga del enable de la
   RAM de fuente.
4. **`video_registers`.** Cada registro comprueba su propia condición de escritura
   y no el `error` global.
5. **Bus MMIO.** Etapa de lectura por dispositivo (arriba).
6. **Reset.** Un único `reset` llegaba a todo el chip: 8,5 ns de ruteo en el
   camino de la CPU y 7,7 ns en el de `sdram_clk`. Hay copias registradas por
   bloque (`reset_mon`, `reset_cpu`, `reset_bus`, `reset_vid`; `reset_ctl` y
   `reset_fab` en el lado de memoria), con `keep` para que no se fusionen.

El margen de `sdram_clk` es fino. **La semilla vale para un netlist concreto:**
cualquier cambio de RTL, incluso un comentario en un `.v` o en el `apio.ini`,
deja el bitstream en STALE y obliga a re-barrer
(`build-sweep --promote`, ver `tools/README.md`).

## Validación

- `mmio_bus_tb.v` y `gpu_mmio_bridge_tb.v`, arriba.
- `gpu_system_tb.v` y `gpu_barrier_tb.v`: el sistema GPU y la barrera con su RAM
  simulada. La barrera es un test propio de la 36.
- `sdram_bank_parallel_tb.v`, `sdram_controller_128_tb.v` y
  `memory_fabric_fifo_6_tb.v`: como en la 35.
- `x.tests/cases-cpu/gpu/launch-run` (capacidad `gpu_core`): la CPU lanza un
  kernel y comprueba los registros al terminar.

## Placa

**Todavía no probado en placa.** El bitstream cumple timing (8 de octubre de
2026) y la simulación pasa. Falta cargarlo, correr `launch-run` y la regresión de
la CPU, para confirmar que el bus MMIO con una etapa más no ha cambiado nada
visible.

## Pendiente

- Probar en placa (`board-upload`, `test-board`).
- **Tiempo máximo en `mmio_mux`** para el acceso a la GPU: si la GPU no contesta,
  el bus MMIO se queda esperando (y con él el monitor).
- Un registro de fin de la parte gráfica (`wait_graphics`), cuando exista el
  rasterizador, y los registros de identidad del hito 2.
- Reutilizar filas abiertas (página abierta), como en la 35.
