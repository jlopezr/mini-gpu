#include "processing.h"
#include "gpu_renderer.h"
#include <stdio.h>
#include <string.h>
#define W 64
#define H 48
static mgl_color_t reference[W*H],gpu[W*H],deferred[W*H];
static unsigned char bytes[16384];
static mgl_cmd_buffer_t cmd;
static mgl_gpu_sprite_t sprites[MGL_GPU_MAX_SPRITES];
static mgl_color_t pix[9]={1,2,3,4,5,6,7,8,9};
static mgl_sprite_t sprite={pix,3,3,3};
void setup(void) {}
void draw(void) {
    background565(0x1234);
    fill565(0xf800); noStroke(); rect(1,2,22,13);
    fill565(0x07e0); circle(30,20,18);
    stroke565(0xffff); strokeWeight(2); line(-2,0,60,44);
    fill565(0x001f); triangle(5,30,19,45,38,27);
    noFill(); rect(3,4,40,32); point(15,15);
    image(&sprite,50,39);
    background565(0x0123);
    fill565(0xf800); noStroke(); rect(-4,-3,27,18);
    stroke565(0xffff); strokeWeight(3); line(0,0,63,47);
    fill565(0x001f); circle(31,24,28);
    fill565(0x07e0); triangle(4,44,62,45,30,1);
    image(&sprite,62,46);
}
int main(void) {
    int result,x,y;
    mgl_gpu_job_t job;
    mgl_bind(reference,W,H,W); mgl_set_deferred(0); draw();
    mgl_bind(gpu,W,H,W);
    result=mgl_cmd_init(&cmd,bytes,sizeof(bytes)); if(result) return 1;
    mgl_set_deferred(&cmd); draw();
    if(mgl_cmd_status(&cmd)) return 2;
    mgl_bind(deferred,W,H,W);
    result=mgl_cmd_render_cpu(&cmd); if(result) return 3;
    if(memcmp(reference,deferred,sizeof(reference))) {
        puts("FAIL: V0 direct != V1 deferred CPU"); return 6;
    }
    result=mgl_gpu_sprites_from_cmd(&cmd,sprites,MGL_GPU_MAX_SPRITES); if(result) return 3;
    job.commands=cmd.bytes; job.command_bytes=cmd.used;
    job.framebuffer=gpu; job.width=W; job.height=H; job.pitch=W;
    job.sprites=sprites; job.sprite_count=cmd.sprite_count;
    result=mgl_gpu_render(&job); if(result) return 4;
    if(memcmp(reference,gpu,sizeof(gpu))) {
        for(y=0;y<H;y++) for(x=0;x<W;x++) if(reference[y*W+x]!=gpu[y*W+x]) {
            printf("FAIL at %d,%d: expected %04x got %04x\n",x,y,
                   (unsigned)reference[y*W+x],(unsigned)gpu[y*W+x]); return 5;
        }
    }
    printf("PASS: V0 direct == V1 deferred CPU == V2 GPU host 8 lanes, %u command bytes\n",(unsigned)cmd.used);
    return 0;
}
