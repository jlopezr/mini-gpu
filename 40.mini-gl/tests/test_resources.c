/* Recursos y handles (mgl_resources.c): los dos modelos de memoria, resolución
   de handles a direcciones, handles inválidos o destruidos, formatos
   rechazados y límites. */
#include "fixture3d.h"
#include "mgl_bytes.h"

static const float xyz[9] = {-0.5f, -0.5f, 0.0f, 0.5f, -0.5f, 0.0f, 0.0f, 0.5f, 0.0f};
static const unsigned short idx[3] = {0, 1, 2};

static mgl_mesh_desc_t app_desc(void) {
    mgl_mesh_desc_t d;
    d.vertex_addr = T_APP_ADDR;
    d.index_addr = T_APP_ADDR + 36U;
    d.vertex_count = 3;
    d.index_count = 3;
    d.vertex_format = MGL_VERTEX_POSITION_F32_XYZ;
    d.index_format = MGL_INDEX_UINT16;
    d.vertex_stride = 12;
    return d;
}

/* Memoria de la aplicación: MiniGL no copia; DRAW_INDEXED lleva sus direcciones. */
static void test_app_memory(void) {
    mgl_mesh_desc_t d = app_desc(), got;
    mgl_mesh_t mesh;
    const unsigned char *p;
    t_init(4096);
    mesh = mgl_create_mesh(&d);
    CHECK(mesh != 0);
    CHECK(mgl_mesh_info(mesh, &got) == MGL_OK);
    CHECK(got.vertex_addr == T_APP_ADDR && got.index_addr == T_APP_ADDR + 36U && got.vertex_count == 3U);
    t_begin();
    mgl_draw_mesh(mesh);
    mgl_end_frame();
    mgl_set_deferred(0);
    p = t_find(MGL_CMD_DRAW_INDEXED, 0);
    CHECK(p && RD32(p + 8) == T_APP_ADDR && RD32(p + 12) == T_APP_ADDR + 36U);
    /* el handle no aparece en ningún sitio del comando */
    CHECK(p && RD32(p + 8) != mesh && RD32(p + 12) != mesh);
}

/* Memoria de MiniGL: copia en la RAM compartida, en el formato serializado. */
static void test_managed_memory(void) {
    mgl_mesh_desc_t d;
    mgl_mesh_t a, b;
    const unsigned char *v;
    int i;
    t_init(4096);
    a = mgl_create_mesh_copy(xyz, 3, idx, 3);
    b = mgl_create_mesh_copy(xyz, 3, idx, 3);
    CHECK(a && b && a != b);
    CHECK(mgl_mesh_info(a, &d) == MGL_OK);
    CHECK(d.vertex_addr >= T_HEAP_ADDR && d.vertex_addr + 36U <= T_HEAP_ADDR + T_HEAP_BYTES);
    CHECK((d.vertex_addr & 15U) == 0 && (d.index_addr & 3U) == 0 && d.vertex_stride == 12U);
    v = (const unsigned char *)mgl_memory_ptr(&t_mem, d.vertex_addr, 36, 4);
    for (i = 0; v && i < 9; i++) CHECK(RD32(v + 4 * i) == mgl_real_to_f32(xyz[i]));
    v = (const unsigned char *)mgl_memory_ptr(&t_mem, d.index_addr, 6, 2);
    CHECK(v && RD16(v) == 0 && RD16(v + 2) == 1 && RD16(v + 4) == 2);
    CHECK(mgl_mesh_info(b, &d) == MGL_OK && d.vertex_addr > T_HEAP_ADDR);
    /* Se dibuja con el renderer como cualquier otra */
    t_begin();
    mgl_clear(0);
    mgl_draw_mesh(b);
    CHECK(t_end_and_run() == MGR_OK);
    CHECK(t_count(0xffff) > 0);
}

/* Handles: 0, destruidos y viejos (el hueco reutilizado da otro handle). */
static void test_handles(void) {
    mgl_mesh_desc_t d = app_desc();
    mgl_mesh_t a, b;
    t_init(4096);
    CHECK(mgl_mesh_info(0, &d) == MGL_ERR_HANDLE);
    CHECK(mgl_mesh_info(0x12345678U, &d) == MGL_ERR_HANDLE);
    a = mgl_create_mesh(&d);
    CHECK(mgl_destroy_mesh(a) == MGL_OK);
    CHECK(mgl_destroy_mesh(a) == MGL_ERR_HANDLE);
    CHECK(mgl_mesh_info(a, &d) == MGL_ERR_HANDLE);
    b = mgl_create_mesh(&d);
    CHECK(b != 0 && b != a && (b & 0xffffU) == (a & 0xffffU)); /* mismo hueco, otro handle */
    t_begin();
    mgl_draw_mesh(a);
    CHECK(mgl_cmd_status(&t_cmd) == MGL_ERR_HANDLE);
    CHECK(t_find(MGL_CMD_DRAW_INDEXED, 0) == 0);
    mgl_end_frame();
    mgl_set_deferred(0);
    /* mgl_resources_init las destruye todas */
    mgl_resources_init(&t_mem, T_HEAP_ADDR, T_HEAP_BYTES);
    CHECK(mgl_mesh_info(b, &d) == MGL_ERR_HANDLE);
}

