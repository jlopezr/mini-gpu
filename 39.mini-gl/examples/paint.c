/* Pintar con el ratón y el teclado: el lienzo no se borra entre frames.
     botón del ratón     pinta (una línea del punto anterior al actual)
     r g b y c m w       color: rojo, verde, azul, amarillo, cian, magenta, blanco
     + -                 grosor del pincel (también flechas arriba y abajo)
     espacio             borra
   En la esquina, el color y el grosor actuales.
   SDL: paint-sdl. Simulador: make sim-paint (la ventana da el ratón y el teclado). */
#include "processing.h"

static int r = 255, g = 255, b = 255, weight = 3, last_key;

static void clear_canvas(void) {
    background(20, 20, 30);
}

void setup(void) {
    size(320, 240);
    clear_canvas();
}

static void color_key(int k) {
    static const char keys[] = "rgbycmw";
    static const unsigned char colors[][3] = {
        {255, 60, 60}, {60, 220, 60}, {70, 110, 255}, {255, 220, 40}, {40, 220, 220}, {230, 60, 230}, {255, 255, 255}};
    int i;
    for (i = 0; keys[i]; i++)
        if (k == keys[i]) {
            r = colors[i][0];
            g = colors[i][1];
            b = colors[i][2];
        }
}

void draw(void) {
    /* key es la última tecla pulsada: se actúa cuando cambia o se vuelve a pulsar. */
    if (keyPressed && key != last_key) {
        if (key == ' ')
            clear_canvas();
        else if (key == '+' || key == '=' || (key == CODED && keyCode == UP))
            weight = weight < 12 ? weight + 1 : 12;
        else if (key == '-' || (key == CODED && keyCode == DOWN))
            weight = weight > 1 ? weight - 1 : 1;
        else
            color_key(key);
    }
    last_key = keyPressed ? key : 0;

    if (mousePressed) {
        stroke(r, g, b);
        strokeWeight(weight);
        line(pmouseX, pmouseY, mouseX, mouseY);
    }

    noStroke();
    fill(20, 20, 30);
    rect(0, 0, 18, 18);
    fill(r, g, b);
    circle(9, 9, weight + 2);
}
