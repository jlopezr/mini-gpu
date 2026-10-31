#include "processing.h"
#define WIDTH 320
#define HEIGHT 240
/* Sustituir por la direccion del backbuffer proporcionada por la plataforma. */
static mg_color_t framebuffer[WIDTH*HEIGHT];
void setup(void) {
    mg_bind(framebuffer,WIDTH,HEIGHT,WIDTH);
    stroke(0xffff);
    strokeWeight(1);
}
void draw(void) {
    background(0x0000);
    fill(0xf800); rect(20,20,100,60);
    fill(0x07e0); circle(170,90,35);
    fill(0x001f); triangle(70,160,150,200,210,130);
    noFill(); stroke(0xffff); line(0,0,319,239);
}
/* La plataforma llama setup una vez y draw en cada frame; aqui no hay main. */
