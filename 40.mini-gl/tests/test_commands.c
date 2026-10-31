/* Codificación del command buffer: cabeceras, SET_MATRIX, DRAW_INDEXED,
   estado redundante, capacidad, compatibilidad 2D y lo que el renderer
   rechaza (formatos reservados, comandos mal formados). */
#include "fixture3d.h"
#include "mgl_bytes.h"
#include "mgr_stages.h"
#include <string.h>

static const float tri_xyz[9] = {-0.5f, -0.5f, 0.0f, 0.5f, -0.5f, 0.0f, 0.0f, 0.5f, 0.0f};
static const unsigned short tri_idx[3] = {0, 1, 2};

/* Cabecera de buffer y compatibilidad con V1: lo 2D sale igual que antes. */
static void test_header_and_2d(void) {
    const unsigned char *p;
    t_init(4096);
    CHECK(t_cmd.used == 16U);
    CHECK(RD32(t_cmd.bytes) == MGL_BUFFER_MAGIC && RD32(t_cmd.bytes + 4) == MGL_BUFFER_VERSION);
    CHECK(RD32(t_cmd.bytes + 8) == 16U && RD32(t_cmd.bytes + 12) == 4096U);
    mgl_set_deferred(&t_cmd);
    mgl_clear(0x1234);
    mgl_rect(1, 2, 3, 4);
    mgl_set_deferred(0);
    CHECK(t_cmd.used == 16U + 16U + 40U);
    CHECK(RD32(t_cmd.bytes + 4) == MGL_BUFFER_VERSION); /* sin 3D sigue siendo versión 1 */
    p = t_cmd.bytes + 16;
    CHECK(RD16(p) == MGL_CMD_CLEAR && RD16(p + 2) == 0 && RD32(p + 4) == 16U);
    CHECK(RD32(p + 8) == 0x1234U && RD32(p + 12) == 0U);
    CHECK(RD32(p + 16) == MGL_CMD_BATCH && RD32(p + 20) == 40U);
    /* V1 lo sigue aceptando; el renderer 3D no (no es versión 2). */
    CHECK(mgr_execute(&t_rnd, T_CMD_ADDR) == MGR_ERR_FORMAT);
}

