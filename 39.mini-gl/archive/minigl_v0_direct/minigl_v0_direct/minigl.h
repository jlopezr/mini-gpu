#ifndef MINIGL_H
#define MINIGL_H
/* C89. El framebuffer contiene pixeles RGB565 de 16 bits. */
typedef unsigned short mg_color_t;
typedef struct {
    const mg_color_t *pixels;
    int width, height, stride; /* stride en pixeles */
} mg_sprite_t;
void mg_bind(mg_color_t *pixels, int width, int height, int stride);
void mg_clear(mg_color_t color);
void mg_fill(mg_color_t color);
void mg_no_fill(void);
void mg_stroke(mg_color_t color);
void mg_no_stroke(void);
void mg_stroke_weight(int width);
void mg_point(int x, int y);
void mg_line(int x0, int y0, int x1, int y1);
void mg_rect(int x, int y, int w, int h);
void mg_circle(int cx, int cy, int radius);
void mg_triangle(int x0, int y0, int x1, int y1, int x2, int y2);
void mg_image(const mg_sprite_t *sprite, int x, int y);
#endif
