/* Dos cubos que se cortan, de colores distintos: sin iluminación, el Z-buffer
   es lo que dibuja la línea donde uno entra en el otro. Encima, en 2D, una
   barra que avanza con frameCount: los comandos 2D y 3D van en el mismo
   command buffer, en orden.
   Uso: boxes [-f frames] [-e K] [-o salida.ppm]   (plataforma 3D) */
#include "processing3d.h"

static float angle = 0.0f;

void setup(void) {
    size(320, 240, P3D);
}

void draw(void) {
    background(10, 10, 30);
    noStroke();

    translate(160, 120, 0);
    rotateY(angle);
    rotateX(angle * 0.4f);
    fill(60, 160, 255);
    box(110);

    rotateX(0.8f);
    rotateY(0.6f);
    fill(255, 90, 60);
    box(95);

    fill(255, 200, 0);
    rect(0, height - 4, frameCount % width, 4);

    angle += 0.03f;
}
