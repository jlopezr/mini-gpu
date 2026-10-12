#include "scheduler.h"

#define NO_EDGE UINT16_MAX
#define NO_SLOT_JOB UINT16_MAX

static gpu_job_id id_of(const gpu_scheduler *s, unsigned i) {
    return (gpu_job_id)((s->jobs[i].generation << 7) | i);
}

static int idx(const gpu_scheduler *s, gpu_job_id id) {
    unsigned i=id&127u;
    return (s->jobs[i].state!=GPU_FREE && s->jobs[i].generation==(id>>7)) ? (int)i : -1;
}

void gpu_scheduler_init(gpu_scheduler *s, gpu_hw_ops hw) {
    /* Byte loop instead of memset: the MiniISA runtime has no libc. */
    unsigned char *p=(unsigned char *)s;
    unsigned i;
    for(i=0;i<sizeof(*s);i++)
        p[i]=0;
    s->hw=hw;
    for(i=0;i<GPU_MAX_JOBS;i++)
        s->jobs[i].first_dependent=NO_EDGE;
    for(i=0;i<GPU_MAX_EDGES;i++)
        s->edges[i].next=(i+1<GPU_MAX_EDGES)?(uint16_t)(i+1):NO_EDGE;
    s->edge_free_head=0;
    for(i=0;i<GPU_MAX_SLOTS;i++)
        s->slot_job[i]=NO_SLOT_JOB;
}
static void edge_free(gpu_scheduler *s, uint16_t e) {
    s->edges[e].next=s->edge_free_head; s->edge_free_head=e;
}
static void resolve_dependents(gpu_scheduler *s, unsigned parent) {
    uint16_t e=s->jobs[parent].first_dependent;
    s->jobs[parent].first_dependent=NO_EDGE;
    while(e!=NO_EDGE) {
        uint16_t next=s->edges[e].next;
        gpu_job *child=&s->jobs[s->edges[e].dependent];
        if(child->state==GPU_BLOCKED && child->pending_deps && --child->pending_deps==0)
            child->state=GPU_READY;
        edge_free(s,e); e=next;
    }
}

