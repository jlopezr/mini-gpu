#include "minigl.h"
static mgl_color_t *fb;
static int fw, fh, pitch;
static mgl_color_t fc = 0xffff, sc = 0xffff;
static int fill_on = 1, stroke_on = 0, sw = 1;
static int min2(int a,int b) { return a < b ? a : b; }
static int max2(int a,int b) { return a > b ? a : b; }
static int abs2(int a) { return a < 0 ? -a : a; }
static void put(int x,int y,mgl_color_t c) {
    if (fb && x >= 0 && y >= 0 && x < fw && y < fh) fb[y*pitch+x]=c;
}
static void brush(int x,int y,mgl_color_t c) {
    int i,j,lo=-(sw/2),hi=lo+sw;
    for(j=lo;j<hi;j++) for(i=lo;i<hi;i++) put(x+i,y+j,c);
}
static void segment(int x0,int y0,int x1,int y1,mgl_color_t c) {
    int dx=abs2(x1-x0),dy=abs2(y1-y0),sx=x0<x1?1:-1,sy=y0<y1?1:-1;
    int err=dx-dy,e;
    for(;;) {
        brush(x0,y0,c);
        if(x0==x1 && y0==y1) break;
        e=2*err;
        if(e>-dy) { err-=dy; x0+=sx; }
        if(e<dx) { err+=dx; y0+=sy; }
    }
}
static long edge(int ax,int ay,int bx,int by,int px,int py) {
    return (long)(px-ax)*(by-ay)-(long)(py-ay)*(bx-ax);
}
void sw_bind(mgl_color_t *pixels,int width,int height,int stride) {
    if(!pixels || width<=0 || height<=0 || stride<width) { fb=0; fw=fh=pitch=0; return; }
    fb=pixels; fw=width; fh=height; pitch=stride;
    fc=0xffff; sc=0xffff; fill_on=1; stroke_on=0; sw=1;
}
void sw_clear(mgl_color_t c) {
    int x,y;
    if(!fb) return;
    for(y=0;y<fh;y++) for(x=0;x<fw;x++) fb[y*pitch+x]=c;
}
void sw_fill(mgl_color_t c) { fc=c; fill_on=1; }
void sw_no_fill(void) { fill_on=0; }
void sw_stroke(mgl_color_t c) { sc=c; stroke_on=1; }
void sw_no_stroke(void) { stroke_on=0; }
void sw_stroke_weight(int w) { sw=w>0?w:1; }
void sw_point(int x,int y) { if(stroke_on) brush(x,y,sc); }
void sw_line(int x0,int y0,int x1,int y1) { if(stroke_on) segment(x0,y0,x1,y1,sc); }
void sw_rect(int x,int y,int w,int h) {
    int xx,yy,x0,x1,y0,y1;
    if(w<=0 || h<=0 || !fb) return;
    x0=max2(0,x); y0=max2(0,y);
    x1=min2(fw,x+w); y1=min2(fh,y+h);
    if(fill_on) for(yy=y0;yy<y1;yy++) for(xx=x0;xx<x1;xx++) put(xx,yy,fc);
    if(stroke_on) {
        segment(x,y,x+w-1,y,sc); segment(x+w-1,y,x+w-1,y+h-1,sc);
        segment(x+w-1,y+h-1,x,y+h-1,sc); segment(x,y+h-1,x,y,sc);
    }
}
void sw_circle(int cx,int cy,int r) {
    int x,y,xx;
    long rr;
    if(r<0 || !fb) return;
    rr=(long)r*r;
    if(fill_on) {
        int x0=max2(0,cx-r),x1=min2(fw-1,cx+r);
        int y0=max2(0,cy-r),y1=min2(fh-1,cy+r);
        for(y=y0;y<=y1;y++) for(x=x0;x<=x1;x++) {
            long dx=x-cx,dy=y-cy;
            if(dx*dx+dy*dy<=rr) put(x,y,fc);
        }
    }
    if(stroke_on) {
        x=r; y=0; xx=1-r;
        while(x>=y) {
            brush(cx+x,cy+y,sc); brush(cx+y,cy+x,sc);
            brush(cx-y,cy+x,sc); brush(cx-x,cy+y,sc);
            brush(cx-x,cy-y,sc); brush(cx-y,cy-x,sc);
            brush(cx+y,cy-x,sc); brush(cx+x,cy-y,sc);
            y++;
            if(xx<0) xx+=2*y+1;
            else { x--; xx+=2*(y-x)+1; }
        }
    }
}
void sw_triangle(int x0,int y0,int x1,int y1,int x2,int y2) {
    int x,y,left,right,top,bottom;
    long area=edge(x0,y0,x1,y1,x2,y2),a,b,c;
    if(!fb) return;
    if(fill_on && area!=0) {
        left=max2(0,min2(x0,min2(x1,x2)));
        right=min2(fw-1,max2(x0,max2(x1,x2)));
        top=max2(0,min2(y0,min2(y1,y2)));
        bottom=min2(fh-1,max2(y0,max2(y1,y2)));
        for(y=top;y<=bottom;y++) for(x=left;x<=right;x++) {
            a=edge(x0,y0,x1,y1,x,y);
            b=edge(x1,y1,x2,y2,x,y);
            c=edge(x2,y2,x0,y0,x,y);
            if((a>=0 && b>=0 && c>=0) || (a<=0 && b<=0 && c<=0)) put(x,y,fc);
        }
    }
    if(stroke_on) {
        segment(x0,y0,x1,y1,sc); segment(x1,y1,x2,y2,sc);
        segment(x2,y2,x0,y0,sc);
    }
}
void sw_image(const mgl_sprite_t *s,int x,int y) {
    int i,j,x0,y0,x1,y1;
    if(!fb || !s || !s->pixels || s->width<=0 || s->height<=0 || s->stride<s->width) return;
    x0=max2(0,x); y0=max2(0,y);
    x1=min2(fw,x+s->width); y1=min2(fh,y+s->height);
    for(j=y0;j<y1;j++) for(i=x0;i<x1;i++)
        put(i,j,s->pixels[(j-y)*s->stride+(i-x)]);
}
