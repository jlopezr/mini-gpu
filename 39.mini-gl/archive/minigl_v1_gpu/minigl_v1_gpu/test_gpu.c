#include "processing.h"
#include "gpu_renderer.h"
#include <stdio.h>
#include <string.h>
#define W 64
#define H 48
static mg_color_t reference[W*H],gpu[W*H],deferred[W*H];
static unsigned char bytes[16384];
static mg_cmd_buffer_t cmd;
static mg_gpu_sprite_t sprites[MG_GPU_MAX_SPRITES];
static mg_color_t pix[9]={1,2,3,4,5,6,7,8,9};
static mg_sprite_t sprite={pix,3,3,3};
void setup(void) {}
void draw(void) {
    background(0x1234);
    fill(0xf800); noStroke(); rect(1,2,22,13);
    fill(0x07e0); circle(30,20,9);
    stroke(0xffff); strokeWeight(2); line(-2,0,60,44);
    fill(0x001f); triangle(5,30,19,45,38,27);
    noFill(); rect(3,4,40,32); point(15,15);
    image(&sprite,50,39);
    background(0x0123);
    fill(0xf800); noStroke(); rect(-4,-3,27,18);
    stroke(0xffff); strokeWeight(3); line(0,0,63,47);
    fill(0x001f); circle(31,24,14);
    fill(0x07e0); triangle(4,44,62,45,30,1);
    image(&sprite,62,46);
}
int main(void) {
    int result,x,y;
    mg_gpu_job_t job;
    mg_bind(reference,W,H,W); mg_set_deferred(0); draw();
    mg_bind(gpu,W,H,W);
    result=mg_cmd_init(&cmd,bytes,sizeof(bytes)); if(result) return 1;
    mg_set_deferred(&cmd); draw();
    if(mg_cmd_status(&cmd)) return 2;
    mg_bind(deferred,W,H,W);
    result=mg_cmd_render_cpu(&cmd); if(result) return 3;
    if(memcmp(reference,deferred,sizeof(reference))) {
        puts("FAIL: V0 direct != V0 deferred"); return 6;
    }
    result=mg_gpu_sprites_from_v0(&cmd,sprites,MG_GPU_MAX_SPRITES); if(result) return 3;
    job.commands=cmd.bytes; job.command_bytes=cmd.used;
    job.framebuffer=gpu; job.width=W; job.height=H; job.pitch=W;
    job.sprites=sprites; job.sprite_count=cmd.sprite_count;
    result=mg_gpu_render_host(&job); if(result) return 4;
    if(memcmp(reference,gpu,sizeof(gpu))) {
        for(y=0;y<H;y++) for(x=0;x<W;x++) if(reference[y*W+x]!=gpu[y*W+x]) {
            printf("FAIL at %d,%d: expected %04x got %04x\n",x,y,
                   (unsigned)reference[y*W+x],(unsigned)gpu[y*W+x]); return 5;
        }
    }
    printf("PASS: V0 direct == V0 deferred == V1 host 8 lanes, %u command bytes\n",(unsigned)cmd.used);
    return 0;
}
