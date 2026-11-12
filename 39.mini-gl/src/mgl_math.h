#ifndef MGL_MATH_H
#define MGL_MATH_H

#include "mgl_config.h"

/* Matemáticas de MiniGL y del renderer: todo el cálculo con mgl_real_t pasa por
   aquí, para que la variante Q16.16 sea cambiar este módulo y no buscar
   operaciones sueltas.

   Convención: matrices 4x4 column-major (m[columna * 4 + fila]), vectores
   columna, ángulos en radianes. Un vértice se transforma con
   Projection * View * Model * v.

   Las funciones que componen (mgl_mat4_mul y las que terminan en _by) multiplican
   por la derecha, como Processing y OpenGL: con M = T * R el vértice primero
   gira y luego se traslada. Por eso translate(); rotateY(); en un sketch gira el
   objeto alrededor de su propio centro y después lo lleva a su sitio.

   Sin math.h: seno, coseno y raíz cuadrada son polinomios y Newton, con las
   mismas operaciones en el host y en MiniGPU (soft-float IEEE), para que los dos
   den los mismos bits. Por lo mismo, en el host se compila con
   -ffp-contract=off (sin fusionar multiplicación y suma). */

typedef struct {
    mgl_real_t m[16];
} mgl_mat4_t;

typedef struct {
    mgl_real_t x, y, z, w;
} mgl_vec4_t;

#define MGL_PI 3.14159265f

mgl_real_t mgl_sin(mgl_real_t a);
mgl_real_t mgl_cos(mgl_real_t a);
/* Lo mismo con una tabla: 4-6 veces más rápido en MiniGPU y error < 1e-4. No
   dan los mismos bits que las de arriba: para quien prefiera velocidad. */
mgl_real_t mgl_sin_fast(mgl_real_t a);
mgl_real_t mgl_cos_fast(mgl_real_t a);
void mgl_sincos_fast(mgl_real_t a, mgl_real_t *s, mgl_real_t *c);
mgl_real_t mgl_sqrt(mgl_real_t v); /* 0 si v <= 0 */
/* Redondeo al entero más cercano (las mitades, lejos de cero). */
mgl_s32 mgl_round(mgl_real_t v);

void mgl_mat4_identity(mgl_mat4_t *out);
/* out = a * b. out puede ser a o b. */
void mgl_mat4_mul(mgl_mat4_t *out, const mgl_mat4_t *a, const mgl_mat4_t *b);
void mgl_mat4_translation(mgl_mat4_t *out, mgl_real_t x, mgl_real_t y, mgl_real_t z);
void mgl_mat4_scaling(mgl_mat4_t *out, mgl_real_t x, mgl_real_t y, mgl_real_t z);
void mgl_mat4_rotation_x(mgl_mat4_t *out, mgl_real_t angle);
void mgl_mat4_rotation_y(mgl_mat4_t *out, mgl_real_t angle);
void mgl_mat4_rotation_z(mgl_mat4_t *out, mgl_real_t angle);
/* Perspectiva de OpenGL: z de -near a -far pasa a [-1, 1]. fovy en radianes. */
void mgl_mat4_perspective(mgl_mat4_t *out, mgl_real_t fovy, mgl_real_t aspect, mgl_real_t near_z,
    mgl_real_t far_z);
/* Cámara en eye mirando a center, con up hacia arriba (gluLookAt). */
void mgl_mat4_look_at(mgl_mat4_t *out, mgl_real_t ex, mgl_real_t ey, mgl_real_t ez, mgl_real_t cx,
    mgl_real_t cy, mgl_real_t cz, mgl_real_t ux, mgl_real_t uy, mgl_real_t uz);

/* m = m * T, m * S, m * R: componer por la derecha (ver arriba). */
void mgl_mat4_translate_by(mgl_mat4_t *m, mgl_real_t x, mgl_real_t y, mgl_real_t z);
void mgl_mat4_scale_by(mgl_mat4_t *m, mgl_real_t x, mgl_real_t y, mgl_real_t z);
void mgl_mat4_rotate_x_by(mgl_mat4_t *m, mgl_real_t angle);
void mgl_mat4_rotate_y_by(mgl_mat4_t *m, mgl_real_t angle);
void mgl_mat4_rotate_z_by(mgl_mat4_t *m, mgl_real_t angle);

/* out = m * (x, y, z, 1). */
void mgl_mat4_transform_point(const mgl_mat4_t *m, mgl_real_t x, mgl_real_t y, mgl_real_t z,
    mgl_vec4_t *out);

/* Formato serializado FLOAT32 <-> mgl_real_t (los bits IEEE-754 de 32 bits). */
mgl_u32 mgl_real_to_f32(mgl_real_t v);
mgl_real_t mgl_real_from_f32(mgl_u32 bits);

#endif
