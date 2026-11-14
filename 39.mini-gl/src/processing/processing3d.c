#include "processing3d.h"
#include "minigl3d.h"

/* Matrices de la cámara (fijas para un tamaño) y del modelo (cambia con
   translate y rotate*, y vuelve a la identidad en cada draw). */
static mgl_mat4_t projection, view, model;
static mgl_mat4_t stack[P3D_MATRIX_STACK];
static int depth;
static int view_w, view_h;
static mgl_mesh_t cube;
/* hint(): test y escritura de profundidad. */
static int depth_test = 1, depth_mask = 1;

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
void perspective(float fovy, float aspect, float z_near, float z_far) {
    mgl_mat4_t flip;
    mgl_mat4_perspective(&projection, fovy, aspect, z_near, z_far);
    mgl_mat4_scaling(&flip, 1.0f, -1.0f, 1.0f);
    mgl_mat4_mul(&projection, &flip, &projection);
}

void processing3d_size(int w, int h) {
    mgl_real_t fov = 1.04719755f, half = 0.523598776f; /* pi / 3 y pi / 6, sin plegar constantes */
    mgl_real_t eye_z = ((mgl_real_t)h * 0.5f) * mgl_cos(half) / mgl_sin(half);
    view_w = w;
    view_h = h;
    perspective(fov, (mgl_real_t)w / (mgl_real_t)h, eye_z * 0.1f, eye_z * 10.0f);
    mgl_mat4_look_at(&view, (mgl_real_t)w * 0.5f, (mgl_real_t)h * 0.5f, eye_z, (mgl_real_t)w * 0.5f,
        (mgl_real_t)h * 0.5f, 0.0f, 0.0f, 1.0f, 0.0f);
    mgl_mat4_identity(&model);
}

void processing3d_begin_draw(void) {
    mgl_mat4_identity(&model);
    depth = 0;
}

void pushMatrix(void) {
    if (depth < P3D_MATRIX_STACK) stack[depth] = model;
    depth++;
}

void popMatrix(void) {
    if (depth == 0) return;
    if (--depth < P3D_MATRIX_STACK) model = stack[depth];
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
    /* Sin test tampoco se escribe, como en OpenGL. */
    mgl_set_depth_test(depth_test);
    mgl_set_depth_write(depth_test && depth_mask);
}

