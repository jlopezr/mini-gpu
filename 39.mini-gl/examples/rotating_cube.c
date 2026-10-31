/* Cubo 3D giratorio: perspectiva, recorte, Z-buffer y framebuffer RGB565 de
   320x240. El cubo (8 vértices, 36 índices) se crea una vez en el primer box();
   en cada frame solo cambia la matriz del modelo.
   Uso: rotating_cube [-f frames] [-e K] [-o salida.ppm]   (plataforma 3D) */
#include "processing3d.h"

static float angle = 0.0f;

void setup(void) {
    size(320, 240, P3D);
}

void draw(void) {
    background(20, 20, 20);

    translate(160, 120, 0);
    rotateX(angle * 0.6f);
    rotateY(angle);

    fill(255, 140, 40);
    noStroke();

    box(100);

    angle += 0.02f;
}
