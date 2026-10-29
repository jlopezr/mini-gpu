#include "gfx.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(void) {
 FILE *fp=fopen("park10.mf","rb");assert(fp);assert(!fseek(fp,0,SEEK_END));long len=ftell(fp);assert(len>0);rewind(fp);
 unsigned char *data=malloc((size_t)len);assert(data);assert(fread(data,1,(size_t)len,fp)==(size_t)len);fclose(fp);
 MfFont font;assert(mf_open(&font,data,(size_t)len)==0);MfGlyph g;assert(mf_find_glyph(&font,'A',&g)==0);
 uint16_t frame[32*32]={0};GfxSurface surface={frame,32,32,32};
 GfxPositionedGlyph pg={'A',2,15};GfxGlyphRun run={&pg,1,0};const MfFont *fonts[]={&font};GfxResources resources={.fonts=fonts,.font_count=1,.runs=&run,.run_count=1};
 GfxDisplayList list;gfx_list_init(&list);
 assert(gfx_list_add(&list,(GfxCommand){.opcode=GFX_SET_CLIP,.data.clip={{0,0,32,32}}})==0);
 assert(gfx_list_add(&list,(GfxCommand){.opcode=GFX_GLYPH_RUN,.data.glyph_run={0,0xffff}})==0);
 assert(gfx_execute_cpu_resources(&list,&surface,&resources)==0);
 int touched=0;for(int i=0;i<32*32;i++)touched+=frame[i]!=0;assert(touched>0);
 for(int i=0;i<32*32;i++)frame[i]=0;
 list.commands[0].data.clip.rect=(GfxRect){0,0,1,1};
 assert(gfx_execute_cpu_resources(&list,&surface,&resources)==0);
 for(int i=0;i<32*32;i++)assert(frame[i]==0);
 gfx_list_destroy(&list);free(data);puts("GLYPH_RUN and clipping OK");return 0;
}
