/* X-Wing giratorio: un modelo OBJ (low-poly-xwing/) convertido con
   tools/obj2shape.py a x_wing_shape.h, 794 vértices y 1382 triángulos con el
   color más frecuente de su cara en la textura (--face-color mayoria: con la
   media, las franjas rojas se mezclaban con el blanco y desaparecían). Como el
   caza TIE, sin luces: un DRAW_INDEXED
   por color, y lo que queda detrás lo tapa el Z-buffer. Sin culling: la malla
   no tiene una orientación coherente (obj2shape.py --cull la rechaza).
   Modelo: "Xwing" de metalmorag (Sketchfab), CC BY 4.0; ver
   low-poly-xwing/README.md.
   Uso: x_wing [-f frames] [-e K] [-o salida.ppm]   (plataforma 3D) */
#include "processing3d.h"
#include "x_wing_shape.h"

static float angle = 0.0f;

void setup(void) {
    size(320, 240, P3D);
}

void draw(void) {
    background(30, 40, 70);

    translate(160, 120, 0);
    rotateX(0.4f);
    rotateY(angle);
    scale(80);

    shape(&x_wing);

    angle += 0.02f;
}
