/* Rejilla de figuras generada con bucles: muchas primitivas pequenas, util
   para ver el tamano del command buffer en V1/V2.
   Uso: pattern [-v 0|1|2|all] [-o salida.ppm] */
#include "processing.h"

#define CELL 20

void setup(void) {
    size(320,240);
}

void draw(void) {
    int i,j,cx,cy;
    background(color(10,10,20));
    strokeWeight(1);
    for(j=0;j<height/CELL;j++) for(i=0;i<width/CELL;i++) {
        cx=i*CELL+CELL/2; cy=j*CELL+CELL/2;
        fill(color(i*255/(width/CELL),j*255/(height/CELL),160));
        if((i+j)%3==0) { noStroke(); circle(cx,cy,CELL/2-2); }
        else if((i+j)%3==1) { stroke(color(255,255,255)); rect(cx-7,cy-7,14,14); }
        else { noStroke(); triangle(cx,cy-8,cx-8,cy+7,cx+8,cy+7); }
    }
}
