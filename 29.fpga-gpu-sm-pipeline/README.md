# Segmentación del cauce del SM

Prototipo en construcción. Parte de `22.fpga-gpu-bl8` tal cual (mismo
`gpu_lsu2.v` y `gpu_lane.v` —que después se extendieron, ver más abajo—,
`gpu_imem_buffer.v`, `instruction_buffer.v`,
`gpu_register_file.v`, `gpu_perf_counters.v`, `gpu_video_regs.v`,
`gpu_aux_adapter_128.v`, `memory_fabric_4.v`, `sdram_controller_128.v` — sin
tocar) y reescribe **solo `gpu_sm.v`**: sustituye la FSM monolítica de 11
estados por instrucción (17,6 ciclos/instrucción medidos en la 22, 94% de las
lanes ociosas) por un cauce segmentado de 6 etapas con registro
**S → F → I → D → X → W**, una instrucción en vuelo por warp, sin bypasses de
registros ni de PC.

El diseño está redactado en [`sm-pipeline.md`](../22.fpga-gpu-bl8/sm-pipeline.md) (heredado de la
22, donde se escribió antes de implementarlo). La especificación ejecutable de
esta misma microarquitectura — mismo nombre de etapas, mismo contrato de una
instrucción por warp, misma prioridad fija W>LSU en el puerto de escritura del
banco de registros — es el simulador de ciclos en
[`25.gpu-sim-cycle-uarch`](../25.gpu-sim-cycle-uarch): su `DESIGN.md` documenta
el contrato ciclo a ciclo y sus tests dan la lista de invariantes que este RTL
debe reproducir.

`gpu_lane.v` (la unidad X) conserva su FSM interna de 15 estados (4 ciclos ALU,
8 MUL, hasta 37 DIV). Colapsarla y segmentar X en sub-etapas (X1/X2/X3...) es
la siguiente iteración, no parte de esta.

## Extensiones sobre la 22: `GETID` y accesos de 8 y 16 bits

Desde la migración a las extensiones de `1.isa` esta carpeta **se aparta de la
22** en cuatro ficheros, y los dos primeros dejan de ser copias suyas:

- **`GETID` completo** (`gpu_lane.v`, `gpu_sm.v`, `gpu_system_bl8.v`): el opcode
  `0x30` con `type` 0 a 4 — `GETTID`, `GETLANE`, `GETWARP`, `GETLWARP`,
  `GETARG`; un `type` mayor es `ERROR_INVALID_ENCODING`. Los dos últimos leen
  los arrays `LOGICAL_WARP_ID[n]` (`0x82010200`) y `WARP_ARG[n]` (`0x82010280`)
  de GPU WARPS (`mmio.md` §14.2), de lectura y escritura por el host con el
  núcleo parado. El monitor tiene una sola ventana para GPU WARPS y la ensancha
  hasta `0x820102A0`; los huecos de en medio contestan error, no cero.
  El `reset` del núcleo los pone a cero, como a los descriptores: el contrato
  dice que `GPU_CONTROL.RESET` los conservaría, pero ese bloque no existe aquí
  (ver `gpu_system_bl8.v`) y el reset del monitor sí reinicia el resto.
- **Accesos de 8 y 16 bits** (`gpu_sm.v`, `gpu_lsu2.v`): `LOADB`, `LOADUB`,
  `STOREB`, `LOADH`, `LOADUH` y `STOREH` (`0x18` a `0x1D`). El SM los despacha a
  la LSU con el tamaño y el signo; el dato de un store pequeño sale replicado en
  los carriles de la palabra y la LSU forma la máscara de bytes con la
  dirección. Una media palabra impar es fallo, y cualquier acceso pequeño a MMIO
  también (`mmio.md` §4.1: los registros son de palabras). Dos lanes en la misma
  palabra no se fusionan aunque escriban bytes distintos: gana la de menor
  índice y la otra espera otra vuelta — es correcto y más lento que fusionarlas.
- **Un fallo antiguo de la LSU, corregido**: con todas las lanes pendientes en
  fallo y la lane 0 apuntando a MMIO, el acceso salía igualmente por el bus. Un
  `STOREH` fallido habría escrito el registro entero.

`gpu_lsu2.v` y `gpu_lane.v` ya no son idénticos a los de la 22, ni
`gpu_system_bl8.v` ni `gpu_sm.v` (que ya no lo eran). Declara las capacidades
`gpu_ids` y `subword_memory` (`tools/capabilities.json`), y su `ISA_PROFILE` pasa
de `0x0B` a `0x0F`.

