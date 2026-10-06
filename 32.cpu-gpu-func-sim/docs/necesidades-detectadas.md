# Necesidades detectadas: GPU como motor DMA/blitter

Notas de trabajo de la revisión de [`integracion cpu-gpu.md`](integracion%20cpu-gpu.md). El resultado está en [`../docs/diseno-gpu-dma.md`](../docs/diseno-gpu-dma.md).
Recogen lo que el diseño pide y la ISA, el MMIO o el RTL todavía no dan, y las
decisiones que se han ido tomando. Material para el documento de diseño; no es el
documento.

Estado: **pendiente** (hay que hacerlo), **hecho**, **descartado**, **pospuesto**.

## Decisiones tomadas

| # | Decisión |
|---|---|
| D1 | **Sin interrupciones.** Todo va por polling sobre `WARP_DONE`. Las necesidades que aparezcan se apuntan aquí. |
| D2 | La **completion por job la calcula el runtime** de la CPU a partir de `WARP_DONE`, que es por warp. El hardware no sabe qué es un job. |
| D3 | La **cola de comandos y la de completions son software** (RAM, escritas por el runtime). La GPU no necesita command processor (mmio.md §14.1). |
| D4 | **Los argumentos llegan por una instrucción**, no por un registro inicializado: `GETARG`. Un solo mecanismo. |
| D5 | **Dos registros por warp**, con dos propósitos distintos: `LOGICAL_WARP_ID` (qué warp lógico es, visible por MMIO para depurar y trazar) y `WARP_ARG` (puntero a los argumentos). |
| D6 | Un job usa **un bloque de argumentos compartido** y cada warp lleva su id lógico. El runtime puede usar un bloque por warp si un kernel lo prefiere: el hardware no lo sabe. |
| D7 | Conjunto de identificadores: `GETTID` (existe), `GETLANE`, `GETWARP` (slot físico, opcional), `GETLWARP` (lógico), `GETARG`. No hay instrucción para leer `WORKGROUP_ID`: solo lo usa `BAR`. |
| D8 | Convención del runtime: `WORKGROUP_ID = job_id`, para que un `BAR` sincronice solo los warps de su job. |
| D9 | Kernels **por palabras** en la v1. El runtime divide cada operación en cabeza, cuerpo alineado y cola, y la CPU hace las partes pequeñas. |
| D10 | `memcpy` con `src` y `dst` no congruentes módulo 4 va por la CPU en la v1. |
| D11 | **Errores de GPU: solo software en la v1.** Un fallo para toda la GPU (hoy, también en el RTL). El runtime valida antes de enviar (rango completo contra `MEM_SIZE`, alineamiento, desbordes), `gpu_done()` y `gpu_wait()` miran `GPU_STATUS.ERROR` además de `WARP_DONE`, atribuye el fallo al job con `FIRST_ERROR`, lee `WARP_DONE` **antes** de `RESET` para no perder los jobs ya terminados, completa el culpable con error y reenvía los demás (los kernels son idempotentes si `src` y `dst` no se solapan). Un job culpable no se reintenta. *Pendiente de revisar:* si el reenvío es automático o decide la aplicación. |
| D12 | **La completion es solo `WARP_DONE`.** Un warp no puede tocar `WARP_*` ni el control (§15) y no puede avisar por MMIO; el despachador es siempre la CPU. Los flags de completion en RAM no se usan: nada garantiza que ese `STORE` se vea después de los datos (la ordenación de `WARP_DONE` sí está garantizada por §18). Idea futura, no ahora: **warps residentes** que leen un buzón en RAM, que exigirían poder ordenar escrituras (un fence, o `BAR` en un workgroup de un solo warp) y gastan ancho de banda sondeando. |
| D13 | **Jobs en orden, uno a la vez, en la v1.** Cada job usa los warps que convenga y el siguiente no empieza hasta que el anterior termina: sin carreras de datos entre jobs y con un asignador trivial. **Jobs concurrentes** con asignador de ranuras, como extensión, con dependencias explícitas (`gpu_fence()` o un campo "depende de"). |
| D14 | **El número de warps de un job se fija al lanzarlo** y es una constante configurable que afinará el benchmark. El kernel recorre su trozo con `stride = nwarps`, que lee del bloque de argumentos, así que no depende de cuántos warps haya en la GPU. |
| D15 | **Protocolo de recogida de `WARP_DONE`**, por una carrera real: `WARP_START` limpia el bit del warp (§14.1), así que reutilizar una ranura antes de leer su bit **pierde la completion** del job anterior. Orden obligatorio: leer `WARP_DONE`; completar los jobs de esos bits; limpiarlos con W1C escribiendo **exactamente el valor leído**, no `0xFFFFFFFF`, para no borrar un bit que se active entre la lectura y la escritura; y solo entonces asignar esas ranuras. |
| D16 | **Reparto estático del trabajo, sin atómicas, en la v1.** Cada warp recorre su trozo por `LOGICAL_WARP_ID` con `stride = nwarps`, sin coordinarse con los demás. El trabajo de `memcpy`, `memset`, `fill` y `blit` es uniforme, así que no hay desequilibrio que justifique repartirlo dinámicamente. |

