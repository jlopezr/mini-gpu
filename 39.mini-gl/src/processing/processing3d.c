#include "processing3d.h"
#include "minigl3d.h"

/* Matrices de la cámara (fijas para un tamaño) y del modelo (cambia con
   translate y rotate*, y vuelve a la identidad en cada draw). */
static mgl_mat4_t projection, view, model;
static int view_w, view_h;
static mgl_mesh_t cube;

/* Cubo unidad centrado en el origen: 8 vértices, 12 triángulos. Con y hacia
   abajo como en Processing; el orden de los índices da igual mientras no haya
   culling. */
static const float cube_positions[8 * 3] = {
    -0.5f, -0.5f, -0.5f, 0.5f, -0.5f, -0.5f, 0.5f, 0.5f, -0.5f, -0.5f, 0.5f, -0.5f,
    -0.5f, -0.5f, 0.5f, 0.5f, -0.5f, 0.5f, 0.5f, 0.5f, 0.5f, -0.5f, 0.5f, 0.5f,
};
static const unsigned short cube_indices[36] = {
    4, 5, 6, 4, 6, 7, /* +z */
    1, 0, 3, 1, 3, 2, /* -z */
    5, 1, 2, 5, 2, 6, /* +x */
    0, 4, 7, 0, 7, 3, /* -x */
    7, 6, 2, 7, 2, 3, /* +y */
    0, 1, 5, 0, 5, 4, /* -y */
};

/* La cámara por defecto de Processing. La y hacia abajo de Processing es una
   simetría (no un giro): se hace invirtiendo y en la proyección, como el propio
   Processing. Por eso cambia el sentido de giro de las caras en pantalla. */
void processing3d_size(int w, int h) {
    mgl_real_t fov = 1.04719755f, half = 0.523598776f; /* pi / 3 y pi / 6, sin plegar constantes */
    mgl_real_t eye_z = ((mgl_real_t)h * 0.5f) * mgl_cos(half) / mgl_sin(half);
    mgl_mat4_t flip;
    view_w = w;
    view_h = h;
    mgl_mat4_perspective(&projection, fov, (mgl_real_t)w / (mgl_real_t)h, eye_z * 0.1f, eye_z * 10.0f);
    mgl_mat4_scaling(&flip, 1.0f, -1.0f, 1.0f);
    mgl_mat4_mul(&projection, &flip, &projection);
    mgl_mat4_look_at(&view, (mgl_real_t)w * 0.5f, (mgl_real_t)h * 0.5f, eye_z, (mgl_real_t)w * 0.5f,
        (mgl_real_t)h * 0.5f, 0.0f, 0.0f, 1.0f, 0.0f);
    mgl_mat4_identity(&model);
}

void processing3d_begin_draw(void) {
    mgl_mat4_identity(&model);
}

void translate(float x, float y, float z) {
    mgl_mat4_translate_by(&model, x, y, z);
}

void rotateX(float angle) {
    mgl_mat4_rotate_x_by(&model, angle);
}

void rotateY(float angle) {
    mgl_mat4_rotate_y_by(&model, angle);
}

void rotateZ(float angle) {
    mgl_mat4_rotate_z_by(&model, angle);
}

void scale(float s) {
    mgl_mat4_scale_by(&model, s, s, s);
}

/* Cámara, modelo y profundidad para dibujar en 3D. */
static void prepare(const mgl_mat4_t *m) {
    mgl_set_viewport(0, 0, view_w, view_h);
    mgl_set_matrix(MGL_MATRIX_PROJECTION, &projection);
    mgl_set_matrix(MGL_MATRIX_VIEW, &view);
    mgl_set_matrix(MGL_MATRIX_MODEL, m);
    mgl_set_depth_test(1);
    mgl_set_depth_write(1);
}

/* La malla se crea la primera vez y se reutiliza; el tamaño va en la matriz. */
void box(float side) {
    mgl_mat4_t m;
    mgl_color_t c;
    if (!mgl_get_fill(&c)) return;
    if (!cube || mgl_mesh_info(cube, 0) != MGL_OK) /* mgl_resources_init la destruye */
        cube = mgl_create_mesh_copy(cube_positions, 8, cube_indices, 36);
    m = model;
    mgl_mat4_scale_by(&m, side, side, side);
    prepare(&m);
    mgl_set_color(c);
    mgl_draw_mesh(cube); /* con cube == 0, MGL_ERR_HANDLE en el buffer */
}

/* Las mallas de los PShape ya dibujados, por dirección del PShape. */
static const PShape *shape_key[P3D_SHAPES];
static mgl_mesh_t shape_mesh[P3D_SHAPES];

