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
/* Doble buffer como en platform_minigpu: frames que no borran (estela), que
   borran a mitad, que no dibujan nada y que cambian el estado para el siguiente. */
#define FRAMES 9
static mgl_color_t reference[FRAMES][W*H],buffer_a[W*H],buffer_b[W*H];
static void frame(int i) {
    if(i==0) { background565(0x1234); fill565(0xf800); }
    else if(i%4==1) { rect(i,i,10,8); fill565((mgl_color_t)(0x0700*i)); }
    else if(i%4==2) { circle(40,20,9); background565((mgl_color_t)(0x0101*i)); rect(i,2*i,6,6); }
    else if(i%4==3) { stroke565(0xffff); line(0,i,W-1,H-1-i); noStroke(); }
}
static int double_buffer(int deferred_mode) {
    static mgl_color_t canvas[W*H];
    mgl_color_t *front=buffer_a,*back=buffer_b,*t;
    int i;
    memset(canvas,0,sizeof(canvas));
    mgl_bind(canvas,W,H,W); mgl_set_deferred(0);
    for(i=0;i<FRAMES;i++) { frame(i); memcpy(reference[i],canvas,sizeof(canvas)); }
    memset(buffer_a,0,sizeof(buffer_a)); memset(buffer_b,0x55,sizeof(buffer_b));
    mgl_bind(back,W,H,W); mgl_set_target(back,front);
    for(i=0;i<FRAMES;i++) {
        if(deferred_mode) {
            if(mgl_cmd_reset(&cmd)) return 1;
            mgl_set_deferred(&cmd); frame(i);
            if(mgl_cmd_render_cpu(&cmd)) return 2;
            mgl_set_deferred(0);
        } else
            frame(i);
        mgl_finish();
        if(memcmp(back,reference[i],sizeof(canvas))) { printf("DIFFERENT frame %d\n",i); return 3; }
        t=front; front=back; back=t;
        mgl_set_target(back,front);
    }
    return 0;
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
    if(double_buffer(0)) return 5;
    if(double_buffer(1)) return 6;
    puts("PASS: doble buffer (mgl_set_target) == un lienzo, directo y diferido");
    return 0;
}