Limitación que hay que dejar escrita: un puntero equivocado pero **dentro de la RAM no da fallo**, corrompe en silencio. La GPU no tiene protección de memoria; la validación en la CPU es la única defensa.

## Necesidades

### N1. Interrupciones — pospuesto

- Una IRQ al hacerse `WARP_DONE != 0` (por warp, no por job) y una espera tipo `WFI`.
- Requiere definir el INTC (`0x80400000`, reservado en mmio.md §11 y §22).
- Hoy: polling (D1). La API deja un punto de enganche (`wait_hook`) para añadirlo sin cambiar el protocolo.

### N2. Registro inicializado al lanzar (R1) — descartado

- La alternativa a `GETARG`: `R1 = WARP_ARG` en todas las lanes al lanzar. Encaja con el ABI (`R1`–`R4` son argumentos) pero obliga a escribir el banco de registros desde el lanzador, y no se ha revisado el RTL.
- Se puede recuperar si se quieren kernels en C con el primer argumento en R1.

### N3. `LOGICAL_WARP_ID[n]` y `WARP_ARG[n]` en GPU WARPS — contrato y simulador hechos, RTL pendiente

- Dos arrays nuevos tras los 32 descriptores (mmio.md §14.2, regla §1.4): `LOGICAL_WARP_ID[n]` en `+0x200` y `WARP_ARG[n]` en `+0x280`.
- Lectura y escritura. Escribirlos en un warp vivo es error, como el resto del descriptor.
- No caben en el descriptor: el stride de 16 bytes está congelado y `SIMT_STATE` no es un hueco libre.
- `LOGICAL_WARP_ID` es el antiguo `warp_user_id` de `propuesta-v0.2.md`, cuya ventana MMIO quedó "pendiente de asignación".
- Tocan: mmio.md, `tools/mmio_map.py` (generado), simulador de la 32 (`GpuWarpsDevice`), simulador de `11` (estado por warp), RTL.

### N4. `GETID` con `type` 1 a 4 — ensamblador y simuladores (11 y 25) hechos, RTL pendiente

- `GETID` es el opcode `0x30`, con el campo `type` en el campo Y. `type = 0` es el encoding actual de `GETTID`, así que los binarios existentes no cambian.

| `type` | Mnemónico | Devuelve |
|---:|---|---|
| 0 | `GETTID` | thread residente: `warp * lanes + lane` (existe) |
| 1 | `GETLANE` | lane dentro del warp |
| 2 | `GETWARP` | slot de warp físico |
| 3 | `GETLWARP` | `LOGICAL_WARP_ID` |
| 4 | `GETARG` | `WARP_ARG` |

- `type >= 5`: reservado, `ERROR_INVALID_ENCODING`.
- **Renombrado:** `GETWID` y `warp_user_id` de `propuesta-v0.2.md`, `v0.3`, `v0.4` y `v0.4b` pasan a `GETLWARP` y `LOGICAL_WARP_ID`. `GETWID` se leía como "workgroup id". Un solo nombre en todas partes, sin alias.
- `warp_user_id` era genérico ("base, tile u objeto"); con el nombre nuevo la intención se estrecha a "id lógico que asigna el lanzador".
- Tocan: las cuatro propuestas, `isa.md`, `mini_asm.py`, simulador de `11` y RTL.
- `GETGWARP`, citado de memoria, no existe en el repo.

### N5. Semántica de reset — contrato y simulador hechos, RTL pendiente

- `propuesta-v0.2.md` dice que `warp_user_id` "vale cero tras reset de GPU".
- En MMIO v2, `GPU_CONTROL.RESET` conserva los descriptores. `LOGICAL_WARP_ID` y `WARP_ARG` son configuración del lanzador: `RESET` los conserva y solo el reset físico los pone a cero.

### N6. Accesos de 8 y 16 bits en la GPU — simulador hecho, RTL pendiente

