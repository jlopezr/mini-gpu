/* Caza TIE giratorio: un modelo OBJ (low-poly-tie-fighter/) convertido con
   tools/obj2shape.py a tie_fighter_shape.h, 1424 vértices y 2150 triángulos
   con el color de su cara en la textura. Como el cubo de colores, sin luces:
   un DRAW_INDEXED por color, y lo que queda detrás lo tapa el Z-buffer.
   Modelo: "Low Poly Tie Fighter Star Wars" de tolotedesign (Sketchfab), CC BY
   4.0; ver low-poly-tie-fighter/README.md.
   Uso: tie_fighter [-f frames] [-e K] [-o salida.ppm]   (plataforma 3D) */
#include "processing3d.h"
#include "tie_fighter_shape.h"

static float angle = 0.0f;

void setup(void) {
    size(320, 240, P3D);
}

void draw(void) {
    background(150, 170, 200);

    translate(160, 120, 0);
    rotateX(0.3f);
    rotateY(angle);
    scale(80);

    shape(&tie_fighter);

    angle += 0.02f;
}
