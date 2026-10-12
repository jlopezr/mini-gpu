/* test-scheduler.c - ejemplo de uso y pruebas del scheduler de jobs de GPU
 *
 * El mismo fuente corre en la CPU de MiniISA (mini-lcc, sin libc) y en el anfitrion:
 *
 *   make sim     en el simulador: main devuelve 0, o la linea del primer CHECK que falla (R1)
 *   make test    en el anfitrion, con -DTEST_HOST: ademas imprime cada fallo
 *
 * La GPU es de mentira (`fake_gpu`): implementa los tres callbacks de gpu_hw_ops
 * con el contrato del README y deja que cada prueba decida cuando acaba un warp.
 * `example_frame` es el ejemplo de uso; el resto, las pruebas.
 */
#include "scheduler.h"

#ifdef TEST_HOST
#include <stdio.h>
#define REPORT(line, text) printf("test-scheduler.c:%d: falla %s\n", line, text)
#else
#define REPORT(line, text) ((void)0)
#endif

static int failures, first_failure;

#define CHECK(cond) check((cond) != 0, __LINE__, #cond)

static void check(int ok, int line, const char *text) {
    if(ok) return;
    if(!failures) first_failure=line;
    failures++;
    REPORT(line, text);
    (void)text;
}

/* ---- GPU de mentira ---------------------------------------------------- */

#define LOG_SIZE 64

typedef struct {
    bool busy[GPU_MAX_SLOTS];      /* lanzado y aun sin consumir con pop_done */
    bool finished[GPU_MAX_SLOTS];  /* terminado, esperando a pop_done */
    bool refuse;                   /* launch lo rechaza todo */
    int bogus;                     /* si >= 0, pop_done lo devuelve una vez (slot falso) */
    unsigned launches;
    uint32_t log_pc[LOG_SIZE], log_warp[LOG_SIZE];
} fake_gpu;

static int fake_pop_done(void *ctx) {
    fake_gpu *g=(fake_gpu *)ctx;
    int slot;
    if(g->bogus>=0) { slot=g->bogus; g->bogus=-1; return slot; }
    for(slot=0;slot<GPU_MAX_SLOTS;slot++)
        if(g->finished[slot]) { g->finished[slot]=false; g->busy[slot]=false; return slot; }
    return -1;
}

static bool fake_slot_available(void *ctx, uint8_t slot) {
    return !((fake_gpu *)ctx)->busy[slot];
}

static bool fake_launch(void *ctx, uint8_t slot, uint32_t pc, uint32_t logical_warp) {
    fake_gpu *g=(fake_gpu *)ctx;
    if(g->refuse || g->busy[slot]) return false;
    g->busy[slot]=true;
    if(g->launches<LOG_SIZE) { g->log_pc[g->launches]=pc; g->log_warp[g->launches]=logical_warp; }
    g->launches++;
    return true;
}

static void fake_init(fake_gpu *g) {
    unsigned i;
    for(i=0;i<GPU_MAX_SLOTS;i++) { g->busy[i]=false; g->finished[i]=false; }
    g->refuse=false; g->bogus=-1; g->launches=0;
}

/* Todos los warps en marcha terminan. */
static void fake_finish_all(fake_gpu *g) {
    unsigned i;
    for(i=0;i<GPU_MAX_SLOTS;i++)
        if(g->busy[i]) g->finished[i]=true;
}

static unsigned fake_busy_count(const fake_gpu *g) {
    unsigned i, n=0;
    for(i=0;i<GPU_MAX_SLOTS;i++) n+=g->busy[i]?1u:0u;
    return n;
}

/* ---- Ayudas ------------------------------------------------------------ */

static gpu_scheduler sched;
static fake_gpu gpu;

static void setup(void) {
    gpu_hw_ops hw;
    fake_init(&gpu);
    hw.pop_done=fake_pop_done;
    hw.slot_available=fake_slot_available;
    hw.launch=fake_launch;
    hw.ctx=&gpu;
    gpu_scheduler_init(&sched, hw);
}

/* En C89 un struct automatico solo se inicializa con constantes: de ahi esta funcion. */
static gpu_job_desc desc(uint32_t pc, uint32_t base_warp, uint32_t warps, gpu_priority priority) {
    gpu_job_desc d;
    d.shader_pc=pc; d.base_warp_id=base_warp; d.warp_count=warps; d.priority=priority;
    return d;
}

