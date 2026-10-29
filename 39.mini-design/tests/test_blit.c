#include "gfx.h"
#include <assert.h>
#include <stdio.h>
int main(void){
    /* 2x2 pattern: black white / white black. */
    uint8_t pixels[]={0x80,0x40};
    GfxBitmap bm={pixels,2,2,1,GFX_BITMAP_MONO1};
    GfxResources r={.bitmaps=&bm,.bitmap_count=1};
    uint16_t data[36]; GfxSurface s={data,6,6,6};
    GfxDisplayList dl;gfx_list_init(&dl);
    GfxCommand cmd={.opcode=GFX_BLIT,.data.blit={
        .resource_id=0,.src={0,0,2,2},.dst={1,1,4,4},
        .foreground=0xf800,.background=0x001f,.mode=GFX_BLIT_OPAQUE}};
    assert(gfx_list_add(&dl,cmd)==0);
    for(int i=0;i<36;i++)data[i]=0x07e0;
    assert(gfx_execute_cpu_resources(&dl,&s,&r)==0);
    assert(data[1*6+1]==0xf800 && data[1*6+3]==0x001f);
    assert(data[3*6+1]==0x001f && data[3*6+3]==0xf800);
    assert(data[0]==0x07e0);
    /* Transparent pixels preserve the existing background. */
    dl.commands[0].data.blit.mode=GFX_BLIT_TRANSPARENT_ZERO;
    for(int i=0;i<36;i++)data[i]=0x07e0;
    assert(gfx_execute_cpu_resources(&dl,&s,&r)==0);
    assert(data[1*6+1]==0xf800 && data[1*6+3]==0x07e0);
    /* Clip must not rescale source sampling. */
    assert(gfx_list_add(&dl,(GfxCommand){.opcode=GFX_SET_CLIP,.data.clip={{2,2,2,2}}})==0);
    /* reset clip must precede blit */
    GfxCommand tmp=dl.commands[0];dl.commands[0]=dl.commands[1];dl.commands[1]=tmp;
    for(int i=0;i<36;i++)data[i]=0x07e0;
    assert(gfx_execute_cpu_resources(&dl,&s,&r)==0);
    assert(data[2*6+2]==0xf800 && data[2*6+3]==0x07e0);
    assert(data[1*6+1]==0x07e0);
    /* Malformed source rect is rejected. */
    dl.commands[1].data.blit.src.w=3;
    assert(gfx_execute_cpu_resources(&dl,&s,&r)!=0);
    gfx_list_destroy(&dl);
    puts("BLIT: scale, color, transparency, clipping, invalid source OK");return 0;
}
