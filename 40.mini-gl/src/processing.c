#include "processing.h"
void background(int r,int g,int b) { mgl_clear(color565(r,g,b)); }
void fill(int r,int g,int b) { mgl_fill(color565(r,g,b)); }
void noFill(void) { mgl_no_fill(); }
void stroke(int r,int g,int b) { mgl_stroke(color565(r,g,b)); }
void background565(mgl_color_t c) { mgl_clear(c); }
void fill565(mgl_color_t c) { mgl_fill(c); }
void stroke565(mgl_color_t c) { mgl_stroke(c); }
void noStroke(void) { mgl_no_stroke(); }
void strokeWeight(int w) { mgl_stroke_weight(w); }
void point(int x,int y) { mgl_point(x,y); }
void line(int x0,int y0,int x1,int y1) { mgl_line(x0,y0,x1,y1); }
void rect(int x,int y,int w,int h) { mgl_rect(x,y,w,h); }
/* MiniGL usa radio y centra el circulo en un pixel: ocupa 2*(d/2)+1 pixeles,
   asi que un diametro par sale un pixel mas ancho. */
void circle(int x,int y,int d) { mgl_circle(x,y,d/2); }
void triangle(int x0,int y0,int x1,int y1,int x2,int y2) { mgl_triangle(x0,y0,x1,y1,x2,y2); }
void image(const mgl_sprite_t *s,int x,int y) { mgl_image(s,x,y); }
mgl_color_t color565(int r,int g,int b) {
    r=r<0?0:r>255?255:r; g=g<0?0:g>255?255:g; b=b<0?0:b>255?255:b;
    return (mgl_color_t)(((unsigned int)r>>3)<<11 | ((unsigned int)g>>2)<<5 | ((unsigned int)b>>3));
}
