/* Todas las primitivas de MiniGL a traves de la API Processing: relleno,
   contorno, grosores, recorte en los bordes y un sprite.
   Uso: shapes [-v 0|1|2|all] [-o salida.ppm] */
#include "processing.h"

#define SW 16
static mgl_color_t sprite_pixels[SW*SW];
static mgl_sprite_t sprite={sprite_pixels,SW,SW,SW};

void setup(void) {
    int x,y;
    size(320,240);
    for(y=0;y<SW;y++) for(x=0;x<SW;x++)
        sprite_pixels[y*SW+x]=((x/4+y/4)&1)?color565(255,255,255):color565(x*16,0,y*16);
}

void draw(void) {
    background(24,32,48);
    noStroke();
    fill(220,60,60); rect(20,20,100,60);
    fill(60,200,90); circle(200,60,80);
    fill(70,110,240); triangle(30,220,140,110,170,210);

    stroke(255,220,0); strokeWeight(4);
    noFill(); rect(190,120,110,90);
    fill(250,140,30); circle(245,165,60);

    stroke(255,255,255); strokeWeight(1);
    line(0,0,width-1,height-1);
    strokeWeight(3); line(width-1,0,0,height-1);
    point(160,120);

    /* Recortadas por los bordes del framebuffer. */
    noStroke(); fill(180,80,220);
    circle(-10,120,60); rect(290,-20,60,50);

    image(&sprite,140,20); image(&sprite,312,232);
}