- Hecho el 2026-10-06 en el simulador de `11` (y por tanto en el de la 32): `LOADB`, `LOADUB`, `STOREB`, `LOADH`, `LOADUH`, `STOREH`, solo contra RAM; contra MMIO son error (§4.1). El perfil de ISA declara `SUBWORD`.
- Ya los tenían la CPU (2, 19, 21, 30) y el modelo de ciclos de la 25.
- **Pendiente en el RTL de la 29**: decodificar `0x18–0x1D` en `gpu_lane.v`, y en la LSU (`gpu_lsu2.v`, coalescencia por línea de 16 bytes) tamaños, extensión de signo y máscaras de bytes. Dos lanes que escriben bytes distintos de la misma palabra se funden en una escritura con `wstrb`. Después, que el perfil del RTL declare `SUBWORD` (hoy `0x0b`).
- Mientras tanto, el simulador va por delante de la placa: un kernel con accesos pequeños corre en el simulador y no en la FPGA.
- Con esto desaparecen los bordes de la D9 y el caso desalineado de la D10.

### N7. Errores por warp en vez de globales — pospuesto

- Hoy un fallo de un warp para toda la GPU: el error es un registro único en `gpu_sm.v` (`error`, `error_code`, `error_warp`…) y `!error` frena el planificador y las barreras. Un job con un fallo tumba los de otras tareas.
- La alternativa: matar solo el warp que falla y dejar correr los demás.
- **No es caro en área, es delicado.** Hace falta: un bit de error por warp; descartar las instrucciones en vuelo de ese warp sin tocar las de los demás; decidir qué hacer con sus respuestas pendientes en la LSU compartida; sacarlo de las barreras para que sus compañeros de workgroup no se queden esperando (el simulador de `11` ya lo hace); y un cambio de contrato: hoy §14.3 habla de "el que causó la parada", y haría falta un registro tipo `WARP_ERROR` y definir cómo queda un warp fallido en `WARP_LIVE` y `WARP_DONE` (no está vivo ni terminado).
- **No medido:** el efecto en frecuencia. Los `!error` están en la ruta del planificador y el proyecto va ajustado en Fmax.
- Evaluarlo junto con N6, porque los dos tocan la LSU y la tubería de la 29. Se puede prototipar antes la semántica en el simulador de `11`, como se hizo con el sub-word.
- La v1 funciona sin él (D11).

### N8. Atómicas y `FENCE` en la GPU — pospuesto

- `atomics.md` propone `ATOMADD`, `ATOMCAS` y `FENCE`, y `propuesta-v0.4b.md` les da opcodes (grupo `0x2A` para las atómicas y `0x36` para `FENCE`). **No están implementadas** en ningún simulador, ensamblador ni RTL.
- **La v1 no las necesita** (D16). La sincronización CPU↔GPU va por `WARP_DONE` (D12) y el reparto es estático.
- Harían falta para extensiones ya anotadas:
  - **Reparto dinámico de trozos** entre warps (`ATOMADD` sobre un contador compartido), si algún kernel tiene trabajo desigual.
  - **Warps residentes** con buzón en RAM (D12): `FENCE` para ordenar los datos antes del flag, y `ATOMADD` o `ATOMCAS` si varios consumidores comparten una cola.
  - **Contador `warps_pending` por job en RAM**, decrementado por cada warp, en lugar de contar con `WARP_DONE` desde la CPU.
- `FENCE = NOP` es una implementación válida mientras la LSU no tenga operaciones pendientes (atomics.md §5), pero la LSU de la 29 coalesce por línea de 16 bytes y tiene etiquetas por warp: **habría que comprobar si puede tener operaciones pendientes** antes de darlo por válido ahí.

### N9. `ANDI`, `ORI` y `XORI` no admitían símbolos `.equ` — resuelto en `1.isa/mini_asm.py`

- Salió al escribir `examples/dma/gpu_runtime.inc`: `ANDI R7, R4, GPU_ST_ERROR` daba «entero inválido». `MOVI`, `ADDI`, `LOAD`, `STORE` y los saltos resuelven etiquetas y `.equ` (`resolve_target`), pero el grupo sin signo (`I3_UNSIGNED_OPS`) llamaba a `parse_int` y solo aceptaba literales.
- Arreglado: ahora usa `resolve_target`, con el mismo rango sin signo de 16 bits (un `.equ` de `0x10000` o negativo sigue siendo error). Test en `test_mini_asm.py`.
- Queda por decidir si `NEW-ASSM` lo hereda, junto con N4.
