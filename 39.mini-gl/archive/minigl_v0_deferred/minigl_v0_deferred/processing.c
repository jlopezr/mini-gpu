#include "processing.h"
void background(mg_color_t c) { mg_clear(c); }
void fill(mg_color_t c) { mg_fill(c); }
void noFill(void) { mg_no_fill(); }
void stroke(mg_color_t c) { mg_stroke(c); }
void noStroke(void) { mg_no_stroke(); }
void strokeWeight(int w) { mg_stroke_weight(w); }
void point(int x,int y) { mg_point(x,y); }
void line(int x0,int y0,int x1,int y1) { mg_line(x0,y0,x1,y1); }
void rect(int x,int y,int w,int h) { mg_rect(x,y,w,h); }
void circle(int x,int y,int r) { mg_circle(x,y,r); }
void triangle(int x0,int y0,int x1,int y1,int x2,int y2) { mg_triangle(x0,y0,x1,y1,x2,y2); }
void image(const mg_sprite_t *s,int x,int y) { mg_image(s,x,y); }
