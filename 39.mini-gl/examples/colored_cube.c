/* Cubo giratorio con una cara de cada color, como en Processing: box() es de
   un solo color, así que las caras se dan una a una con beginShape(QUADS) y un
   fill() antes de cada una. Las que quedan detrás las tapa el Z-buffer.
   Uso: colored_cube [-f frames] [-e K] [-o salida.ppm]   (plataforma 3D) */
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

    noStroke();
    beginShape(QUADS);
    fill(230, 40, 40); /* +z, de frente */
    vertex(-50, -50, 50);
    vertex(50, -50, 50);
    vertex(50, 50, 50);
    vertex(-50, 50, 50);
    fill(40, 200, 60); /* -z */
    vertex(50, -50, -50);
    vertex(-50, -50, -50);
    vertex(-50, 50, -50);
    vertex(50, 50, -50);
    fill(40, 90, 230); /* +x */
    vertex(50, -50, 50);
    vertex(50, -50, -50);
    vertex(50, 50, -50);
    vertex(50, 50, 50);
    fill(240, 220, 40); /* -x */
    vertex(-50, -50, -50);
    vertex(-50, -50, 50);
    vertex(-50, 50, 50);
    vertex(-50, 50, -50);
    fill(40, 220, 220); /* +y, abajo (y hacia abajo, como en Processing) */
    vertex(-50, 50, 50);
    vertex(50, 50, 50);
    vertex(50, 50, -50);
    vertex(-50, 50, -50);
    fill(220, 60, 220); /* -y, arriba */
    vertex(-50, -50, -50);
    vertex(50, -50, -50);
    vertex(50, -50, 50);
    vertex(-50, -50, 50);
    endShape();

    angle += 0.02f;
}
