#ifndef RASTER_H
#define RASTER_H

#include "minigl.h"

void sw_bind(mgl_color_t *,int,int,int);
void sw_set_target(mgl_color_t *);
void sw_clear(mgl_color_t);
void sw_fill(mgl_color_t);
void sw_no_fill(void);
void sw_stroke(mgl_color_t);
void sw_no_stroke(void);
void sw_stroke_weight(int);
void sw_point(int,int);
void sw_line(int,int,int,int);
void sw_rect(int,int,int,int);
void sw_circle(int,int,int);
void sw_triangle(int,int,int,int,int,int);
void sw_image(const mgl_sprite_t *,int,int);

#endif