static gpu_job_state state_of(gpu_job_id id) {
    gpu_job_state st;
    if(gpu_job_status(&sched, id, &st)!=GPU_OK) return GPU_FREE;
    return st;
}

/* Una vuelta del bucle de la CPU: recoge terminaciones y lanza. Luego acaba todo lo lanzado. */
static void run_rounds(unsigned rounds) {
    while(rounds--) {
        gpu_scheduler_poll(&sched);
        fake_finish_all(&gpu);
    }
    gpu_scheduler_poll(&sched);
}

/* ---- Ejemplo de uso ---------------------------------------------------- */

/* Un fotograma: un compute de fisica, una pasada de render que depende de el y un
 * post-proceso que depende del render. Con los IDs se pregunta el estado y, al
 * acabar, se liberan las entradas para reutilizarlas.
 */
static void example_frame(void) {
    gpu_job_id physics, scene, post;
    gpu_job_desc d;

    setup();

    d=desc(0x1000, 0, 4, GPU_COMPUTE);             /* shader en 0x1000, warps logicos 0..3 */
    CHECK(gpu_submit(&sched, d, 0, 0, &physics)==GPU_OK);
    d=desc(0x2000, 0, 12, GPU_RENDER);
    CHECK(gpu_submit(&sched, d, &physics, 1, &scene)==GPU_OK);
    d=desc(0x3000, 100, 2, GPU_RENDER);
    CHECK(gpu_submit(&sched, d, &scene, 1, &post)==GPU_OK);

    CHECK(state_of(physics)==GPU_READY);
    CHECK(state_of(scene)==GPU_BLOCKED);

    gpu_scheduler_poll(&sched);                   /* 4 warps de fisica a 4 de los 8 slots */
    CHECK(gpu.launches==4);
    CHECK(state_of(physics)==GPU_ACTIVE);
    CHECK(gpu.log_pc[0]==0x1000 && gpu.log_warp[0]==0 && gpu.log_warp[3]==3);

    run_rounds(4);                                /* fisica -> escena (12 warps, 2 tandas) -> post */
    CHECK(state_of(physics)==GPU_DONE);
    CHECK(state_of(scene)==GPU_DONE);
    CHECK(state_of(post)==GPU_DONE);
    CHECK(gpu.launches==4+12+2);
    CHECK(gpu.log_pc[16]==0x3000 && gpu.log_warp[16]==100 && gpu.log_warp[17]==101);

    CHECK(gpu_release(&sched, physics)==GPU_OK);
    CHECK(gpu_release(&sched, scene)==GPU_OK);
    CHECK(gpu_release(&sched, post)==GPU_OK);
    CHECK(gpu_job_status(&sched, physics, 0)==GPU_ERR_ID);
}

/* ---- Pruebas ------------------------------------------------------------ */

static void test_render_before_compute(void) {
    gpu_job_id c, r;
    gpu_job_desc d;
    setup();
    d=desc(0xC0, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &c)==GPU_OK);
    d=desc(0xA0, 0, 1, GPU_RENDER);
    CHECK(gpu_submit(&sched, d, 0, 0, &r)==GPU_OK);
    gpu_scheduler_poll(&sched);
    CHECK(gpu.launches==2);
    CHECK(gpu.log_pc[0]==0xA0 && gpu.log_pc[1]==0xC0);   /* aunque el compute llego antes */
}

static void test_slots_limit_and_round_robin(void) {
    gpu_job_id a, b;
    gpu_job_desc d;
    unsigned i, from_a=0;
    setup();
    d=desc(0xA, 0, 20, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &a)==GPU_OK);
    d=desc(0xB, 0, 20, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &b)==GPU_OK);
    gpu_scheduler_poll(&sched);
    CHECK(gpu.launches==GPU_MAX_SLOTS);
    CHECK(fake_busy_count(&gpu)==GPU_MAX_SLOTS);
    for(i=0;i<GPU_MAX_SLOTS;i++) from_a+=gpu.log_pc[i]==0xA?1u:0u;
    CHECK(from_a==GPU_MAX_SLOTS/2);                        /* se alternan, warp a warp */
    gpu_scheduler_poll(&sched);                            /* nada termino: no lanza mas */
    CHECK(gpu.launches==GPU_MAX_SLOTS);
    run_rounds(5);
    CHECK(state_of(a)==GPU_DONE && state_of(b)==GPU_DONE);
    CHECK(gpu.launches==40);
}

