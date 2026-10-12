/* demo.c - el scheduler sobre la GPU de verdad: un job de 4 warps
 *
 *   make demo-sim     compila con build-c y lo ejecuta en sim-sys (R1 = 0 si todo va bien)
 *
 * Los tres callbacks de gpu_hw_ops hablan con la GPU por MMIO (mmio.md §14):
 *
 *   launch          rellena el descriptor del slot (PC, ACTIVE, GROUP, LOGICAL_ID, ARG)
 *                   y lo arranca con WARP_START
 *   slot_available  el slot no esta vivo ni tiene una terminacion sin recoger
 *   pop_done        un bit de WARP_DONE, que se limpia escribiendolo (W1C)
 *
 * WARP_DONE se queda a 1 hasta que pop_done lo limpia, asi que una terminacion
 * no se pierde ni se reutiliza el slot antes de recogerla: es el contrato de
 * scheduler.h. El kernel usa el warp LOGICO (__gpu_lwarp): el scheduler elige
 * el slot fisico, y GETTID se basa en el fisico.
 */
#include "scheduler.h"
#include "gpu.h"
#include "mmio.h"

#define WARPS       4
#define MAX_LANES   32
#define VALUE       1000
#define POLL_LIMIT  100000

#define GPU_ST_ERROR 0x8                      /* GPU_STATUS.ERROR (mmio.md §14.1) */

/* Bloque de argumentos estandar (gpu_runtime.inc): nwarps, nlanes y p0..p5.
   El kernel lo lee con GETARG; mini-opt carga sus parametros de p0..p3. */
typedef struct {
    int nwarps, nlanes;
    int p[6];
} GpuBlock;

/* Lo que comparten los callbacks: un job en vuelo, asi que un solo bloque. */
typedef struct {
    unsigned num_warps;                       /* slots fisicos (GPU_CAPS) */
    unsigned all_lanes;                       /* mascara ACTIVE con todas las lanes */
    GpuBlock *block;
} demo_gpu;

int result[WARPS * MAX_LANES];

/* Cada hilo escribe VALUE + su indice global. */
void KERNEL(fill)(int *dst, int value, int nlanes) {
    int i = __gpu_lwarp * nlanes + __gpu_lane;
    dst[i] = value + i;
}

/* ---- callbacks ---- */

static bool hw_launch(void *ctx, uint8_t slot, uint32_t pc, uint32_t logical_warp) {
    demo_gpu *g = (demo_gpu *)ctx;
    unsigned desc = MMIO_GPU_WARPS_BASE + slot * MMIO_GPU_WARPS_STRIDE;
    unsigned per_warp = MMIO_GPU_WARPS_BASE + slot * 4;
    REG(desc + MMIO_GPU_WARPS_PC_OFF) = pc;
    REG(desc + MMIO_GPU_WARPS_ACTIVE_OFF) = g->all_lanes;
    REG(desc + MMIO_GPU_WARPS_GROUP_OFF) = 1;                /* id de grupo para BAR */
    REG(per_warp + MMIO_GPU_WARPS_LOGICAL_ID_OFF) = logical_warp;
    REG(per_warp + MMIO_GPU_WARPS_ARG_OFF) = (unsigned)g->block;
    REG(MMIO_GPU_WARP_START_ADDR) = 1u << slot;              /* descriptor primero, luego arrancar */
    return true;
}

static bool hw_slot_available(void *ctx, uint8_t slot) {
    demo_gpu *g = (demo_gpu *)ctx;
    unsigned busy = REG(MMIO_GPU_WARP_LIVE_ADDR) | REG(MMIO_GPU_WARP_DONE_ADDR);
    return slot < g->num_warps && !(busy & (1u << slot));
}

static int hw_pop_done(void *ctx) {
    unsigned done = REG(MMIO_GPU_WARP_DONE_ADDR);
    int slot;
    (void)ctx;
    for (slot = 0; slot < GPU_MAX_SLOTS; slot++)
        if (done & (1u << slot)) {
            REG(MMIO_GPU_WARP_DONE_ADDR) = 1u << slot;      /* W1C: solo este */
            return slot;
        }
    return -1;
}

/* ---- programa ---- */

static gpu_scheduler sched;
static GpuBlock block;

int main(void) {
    demo_gpu gpu;
    gpu_hw_ops hw;
    gpu_job_desc job;
    gpu_job_id id;
    gpu_job_state state;
    unsigned caps, lanes, polls;
    int i;

    /* Configurar: lo que hay en la GPU y el bloque de argumentos del kernel. */
    caps = REG(MMIO_GPU_CAPS_ADDR);
    gpu.num_warps = caps & 0xFF;
    lanes = (caps >> 8) & 0xFF;
    if (gpu.num_warps > GPU_MAX_SLOTS) gpu.num_warps = GPU_MAX_SLOTS;
    if (lanes > MAX_LANES) return 1;
    gpu.all_lanes = (1u << lanes) - 1;
    gpu.block = &block;
    block.nwarps = WARPS;
    block.nlanes = (int)lanes;
    block.p[0] = (int)result;
    block.p[1] = VALUE;
    block.p[2] = (int)lanes;

    hw.launch = hw_launch;
    hw.slot_available = hw_slot_available;
    hw.pop_done = hw_pop_done;
    hw.ctx = &gpu;
    gpu_scheduler_init(&sched, hw);

    /* Un job: el kernel fill en WARPS warps logicos (0..WARPS-1). */
    job.shader_pc = (uint32_t)KERNEL(fill);
    job.base_warp_id = 0;
    job.warp_count = WARPS;
    job.priority = GPU_COMPUTE;
    if (gpu_submit(&sched, job, 0, 0, &id) != GPU_OK) return 2;

    /* El bucle de la CPU: poll hasta que acabe. */
    for (polls = 0; polls < POLL_LIMIT; polls++) {
        gpu_scheduler_poll(&sched);
        if (REG(MMIO_GPU_STATUS_ADDR) & GPU_ST_ERROR) return 3;
        gpu_job_status(&sched, id, &state);
        if (state == GPU_DONE) break;
    }
    if (state != GPU_DONE) return 4;
    gpu_release(&sched, id);

    for (i = 0; i < WARPS * (int)lanes; i++)
        if (result[i] != VALUE + i) return 100 + i;
    return 0;
}
