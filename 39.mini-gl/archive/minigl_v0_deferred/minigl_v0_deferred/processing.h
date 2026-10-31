#ifndef PROCESSING_H
#define PROCESSING_H
#include "minigl.h"
/* API Processing, deliberadamente delgada sobre MiniGL. */
void background(mg_color_t color);
void fill(mg_color_t color);
void noFill(void);
void stroke(mg_color_t color);
void noStroke(void);
void strokeWeight(int width);
void point(int x, int y);
void line(int x0, int y0, int x1, int y1);
void rect(int x, int y, int w, int h);
void circle(int cx, int cy, int radius);
void triangle(int x0, int y0, int x1, int y1, int x2, int y2);
void image(const mg_sprite_t *sprite, int x, int y);
/* La aplicacion define setup() y draw(); el bucle lo proporciona la plataforma. */
void setup(void);
void draw(void);
#endif
