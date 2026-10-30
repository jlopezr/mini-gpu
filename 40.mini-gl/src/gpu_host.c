#include "gpu_renderer.h"
/* Functional simulation: process each command for all lanes before next command.
   It is NOT a cycle-accurate SIMT or memory timing simulation. */
int mgl_test_lane;
int mgl_gpu_render_host(const mgl_gpu_job_t *j) {
    /* To preserve draw order, invoke the single-command worker per lane.
       See gpu_renderer.c host-specific entry point below. */
    extern int mgl_gpu_render_host_commands(const mgl_gpu_job_t *j);
    return mgl_gpu_render_host_commands(j);
}
