#ifndef PROCESSING3D_H
#define PROCESSING3D_H

/* MiniProcessing 3D: lo justo para el cubo (size con P3D, translate, rotateX,
   rotateY y box), como capa fina sobre MiniGL 3D. El resto (background, fill,
   noStroke, y todo lo 2D) es lo de processing.h: en un sketch 3D lo 2D se
   dibuja encima, en el orden en que se llama, sin profundidad.

   Como en Processing:
   - y hacia abajo y z hacia el espectador, en píxeles; el origen arriba a la
     izquierda. La cámara está en (width/2, height/2, (height/2) / tan(30°))
     mirando a (width/2, height/2, 0), con 60° de campo vertical, así que en
     z = 0 una unidad es un píxel. Cerca y lejos: z de la cámara / 10 y * 10.
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
void box(float side);

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

#endif
