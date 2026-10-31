/* Animación: pelotas que rebotan, un círculo que sigue al ratón (más grande
   con el botón pulsado) y una barra que avanza con frameCount.
   Pensado para la plataforma SDL; en la host solo se guarda el primer frame.
   Uso: bounce-sdl [-v 0|1|2] [-s escala]   o   bounce [-v 0|1|2|all] */
#include "processing.h"

#define BALLS 12

static int bx[BALLS], by[BALLS], vx[BALLS], vy[BALLS], r[BALLS];

void setup(void) {
    int i;
    size(320, 240);
    for (i = 0; i < BALLS; i++) {
        r[i] = 6 + (i * 7) % 14;
        bx[i] = 20 + (i * 53) % 280;
        by[i] = 20 + (i * 37) % 200;
        vx[i] = 1 + i % 3;
        vy[i] = 1 + (i * 2) % 4;
        if (i & 1) vx[i] = -vx[i];
    }
}

void draw(void) {
    int i;
    background(16, 16, 32);

    noStroke();
    for (i = 0; i < BALLS; i++) {
        bx[i] += vx[i];
        by[i] += vy[i];
        if (bx[i] < r[i] || bx[i] >= width - r[i]) vx[i] = -vx[i];
        if (by[i] < r[i] || by[i] >= height - r[i]) vy[i] = -vy[i];
        fill((i * 40 + frameCount) % 256, 120 + (i * 11) % 136, 200);
        circle(bx[i], by[i], 2 * r[i]);
    }

    stroke(255, 255, 255);
    strokeWeight(2);
    noFill();
    circle(mouseX, mouseY, mousePressed ? 40 : 20);

    noStroke();
    fill(255, 200, 0);
    rect(0, height - 4, frameCount % width, 4);
}