| Documento | De qué va |
| --- | --- |
| [`sm-pipeline.md`](../22.fpga-gpu-bl8/sm-pipeline.md) | El diseño del cauce de 6 etapas: motivación, riesgos, roadmap |
| [`lsu-v2.md`](../22.fpga-gpu-bl8/lsu-v2.md) | La LSU heredada de la 22 (sin cambios aquí) |
| [`profiling.md`](../22.fpga-gpu-bl8/profiling.md) | Línea base de ciclos/instrucción de la 22, el número a batir |
| [`mmio.md`](../22.fpga-gpu-bl8/mmio.md) / [`video-scanout.md`](../22.fpga-gpu-bl8/video-scanout.md) | Heredados de la 22, sin cambios funcionales |

## Estado

| Pieza | Estado |
| --- | --- |
| `gpu_register_file.v` | Copiado tal cual de la 22, sin tocar |
| `gpu_lsu2.v`, `gpu_lane.v` | Copiados de la 22 y **extendidos**: accesos de 8 y 16 bits en la LSU y `GETID` en la lane (sección de arriba) |
| `gpu_imem_buffer.v` | **Revisado y corregido**: el pulso de un ciclo de la respuesta se pierde si I está ocupada reteniendo la anterior (contrapresión I→F). Se retiene ahora en un registro hasta que `imem_rsp_ready` la consume |
| `gpu_sm.v` — cauce S/F/I/D/X/W | **Reescrito.** Una instrucción en vuelo por warp, sin bypasses; `gpu_lane` reutilizada tal cual como X |
| Suite completa (`.\tools\test.ps1 --prototype 29`) | **Pasa entera**: 36 casos diferenciales (los dos últimos, `GETID` y accesos pequeños), MMIO, vídeo, LSU, regiones SIMT, barreras, UART físico, bench |

Tres bugs de temporización reales encontrados y corregidos durante la implementación,
todos por la misma causa raíz (un módulo compartido — el puerto de RF, el
buffer de instrucciones, o el cerrojo de S — asumía implícitamente que solo
había una instrucción en vuelo a la vez, invariante que el cauce segmentado
rompe a propósito):

1. El puerto de lectura de `gpu_register_file` tiene un ciclo de latencia;
   capturar el operando en el mismo flanco en que se presenta la dirección
   lee el dato viejo. Hace falta un ciclo de asentamiento explícito (`d_settled`/`d_ready`).
2. Mismo problema entre `gpu_sm` y `gpu_lane`: pulsar `step_request` en el
   mismo flanco en que `x_instruction` se actualiza hace que la lane capture
   la instrucción vieja (`x_started`).
3. `gpu_imem_buffer.v` entrega la respuesta como pulso de un ciclo; si I está
   ocupada esperando a D, la respuesta se pierde para siempre. Corregido
   reteniéndola en un registro.
4. El modo STEP podía retirar dos instrucciones en vez de una si el hueco se
   liberaba justo cuando se reconocía la pausa (`step_locked`).

Pendiente de esta iteración: medir Fmax con síntesis (`build --prototype 29
--background`) y comparar ciclos/instrucción contra la línea base de la 22
en cargas con más de un par de warps activos (el primer sondeo con pocos
warps da ~20 ciclos/instr, dominado por las burbujas conservadoras del
cauce — sin bypass en ningún punto — más que por el trabajo real).

## Verificación

1. Los 34 casos diferenciales de ISA (`gpu_system_bl8_tb.v`) son la red de
   seguridad obligatoria en cada paso.
2. Comparar ciclos/instrucción contra la línea base de la 22
   (`profiling.md`: 17,57 ciclos/instr) usando los mismos contadores de
   `gpu_perf_counters.v` (`CYCLES`/`RETIRED`). Objetivo del primer paso: bajar
   hacia ~4,75 ciclos/instrucción.
3. Contraste de cordura, no automatizado, contra trazas de
   `tools/gpusim-cycle` (25) en programas pequeños — no hay cosimulación
   ciclo a ciclo hoy entre este RTL y el simulador Python.
4. Síntesis temprana (`build --prototype 29 --background`) en cuanto el
   cauce compile, para vigilar pronto si el Fmax se resiente (el crítico
   hoy vive en `gpu_lsu2`).