void shape(const PShape *s) {
    unsigned int i, first = 0;
    int slot = -1;
    for (i = 0; i < P3D_SHAPES && shape_key[i]; i++)
        if (shape_key[i] == s) slot = (int)i;
    if (slot < 0) {
        if (i == P3D_SHAPES) return;
        slot = (int)i;
        shape_key[slot] = s;
    }
    if (!shape_mesh[slot] || mgl_mesh_info(shape_mesh[slot], 0) != MGL_OK) /* como el cubo */
        shape_mesh[slot] = mgl_create_mesh_copy(s->positions, s->vertex_count, s->indices, s->index_count);
    prepare(&model);
    /* Las caras traseras: con la y invertida de la proyección, una cara de
       frente (antihoraria en el OBJ) queda horaria en pantalla, y para MiniGL
       es la de detrás (ver processing3d_size). */
    if (s->cull) mgl_set_cull(MGL_CULL_FRONT);
    for (i = 0; i < s->group_count; i++) {
        const PShapeGroup *g = &s->groups[i];
        mgl_set_color(color565(g->r, g->g, g->b));
        mgl_draw_mesh_range(shape_mesh[slot], first, g->end - first); /* malla 0: MGL_ERR_HANDLE */
        first = g->end;
    }
    if (s->cull) mgl_set_cull(MGL_CULL_NONE); /* box() y beginShape no descartan nada */
}

/* beginShape/vertex/endShape: los vértices se guardan aquí y endShape los
   copia a memoria de frame como una malla, que se dibuja por tramos de
   primitivas seguidas del mismo color (un SET_COLOR y un DRAW_INDEXED por
   tramo), en el orden en que se dieron. */
static float shape_xyz[P3D_SHAPE_VERTICES * 3];
static mgl_color_t shape_color[P3D_SHAPE_VERTICES];
static unsigned char shape_filled[P3D_SHAPE_VERTICES];
static unsigned short shape_indices[P3D_SHAPE_VERTICES / 4 * 6 + P3D_SHAPE_VERTICES];
static int shape_kind, shape_n, in_shape;

void beginShape(int kind) {
    in_shape = kind == TRIANGLES || kind == QUADS;
    shape_kind = kind;
    shape_n = 0;
}

void vertex(float x, float y, float z) {
    if (!in_shape || shape_n >= P3D_SHAPE_VERTICES) return;
    shape_xyz[3 * shape_n] = x;
    shape_xyz[3 * shape_n + 1] = y;
    shape_xyz[3 * shape_n + 2] = z;
    shape_filled[shape_n] = (unsigned char)mgl_get_fill(&shape_color[shape_n]);
    shape_n++;
}

void endShape(void) {
    int per = shape_kind == QUADS ? 4 : 3, prims, p, v, m = 0, run, k;
    mgl_color_t color[P3D_SHAPE_VERTICES / 3];
    int start[P3D_SHAPE_VERTICES / 3 + 1], runs = 0;
    mgl_mesh_t mesh;
    if (!in_shape) return;
    in_shape = 0;
    prims = shape_n / per;
    /* Índices de las primitivas con relleno; un tramo nuevo cuando cambia el color. */
    for (p = 0; p < prims; p++) {
        v = p * per;
        if (!shape_filled[v]) continue;
        if (!runs || shape_color[v] != color[runs - 1]) {
            color[runs] = shape_color[v];
            start[runs++] = m;
        }
        shape_indices[m++] = (unsigned short)v; /* el cuadrilátero, en dos triángulos */
        shape_indices[m++] = (unsigned short)(v + 1);
        shape_indices[m++] = (unsigned short)(v + 2);
        if (per == 4) {
            shape_indices[m++] = (unsigned short)v;
            shape_indices[m++] = (unsigned short)(v + 2);
            shape_indices[m++] = (unsigned short)(v + 3);
        }
    }
    if (!m) return;
    start[runs] = m;
    mesh = mgl_create_mesh_frame(shape_xyz, (mgl_u32)(prims * per), shape_indices, (mgl_u32)m);
    prepare(&model);
    for (run = 0; run < runs; run++) {
        k = start[run + 1] - start[run];
        mgl_set_color(color[run]);
        mgl_draw_mesh_range(mesh, (mgl_u32)start[run], (mgl_u32)k); /* mesh == 0: MGL_ERR_HANDLE */
    }
    mgl_destroy_mesh(mesh); /* el buffer ya tiene las direcciones; los datos valen hasta el próximo frame */
}
