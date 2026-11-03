#ifndef PROCESSING3D_H
#define PROCESSING3D_H

/* MiniProcessing 3D: lo justo para el cubo y los modelos (size con P3D,
   translate, rotate*, scale, pushMatrix/popMatrix, perspective, box,
   beginShape y shape),
   como capa fina sobre MiniGL 3D. El resto (background, fill, noStroke, y todo lo 2D) es lo de
   processing.h: en un sketch 3D lo 2D se dibuja encima, en el orden en que se
   llama, sin profundidad.

   Como en Processing:
   - y hacia abajo y z hacia el espectador, en píxeles; el origen arriba a la
     izquierda. La cámara está en (width/2, height/2, (height/2) / tan(30°))
     mirando a (width/2, height/2, 0), con 60° de campo vertical, así que en
     z = 0 una unidad es un píxel. Cerca y lejos: z de la cámara / 10 y * 10
     (perspective() los cambia).
   - La matriz del modelo vuelve a la identidad al empezar cada draw().
     translate() y rotate*() la componen por la derecha (mgl_math.h): lo último
     que se llama es lo primero que se aplica al objeto.
   - box(s) es un cubo de lado s centrado en el origen local, del color de
     fill(). Con noFill() no se dibuja; el contorno (stroke) no se dibuja nunca.

   size() tiene tres argumentos en un sketch 3D: es una macro, porque C89 no
   tiene sobrecarga, y size(w, h) sigue siendo la de los sketches 2D. */

#include "processing.h"
#include "mgl_math.h"

#define P2D 0
#define P3D 1

void size_renderer(int w, int h, int renderer);
#undef size
#define size(w, h, renderer) size_renderer(w, h, renderer)

void translate(float x, float y, float z);
void rotateX(float angle);
void rotateY(float angle);
void rotateZ(float angle);
void scale(float s);
/* Guardan y recuperan la matriz del modelo, como en Processing: para colocar
   varios objetos a partir de la misma (la de la cámara de un juego, por
   ejemplo). Como mucho P3D_MATRIX_STACK guardadas; las que no caben no se
   guardan, pero cada popMatrix() sigue emparejado con su pushMatrix(). La pila
   se vacía al empezar cada draw(). */
#define P3D_MATRIX_STACK 8
void pushMatrix(void);
void popMatrix(void);
/* La proyección, como en Processing: campo vertical en radianes, ancho / alto
   y los planos cercano y lejano (z de la cámara / 10 y * 10 por defecto, lo
   que deja size()). Dura hasta otro perspective() o size(). Con el Z-buffer de
   16 bits, cuanto más cerca el plano cercano, menos precisión a lo lejos. */
void perspective(float fovy, float aspect, float z_near, float z_far);
void box(float side);

/* Un modelo ya convertido (tools/obj2shape.py lo genera a partir de un OBJ):
   como el PShape de loadShape("modelo.obj") en Processing, pero en un .h,
   porque en MiniGPU no hay ficheros. Posiciones x, y, z por vértice e índices
   de triángulos agrupados por color: el grupo i son los índices desde el
   final del anterior (0 para el primero) hasta end. shape(s) lo dibuja con sus
   colores, sin mirar fill(); la malla se crea en el primer shape() y se
   reutiliza, como la de box(). Como mucho P3D_SHAPES modelos distintos.
   Con cull no se rasterizan las caras traseras (las que se ven en sentido
   horario, con los vértices del OBJ en sentido antihorario de frente): la
   mitad de triángulos y fragmentos, y la misma imagen si la malla tiene una
   orientación coherente y sus huecos no se ven desde fuera (obj2shape.py
   --cull comprueba lo primero; lo segundo, mirándolo). */
typedef struct {
    unsigned char r, g, b;
    unsigned short end;
} PShapeGroup;

typedef struct {
    const float *positions;
    unsigned int vertex_count;
    const unsigned short *indices;
    unsigned int index_count;
    const PShapeGroup *groups;
    unsigned int group_count;
    int cull;
} PShape;

#define P3D_SHAPES 64

void shape(const PShape *s);

/* Olvida los modelos ya dibujados y vacía la memoria de MiniGL donde están
   sus mallas (que no se libera de una en una), para hacer otros con los
   mismos PShape o con otros (el siguiente nivel de un juego). Hay que
   llamarlo antes de dibujar nada en el frame: lo de beginShape/endShape de
   este frame también se pierde. */
void resetShapes(void);

/* Figuras con los vértices uno a uno, como en Processing:
     beginShape(QUADS); fill(...); vertex(x, y, z); ... endShape();
   TRIANGLES: cada 3 vértices un triángulo; QUADS: cada 4 un cuadrilátero
   (convexo y plano). El color de cada primitiva es el fill() de su primer
   vértice: plano, sin interpolar entre vértices como Processing (con el mismo
   color en todos los vértices de la cara, que es lo habitual, da lo mismo).
   Un vértice con noFill() deja su primitiva sin dibujar. Como mucho
   P3D_SHAPE_VERTICES vértices por figura; los que sobren se ignoran. */
#define TRIANGLES 9 /* los valores de Processing */
#define QUADS 17
#define P3D_SHAPE_VERTICES 256

void beginShape(int kind);
void vertex(float x, float y, float z);
void endShape(void);

/* Para la plataforma: al principio de cada draw() (y de setup()). */
void processing3d_begin_draw(void);
/* Para la plataforma: tras size_renderer, con el tamaño ya fijado. */
void processing3d_size(int w, int h);
/* Lo pone el contexto: vacía la memoria de MiniGL (para resetShapes). */
void processing3d_reset_memory(void);

#endif
