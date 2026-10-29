#include "gfx.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int add(GfxDisplayList *l,GfxCommand c){return gfx_list_add(l,c);}
static int rect(GfxDisplayList *l,int x,int y,int w,int h,uint16_t c){return add(l,(GfxCommand){.opcode=GFX_FILL_RECT,.data.fill_rect={{x,y,w,h},c}});}
static int clip(GfxDisplayList *l,int x,int y,int w,int h){return add(l,(GfxCommand){.opcode=GFX_SET_CLIP,.data.clip={{x,y,w,h}}});}
static int run_cmd(GfxDisplayList *l,uint32_t id,uint16_t color){return add(l,(GfxCommand){.opcode=GFX_GLYPH_RUN,.data.glyph_run={id,color}});}
static uint8_t *load(const char *file,size_t *n){FILE *f=fopen(file,"rb");if(!f)return NULL;if(fseek(f,0,SEEK_END)){fclose(f);return NULL;}long z=ftell(f);if(z<=0||fseek(f,0,SEEK_SET)){fclose(f);return NULL;}uint8_t *p=malloc((size_t)z);if(!p){fclose(f);return NULL;}if(fread(p,1,(size_t)z,f)!=(size_t)z){free(p);fclose(f);return NULL;}fclose(f);*n=(size_t)z;return p;}
static int build_text(const MfFont *font,const char *text,int x,int baseline,GfxPositionedGlyph *out,uint32_t *count){
    uint32_t n=0;int pen=x;
    for(const unsigned char *p=(const unsigned char*)text;*p;p++){
        if(n>=256)return -1;
        MfGlyph g;
        if(mf_find_glyph(font,*p,&g)){
            if(*p==' '){pen+=font->pixel_size/2;continue;}
            return -1;
        }
        out[n++]=(GfxPositionedGlyph){*p,pen,baseline};pen+=g.advance_x;
    }
    *count=n;return 0;
}
static int demo(const MfFont *font,int w,int h,const char *path){
    uint16_t *pixels=calloc((size_t)w*h,sizeof(uint16_t));if(!pixels)return -1;
    GfxSurface surface={pixels,(uint32_t)w,(uint32_t)h,(uint32_t)w};
    GfxPositionedGlyph glyphs[3][256];uint32_t counts[3];
    const char *lines[]={"THE MINIGPU TIMES","PARK 10 - ORIGINAL NEWSMASTER FONT","GLYPH RUN / RGB565 / CLIPPING"};
    int base[]={64,97,128};
    int k=(w==640)?2:1;
    for(int i=0;i<3;i++)if(build_text(font,lines[i],22*k,base[i]*k,glyphs[i],&counts[i])){free(pixels);return -1;}
    GfxGlyphRun runs[3];for(int i=0;i<3;i++)runs[i]=(GfxGlyphRun){glyphs[i],counts[i],0};
    const MfFont *fonts[]={font};GfxResources resources={.fonts=fonts,.font_count=1,.runs=runs,.run_count=3};
    GfxDisplayList dl;gfx_list_init(&dl);
    int fail=0;
    fail|=add(&dl,(GfxCommand){.opcode=GFX_CLEAR,.data.clear={0x3A4B}});
    fail|=rect(&dl,12*k,8*k,296*k,220*k,0xFFDE);
    fail|=rect(&dl,12*k,8*k,296*k,24*k,0x1946);
    fail|=rect(&dl,20*k,145*k,280*k,2*k,0x1946);
    fail|=clip(&dl,20*k,35*k,280*k,108*k);
    fail|=run_cmd(&dl,0,0x0000);
    fail|=run_cmd(&dl,1,0x0010);
    fail|=run_cmd(&dl,2,0x7800);
    fail|=clip(&dl,0,0,w,h);
    fail|=rect(&dl,20*k,170*k,280*k,37*k,0xC638);
    fail|=rect(&dl,20*k,214*k,280*k,5*k,0x1946);
    if(!fail)fail=gfx_execute_cpu_resources(&dl,&surface,&resources);
    if(!fail)fail=gfx_write_ppm(path,&surface);
    gfx_list_destroy(&dl);free(pixels);
    if(!fail)printf("Created %s\n",path);
    return fail;
}
int main(int argc,char **argv){
    const char *path=argc>1?argv[1]:"park10.mf";
    size_t n=0;uint8_t *data=load(path,&n);MfFont font;
    if(!data||mf_open(&font,data,n)){fprintf(stderr,"Cannot open MFNT font: %s\n",path);free(data);return 1;}
    int rc=demo(&font,320,240,"demo-320x240.ppm")||demo(&font,640,480,"demo-640x480.ppm");free(data);return rc?1:0;
}