static void test_dependencies(void) {
    gpu_job_id a, b, c, done_dep, deps[2];
    gpu_job_desc d;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &a)==GPU_OK);
    CHECK(gpu_submit(&sched, d, 0, 0, &b)==GPU_OK);
    deps[0]=a; deps[1]=b;
    CHECK(gpu_submit(&sched, d, deps, 2, &c)==GPU_OK);
    CHECK(state_of(c)==GPU_BLOCKED);
    gpu_scheduler_poll(&sched);
    gpu.finished[0]=true;                                  /* solo acaba a */
    gpu_scheduler_poll(&sched);
    CHECK(state_of(a)==GPU_DONE);
    CHECK(state_of(c)==GPU_BLOCKED);                       /* todavia espera a b */
    run_rounds(2);
    CHECK(state_of(c)==GPU_DONE);
    /* Una dependencia ya DONE cuenta como satisfecha. */
    CHECK(gpu_submit(&sched, d, &a, 1, &done_dep)==GPU_OK);
    CHECK(state_of(done_dep)==GPU_READY);
}

static void test_empty_jobs(void) {
    gpu_job_id a, e1, e2, after;
    gpu_job_desc d;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &a)==GPU_OK);
    d=desc(0, 0, 0, GPU_RENDER);                           /* sin warps */
    CHECK(gpu_submit(&sched, d, &a, 1, &e1)==GPU_OK);
    CHECK(gpu_submit(&sched, d, &e1, 1, &e2)==GPU_OK);
    d=desc(0x20, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, &e2, 1, &after)==GPU_OK);
    run_rounds(1);                                         /* a acaba; e1 y e2 en el mismo poll */
    CHECK(state_of(e1)==GPU_DONE && state_of(e2)==GPU_DONE);
    CHECK(state_of(after)==GPU_ACTIVE);                    /* y after ya se lanza en ese poll */
    run_rounds(1);
    CHECK(state_of(after)==GPU_DONE);
    CHECK(gpu.launches==2);                                /* los vacios no se lanzan */
}

static void test_submit_errors(void) {
    gpu_job_id a, x, stale, deps[2];
    gpu_job_desc d;
    unsigned i;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, 0)==GPU_ERR_DEP);    /* sin out */
    CHECK(gpu_submit(&sched, d, 0, 1, &x)==GPU_ERR_DEP);   /* ndeps sin deps */
    d.priority=(gpu_priority)2;
    CHECK(gpu_submit(&sched, d, 0, 0, &x)==GPU_ERR_DEP);   /* prioridad que no existe */
    d.priority=GPU_COMPUTE;
    CHECK(gpu_submit(&sched, d, 0, 0, &a)==GPU_OK);
    deps[0]=a; deps[1]=a;
    CHECK(gpu_submit(&sched, d, deps, 2, &x)==GPU_ERR_DEP); /* repetida */
    stale=a;
    CHECK(gpu_cancel(&sched, a)==GPU_OK);
    CHECK(gpu_submit(&sched, d, &a, 1, &x)==GPU_ERR_DEP);  /* cancelada */
    CHECK(gpu_release(&sched, a)==GPU_OK);
    CHECK(gpu_submit(&sched, d, &stale, 1, &x)==GPU_ERR_DEP); /* ID obsoleto */
    CHECK(gpu_cancel(&sched, stale)==GPU_ERR_ID);
    CHECK(gpu_release(&sched, stale)==GPU_ERR_ID);
    /* Tabla llena. */
    for(i=0;i<GPU_MAX_JOBS;i++) CHECK(gpu_submit(&sched, d, 0, 0, &x)==GPU_OK);
    CHECK(gpu_submit(&sched, d, 0, 0, &x)==GPU_ERR_FULL);
}

/* 64 padres y unos hijos que dependen de los 64: 8 hijos gastan las 512 aristas.
 * El noveno no cabe, y GPU_ERR_CAPACITY no toca nada: ni una entrada ni una arista. */
