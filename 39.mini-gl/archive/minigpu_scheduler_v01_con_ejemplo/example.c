#include "scheduler_v01.h"
#include <stdio.h>
#include <stdlib.h>

typedef struct { int ticks[GPU_MAX_SLOTS]; } fake_gpu;
static int pop_done(void *ctx) {
    fake_gpu *g=ctx;
    for(int i=0;i<GPU_MAX_SLOTS;i++) if(g->ticks[i]==-1) {g->ticks[i]=0; return i;}
    return -1;
}
static bool available(void *ctx,uint8_t slot) {return ((fake_gpu*)ctx)->ticks[slot]==0;}
static bool launch(void *ctx,uint8_t slot,uint32_t pc,uint32_t wid) {
    fake_gpu *g=ctx;
    if(g->ticks[slot]) return false;
    g->ticks[slot]=3;
    printf("  launch slot=%u pc=0x%04x logical_warp=%u\n",slot,(unsigned)pc,(unsigned)wid);
    return true;
}
static void gpu_tick(fake_gpu *g) {
    for(int i=0;i<GPU_MAX_SLOTS;i++) if(g->ticks[i]>0 && --g->ticks[i]==0) g->ticks[i]=-1;
}
static void check(gpu_result r) {if(r!=GPU_OK){fprintf(stderr,"error %d\n",r);exit(1);}}
static gpu_job_id add(gpu_scheduler *s,const char *name,uint32_t pc,uint32_t base,
                      uint32_t count,gpu_priority prio,const gpu_job_id *deps,uint16_t n) {
    gpu_job_id id;
    check(gpu_submit(s,(gpu_job_desc){pc,base,count,prio},deps,n,&id));
    printf("submit %-8s id=%u warps=%u deps=%u\n",name,id,count,n);
    return id;
}
static gpu_job_state state(gpu_scheduler *s,gpu_job_id id) {
    gpu_job_state st;check(gpu_job_status(s,id,&st));return st;
}
int main(void) {
    fake_gpu gpu={0}; gpu_scheduler s;
    gpu_scheduler_init(&s,(gpu_hw_ops){pop_done,available,launch,&gpu});
    gpu_job_id clear=add(&s,"CLEAR",0x1000,0,12,GPU_RENDER,NULL,0);
    gpu_job_id draw=add(&s,"DRAW",0x2000,100,8,GPU_RENDER,&clear,1);
    gpu_job_id compute=add(&s,"COMPUTE",0x3000,1000,16,GPU_COMPUTE,NULL,0);
    gpu_job_id deps[]={draw,compute};
    gpu_job_id present=add(&s,"PRESENT",0x4000,200,1,GPU_RENDER,deps,2);
    for(int t=0;t<100;t++) {
        printf("tick %d\n",t);
        gpu_scheduler_poll(&s);
        if(state(&s,clear)!=GPU_DONE && s.jobs[draw&127].next_warp) return 2;
        if((state(&s,draw)!=GPU_DONE || state(&s,compute)!=GPU_DONE) && s.jobs[present&127].next_warp) return 3;
        if(state(&s,present)==GPU_DONE) {
            puts("OK: dependencias y finalizacion correctas");
            check(gpu_release(&s,present));check(gpu_release(&s,draw));
            check(gpu_release(&s,compute));check(gpu_release(&s,clear));
            return 0;
        }
        gpu_tick(&gpu);
    }
    return 4;
}
