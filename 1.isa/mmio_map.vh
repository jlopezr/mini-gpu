// -------------------------------------------------------------------------
// FUENTE UNICA DEL MAPA MMIO v2
//
// Contrato: 1.isa/mmio.md (§20 pide exactamente este fichero).
//
// REGLAS DE ESTE FICHERO, y no son estilo:
//
//   1. Solo `define`, nombre y constante. Ni una expresion, ni un `ifdef`,
//      ni una concatenacion, ni aritmetica.
//   2. Un `define` por linea, con la constante en hexadecimal de 32 bits.
//   3. Nada que no sea una direccion o un offset.
//
// El motivo de la regla 1 es que este fichero lo lee un script de Python
// (`tools/generate_mmio.py`) con una expresion regular de tres lineas. En
// cuanto haya una expresion dentro, leerlo pide un parser de Verilog, y
// entonces la fuente unica deja de ser unica: alguien escribira las
// constantes a mano en el lado Python "solo esta vez".
//
// COMO SE USA. No se edita nada generado a partir de aqui. Se toca este
// fichero y se regenera:
//
//     ./tools/generate-mmio
//
// Y hay un test que comprueba que lo generado esta al dia
// (`x.tests/test_mmio_map.py`), porque un fichero generado se desincroniza en
// silencio y un test que compara falla a gritos.
// -------------------------------------------------------------------------

// ==== Memoria principal ==================================================

`define MMIO_MEM_BASE              32'h0000_0000
`define MMIO_MEM_SIZE_SDRAM        32'h0200_0000
`define MMIO_MEM_SIZE_EBR          32'h0000_8000

// ==== Bases de bloque, todas alineadas a 64 KiB (mmio.md §2) =============

`define MMIO_SYSTEM_BASE           32'h8000_0000
`define MMIO_FABRIC_BASE           32'h8001_0000
`define MMIO_SDRAM_BASE            32'h8002_0000
`define MMIO_SERIAL_BASE           32'h8010_0000
`define MMIO_VIDEO_BASE            32'h8020_0000
`define MMIO_TIMER_BASE            32'h8030_0000
`define MMIO_INTC_BASE             32'h8040_0000
`define MMIO_DMA_BASE              32'h8050_0000
`define MMIO_CPU_BASE              32'h8100_0000
`define MMIO_CPU_PERF_BASE         32'h8101_0000
`define MMIO_CPU_DEBUG_BASE        32'h8102_0000
`define MMIO_GPU_BASE              32'h8200_0000
`define MMIO_GPU_WARPS_BASE        32'h8201_0000
`define MMIO_GPU_SIMT_BASE         32'h8202_0000
`define MMIO_GPU_PERF_BASE         32'h8203_0000

// Tamano de un bloque. Todos miden lo mismo, y es lo que hace que la
// decodificacion sea un rango y no una tabla.
`define MMIO_BLOCK_SIZE            32'h0001_0000

// ==== SYSTEM (mmio.md §5) ================================================

`define MMIO_SYSTEM_MAGIC_OFF      32'h0000_0000
`define MMIO_SYSTEM_MMIO_VERSION_OFF 32'h0000_0004
`define MMIO_SYSTEM_SYSTEM_ID_OFF  32'h0000_0008
`define MMIO_SYSTEM_DEVICES_OFF    32'h0000_000C
`define MMIO_SYSTEM_MEM_BASE_OFF   32'h0000_0010
`define MMIO_SYSTEM_MEM_SIZE_OFF   32'h0000_0014
`define MMIO_SYSTEM_MONITOR_VERSION_OFF 32'h0000_0018

// Valor del magic, no una direccion. Vive aqui porque el RTL, el monitor y
// los simuladores lo necesitan identico y es justo la clase de constante que
// se copia mal.
`define MMIO_MAGIC_VALUE           32'h4D47_4155

// Bits de DEVICES (mmio.md §5.4). Congelados: un bit nunca cambia de
// significado ni se reutiliza.
`define MMIO_DEV_SYSTEM_BIT        32'h0000_0000
`define MMIO_DEV_FABRIC_BIT        32'h0000_0001
`define MMIO_DEV_SDRAM_BIT         32'h0000_0002
`define MMIO_DEV_EBR_BIT           32'h0000_0003
`define MMIO_DEV_SERIAL_BIT        32'h0000_0004
`define MMIO_DEV_VIDEO_BIT         32'h0000_0005
`define MMIO_DEV_TIMER_BIT         32'h0000_0006
`define MMIO_DEV_INTC_BIT          32'h0000_0007
`define MMIO_DEV_DMA_BIT           32'h0000_0008
`define MMIO_DEV_CPU_BIT           32'h0000_0009
`define MMIO_DEV_GPU_BIT           32'h0000_000A

// ==== SERIAL (mmio.md §8) ================================================

`define MMIO_SERIAL_DATA_OFF       32'h0000_0000
`define MMIO_SERIAL_STATUS_OFF     32'h0000_0004
`define MMIO_SERIAL_PEEK_OFF       32'h0000_0008

// ==== VIDEO (mmio.md §9) =================================================

`define MMIO_VIDEO_CTRL_OFF        32'h0000_0000
`define MMIO_VIDEO_FB_FRONT_OFF    32'h0000_0004
`define MMIO_VIDEO_FB_BACK_OFF     32'h0000_0008
`define MMIO_VIDEO_SWAP_OFF        32'h0000_000C
`define MMIO_VIDEO_STATUS_OFF      32'h0000_0010
`define MMIO_VIDEO_FRAME_COUNT_OFF 32'h0000_0014
`define MMIO_VIDEO_SWAP_COUNT_OFF  32'h0000_0018
`define MMIO_VIDEO_HALT_AT_OFF     32'h0000_001C
`define MMIO_VIDEO_HALT_TARGET_OFF 32'h0000_0020
`define MMIO_VIDEO_TX_OFF          32'h0000_0024

// Modos de CTRL (mmio.md §9.1). El 3 esta reservado y escribirlo es error.
`define MMIO_VIDEO_MODE_BLANK      32'h0000_0000
`define MMIO_VIDEO_MODE_PATTERN    32'h0000_0001
`define MMIO_VIDEO_MODE_SCANOUT    32'h0000_0002

