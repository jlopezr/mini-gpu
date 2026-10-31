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

/* La malla se crea la primera vez y se reutiliza; el tamaño va en la matriz. */
void box(float side) {
    mgl_mat4_t m;
    mgl_color_t c;
    if (!mgl_get_fill(&c)) return;
    if (!cube || mgl_mesh_info(cube, 0) != MGL_OK) /* mgl_resources_init la destruye */
        cube = mgl_create_mesh_copy(cube_positions, 8, cube_indices, 36);
    m = model;
    mgl_mat4_scale_by(&m, side, side, side);
    mgl_set_viewport(0, 0, view_w, view_h);
    mgl_set_matrix(MGL_MATRIX_PROJECTION, &projection);
    mgl_set_matrix(MGL_MATRIX_VIEW, &view);
    mgl_set_matrix(MGL_MATRIX_MODEL, &m);
    mgl_set_depth_test(1);
    mgl_set_depth_write(1);
    mgl_set_color(c);
    mgl_draw_mesh(cube); /* con cube == 0, MGL_ERR_HANDLE en el buffer */
}
