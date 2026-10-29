#include "gfx.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

static int add_clear(GfxDisplayList *l,uint16_t color) {
    GfxCommand c={.opcode=GFX_CLEAR,.data.clear={color}};return gfx_list_add(l,c);
}
static int add_clip(GfxDisplayList *l,GfxRect r) {
    GfxCommand c={.opcode=GFX_SET_CLIP,.data.clip={r}};return gfx_list_add(l,c);
}
static int add_rect(GfxDisplayList *l,GfxRect r,uint16_t color) {
    GfxCommand c={.opcode=GFX_FILL_RECT,.data.fill_rect={r,color}};return gfx_list_add(l,c);
}
static int add_line(GfxDisplayList *l,int x0,int y0,int x1,int y1,uint16_t color) {
    GfxCommand c={.opcode=GFX_DRAW_LINE,.data.line={x0,y0,x1,y1,color}};return gfx_list_add(l,c);
}
static int demo(uint32_t width,uint32_t height,const char *path) {
    uint16_t *pixels=calloc((size_t)width*height,sizeof(*pixels));
    if (!pixels) return -1;
    GfxSurface surface={pixels,width,height,width};
    GfxDisplayList list;
    gfx_list_init(&list);
    int scale=(int)(width/320);
    int ok=0;
    /* Identical logical scene at two target resolutions. */
    #define R(X,Y,W,H) (GfxRect){(X)*scale,(Y)*scale,(W)*scale,(H)*scale}
    if (add_clear(&list,0x3186) ||
        add_rect(&list,R(14,10,292,220),0xFFFF) ||
        add_rect(&list,R(14,10,292,24),0x18C3) ||
        add_rect(&list,R(22,44,276,4),0x18C3) ||
        add_rect(&list,R(22,55,126,125),0xDF1C) ||
        add_rect(&list,R(158,55,140,125),0xE79C) ||
        add_rect(&list,R(22,190,276,25),0x7BEF) ||
        add_clip(&list,R(22,55,126,125)) ||
        add_line(&list,10*scale,60*scale,170*scale,200*scale,0x001F) ||
        add_clip(&list,R(0,0,320,240)) ||
        add_line(&list,158*scale,180*scale,298*scale,55*scale,0xF800)) goto done;
    if (gfx_execute_cpu(&list,&surface) || gfx_write_ppm(path,&surface)) goto done;
    ok=1;
    printf("Created %s (%ux%u RGB565)\n",path,width,height);
 done:
    gfx_list_destroy(&list);
    free(pixels);
    return ok?0:-1;
}
int main(void) {
    return demo(320,240,"demo-320x240.ppm") || demo(640,480,"demo-640x480.ppm") ? 1:0;
}