/* El frame del cubo de docs/3d.md §12, comando a comando. */
static void test_cube_sequence(void) {
    static const unsigned int expected[] = {MGL_CMD_SET_RENDER_TARGET, MGL_CMD_CLEAR,
        MGL_CMD_SET_VIEWPORT, MGL_CMD_SET_MATRIX, MGL_CMD_SET_MATRIX, MGL_CMD_SET_MATRIX,
        MGL_CMD_SET_RENDER_STATE, MGL_CMD_SET_COLOR, MGL_CMD_DRAW_INDEXED, MGL_CMD_END_FRAME, 0};
    static const mgl_u32 sizes[] = {32, 16, 16, 80, 80, 80, 16, 16, 32, 16};
    mgl_mat4_t proj, view, model;
    mgl_mesh_t mesh;
    const unsigned char *p;
    mgl_u32 off;
    int i;
    t_init(4096);
    mesh = t_mesh(0, tri_xyz, 3, tri_idx, 3);
    CHECK(mesh != 0);
    mgl_mat4_perspective(&proj, 1.0f, 1.333f, 1.0f, 100.0f);
    mgl_mat4_translation(&view, 0.0f, 0.0f, -5.0f);
    mgl_mat4_rotation_y(&model, 0.3f);
    t_begin();
    CHECK(RD32(t_cmd.bytes + 4) == MGL_BUFFER_VERSION_3D);
    mgl_clear(0x2104);
    mgl_set_viewport(0, 0, T_W, T_H);
    mgl_set_matrix(MGL_MATRIX_PROJECTION, &proj);
    mgl_set_matrix(MGL_MATRIX_VIEW, &view);
    mgl_set_matrix(MGL_MATRIX_MODEL, &model);
    mgl_set_depth_test(1);
    mgl_set_depth_write(1);
    mgl_set_color(0xfc65);
    mgl_draw_mesh(mesh);
    CHECK(mgl_end_frame() == MGL_OK);
    mgl_set_deferred(0);
    for (i = 0; expected[i]; i++) CHECK(t_opcode_at(i) == expected[i]);
    CHECK(t_opcode_at(i) == 0);
    for (off = 16, i = 0; off < t_cmd.used; off += RD32(t_cmd.bytes + off + 4), i++) {
        CHECK(RD32(t_cmd.bytes + off + 4) == sizes[i]);
        CHECK(RD16(t_cmd.bytes + off + 2) == (i == 1 ? MGL_CLEAR_DEPTH : 0U));
    }
    CHECK(RD32(t_cmd.bytes + 8) == t_cmd.used);

    /* SET_RENDER_TARGET */
    p = t_find(MGL_CMD_SET_RENDER_TARGET, 0);
    CHECK(p && RD32(p + 8) == T_FB_ADDR && RD32(p + 12) == T_DEPTH_ADDR);
    CHECK(p && RD16(p + 16) == T_W && RD16(p + 18) == T_H && RD16(p + 20) == T_W && RD16(p + 22) == T_W);
    CHECK(p && RD16(p + 24) == MGL_COLOR_RGB565 && RD16(p + 26) == MGL_DEPTH_U16 && RD32(p + 28) == 0U);
    /* CLEAR con profundidad a lejos */
    p = t_find(MGL_CMD_CLEAR, 0);
    CHECK(p && RD32(p + 8) == 0x2104U && RD32(p + 12) == MGL_DEPTH_ONE);
    /* SET_VIEWPORT */
    p = t_find(MGL_CMD_SET_VIEWPORT, 0);
    CHECK(p && LOW(RD32(p + 8)) == 0 && HIGH(RD32(p + 8)) == 0);
    CHECK(p && LOW(RD32(p + 12)) == T_W && HIGH(RD32(p + 12)) == T_H);
    /* SET_MATRIX: Projection, View, Model en ese orden; valor copiado, bits IEEE little-endian */
    p = t_find(MGL_CMD_SET_MATRIX, 0);
    CHECK(p && RD32(p + 8) == MGL_MATRIX_PROJECTION && RD32(p + 12) == MGL_FORMAT_FLOAT32);
    for (i = 0; p && i < 16; i++) CHECK(RD32(p + 16 + 4 * i) == mgl_real_to_f32(proj.m[i]));
    p = t_find(MGL_CMD_SET_MATRIX, 1);
    CHECK(p && RD32(p + 8) == MGL_MATRIX_VIEW);
    CHECK(p && RD32(p + 16 + 4 * 14) == 0xC0A00000U); /* -5.0f */
    p = t_find(MGL_CMD_SET_MATRIX, 2);
    CHECK(p && RD32(p + 8) == MGL_MATRIX_MODEL);
    /* SET_RENDER_STATE y SET_COLOR */
    p = t_find(MGL_CMD_SET_RENDER_STATE, 0);
    CHECK(p && RD32(p + 8) == (MGL_STATE_DEPTH_TEST | MGL_STATE_DEPTH_WRITE) && RD32(p + 12) == 0U);
    p = t_find(MGL_CMD_SET_COLOR, 0);
    CHECK(p && RD32(p + 8) == 0xfc65U);
    /* DRAW_INDEXED: direcciones, no handles */
    p = t_find(MGL_CMD_DRAW_INDEXED, 0);
    CHECK(p && RD32(p + 8) == T_APP_ADDR && RD32(p + 12) == T_APP_ADDR + 36U);
    CHECK(p && RD32(p + 16) == 3U && RD32(p + 20) == 3U);
    CHECK(p && RD16(p + 24) == MGL_VERTEX_POSITION_F32_XYZ && RD16(p + 26) == MGL_INDEX_UINT16);
    CHECK(p && RD16(p + 28) == 12U && RD16(p + 30) == MGL_TOPOLOGY_TRIANGLES);
    /* END_FRAME lleva el número de frame */
    p = t_find(MGL_CMD_END_FRAME, 0);
    CHECK(p && RD32(p + 8) != 0U && RD32(p + 12) == 0U);
    CHECK(t_run() == MGR_OK);
    CHECK(t_rnd.stats.frames == 1U && t_rnd.stats.triangles == 1U);
}