#define PARENTS 64
static void test_edge_capacity(void) {
    gpu_job_id parents[PARENTS], children[GPU_MAX_EDGES/PARENTS], x;
    gpu_job_desc d;
    unsigned i;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    for(i=0;i<PARENTS;i++) CHECK(gpu_submit(&sched, d, 0, 0, &parents[i])==GPU_OK);
    for(i=0;i<GPU_MAX_EDGES/PARENTS;i++)
        CHECK(gpu_submit(&sched, d, parents, PARENTS, &children[i])==GPU_OK);
    CHECK(gpu_submit(&sched, d, parents, PARENTS, &x)==GPU_ERR_CAPACITY);
    CHECK(gpu_submit(&sched, d, parents, 1, &x)==GPU_ERR_CAPACITY);
    CHECK(gpu_submit(&sched, d, 0, 0, &x)==GPU_OK);         /* sin dependencias si cabe */
    /* Cancelar un hijo devuelve sus 64 aristas. */
    CHECK(gpu_cancel(&sched, children[0])==GPU_OK);
    CHECK(gpu_submit(&sched, d, parents, PARENTS, &x)==GPU_OK);
    CHECK(gpu_submit(&sched, d, parents, 1, &x)==GPU_ERR_CAPACITY);
    /* Y al acabar los padres, todas: los hijos pasan a READY. */
    run_rounds(PARENTS/GPU_MAX_SLOTS);
    CHECK(state_of(children[1])==GPU_READY || state_of(children[1])==GPU_ACTIVE
          || state_of(children[1])==GPU_DONE);
    CHECK(gpu_submit(&sched, d, parents, PARENTS, &x)==GPU_OK); /* padres DONE: no gastan aristas */
}

static void test_cancel_tree(void) {
    gpu_job_id root, other, child, grandchild, deps[2];
    gpu_job_desc d;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &root)==GPU_OK);
    CHECK(gpu_submit(&sched, d, 0, 0, &other)==GPU_OK);
    deps[0]=root; deps[1]=other;
    CHECK(gpu_submit(&sched, d, deps, 2, &child)==GPU_OK);
    CHECK(gpu_submit(&sched, d, &child, 1, &grandchild)==GPU_OK);
    CHECK(gpu_cancel(&sched, root)==GPU_OK);
    CHECK(state_of(root)==GPU_CANCELLED);
    CHECK(state_of(child)==GPU_CANCELLED);
    CHECK(state_of(grandchild)==GPU_CANCELLED);
    CHECK(state_of(other)==GPU_READY);                     /* el otro padre sigue */
    CHECK(gpu_cancel(&sched, root)==GPU_OK);               /* idempotente */
    /* `other` ya no tiene a `child` en su lista: se puede liberar al acabar. */
    run_rounds(1);
    CHECK(state_of(other)==GPU_DONE);
    CHECK(gpu_release(&sched, other)==GPU_OK);
    CHECK(gpu_release(&sched, child)==GPU_OK);
    CHECK(gpu.launches==1);
}

/* Si un descendiente ya lanzo warps, no se cancela nada. */
static void test_cancel_is_all_or_nothing(void) {
    gpu_job_id a, b, c, deps[2];
    gpu_job_desc d;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &a)==GPU_OK);
    gpu_scheduler_poll(&sched);
    CHECK(state_of(a)==GPU_ACTIVE);
    CHECK(gpu_cancel(&sched, a)==GPU_ERR_STATE);           /* ya en la GPU */
    gpu.refuse=true;                                       /* que nada mas llegue a lanzarse */
    CHECK(gpu_submit(&sched, d, 0, 0, &b)==GPU_OK);
    deps[0]=a; deps[1]=b;
    CHECK(gpu_submit(&sched, d, deps, 2, &c)==GPU_OK);
    gpu.refuse=false;
    gpu_scheduler_poll(&sched);                            /* b se lanza; c sigue esperando */
    CHECK(state_of(b)==GPU_ACTIVE);
    CHECK(state_of(c)==GPU_BLOCKED);
    CHECK(gpu_cancel(&sched, c)==GPU_OK);                  /* una hoja bloqueada si */
    CHECK(gpu_submit(&sched, d, &b, 1, &c)==GPU_OK);
    CHECK(gpu_cancel(&sched, b)==GPU_ERR_STATE);
    CHECK(state_of(c)==GPU_BLOCKED);                       /* intacto */
    run_rounds(2);
    CHECK(state_of(c)==GPU_DONE);
}

/* Regresion: 63 capas de dos jobs, cada uno dependiente de los dos de la capa anterior.
 * Hay 2^63 caminos desde la raiz; un recorrido recursivo sin marcas no acaba nunca. */
