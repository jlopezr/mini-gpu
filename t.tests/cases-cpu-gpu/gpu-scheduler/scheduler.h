#ifndef MINIGPU_SCHEDULER_V01_H
#define MINIGPU_SCHEDULER_V01_H

#include <stdint.h>
#include <stdbool.h>

#define GPU_MAX_JOBS 128
#define GPU_MAX_SLOTS 8
#define GPU_MAX_EDGES 512
#define GPU_INVALID_JOB UINT16_MAX

typedef uint16_t gpu_job_id;
typedef enum { GPU_FREE, GPU_BLOCKED, GPU_READY, GPU_ACTIVE, GPU_DONE, GPU_CANCELLED } gpu_job_state;
typedef enum { GPU_RENDER=0, GPU_COMPUTE=1 } gpu_priority;
typedef enum { GPU_OK=0, GPU_ERR_ID=-1, GPU_ERR_FULL=-2, GPU_ERR_DEP=-3, GPU_ERR_STATE=-4, GPU_ERR_CAPACITY=-5 } gpu_result;
typedef struct { uint32_t shader_pc, base_warp_id, warp_count; gpu_priority priority; } gpu_job_desc;
typedef struct {
    /* pop_done returns a completed physical slot (0..7), or -1 if none.
       Completion must remain latched until consumed. */
    int (*pop_done)(void *ctx);
    /* slot_available must be false until previous completion was consumed. */
    bool (*slot_available)(void *ctx, uint8_t slot);
    /* true iff launch accepted; the slot must then remain reserved until done. */
    bool (*launch)(void *ctx, uint8_t slot, uint32_t pc, uint32_t logical_warp);
    void *ctx;
} gpu_hw_ops;

typedef struct {
    uint32_t shader_pc, base_warp_id, warp_count, next_warp, completed;
    uint16_t generation, pending_deps, first_dependent;
    uint8_t priority, state;
} gpu_job;

typedef struct { uint8_t dependent; uint16_t next; } gpu_edge;

typedef struct {
    gpu_job jobs[GPU_MAX_JOBS];
    gpu_edge edges[GPU_MAX_EDGES];
    uint16_t edge_free_head;
    uint16_t slot_job[GPU_MAX_SLOTS];
    uint8_t cursor[2];
    gpu_hw_ops hw;
} gpu_scheduler;

void gpu_scheduler_init(gpu_scheduler *s, gpu_hw_ops hw);
gpu_result gpu_submit(gpu_scheduler *s, gpu_job_desc desc, const gpu_job_id *deps, uint16_t ndeps, gpu_job_id *out);
void gpu_scheduler_poll(gpu_scheduler *s);
gpu_result gpu_job_status(const gpu_scheduler *s, gpu_job_id id, gpu_job_state *state);
gpu_result gpu_cancel(gpu_scheduler *s, gpu_job_id id);
gpu_result gpu_release(gpu_scheduler *s, gpu_job_id id);

#endif