/* SET_MATRIX ida y vuelta: lo que decodifica el renderer es la matriz original, bit a bit. */
static void test_matrix_roundtrip(void) {
    mgl_mat4_t m;
    mgr_state_t s;
    const unsigned char *p;
    int i;
    t_init(4096);
    for (i = 0; i < 16; i++) m.m[i] = (float)(i * i) * 0.37f - 3.0f;
    m.m[5] = -0.0f;
    t_begin();
    mgl_set_matrix(MGL_MATRIX_VIEW, &m);
    mgl_draw_mesh(t_mesh(0, tri_xyz, 3, tri_idx, 3));
    mgl_end_frame();
    mgl_set_deferred(0);
    p = t_find(MGL_CMD_SET_MATRIX, 1);
    CHECK(p && RD32(p + 8) == MGL_MATRIX_VIEW);
    if (!p) return;
    mgr_state_reset(&s);
    CHECK(mgr_state_matrix(&s, p) == MGR_OK);
    for (i = 0; i < 16; i++) CHECK(mgl_real_to_f32(s.matrix[1].m[i]) == mgl_real_to_f32(m.m[i]));
}

/* Lo que ya se emitió en el frame no se repite; un frame nuevo lo vuelve a emitir todo. */
static void test_redundant_state(void) {
    mgl_mesh_t mesh;
    mgl_mat4_t m;
    t_init(4096);
    mesh = t_mesh(0, tri_xyz, 3, tri_idx, 3);
    mgl_mat4_identity(&m);
    t_begin();
    mgl_set_color(0x1111);
    mgl_draw_mesh(mesh);
    mgl_draw_mesh(mesh); /* nada cambia: solo DRAW_INDEXED */
    mgl_set_color(0x2222);
    mgl_draw_mesh(mesh); /* solo cambia el color */
    mgl_set_matrix(MGL_MATRIX_MODEL, &m);
    mgl_draw_mesh(mesh); /* el mismo valor: nada */
    m.m[12] = 0.25f;
    mgl_set_matrix(MGL_MATRIX_MODEL, &m);
    mgl_draw_mesh(mesh); /* solo MODEL */
    mgl_end_frame();
    CHECK(t_opcode_at(0) == MGL_CMD_SET_RENDER_TARGET);
    CHECK(t_opcode_at(1) == MGL_CMD_SET_VIEWPORT);
    CHECK(t_opcode_at(5) == MGL_CMD_SET_RENDER_STATE);
    CHECK(t_opcode_at(6) == MGL_CMD_SET_COLOR);
    CHECK(t_opcode_at(7) == MGL_CMD_DRAW_INDEXED);
    CHECK(t_opcode_at(8) == MGL_CMD_DRAW_INDEXED);
    CHECK(t_opcode_at(9) == MGL_CMD_SET_COLOR);
    CHECK(t_opcode_at(10) == MGL_CMD_DRAW_INDEXED);
    CHECK(t_opcode_at(11) == MGL_CMD_DRAW_INDEXED);
    CHECK(t_opcode_at(12) == MGL_CMD_SET_MATRIX);
    CHECK(t_opcode_at(13) == MGL_CMD_DRAW_INDEXED);
    CHECK(t_opcode_at(14) == MGL_CMD_END_FRAME);
    CHECK(t_run() == MGR_OK);
    /* Frame siguiente en el mismo buffer: todo el estado otra vez. */
    mgl_begin_frame();
    mgl_draw_mesh(mesh);
    mgl_end_frame();
    mgl_set_deferred(0);
    CHECK(t_opcode_at(15) == MGL_CMD_SET_RENDER_TARGET);
    CHECK(t_opcode_at(16) == MGL_CMD_SET_VIEWPORT);
    CHECK(t_opcode_at(20) == MGL_CMD_SET_RENDER_STATE);
    CHECK(t_opcode_at(21) == MGL_CMD_SET_COLOR);
    CHECK(t_find(MGL_CMD_SET_COLOR, 2) && RD32(t_find(MGL_CMD_SET_COLOR, 2) + 8) == 0x2222U);
    CHECK(t_opcode_at(22) == MGL_CMD_DRAW_INDEXED);
    mgr_reset_stats(&t_rnd);
    CHECK(t_run() == MGR_OK && t_rnd.stats.frames == 2U); /* el buffer tiene los dos frames */
}

