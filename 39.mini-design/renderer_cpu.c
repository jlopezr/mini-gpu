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
static int draw_run(GfxSurface *s, GfxRect clip, const GfxResources *resources, uint32_t run_id, uint16_t color) {
    if (!resources || run_id >= resources->run_count || !resources->runs) return -1;
    const GfxGlyphRun *run=&resources->runs[run_id];
    if (!resources->fonts || run->font_id>=resources->font_count || !run->glyphs) return -1;
    const MfFont *font=resources->fonts[run->font_id];
    if (!font) return -1;
    for (uint32_t i=0;i<run->count;i++) {
        const GfxPositionedGlyph *pg=&run->glyphs[i];
        MfGlyph glyph;
        if (mf_find_glyph(font,pg->glyph_id,&glyph)) return -1;
        int64_t x0=(int64_t)pg->x+glyph.bearing_x;
        int64_t y0=(int64_t)pg->y-glyph.bearing_y;
        for (uint32_t gy=0;gy<glyph.height;gy++) {
            int64_t y=y0+gy;
            if (y<clip.y || y>=(int64_t)clip.y+clip.h) continue;
            for (uint32_t gx=0;gx<glyph.width;gx++) {
                int64_t x=x0+gx;
                if (x>=clip.x && x<(int64_t)clip.x+clip.w && mf_glyph_pixel(font,&glyph,gx,gy))
                    s->pixels[(size_t)y*s->stride+(size_t)x]=color;
            }
        }
    }
    return 0;
}
static int draw_blit(GfxSurface *s, GfxRect clip, const GfxResources *r,
                     const GfxCommand *c) {
    const uint32_t id = c->data.blit.resource_id;
    if (!r || !r->bitmaps || id >= r->bitmap_count) return -1;
    const GfxBitmap *bm = &r->bitmaps[id];
    GfxRect src = c->data.blit.src, dst = c->data.blit.dst;
    if (!bm->pixels || bm->format != GFX_BITMAP_MONO1 ||
        bm->width == 0 || bm->height == 0 ||
        bm->stride_bytes < ((uint64_t)bm->width + 7u) / 8u ||
        src.w <= 0 || src.h <= 0 || dst.w <= 0 || dst.h <= 0 ||
        src.x < 0 || src.y < 0 ||
        (uint64_t)(uint32_t)src.x + (uint32_t)src.w > bm->width ||
        (uint64_t)(uint32_t)src.y + (uint32_t)src.h > bm->height ||
        c->data.blit.mode > GFX_BLIT_TRANSPARENT_ZERO) return -1;
    /* Destination is clipped before sampling; clipping does not distort scale. */
    GfxRect visible = intersect(dst, clip);
    if (visible.w == 0 || visible.h == 0) return 0;
    for (int64_t y = visible.y; y < (int64_t)visible.y + visible.h; ++y) {
        int64_t sy = src.y + ((y - dst.y) * src.h) / dst.h;
        const uint8_t *row = bm->pixels + (size_t)sy * bm->stride_bytes;
        for (int64_t x = visible.x; x < (int64_t)visible.x + visible.w; ++x) {
            int64_t sx = src.x + ((x - dst.x) * src.w) / dst.w;
            int set = (row[(size_t)sx >> 3] >> (7 - (sx & 7))) & 1;
            if (set || c->data.blit.mode == GFX_BLIT_OPAQUE)
                s->pixels[(size_t)y * s->stride + (size_t)x] =
                    set ? c->data.blit.foreground : c->data.blit.background;
        }
    }
    return 0;
}
int gfx_execute_cpu_resources(const GfxDisplayList *list, GfxSurface *s, const GfxResources *resources) {
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
        case GFX_BLIT:
            if (draw_blit(s,clip,resources,c)) return -3;
            break;
        case GFX_GLYPH_RUN:
            if (draw_run(s,clip,resources,c->data.glyph_run.run_id,c->data.glyph_run.color)) return -3;
            break;
        default: return -2; /* planned commands, not silently ignored */
        }
    }
    return 0;
}
int gfx_execute_cpu(const GfxDisplayList *list, GfxSurface *surface) {
    return gfx_execute_cpu_resources(list,surface,NULL);
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
