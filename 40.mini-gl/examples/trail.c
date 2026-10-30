/* Estela: draw() no borra, así que cada frame dibuja encima de los anteriores,
   como en Processing. Un pincel recorre la pantalla en una curva de Lissajous y
   cambia de color con frameCount; cada 120 frames un rectángulo tapa una franja.
   Sirve para comprobar que las plataformas conservan el lienzo entre frames. */
#include "processing.h"

/* Una onda triangular de periodo 4 * half, entre 0 y half. */
static int wave(int t, int half) {
    t %= 2 * half;
    return t < half ? t : 2 * half - t;
}

void setup(void) {
    size(320, 240);
    background(0, 0, 40);
    noStroke();
}

void draw(void) {
    int x = 10 + wave(frameCount * 3, 300), y = 10 + wave(frameCount * 2, 220);
    fill((frameCount * 5) % 256, 255 - (frameCount * 3) % 256, 160);
    circle(x, y, 12);
    if (frameCount % 120 == 0) {
        fill(0, 0, 40);
        rect(0, (frameCount / 120 * 30) % height, width, 30);
    }
    stroke(255, 255, 255);
    point(width - 1 - x, height - 1 - y);
    noStroke();
}