/* Capacidad: lo que no cabe da MGL_ERR_SPACE, no se escribe fuera y el error se queda. */
static void test_capacity(void) {
    mgl_mesh_t mesh;
    mgl_u32 used;
    t_init(16 + 32 + 16 + 80 + 40);
    mesh = t_mesh(0, tri_xyz, 3, tri_idx, 3);
    t_begin();
    mgl_clear(0);
    used = t_cmd.used;
    CHECK(used == 16U + 32U + 16U && mgl_cmd_status(&t_cmd) == MGL_OK);
    mgl_draw_mesh(mesh); /* VIEWPORT cabe, la primera matriz también, la segunda no */
    CHECK(mgl_cmd_status(&t_cmd) == MGL_ERR_SPACE);
    CHECK(t_cmd.used <= t_cmd.capacity);
    used = t_cmd.used;
    mgl_clear(0);
    mgl_rect(0, 0, 1, 1);
    CHECK(t_cmd.used == used);
    CHECK(mgl_end_frame() == MGL_ERR_SPACE);
    mgl_set_deferred(0);
    /* mgl_cmd_reset lo vacía y vuelve a versión 1 */
    CHECK(mgl_cmd_reset(&t_cmd) == MGL_OK && mgl_cmd_status(&t_cmd) == MGL_OK);
    CHECK(RD32(t_cmd.bytes + 4) == MGL_BUFFER_VERSION);
}

/* Errores de uso en MiniGL. */
static void test_api_errors(void) {
    mgl_mat4_t m;
    t_init(4096);
    mgl_set_deferred(&t_cmd);
    mgl_draw_mesh(t_mesh(0, tri_xyz, 3, tri_idx, 3)); /* fuera de un frame */
    CHECK(mgl_cmd_status(&t_cmd) == MGL_ERR_STATE);
    t_begin();
    mgl_mat4_identity(&m);
    mgl_set_matrix(7, &m);
    CHECK(mgl_cmd_status(&t_cmd) == MGL_ERR_ARGUMENT);
    mgl_end_frame();
    t_begin();
    mgl_set_viewport(0, 0, 0, 10);
    CHECK(mgl_cmd_status(&t_cmd) == MGL_ERR_ARGUMENT);
    mgl_end_frame();
    mgl_set_deferred(0);
    /* En modo directo el 3D no hace nada y mgl_end_frame lo dice */
    CHECK(mgl_end_frame() == MGL_ERR_STATE);
}

/* Construye a mano un buffer de versión 2 con SET_RENDER_TARGET y un comando. */
static unsigned char *raw_begin(void) {
    unsigned char *b = t_cmd.bytes, *p = b + 16;
    WR32(b, MGL_BUFFER_MAGIC);
    WR32(b + 4, MGL_BUFFER_VERSION_3D);
    WR32(b + 12, t_cmd.capacity);
    WR16(p, MGL_CMD_SET_RENDER_TARGET);
    WR16(p + 2, 0);
    WR32(p + 4, 32U);
    WR32(p + 8, T_FB_ADDR);
    WR32(p + 12, 0U);
    WR16(p + 16, T_W);
    WR16(p + 18, T_H);
    WR16(p + 20, T_W);
    WR16(p + 22, 0);
    WR16(p + 24, MGL_COLOR_RGB565);
    WR16(p + 26, MGL_DEPTH_NONE);
    WR32(p + 28, 0U);
    return p + 32;
}