void hint(int which) {
    if (which == DISABLE_DEPTH_TEST || which == ENABLE_DEPTH_TEST) depth_test = which == ENABLE_DEPTH_TEST;
    if (which == DISABLE_DEPTH_MASK || which == ENABLE_DEPTH_MASK) depth_mask = which == ENABLE_DEPTH_MASK;
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

/* Las mallas de los PShape ya dibujados, por dirección del PShape. La malla lleva el color de cada vértice
   (el de su grupo), así que se dibuja entera con un DRAW_INDEXED: un SET_COLOR y un DRAW_INDEXED por grupo
   eran unas 700 instrucciones por grupo y frame en MiniGPU. Leer el color cuesta unas 5 por triángulo, así
   que solo compensa con menos de SHAPE_TRIS_PER_DRAW triángulos por cada grupo que se ahorra (los modelos de
   racer, sí; el caza TIE, 2150 triángulos en 4 colores, no). Si no compensa, o si un vértice está en grupos
   de dos colores (no se puede), shape_grouped: por grupos, como antes, con el color de SET_COLOR. */
#define SHAPE_TRIS_PER_DRAW 128U
static const PShape *shape_key[P3D_SHAPES];
static mgl_mesh_t shape_mesh[P3D_SHAPES];
static unsigned char shape_grouped[P3D_SHAPES];
static unsigned char shape_unstyled[P3D_SHAPES]; /* disableStyle() */
/* Pista para encontrar el hueco sin recorrerlos: por bits de la dirección del PShape, el último hueco que
   tuvo esa pista. Si no acierta (otro PShape con la misma), se busca y se apunta. Un juego con unos 50
   modelos recorría 50 huecos en cada shape(): ~340 instrucciones en MiniGPU. */
static unsigned char shape_hint[P3D_SHAPES];

/* El hueco de s (lo ocupa si es nuevo), o -1 si no quedan. */
static int shape_slot(const PShape *s) {
    unsigned int i, h;
    unsigned long a = (unsigned long)s;
    int slot;
    h = (unsigned int)((a >> 4) ^ (a >> 10)) & (P3D_SHAPES - 1U);
    slot = shape_hint[h];
    if (shape_key[slot] == s) return slot;
    slot = -1;
    for (i = 0; i < P3D_SHAPES && shape_key[i]; i++)
        if (shape_key[i] == s) {
            slot = (int)i;
            break;
        }
    if (slot < 0) {
        if (i == P3D_SHAPES) return -1;
        slot = (int)i;
        shape_key[slot] = s;
        shape_unstyled[slot] = 0;
    }
    shape_hint[h] = (unsigned char)slot;
    return slot;
}

static mgl_mesh_t shape_create(const PShape *s, int slot) {
    unsigned int i, first = 0;
    const PShapeGroup *g;
    mgl_mesh_t m = mgl_create_mesh_copy_rgb565(s->positions, 0, s->vertex_count, s->indices, s->index_count);
    shape_grouped[slot] = s->index_count / 3U >= SHAPE_TRIS_PER_DRAW * (s->group_count ? s->group_count - 1U : 0U);
    for (i = 0, g = s->groups; m && !shape_grouped[slot] && i < s->group_count; i++, g++) {
        if (g->end < first || mgl_mesh_color_range(m, first, g->end - first, color565(g->r, g->g, g->b)) != MGL_OK)
            shape_grouped[slot] = 1;
        first = g->end;
    }
    return m;
}

void shape(const PShape *s) {
    unsigned int i, first = 0;
    const PShapeGroup *g;
    mgl_color_t c;
    int slot = shape_slot(s);
    mgl_mesh_t m;
    if (slot < 0) return;
    if (!shape_mesh[slot] || mgl_mesh_info(shape_mesh[slot], 0) != MGL_OK) /* como el cubo */
        shape_mesh[slot] = shape_create(s, slot);
    m = shape_mesh[slot];
    if (shape_unstyled[slot] && !mgl_get_fill(&c)) return; /* sin estilo y noFill(): como box() */
    prepare(&model);
    /* Las caras traseras: con la y invertida de la proyección, una cara de
       frente (antihoraria en el OBJ) queda horaria en pantalla, y para MiniGL
       es la de detrás (ver processing3d_size). */
    if (s->cull) mgl_set_cull(MGL_CULL_FRONT);
    /* Solo hasta el final del último grupo, como antes: lo que no está en ningún grupo no se dibuja. */
    if (s->group_count) {
        if (shape_unstyled[slot]) {
            mgl_set_color(c);
            mgl_draw_mesh_range_uniform(m, 0, s->groups[s->group_count - 1U].end);
        } else if (!shape_grouped[slot]) {
            mgl_draw_mesh_range(m, 0, s->groups[s->group_count - 1U].end); /* malla 0: MGL_ERR_HANDLE */
        } else {
            for (i = 0, g = s->groups; i < s->group_count; i++, g++) { /* g por puntero: sin MUL por grupo */
                mgl_set_color(color565(g->r, g->g, g->b));
                mgl_draw_mesh_range_uniform(m, first, g->end - first);
                first = g->end;
            }
        }
    }
    if (s->cull) mgl_set_cull(MGL_CULL_NONE); /* box() y beginShape no descartan nada */
}

void disableStyle(const PShape *s) {
    int slot = shape_slot(s);
    if (slot >= 0) shape_unstyled[slot] = 1;
}

void enableStyle(const PShape *s) {
    int slot = shape_slot(s);
    if (slot >= 0) shape_unstyled[slot] = 0;
}

void resetShapes(void) {
    unsigned int i;
    for (i = 0; i < P3D_SHAPES; i++) {
        shape_key[i] = 0;
        shape_mesh[i] = 0;
    }
    cube = 0;
    processing3d_reset_memory();
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
