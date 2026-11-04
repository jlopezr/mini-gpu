#include "minigl.h"
#include "raster.h"
#include <string.h>
/* Evita depender de stdint.h (C99). */
typedef char check_u32[(sizeof(mg_u32)==4)?1:-1];
typedef char check_u16[(sizeof(mg_color_t)==2)?1:-1];
#define OP_CLEAR 1U
#define OP_BATCH 2U
#define PR_POINT 1U
#define PR_LINE 2U
#define PR_RECT 3U
#define PR_CIRCLE 4U
#define PR_TRIANGLE 5U
#define PR_IMAGE 6U
#define FLAG_FILL 1U
#define FLAG_STROKE 2U
static mg_cmd_buffer_t *current;
static mg_color_t fill_color=0xffff,stroke_color=0xffff;
static unsigned int flags=FLAG_FILL,weight=1;
static void wr16(unsigned char *p,unsigned int v) { p[0]=(unsigned char)v; p[1]=(unsigned char)(v>>8); }
static void wr32(unsigned char *p,mg_u32 v) { p[0]=(unsigned char)v; p[1]=(unsigned char)(v>>8); p[2]=(unsigned char)(v>>16); p[3]=(unsigned char)(v>>24); }
static unsigned int rd16(const unsigned char *p) { return (unsigned int)p[0]|((unsigned int)p[1]<<8); }
static mg_u32 rd32(const unsigned char *p) { return (mg_u32)p[0]|((mg_u32)p[1]<<8)|((mg_u32)p[2]<<16)|((mg_u32)p[3]<<24); }
static mg_u32 pack(int a,int b) { return (mg_u32)((unsigned int)a&65535U)|((mg_u32)((unsigned int)b&65535U)<<16); }
static int low(mg_u32 p) { unsigned int v=(unsigned int)(p&65535U); return v>=32768U?(int)v-65536:(int)v; }
static int high(mg_u32 p) { return low(p>>16); }
static int fit(int v) { return v>=-32768 && v<=32767; }
static void header(mg_cmd_buffer_t *b) { wr32(b->bytes,MG_BUFFER_MAGIC); wr32(b->bytes+4,MG_BUFFER_VERSION); wr32(b->bytes+8,b->used); wr32(b->bytes+12,b->capacity); }
int mg_cmd_init(mg_cmd_buffer_t *b,void *memory,mg_u32 capacity) {
    if(!b || !memory || capacity<16U) return MG_ERR_ARGUMENT;
    memset(b,0,sizeof(*b)); b->bytes=(unsigned char *)memory; b->capacity=capacity;
    return mg_cmd_reset(b);
}
int mg_cmd_reset(mg_cmd_buffer_t *b) {
    if(!b || !b->bytes || b->capacity<16U) return MG_ERR_ARGUMENT;
    b->used=16; b->sprite_count=0; b->error=MG_OK; header(b); return MG_OK;
}
int mg_cmd_status(const mg_cmd_buffer_t *b) { return b?b->error:MG_ERR_ARGUMENT; }
void mg_set_deferred(mg_cmd_buffer_t *b) {
    current=b;
    if(!b) {
        if(flags&FLAG_FILL) sw_fill(fill_color); else sw_no_fill();
        if(flags&FLAG_STROKE) sw_stroke(stroke_color); else sw_no_stroke();
        sw_stroke_weight((int)weight);
    }
}
void mg_bind(mg_color_t *p,int w,int h,int stride) {
    sw_bind(p,w,h,stride); fill_color=stroke_color=0xffff; flags=FLAG_FILL; weight=1;
}
static void emit_clear(mg_color_t color) {
    unsigned char *p; mg_cmd_buffer_t *b=current;
    if(b->error) return;
    if(b->capacity-b->used<16U) { b->error=MG_ERR_SPACE; return; }
    p=b->bytes+b->used; wr32(p,OP_CLEAR); wr32(p+4,16); wr32(p+8,color); wr32(p+12,0);
    b->used+=16; header(b);
}
static void emit(mg_u32 type,mg_u32 p0,mg_u32 p1,mg_u32 p2) {
    unsigned char *p; mg_cmd_buffer_t *b=current;
    if(b->error) return;
    if(b->capacity-b->used<40U) { b->error=MG_ERR_SPACE; return; }
    p=b->bytes+b->used;
    wr32(p,OP_BATCH); wr32(p+4,40); wr32(p+8,1); wr32(p+12,0);
    wr32(p+16,type); wr32(p+20,p0); wr32(p+24,p1); wr32(p+28,p2);
    wr16(p+32,fill_color); wr16(p+34,stroke_color);
    wr16(p+36,flags); wr16(p+38,weight);
    b->used+=40; header(b);
}
void mg_clear(mg_color_t c) { if(current) emit_clear(c); else sw_clear(c); }
void mg_fill(mg_color_t c) { fill_color=c; flags|=FLAG_FILL; if(!current) sw_fill(c); }
void mg_no_fill(void) { flags&=~FLAG_FILL; if(!current) sw_no_fill(); }
void mg_stroke(mg_color_t c) { stroke_color=c; flags|=FLAG_STROKE; if(!current) sw_stroke(c); }
void mg_no_stroke(void) { flags&=~FLAG_STROKE; if(!current) sw_no_stroke(); }
void mg_stroke_weight(int w) { weight=(unsigned int)(w>0?w:1); if(weight>65535U) weight=65535U; if(!current) sw_stroke_weight((int)weight); }
void mg_point(int x,int y) { if(current) { if(fit(x)&&fit(y)) emit(PR_POINT,pack(x,y),0,0); else current->error=MG_ERR_ARGUMENT; } else sw_point(x,y); }
void mg_line(int x,int y,int a,int b) { if(current) { if(fit(x)&&fit(y)&&fit(a)&&fit(b)) emit(PR_LINE,pack(x,y),pack(a,b),0); else current->error=MG_ERR_ARGUMENT; } else sw_line(x,y,a,b); }
void mg_rect(int x,int y,int w,int h) { if(current) { if(fit(x)&&fit(y)&&fit(w)&&fit(h)) emit(PR_RECT,pack(x,y),pack(w,h),0); else current->error=MG_ERR_ARGUMENT; } else sw_rect(x,y,w,h); }
void mg_circle(int x,int y,int r) { if(current) { if(fit(x)&&fit(y)&&fit(r)) emit(PR_CIRCLE,pack(x,y),pack(r,0),0); else current->error=MG_ERR_ARGUMENT; } else sw_circle(x,y,r); }
void mg_triangle(int x,int y,int a,int b,int c,int d) { if(current) { if(fit(x)&&fit(y)&&fit(a)&&fit(b)&&fit(c)&&fit(d)) emit(PR_TRIANGLE,pack(x,y),pack(a,b),pack(c,d)); else current->error=MG_ERR_ARGUMENT; } else sw_triangle(x,y,a,b,c,d); }
void mg_image(const mg_sprite_t *s,int x,int y) {
    unsigned int i; mg_cmd_buffer_t *b=current;
    if(!b) { sw_image(s,x,y); return; }
    if(b->error) return;
    if(!s || !fit(x) || !fit(y)) { b->error=MG_ERR_ARGUMENT; return; }
    for(i=0;i<b->sprite_count;i++) if(b->sprites[i]==s) break;
    if(i==b->sprite_count) {
        if(i>=256U) { b->error=MG_ERR_SPRITES; return; }
        b->sprites[i]=s; b->sprite_count++;
    }
    emit(PR_IMAGE,pack(x,y),(mg_u32)i,0);
}
static void apply(unsigned int f,mg_color_t fc,mg_color_t sc,int w) {
    if(f&FLAG_FILL) sw_fill(fc); else sw_no_fill();
    if(f&FLAG_STROKE) sw_stroke(sc); else sw_no_stroke();
    sw_stroke_weight(w);
}
int mg_cmd_render_cpu(const mg_cmd_buffer_t *b) {
    mg_u32 off,op,size,t,p0,p1,p2; const unsigned char *p; mg_cmd_buffer_t *saved=current;
    if(!b || !b->bytes || b->used<16U || b->used>b->capacity || b->error) return MG_ERR_ARGUMENT;
    if(rd32(b->bytes)!=MG_BUFFER_MAGIC || rd32(b->bytes+4)!=MG_BUFFER_VERSION || rd32(b->bytes+8)!=b->used || rd32(b->bytes+12)!=b->capacity) return MG_ERR_ARGUMENT;
    current=0;
    for(off=16;off<b->used;off+=size) {
        if(b->used-off<16U) { current=saved; return MG_ERR_ARGUMENT; }
        p=b->bytes+off; op=rd32(p); size=rd32(p+4);
        if(size<16U || size>b->used-off) { current=saved; return MG_ERR_ARGUMENT; }
        if(op==OP_CLEAR) {
            if(size!=16U) { current=saved; return MG_ERR_ARGUMENT; }
            sw_clear((mg_color_t)rd32(p+8));
        } else if(op==OP_BATCH) {
            if(size!=40U || rd32(p+8)!=1U) { current=saved; return MG_ERR_ARGUMENT; }
            t=rd32(p+16); p0=rd32(p+20); p1=rd32(p+24); p2=rd32(p+28);
            apply(rd16(p+36), (mg_color_t)rd16(p+32),(mg_color_t)rd16(p+34),(int)rd16(p+38));
            if(t==PR_POINT) sw_point(low(p0),high(p0));
            else if(t==PR_LINE) sw_line(low(p0),high(p0),low(p1),high(p1));
            else if(t==PR_RECT) sw_rect(low(p0),high(p0),low(p1),high(p1));
            else if(t==PR_CIRCLE) sw_circle(low(p0),high(p0),low(p1));
            else if(t==PR_TRIANGLE) sw_triangle(low(p0),high(p0),low(p1),high(p1),low(p2),high(p2));
            else if(t==PR_IMAGE) {
                if(p1>=b->sprite_count) { current=saved; return MG_ERR_ARGUMENT; }
                sw_image(b->sprites[p1],low(p0),high(p0));
            } else { current=saved; return MG_ERR_ARGUMENT; }
        } else { current=saved; return MG_ERR_ARGUMENT; }
    }
    current=saved; return MG_OK;
}