static int raw_run(unsigned char *end) {
    WR32(t_cmd.bytes + 8, (mgl_u32)(end - t_cmd.bytes));
    return t_run();
}

static unsigned char *raw_cmd(unsigned char *p, unsigned int op, unsigned int flags, mgl_u32 size,
    mgl_u32 a0, mgl_u32 a1) {
    memset(p, 0, size);
    WR16(p, op);
    WR16(p + 2, flags);
    WR32(p + 4, size);
    WR32(p + 8, a0);
    WR32(p + 12, a1);
    return p;
}

static unsigned char *raw_draw(unsigned char *p, mgl_u32 vaddr, mgl_u32 iaddr, mgl_u32 vcount,
    mgl_u32 icount, unsigned int vformat, unsigned int iformat) {
    raw_cmd(p, MGL_CMD_DRAW_INDEXED, 0, 32, vaddr, iaddr);
    WR32(p + 16, vcount);
    WR32(p + 20, icount);
    WR16(p + 24, vformat);
    WR16(p + 26, iformat);
    WR16(p + 28, 12);
    WR16(p + 30, MGL_TOPOLOGY_TRIANGLES);
    return p + 32;
}

/* Lo que el renderer rechaza: formatos reservados (UNSUPPORTED) y buffers mal formados. */
static void test_renderer_rejects(void) {
    unsigned char *p;
    mgl_u32 app = T_APP_ADDR;
    t_init(4096);
    t_mesh(0, tri_xyz, 3, tri_idx, 3); /* deja vértices e índices en T_APP_ADDR */

    p = raw_begin();
    CHECK(raw_run(p) == MGR_OK);
    p = raw_begin();
    raw_cmd(p, MGL_CMD_SET_MATRIX, 0, 80, MGL_MATRIX_MODEL, MGL_FORMAT_Q16_16);
    CHECK(raw_run(p + 80) == MGR_ERR_UNSUPPORTED);
    CHECK(t_rnd.error_offset == 16U + 32U);
    p = raw_begin();
    raw_cmd(p, MGL_CMD_SET_MATRIX, 0, 80, MGL_MATRIX_MODEL, 9);
    CHECK(raw_run(p + 80) == MGR_ERR_FORMAT);
    p = raw_begin();
    raw_cmd(p, MGL_CMD_SET_MATRIX, 0, 80, 0, MGL_FORMAT_FLOAT32);
    CHECK(raw_run(p + 80) == MGR_ERR_FORMAT);
    p = raw_begin();
    raw_cmd(p, MGL_CMD_SET_RENDER_STATE, 0, 16, MGL_STATE_BLEND, 0);
    CHECK(raw_run(p + 16) == MGR_ERR_UNSUPPORTED);
    p = raw_begin();
    raw_cmd(p, MGL_CMD_SET_RENDER_STATE, 0, 16, 0x100, 0);
    CHECK(raw_run(p + 16) == MGR_ERR_FORMAT);
    p = raw_begin();
    CHECK(raw_run(raw_draw(p, app, app + 36, 3, 3, MGL_VERTEX_POSITION_F32_XYZ, MGL_INDEX_UINT16)) == MGR_OK);
    p = raw_begin();
    CHECK(raw_run(raw_draw(p, app, app + 36, 3, 3, MGL_VERTEX_POSITION_Q16_16_XYZ, MGL_INDEX_UINT16)) ==
        MGR_ERR_UNSUPPORTED);
    p = raw_begin();
    CHECK(raw_run(raw_draw(p, app, app + 36, 3, 3, MGL_VERTEX_POSITION_F32_XYZ, MGL_INDEX_UINT32)) ==
        MGR_ERR_UNSUPPORTED);
    p = raw_begin(); /* índice 2 con dos vértices */
    CHECK(raw_run(raw_draw(p, app, app + 36, 2, 3, MGL_VERTEX_POSITION_F32_XYZ, MGL_INDEX_UINT16)) ==
        MGR_ERR_LIMIT);
    p = raw_begin(); /* fuera de la RAM */
    CHECK(raw_run(raw_draw(p, T_RAM_ADDR + T_RAM_SIZE - 8, app + 36, 3, 3, MGL_VERTEX_POSITION_F32_XYZ,
              MGL_INDEX_UINT16)) == MGR_ERR_MEMORY);
    p = raw_begin(); /* mal alineado */
    CHECK(raw_run(raw_draw(p, app + 2, app + 36, 3, 3, MGL_VERTEX_POSITION_F32_XYZ, MGL_INDEX_UINT16)) ==
        MGR_ERR_MEMORY);
    p = raw_begin(); /* opcode desconocido */
    raw_cmd(p, 0x77, 0, 16, 0, 0);
    CHECK(raw_run(p + 16) == MGR_ERR_FORMAT);
    p = raw_begin(); /* tamaño que no es el del opcode */
    raw_cmd(p, MGL_CMD_SET_COLOR, 0, 20, 0, 0);
    CHECK(raw_run(p + 20) == MGR_ERR_FORMAT);
    p = raw_begin(); /* flags en un comando que no los tiene */
    raw_cmd(p, MGL_CMD_SET_COLOR, 1, 16, 0, 0);
    CHECK(raw_run(p + 16) == MGR_ERR_FORMAT);
    p = raw_begin(); /* comando cortado: el size pasa del final */
    raw_cmd(p, MGL_CMD_SET_COLOR, 0, 16, 0, 0);
    CHECK(raw_run(p + 12) == MGR_ERR_FORMAT);
    p = raw_begin(); /* reservado distinto de 0 */
    raw_cmd(p, MGL_CMD_SET_COLOR, 0, 16, 0, 5);
    CHECK(raw_run(p + 16) == MGR_ERR_FORMAT);
    p = raw_begin(); /* CLEAR de profundidad sin buffer de profundidad: vale, no hay nada que borrar */
    raw_cmd(p, MGL_CMD_CLEAR, MGL_CLEAR_DEPTH, 16, 0, MGL_DEPTH_ONE);
    CHECK(raw_run(p + 16) == MGR_OK);
    p = raw_begin(); /* profundidad fuera de [0, 1] */
    raw_cmd(p, MGL_CMD_CLEAR, MGL_CLEAR_DEPTH, 16, 0, MGL_DEPTH_ONE + 1);
    CHECK(raw_run(p + 16) == MGR_ERR_FORMAT);
    /* IMAGE lleva un handle de V1: no se puede resolver sin MiniGL */
    p = raw_begin();
    raw_cmd(p, MGL_CMD_BATCH, 0, 40, 1, 0);
    WR32(p + 16, MGL_PRIM_IMAGE);
    CHECK(raw_run(p + 40) == MGR_ERR_UNSUPPORTED);
    /* Dibujar sin destino */
    p = t_cmd.bytes + 16;
    CHECK(raw_run(raw_draw(p, app, app + 36, 3, 3, MGL_VERTEX_POSITION_F32_XYZ, MGL_INDEX_UINT16)) ==
        MGR_ERR_STATE);
    /* Cabeceras */
    p = raw_begin();
    WR32(t_cmd.bytes, 0x12345678U);
    CHECK(raw_run(p) == MGR_ERR_FORMAT);
    p = raw_begin();
    WR32(t_cmd.bytes + 12, 20U); /* used > capacity */
    CHECK(raw_run(p) == MGR_ERR_FORMAT);
    CHECK(mgr_execute(&t_rnd, T_RAM_ADDR - 16) == MGR_ERR_MEMORY);
}

int main(void) {
    test_header_and_2d();
    test_cube_sequence();
    test_matrix_roundtrip();
    test_redundant_state();
    test_capacity();
    test_api_errors();
    test_renderer_rejects();
    return t_report("test_commands: cabeceras, SET_MATRIX, DRAW_INDEXED, estado, capacidad y rechazos");
}
