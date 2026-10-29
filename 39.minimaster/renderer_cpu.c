#include "gfx.h"
#include <stdio.h>
#include <stdint.h>
#include <limits.h>

static GfxRect intersect(GfxRect a, GfxRect b) {
    int64_t x0 = a.x > b.x ? a.x : b.x;
    int64_t y0 = a.y > b.y ? a.y : b.y;
    int64_t ax1 = (int64_t)a.x + a.w, bx1 = (int64_t)b.x + b.w;
    int64_t ay1 = (int64_t)a.y + a.h, by1 = (int64_t)b.y + b.h;
    int64_t x1 = ax1 < bx1 ? ax1 : bx1;
    int64_t y1 = ay1 < by1 ? ay1 : by1;
    if (x1 <= x0 || y1 <= y0) return (GfxRect){0,0,0,0};
    return (GfxRect){(int32_t)x0,(int32_t)y0,(int32_t)(x1-x0),(int32_t)(y1-y0)};
}
static void fill(GfxSurface *s, GfxRect r, uint16_t color) {
    if (r.w <= 0 || r.h <= 0) return;
    for (int32_t y = r.y; y < r.y+r.h; ++y)
        for (int32_t x = r.x; x < r.x+r.w; ++x)
            s->pixels[(size_t)y*s->stride+(size_t)x] = color;
}
static void pixel(GfxSurface *s, GfxRect clip, int64_t x, int64_t y, uint16_t color) {
    if (x >= clip.x && x < (int64_t)clip.x+clip.w &&
        y >= clip.y && y < (int64_t)clip.y+clip.h)
        s->pixels[(size_t)y*s->stride+(size_t)x] = color;
}
static void line(GfxSurface *s, GfxRect clip, int64_t x0,int64_t y0,int64_t x1,int64_t y1,uint16_t color) {
    /* Bresenham, but reject excessively long off-screen lines in this reference
       backend to prevent pathological iteration; demo coordinates are bounded. */
    int64_t dx = x1>x0 ? x1-x0 : x0-x1;
    int64_t dy = y1>y0 ? y1-y0 : y0-y1;
    if (dx > 1000000 || dy > 1000000) return;
    int64_t sx=x0<x1?1:-1, sy=y0<y1?1:-1, err=dx-dy;
    for (;;) {
        pixel(s,clip,x0,y0,color);
        if (x0==x1 && y0==y1) break;
        int64_t twice=2*err;
        if (twice>-dy) {err-=dy;x0+=sx;}
        if (twice< dx) {err+=dx;y0+=sy;}
    }
}
int gfx_execute_cpu(const GfxDisplayList *list, GfxSurface *s) {
    if (!list || !s || !s->pixels || !s->width || !s->height ||
        s->width > INT32_MAX || s->height > INT32_MAX || s->stride < s->width ||
        (list->count && !list->commands)) return -1;
    GfxRect bounds = {0,0,(int32_t)s->width,(int32_t)s->height};
    GfxRect clip = bounds;
    for (uint32_t i=0; i<list->count; ++i) {
        const GfxCommand *c=&list->commands[i];
        switch (c->opcode) {
        case GFX_CLEAR: fill(s,bounds,c->data.clear.color); break;
        case GFX_SET_CLIP: clip=intersect(bounds,c->data.clip.rect); break;
        case GFX_FILL_RECT: fill(s,intersect(clip,c->data.fill_rect.rect),c->data.fill_rect.color); break;
        case GFX_DRAW_LINE:
            line(s,clip,c->data.line.x0,c->data.line.y0,c->data.line.x1,c->data.line.y1,c->data.line.color);
            break;
        default: return -2; /* planned commands, not silently ignored */
        }
    }
    return 0;
}
int gfx_write_ppm(const char *filename, const GfxSurface *s) {
    if (!filename || !s || !s->pixels || !s->width || !s->height || s->stride<s->width) return -1;
    FILE *f=fopen(filename,"wb");
    if (!f) return -1;
    if (fprintf(f,"P6\n%u %u\n255\n",s->width,s->height)<0) {fclose(f);return -1;}
    for (uint32_t y=0;y<s->height;y++) for (uint32_t x=0;x<s->width;x++) {
        uint16_t v=s->pixels[(size_t)y*s->stride+x];
        unsigned char rgb[3]={(unsigned char)(((v>>11)&31)*255/31),
                              (unsigned char)(((v>>5)&63)*255/63),
                              (unsigned char)((v&31)*255/31)};
        if (fwrite(rgb,1,3,f)!=3) {fclose(f);return -1;}
    }
    return fclose(f)==0?0:-1;
}
