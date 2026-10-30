#ifndef RASTER_H
#define RASTER_H
#include "minigl.h"
void sw_bind(mg_color_t *,int,int,int);
void sw_clear(mg_color_t);
void sw_fill(mg_color_t);
void sw_no_fill(void);
void sw_stroke(mg_color_t);
void sw_no_stroke(void);
void sw_stroke_weight(int);
void sw_point(int,int);
void sw_line(int,int,int,int);
void sw_rect(int,int,int,int);
void sw_circle(int,int,int);
void sw_triangle(int,int,int,int,int,int);
void sw_image(const mg_sprite_t *,int,int);
#endif