/* Formatos reservados (UNSUPPORTED en el renderer; aquí ni se crean) y descripciones malas. */
static void test_rejected(void) {
    mgl_mesh_desc_t d;
    t_init(4096);
    d = app_desc();
    d.vertex_format = MGL_VERTEX_POSITION_Q16_16_XYZ;
    CHECK(mgl_create_mesh(&d) == 0);
    d = app_desc();
    d.index_format = MGL_INDEX_UINT32;
    CHECK(mgl_create_mesh(&d) == 0);
    d = app_desc();
    d.vertex_stride = 10;
    CHECK(mgl_create_mesh(&d) == 0);
    d = app_desc();
    d.index_count = 4;
    CHECK(mgl_create_mesh(&d) == 0);
    d = app_desc();
    d.vertex_addr = T_RAM_ADDR + T_RAM_SIZE - 16; /* no caben 36 bytes */
    CHECK(mgl_create_mesh(&d) == 0);
    d = app_desc();
    d.vertex_addr = 0x00100000U; /* fuera de la RAM compartida */
    CHECK(mgl_create_mesh(&d) == 0);
    d = app_desc();
    d.index_addr = T_APP_ADDR + 37U; /* desalineado */
    CHECK(mgl_create_mesh(&d) == 0);
    CHECK(mgl_create_mesh(0) == 0);
    CHECK(mgl_create_mesh_copy(xyz, 0, idx, 3) == 0);
}

/* Límites: memoria de MiniGL agotada (sin dejar nada a medias) y tabla llena. */
static void test_limits(void) {
    static float big[3 * 2000];
    static unsigned short big_idx[3 * 2000];
    mgl_mesh_desc_t d = app_desc();
    mgl_u32 before, after;
    int i, made = 0;
    t_init(4096);
    for (i = 0; i < 3 * 2000; i++) {
        big[i] = (float)i;
        big_idx[i] = (unsigned short)(i % 2000);
    }
    before = mgl_alloc(4, 4);
    CHECK(mgl_create_mesh_copy(big, 2000, big_idx, 6000) == 0); /* 24000 + 12000 > 32 KB */
    after = mgl_alloc(4, 4);
    CHECK(after == before + 4U); /* lo que se reservó para la malla que no cupo, se devolvió */
    CHECK(mgl_alloc(T_HEAP_BYTES, 4) == 0 && mgl_alloc(16, 3) == 0);
    for (i = 0; i < MGL_MAX_MESHES + 4; i++)
        if (mgl_create_mesh(&d)) made++;
    CHECK(made == MGL_MAX_MESHES);
}

/* Memoria de frame: mallas que valen un frame; mgl_begin_frame la vacía. */
static void test_frame_memory(void) {
    mgl_mesh_desc_t d;
    mgl_mesh_t a, b;
    mgl_u32 first;
    t_init(4096);
    t_begin();
    a = mgl_create_mesh_frame(xyz, 3, idx, 3);
    CHECK(a && mgl_mesh_info(a, &d) == MGL_OK);
    CHECK(d.vertex_addr >= T_FRAME_ADDR && d.index_addr + 6U <= T_FRAME_ADDR + T_FRAME_BYTES);
    first = d.vertex_addr;
    mgl_clear(0);
    mgl_draw_mesh(a);
    CHECK(mgl_destroy_mesh(a) == MGL_OK); /* en cuanto se ha dibujado */
    b = mgl_create_mesh_frame(xyz, 3, idx, 3);
    CHECK(mgl_mesh_info(b, &d) == MGL_OK && d.vertex_addr > first); /* el mismo frame: más adelante */
    mgl_destroy_mesh(b);
    CHECK(t_end_and_run() == MGR_OK && t_count(0xffff) > 0);
    t_begin(); /* frame nuevo: vuelve a empezar */
    a = mgl_create_mesh_frame(xyz, 3, idx, 3);
    CHECK(mgl_mesh_info(a, &d) == MGL_OK && d.vertex_addr == first);
    mgl_destroy_mesh(a);
    mgl_end_frame();
    mgl_set_deferred(0);
    /* No cabe: 0, y no se queda nada a medias */
    CHECK(mgl_frame_alloc(T_FRAME_BYTES + 4U, 4) == 0);
    CHECK(mgl_frame_memory_init(T_RAM_ADDR + T_RAM_SIZE - 16U, 64U) == MGL_ERR_MEMORY);
    CHECK(mgl_create_mesh_frame(xyz, 3, idx, 3) == 0); /* sin memoria de frame */
}

int main(void) {
    test_app_memory();
    test_managed_memory();
    test_handles();
    test_rejected();
    test_limits();
    test_frame_memory();
    return t_report("test_resources: memoria de la aplicación, de MiniGL y de frame, handles y límites");
}
