#include "processing.h"
void background(mgl_color_t c) { mgl_clear(c); }
void fill(mgl_color_t c) { mgl_fill(c); }
void noFill(void) { mgl_no_fill(); }
void stroke(mgl_color_t c) { mgl_stroke(c); }
void noStroke(void) { mgl_no_stroke(); }
void strokeWeight(int w) { mgl_stroke_weight(w); }
void point(int x,int y) { mgl_point(x,y); }
void line(int x0,int y0,int x1,int y1) { mgl_line(x0,y0,x1,y1); }
void rect(int x,int y,int w,int h) { mgl_rect(x,y,w,h); }
void circle(int x,int y,int r) { mgl_circle(x,y,r); }
void triangle(int x0,int y0,int x1,int y1,int x2,int y2) { mgl_triangle(x0,y0,x1,y1,x2,y2); }
void image(const mgl_sprite_t *s,int x,int y) { mgl_image(s,x,y); }