// Alineamiento exigido a FB_FRONT y FB_BACK (mmio.md §9.2). Desalinear es
// error, no se trunca.
`define MMIO_VIDEO_FB_ALIGN        32'h0000_0010

// Bits de HALT_TARGET (mmio.md §9.6).
`define MMIO_VIDEO_HALT_CPU_BIT    32'h0000_0000
`define MMIO_VIDEO_HALT_GPU_BIT    32'h0000_0001

// ==== Bloques de contadores (mmio.md §12.6) ==============================
//
// La disposicion vale para CPU PERFORMANCE y GPU PERFORMANCE, y para FABRIC y
// SDRAM cuando se definan. El contador n esta en +4n; el control va DETRAS de
// la extension maxima del array, nunca intercalado.

`define MMIO_PERF_MAX_COUNTERS     32'h0000_0040
`define MMIO_PERF_CTRL_OFF         32'h0000_0100
`define MMIO_PERF_OVF0_OFF         32'h0000_0104
`define MMIO_PERF_OVF1_OFF         32'h0000_0108

`define MMIO_PERF_CTRL_ENABLE_BIT  32'h0000_0000
`define MMIO_PERF_CTRL_RESET_BIT   32'h0000_0001

// Ranuras del array, comunes a las dos familias salvo la 4.
`define MMIO_PERF_CYCLES_OFF       32'h0000_0000
`define MMIO_PERF_RETIRED_OFF      32'h0000_0004
`define MMIO_PERF_IMEM_HITS_OFF    32'h0000_0008
`define MMIO_PERF_IMEM_MISSES_OFF  32'h0000_000C
`define MMIO_PERF_MEM_TX_OFF       32'h0000_0010
`define MMIO_PERF_LSU_TX_OFF       32'h0000_0010
`define MMIO_PERF_STALL_MEM_OFF    32'h0000_0014

// ==== CPU CORE (mmio.md §13.1) ===========================================

`define MMIO_CPU_ID_OFF            32'h0000_0000
`define MMIO_CPU_VERSION_OFF       32'h0000_0004
`define MMIO_CPU_ISA_OFF           32'h0000_0008
`define MMIO_CPU_FEATURES_OFF      32'h0000_000C
`define MMIO_CPU_STATUS_OFF        32'h0000_0010

// ==== GPU CORE / CONTROL (mmio.md §14.1) =================================

`define MMIO_GPU_ID_OFF            32'h0000_0000
`define MMIO_GPU_VERSION_OFF       32'h0000_0004
`define MMIO_GPU_ISA_OFF           32'h0000_0008
`define MMIO_GPU_FEATURES_OFF      32'h0000_000C
`define MMIO_GPU_CAPS_OFF          32'h0000_0010
`define MMIO_GPU_STATUS_OFF        32'h0000_0014
`define MMIO_GPU_CONTROL_OFF       32'h0000_0018
`define MMIO_GPU_WARP_START_OFF    32'h0000_001C
`define MMIO_GPU_WARP_LIVE_OFF     32'h0000_0020
`define MMIO_GPU_WARP_DONE_OFF     32'h0000_0024

// ==== GPU WARPS (mmio.md §14.2) ==========================================
//
// Array de descriptores: el descriptor n esta en base + 16n.
//
// OJO CON EL NOMBRE. Un `_OFF` pertenece al bloque cuyo `_BASE` sea el prefijo
// mas largo de su nombre, asi que estos tienen que llamarse `GPU_WARPS_` --con
// S, como `MMIO_GPU_WARPS_BASE`-- y no `GPU_WARP_`. Con la S mal puesta, el
// generador los colgaba de `MMIO_GPU_BASE` y `GPU_WARP_PC` salia en la misma
// direccion que `GPU_ID`. Hay una comprobacion de colisiones que lo caza, pero
// el nombre correcto evita tener que leerla.

`define MMIO_GPU_WARPS_STRIDE      32'h0000_0010
`define MMIO_GPU_WARPS_PC_OFF      32'h0000_0000
`define MMIO_GPU_WARPS_ACTIVE_OFF  32'h0000_0004
`define MMIO_GPU_WARPS_GROUP_OFF   32'h0000_0008
`define MMIO_GPU_WARPS_SIMT_OFF    32'h0000_000C

// ==== GPU SIMT DEBUG (mmio.md §14.3) =====================================

`define MMIO_GPU_SIMT_CONTEXT_OFF  32'h0000_0000
`define MMIO_GPU_SIMT_LSU_SLOTS_OFF 32'h0000_0004
`define MMIO_GPU_SIMT_FIRST_ERROR_OFF 32'h0000_0008
`define MMIO_GPU_SIMT_FIRST_ERROR_PC_OFF 32'h0000_000C
`define MMIO_GPU_SIMT_WARP_RETIRED_OFF 32'h0000_0010
