#ifndef PROCESSING_H
#define PROCESSING_H

#include "minigl.h"

/* API Processing, deliberadamente delgada sobre MiniGL.
   Colores como en Arduino TFT y en la forma (r,g,b) de Processing: canales
   0..255, convertidos a RGB565. Las variantes *565 reciben RGB565 directo;
   color565() es la de Adafruit_GFX. */

mgl_color_t color565(int r, int g, int b);
void background(int r, int g, int b);
void fill(int r, int g, int b);
void noFill(void);
void stroke(int r, int g, int b);
void background565(mgl_color_t color);
void fill565(mgl_color_t color);
void stroke565(mgl_color_t color);
void noStroke(void);
void strokeWeight(int width);
void point(int x, int y);
void line(int x0, int y0, int x1, int y1);
void rect(int x, int y, int w, int h);
void circle(int cx, int cy, int diameter);
void triangle(int x0, int y0, int x1, int y1, int x2, int y2);
void image(const mgl_sprite_t *sprite, int x, int y);

/* La aplicacion define setup() y draw(); el bucle lo proporciona la plataforma.
   La plataforma tambien proporciona size(), que se llama al principio de
   setup() como en Processing, y width/height con el tamano actual. */
void setup(void);
void draw(void);
void size(int w, int h);
extern int width, height;

#endif