static void test_cancel_diamonds(void) {
    gpu_job_id root, left, right, deps[2];
    gpu_job_desc d;
    unsigned layer;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &root)==GPU_OK);
    deps[0]=root; deps[1]=root;
    for(layer=0;layer<(GPU_MAX_JOBS-1)/2;layer++) {
        unsigned n=layer?2u:1u;
        CHECK(gpu_submit(&sched, d, deps, (uint16_t)n, &left)==GPU_OK);
        CHECK(gpu_submit(&sched, d, deps, (uint16_t)n, &right)==GPU_OK);
        deps[0]=left; deps[1]=right;
    }
    CHECK(gpu_cancel(&sched, root)==GPU_OK);
    CHECK(state_of(left)==GPU_CANCELLED && state_of(right)==GPU_CANCELLED);
    run_rounds(1);
    CHECK(gpu.launches==0);
}

static void test_release(void) {
    gpu_job_id a, b;
    gpu_job_desc d;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &a)==GPU_OK);
    CHECK(gpu_release(&sched, a)==GPU_ERR_STATE);          /* READY */
    gpu_scheduler_poll(&sched);
    CHECK(gpu_release(&sched, a)==GPU_ERR_STATE);          /* ACTIVE */
    run_rounds(1);
    CHECK(gpu_release(&sched, a)==GPU_OK);
    CHECK(gpu_submit(&sched, d, 0, 0, &b)==GPU_OK);        /* misma entrada, otra generacion */
    CHECK((a&127u)==(b&127u) && a!=b);
    CHECK(gpu_job_status(&sched, a, 0)==GPU_ERR_ID);
}

/* Regresion: el job 127 con generacion 511 tendria el ID 0xFFFF, que es GPU_INVALID_JOB. */
static void test_id_never_invalid(void) {
    gpu_job_id x, last;
    gpu_job_desc d;
    unsigned i, ok=1, distinct=1;
    setup();
    d=desc(0x10, 0, 1, GPU_COMPUTE);
    for(i=0;i<GPU_MAX_JOBS-1;i++) CHECK(gpu_submit(&sched, d, 0, 0, &x)==GPU_OK);
    last=GPU_INVALID_JOB;
    for(i=0;i<520;i++) {                                   /* pasa por la generacion 511, que se salta */
        if(gpu_submit(&sched, d, 0, 0, &x)!=GPU_OK) { ok=0; break; }
        if((x&127u)!=127u || x==GPU_INVALID_JOB) ok=0;
        if(x==last) distinct=0;
        if(gpu_cancel(&sched, x)!=GPU_OK || gpu_release(&sched, x)!=GPU_OK) ok=0;
        last=x;
    }
    CHECK(ok);
    CHECK(distinct);
    CHECK(gpu_job_status(&sched, GPU_INVALID_JOB, 0)==GPU_ERR_ID);
}

/* El hardware rechaza un launch, o pop_done devuelve un slot que no estaba en uso. */
static void test_hardware_hiccups(void) {
    gpu_job_id a;
    gpu_job_state st;
    gpu_job_desc d;
    setup();
    d=desc(0x10, 0, 2, GPU_COMPUTE);
    CHECK(gpu_submit(&sched, d, 0, 0, &a)==GPU_OK);
    gpu.refuse=true;
    gpu_scheduler_poll(&sched);
    CHECK(gpu.launches==0 && state_of(a)==GPU_READY);
    gpu.refuse=false;
    gpu.bogus=5;                                           /* slot libre */
    gpu_scheduler_poll(&sched);
    CHECK(gpu.launches==2);
    gpu.bogus=GPU_MAX_SLOTS+3;                             /* fuera de rango */
    gpu_scheduler_poll(&sched);
    CHECK(gpu_job_status(&sched, a, &st)==GPU_OK && st==GPU_ACTIVE);
    run_rounds(1);
    CHECK(state_of(a)==GPU_DONE);
}

int main(void) {
    example_frame();
    test_render_before_compute();
    test_slots_limit_and_round_robin();
    test_dependencies();
    test_empty_jobs();
    test_submit_errors();
    test_edge_capacity();
    test_cancel_tree();
    test_cancel_is_all_or_nothing();
    test_cancel_diamonds();
    test_release();
    test_id_never_invalid();
    test_hardware_hiccups();
#ifdef TEST_HOST
    if(failures) { printf("%d fallos\n", failures); return 1; }
    printf("todo bien\n");
#endif
    return first_failure;
}
