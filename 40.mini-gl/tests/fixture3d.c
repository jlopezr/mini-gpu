#include "fixture3d.h"
#include "mgl_bytes.h"
#include <stdlib.h>
#include <string.h>

unsigned char *t_ram;
mgl_memory_t t_mem;
mgl_cmd_buffer_t t_cmd;
mgr_renderer_t t_rnd;
int t_failures;

void t_init(mgl_u32 capacity) {
    if (!t_ram) t_ram = (unsigned char *)malloc(T_RAM_SIZE);
    if (!t_ram) {
        puts("sin memoria");
        exit(1);
    }
    memset(t_ram, 0, T_RAM_SIZE);
    if (mgl_memory_init(&t_mem, t_ram, T_RAM_ADDR, T_RAM_SIZE) ||
        mgl_cmd_init(&t_cmd, mgl_memory_ptr(&t_mem, T_CMD_ADDR, capacity, 4), capacity) != MGL_OK ||
        mgl_resources_init(&t_mem, T_HEAP_ADDR, T_HEAP_BYTES) != MGL_OK ||
        mgl_frame_memory_init(T_FRAME_ADDR, T_FRAME_BYTES) != MGL_OK ||
        mgr_init(&t_rnd, &t_mem) != MGR_OK) {
        puts("FAIL: no se pudo preparar el entorno");
        exit(1);
    }
    mgl_reset_state3d();
}

void t_begin(void) {
    mgl_render_target_t t;
    t.color_addr = T_FB_ADDR;
    t.depth_addr = T_DEPTH_ADDR;
    t.width = T_W;
    t.height = T_H;
    t.color_stride = T_W;
    t.depth_stride = T_W;
    mgl_cmd_reset(&t_cmd);
    mgl_set_deferred(&t_cmd);
    mgl_set_render_target(&t);
    mgl_begin_frame();
}

int t_run(void) {
    return mgr_execute(&t_rnd, T_CMD_ADDR);
}

int t_end_and_run(void) {
    int r = mgl_end_frame();
    mgl_set_deferred(0);
    return r != MGL_OK ? r : t_run();
}

mgl_color_t t_pixel(int x, int y) {
    return ((mgl_color_t *)mgl_memory_ptr(&t_mem, T_FB_ADDR, T_W * T_H * 2, 2))[y * T_W + x];
}

mgl_u16 t_depth(int x, int y) {
    return ((mgl_u16 *)mgl_memory_ptr(&t_mem, T_DEPTH_ADDR, T_W * T_H * 2, 2))[y * T_W + x];
}

int t_count(mgl_color_t c) {
    int x, y, n = 0;
    for (y = 0; y < T_H; y++)
        for (x = 0; x < T_W; x++)
            if (t_pixel(x, y) == c) n++;
    return n;
}

const unsigned char *t_find(unsigned int opcode, int nth) {
    mgl_u32 off;
    for (off = 16; off + 16 <= t_cmd.used; off += RD32(t_cmd.bytes + off + 4)) {
        if (RD32(t_cmd.bytes + off + 4) < 16U) return 0;
        if (RD16(t_cmd.bytes + off) == opcode && nth-- == 0) return t_cmd.bytes + off;
    }
    return 0;
}

unsigned int t_opcode_at(int i) {
    mgl_u32 off;
    for (off = 16; off + 16 <= t_cmd.used; off += RD32(t_cmd.bytes + off + 4)) {
        if (RD32(t_cmd.bytes + off + 4) < 16U) return 0;
        if (i-- == 0) return RD16(t_cmd.bytes + off);
    }
    return 0;
}

mgl_mesh_t t_mesh(mgl_u32 offset, const float *xyz, mgl_u32 n, const unsigned short *idx, mgl_u32 m) {
    mgl_mesh_desc_t d;
    unsigned char *p;
    mgl_u32 i;
    d.vertex_addr = T_APP_ADDR + offset;
    d.index_addr = d.vertex_addr + n * 12U;
    d.vertex_count = n;
    d.index_count = m;
    d.vertex_format = MGL_VERTEX_POSITION_F32_XYZ;
    d.index_format = MGL_INDEX_UINT16;
    d.vertex_stride = 12;
    p = (unsigned char *)mgl_memory_ptr(&t_mem, d.vertex_addr, n * 12U + m * 2U, 4);
    for (i = 0; i < n * 3U; i++, p += 4) WR32(p, mgl_real_to_f32(xyz[i]));
    for (i = 0; i < m; i++, p += 2) WR16(p, idx[i]);
    return mgl_create_mesh(&d);
}

void t_triangle(mgl_u32 offset, float x0, float y0, float z0, float x1, float y1, float z1, float x2,
    float y2, float z2) {
    static const unsigned short idx[3] = {0, 1, 2};
    float xyz[9];
    mgl_mat4_t id;
    mgl_mesh_t mesh;
    xyz[0] = x0;
    xyz[1] = y0;
    xyz[2] = z0;
    xyz[3] = x1;
    xyz[4] = y1;
    xyz[5] = z1;
    xyz[6] = x2;
    xyz[7] = y2;
    xyz[8] = z2;
    mesh = t_mesh(offset, xyz, 3, idx, 3);
    mgl_mat4_identity(&id);
    mgl_set_matrix(MGL_MATRIX_MODEL, &id);
    mgl_set_matrix(MGL_MATRIX_VIEW, &id);
    mgl_set_matrix(MGL_MATRIX_PROJECTION, &id);
    mgl_draw_mesh(mesh);
    mgl_destroy_mesh(mesh); /* el buffer ya tiene las direcciones; los datos siguen ahí */
}

int t_report(const char *name) {
    if (t_failures) {
        printf("FAIL: %s, %d comprobaciones fallidas\n", name, t_failures);
        return 1;
    }
    printf("PASS: %s\n", name);
    return 0;
}