gpu_result gpu_submit(gpu_scheduler *s, gpu_job_desc desc, const gpu_job_id *deps, uint16_t ndeps, gpu_job_id *out) {
    int free_i=-1;
    unsigned i, d, k, live, available;
    uint16_t e;
    gpu_job *job;
    if(!out || (ndeps && !deps) || desc.priority>GPU_COMPUTE)
        return GPU_ERR_DEP;
    for(i=0;i<GPU_MAX_JOBS;i++) if(s->jobs[i].state==GPU_FREE) {
        free_i=(int)i;break;
    }
    if(free_i<0) return GPU_ERR_FULL;
    /* Validate dependencies and count live ones before mutating state. */
    live=0;
    for(d=0;d<ndeps;d++) {
        int j=idx(s,deps[d]);
        if(j<0 || s->jobs[j].state==GPU_CANCELLED) return GPU_ERR_DEP;
        for(k=0;k<d;k++) if(deps[k]==deps[d]) return GPU_ERR_DEP;
        if(s->jobs[j].state!=GPU_DONE) live++;
    }
    available=0;
    for(e=s->edge_free_head;e!=NO_EDGE;e=s->edges[e].next) available++;
    if(available<live) return GPU_ERR_CAPACITY;
    job=&s->jobs[free_i];
    job->shader_pc=desc.shader_pc; job->base_warp_id=desc.base_warp_id;
    job->warp_count=desc.warp_count; job->next_warp=job->completed=0;
    job->priority=(uint8_t)desc.priority; job->pending_deps=(uint16_t)live;
    job->first_dependent=NO_EDGE;
    job->state=live?GPU_BLOCKED:GPU_READY;
    *out=id_of(s,(unsigned)free_i);
    for(d=0;d<ndeps;d++) {
        int j=idx(s,deps[d]);
        if(s->jobs[j].state==GPU_DONE) continue;
        e=s->edge_free_head; s->edge_free_head=s->edges[e].next;
        s->edges[e].dependent=(uint8_t)free_i;
        s->edges[e].next=s->jobs[j].first_dependent;
        s->jobs[j].first_dependent=e;
    }
    return GPU_OK;
}
static int choose(gpu_scheduler *s) {
    unsigned p, step;
    for(p=0;p<2;p++) {
        for(step=0;step<GPU_MAX_JOBS;step++) {
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
    bool changed;
    unsigned i, slot_i;
    while((slot=s->hw.pop_done(s->hw.ctx))>=0) {
        gpu_job *j;
        if(slot>=GPU_MAX_SLOTS || s->slot_job[slot]==NO_SLOT_JOB) continue; /* HW contract violation */
        i=s->slot_job[slot]; s->slot_job[slot]=NO_SLOT_JOB;
        j=&s->jobs[i]; j->completed++;
        if(j->completed==j->warp_count) {j->state=GPU_DONE; resolve_dependents(s,i);}
    }
    /* Empty jobs complete without a hardware launch. Repeat for dependency chains. */
    do {
        changed=false;
        for(i=0;i<GPU_MAX_JOBS;i++) {
            gpu_job *j=&s->jobs[i];
            if(j->state==GPU_READY && j->warp_count==0) {
                j->state=GPU_DONE; resolve_dependents(s,i); changed=true;
            }
        }
    } while(changed);
    for(slot_i=0;slot_i<GPU_MAX_SLOTS;slot_i++) {
        int ji;
        gpu_job *j;
        uint32_t logical;
        if(s->slot_job[slot_i]!=NO_SLOT_JOB || !s->hw.slot_available(s->hw.ctx,(uint8_t)slot_i)) continue;
        ji=choose(s); if(ji<0) break;
        j=&s->jobs[ji];
        logical=j->base_warp_id+j->next_warp;
        if(s->hw.launch(s->hw.ctx,(uint8_t)slot_i,j->shader_pc,logical)) {
            s->slot_job[slot_i]=(uint16_t)ji;
            j->next_warp++; j->state=GPU_ACTIVE;
        }
    }
}

gpu_result gpu_job_status(const gpu_scheduler *s, gpu_job_id id, gpu_job_state *state) {
    int i=idx(s,id); if(i<0 || !state) return GPU_ERR_ID;
    *state=(gpu_job_state)s->jobs[i].state; return GPU_OK;
}

gpu_result gpu_cancel(gpu_scheduler *s, gpu_job_id id) {
    /* The tree is walked breadth-first with each job marked once. A recursive walk
       visits a job once per path, which is exponential on chains of diamonds. */
    uint8_t queue[GPU_MAX_JOBS], in_tree[GPU_MAX_JOBS];
    unsigned i, head, n;
    uint16_t e, *p;
    int root=idx(s,id); if(root<0) return GPU_ERR_ID;
    if(s->jobs[root].state==GPU_CANCELLED) return GPU_OK;
    for(i=0;i<GPU_MAX_JOBS;i++) in_tree[i]=0;
    queue[0]=(uint8_t)root; in_tree[root]=1; n=1;
    /* Check every descendant before touching anything: cancellation is all or nothing. */
    for(head=0;head<n;head++) {
        const gpu_job *j=&s->jobs[queue[head]];
        if((j->state!=GPU_BLOCKED && j->state!=GPU_READY) || j->next_warp) return GPU_ERR_STATE;
        for(e=j->first_dependent;e!=NO_EDGE;e=s->edges[e].next) {
            unsigned d=s->edges[e].dependent;
            if(!in_tree[d]) { in_tree[d]=1; queue[n++]=(uint8_t)d; }
        }
    }
    /* Free every edge into the tree, from live parents outside it and from inside.
       Edges out of the tree do not exist: every dependent of a tree job is in the tree. */
    for(i=0;i<GPU_MAX_JOBS;i++) {
        p=&s->jobs[i].first_dependent;
        while(*p!=NO_EDGE) {
            e=*p;
            if(in_tree[s->edges[e].dependent]) { *p=s->edges[e].next; edge_free(s,e); }
            else p=&s->edges[e].next;
        }
    }
    for(head=0;head<n;head++) {
        gpu_job *j=&s->jobs[queue[head]];
        j->pending_deps=0; j->state=GPU_CANCELLED;
    }
    return GPU_OK;
}

gpu_result gpu_release(gpu_scheduler *s, gpu_job_id id) {
    int i=idx(s,id);
    gpu_job *j;
    if(i<0) return GPU_ERR_ID;
    j=&s->jobs[i];
    if(j->state!=GPU_DONE && j->state!=GPU_CANCELLED) return GPU_ERR_STATE;
    if(j->first_dependent!=NO_EDGE) return GPU_ERR_STATE;
    /* Job 127 with generation 511 would get ID 0xFFFF == GPU_INVALID_JOB: skip that generation. */
    do j->generation=(uint16_t)((j->generation+1)&511u);
    while(id_of(s,(unsigned)i)==GPU_INVALID_JOB);
    j->state=GPU_FREE;
    return GPU_OK;
}
