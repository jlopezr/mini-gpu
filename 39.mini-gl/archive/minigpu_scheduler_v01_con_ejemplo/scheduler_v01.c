#include "scheduler_v01.h"
#include <string.h>
#define NO_EDGE UINT16_MAX
#define NO_SLOT_JOB UINT16_MAX
static gpu_job_id id_of(const gpu_scheduler *s, unsigned i) { return (gpu_job_id)((s->jobs[i].generation << 7) | i); }
static int idx(const gpu_scheduler *s, gpu_job_id id) {
    unsigned i=id&127u;
    return (s->jobs[i].state!=GPU_FREE && s->jobs[i].generation==(id>>7)) ? (int)i : -1;
}
void gpu_scheduler_init(gpu_scheduler *s, gpu_hw_ops hw) {
    memset(s,0,sizeof(*s)); s->hw=hw;
    for(unsigned i=0;i<GPU_MAX_JOBS;i++) s->jobs[i].first_dependent=NO_EDGE;
    for(unsigned i=0;i<GPU_MAX_EDGES;i++) s->edges[i].next=(i+1<GPU_MAX_EDGES)?(uint16_t)(i+1):NO_EDGE;
    s->edge_free_head=0;
    for(unsigned i=0;i<GPU_MAX_SLOTS;i++) s->slot_job[i]=NO_SLOT_JOB;
}
static void edge_free(gpu_scheduler *s, uint16_t e) {
    s->edges[e].next=s->edge_free_head; s->edge_free_head=e;
}
static void resolve_dependents(gpu_scheduler *s, unsigned parent, bool cancel) {
    uint16_t e=s->jobs[parent].first_dependent;
    s->jobs[parent].first_dependent=NO_EDGE;
    while(e!=NO_EDGE) {
        uint16_t next=s->edges[e].next;
        gpu_job *child=&s->jobs[s->edges[e].dependent];
        if(child->state==GPU_BLOCKED) {
            if(cancel) {
                child->state=GPU_CANCELLED;
                resolve_dependents(s,s->edges[e].dependent,true);
            } else if(child->pending_deps && --child->pending_deps==0) {
                child->state=GPU_READY;
            }
        }
        edge_free(s,e); e=next;
    }
}
gpu_result gpu_submit(gpu_scheduler *s, gpu_job_desc desc, const gpu_job_id *deps, uint16_t ndeps, gpu_job_id *out) {
    if(!out || (ndeps && !deps) || desc.priority>GPU_COMPUTE) return GPU_ERR_DEP;
    int free_i=-1;
    for(unsigned i=0;i<GPU_MAX_JOBS;i++) if(s->jobs[i].state==GPU_FREE) {free_i=(int)i;break;}
    if(free_i<0) return GPU_ERR_FULL;
    /* Validate dependencies and count live ones before mutating state. */
    unsigned live=0;
    for(unsigned d=0;d<ndeps;d++) {
        int j=idx(s,deps[d]);
        if(j<0 || s->jobs[j].state==GPU_CANCELLED) return GPU_ERR_DEP;
        for(unsigned k=0;k<d;k++) if(deps[k]==deps[d]) return GPU_ERR_DEP;
        if(s->jobs[j].state!=GPU_DONE) live++;
    }
    unsigned available=0;
    for(uint16_t e=s->edge_free_head;e!=NO_EDGE;e=s->edges[e].next) available++;
    if(available<live) return GPU_ERR_CAPACITY;
    gpu_job *job=&s->jobs[free_i];
    job->shader_pc=desc.shader_pc; job->base_warp_id=desc.base_warp_id;
    job->warp_count=desc.warp_count; job->next_warp=job->completed=0;
    job->priority=(uint8_t)desc.priority; job->pending_deps=(uint16_t)live;
    job->first_dependent=NO_EDGE;
    job->state=live?GPU_BLOCKED:GPU_READY;
    *out=id_of(s,(unsigned)free_i);
    for(unsigned d=0;d<ndeps;d++) {
        int j=idx(s,deps[d]);
        if(s->jobs[j].state==GPU_DONE) continue;
        uint16_t e=s->edge_free_head; s->edge_free_head=s->edges[e].next;
        s->edges[e].dependent=(uint8_t)free_i;
        s->edges[e].next=s->jobs[j].first_dependent;
        s->jobs[j].first_dependent=e;
    }
    return GPU_OK;
}
static int choose(gpu_scheduler *s) {
    for(unsigned p=0;p<2;p++) {
        for(unsigned step=0;step<GPU_MAX_JOBS;step++) {
            unsigned i=(s->cursor[p]+step)&127u;
            gpu_job *j=&s->jobs[i];
            if(j->priority==p && (j->state==GPU_READY || j->state==GPU_ACTIVE) && j->next_warp<j->warp_count) {
                s->cursor[p]=(uint8_t)((i+1)&127u); return (int)i;
            }
        }
    }
    return -1;
}
void gpu_scheduler_poll(gpu_scheduler *s) {
    int slot;
    while((slot=s->hw.pop_done(s->hw.ctx))>=0) {
        if(slot>=GPU_MAX_SLOTS || s->slot_job[slot]==NO_SLOT_JOB) continue; /* HW contract violation */
        unsigned i=s->slot_job[slot]; s->slot_job[slot]=NO_SLOT_JOB;
        gpu_job *j=&s->jobs[i]; j->completed++;
        if(j->completed==j->warp_count) {j->state=GPU_DONE; resolve_dependents(s,i,false);}
    }
    /* Empty jobs complete without a hardware launch. Repeat for dependency chains. */
    bool changed;
    do {
        changed=false;
        for(unsigned i=0;i<GPU_MAX_JOBS;i++) {
            gpu_job *j=&s->jobs[i];
            if(j->state==GPU_READY && j->warp_count==0) {
                j->state=GPU_DONE; resolve_dependents(s,i,false); changed=true;
            }
        }
    } while(changed);
    for(unsigned slot_i=0;slot_i<GPU_MAX_SLOTS;slot_i++) {
        if(s->slot_job[slot_i]!=NO_SLOT_JOB || !s->hw.slot_available(s->hw.ctx,(uint8_t)slot_i)) continue;
        int i=choose(s); if(i<0) break;
        gpu_job *j=&s->jobs[i];
        uint32_t logical=j->base_warp_id+j->next_warp;
        if(s->hw.launch(s->hw.ctx,(uint8_t)slot_i,j->shader_pc,logical)) {
            s->slot_job[slot_i]=(uint16_t)i;
            j->next_warp++; j->state=GPU_ACTIVE;
        }
    }
}
gpu_result gpu_job_status(const gpu_scheduler *s, gpu_job_id id, gpu_job_state *state) {
    int i=idx(s,id); if(i<0 || !state) return GPU_ERR_ID;
    *state=(gpu_job_state)s->jobs[i].state; return GPU_OK;
}
static bool cancellable(const gpu_scheduler *s, unsigned i) {
    const gpu_job *j=&s->jobs[i];
    if(j->state==GPU_CANCELLED) return true;
    if((j->state!=GPU_BLOCKED && j->state!=GPU_READY) || j->next_warp) return false;
    for(uint16_t e=j->first_dependent;e!=NO_EDGE;e=s->edges[e].next)
        if(!cancellable(s,s->edges[e].dependent)) return false;
    return true;
}
static void detach_from_parents(gpu_scheduler *s, unsigned child) {
    for(unsigned i=0;i<GPU_MAX_JOBS;i++) {
        uint16_t *p=&s->jobs[i].first_dependent;
        while(*p!=NO_EDGE) {
            uint16_t e=*p;
            if(s->edges[e].dependent==child) { *p=s->edges[e].next; edge_free(s,e); }
            else p=&s->edges[e].next;
        }
    }
}
static void cancel_tree(gpu_scheduler *s, unsigned i) {
    gpu_job *j=&s->jobs[i];
    if(j->state==GPU_CANCELLED) return;
    uint16_t e=j->first_dependent; j->first_dependent=NO_EDGE;
    while(e!=NO_EDGE) {
        uint16_t next=s->edges[e].next;
        cancel_tree(s,s->edges[e].dependent);
        edge_free(s,e); e=next;
    }
    detach_from_parents(s,i);
    j->pending_deps=0; j->state=GPU_CANCELLED;
}
gpu_result gpu_cancel(gpu_scheduler *s, gpu_job_id id) {
    int i=idx(s,id); if(i<0) return GPU_ERR_ID;
    if(!cancellable(s,(unsigned)i)) return GPU_ERR_STATE;
    cancel_tree(s,(unsigned)i); return GPU_OK;
}
gpu_result gpu_release(gpu_scheduler *s, gpu_job_id id) {
    int i=idx(s,id); if(i<0) return GPU_ERR_ID;
    gpu_job *j=&s->jobs[i];
    if(j->state!=GPU_DONE && j->state!=GPU_CANCELLED) return GPU_ERR_STATE;
    if(j->first_dependent!=NO_EDGE) return GPU_ERR_STATE;
    j->state=GPU_FREE; j->generation=(uint16_t)((j->generation+1)&511u);
    return GPU_OK;
}
