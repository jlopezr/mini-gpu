#include "processing.h"
#include <stdio.h>
#include <string.h>
#define W 64
#define H 48
static mgl_color_t direct[W*H],deferred[W*H];
static unsigned char memory[8192];
static mgl_cmd_buffer_t cmd;
static mgl_color_t sprite_pixels[9]={1,2,3,4,5,6,7,8,9};
static mgl_sprite_t sprite={sprite_pixels,3,3,3};
void setup(void) {}
void draw(void) {
    background565(0x1234);
    fill565(0xf800); noStroke(); rect(1,2,22,13);
    fill565(0x07e0); circle(30,20,18);
    stroke565(0xffff); strokeWeight(2); line(-2,0,60,44);
    fill565(0x001f); triangle(5,30,19,45,38,27);
    noFill(); rect(3,4,40,32); point(15,15);
    image(&sprite,50,39);
}
int main(void) {
    int result;
    mgl_bind(direct,W,H,W); mgl_set_deferred(0); draw();
    mgl_bind(deferred,W,H,W);
    result=mgl_cmd_init(&cmd,memory,sizeof(memory)); if(result) return 1;
    mgl_set_deferred(&cmd); draw();
    if(mgl_cmd_status(&cmd)) return 2;
    result=mgl_cmd_render_cpu(&cmd); if(result) return 3;
    if(memcmp(direct,deferred,sizeof(direct))) { puts("DIFFERENT"); return 4; }
    printf("PASS: V0 direct == V1 deferred CPU, bytes=%u\n",(unsigned)cmd.used);
    mgl_set_deferred(0);
    return 0;
}
