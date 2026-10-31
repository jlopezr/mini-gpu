#include "minifont.h"
#include <string.h>
static uint16_t u16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
static uint32_t u32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static int16_t i16(const uint8_t *p) {
    uint16_t v = u16(p);
    return (int16_t)((int32_t)(v ^ 0x8000) - 0x8000);
}
static int range(size_t size, uint64_t off, uint64_t len) { return off <= size && len <= size - off; }
static int glyph_at(const MfFont *f, uint32_t ix, MfGlyph *g) {
    if (!f || !g || ix >= f->glyph_count)
        return -1;
    const uint8_t *p = f->data + f->glyph_table_offset + (size_t)ix * 24;
    g->codepoint = u32(p);
    g->bitmap_offset = u32(p + 4);
    g->bearing_x = i16(p + 8);
    g->bearing_y = i16(p + 10);
    g->width = u16(p + 12);
    g->height = u16(p + 14);
    g->advance_x = i16(p + 16);
    g->bitmap_size = u32(p + 20);
    return 0;
}
int mf_open(MfFont *f, const void *data, size_t size) {
    if (!f || !data || size < MF_HEADER_SIZE)
        return -1;
    memset(f, 0, sizeof(*f));
    const uint8_t *p = (const uint8_t *)data;
    if (memcmp(p, "MFNT", 4) || u16(p + 4) != MF_VERSION || u16(p + 6) != 0 || u16(p + 18) == 0xffff || !u16(p + 30) || !u16(p + 32))
        return -1;
    for (int i = 34; i < MF_HEADER_SIZE; i++)
        if (p[i])
            return -1;
    uint32_t n = u32(p + 8), to = u32(p + 12), bo = u32(p + 16);
    if (to < MF_HEADER_SIZE || !range(size, to, (uint64_t)n * 24) || bo < to + (uint64_t)n * 24 || bo > size)
        return -1;
    f->data = p;
    f->size = size;
    f->glyph_count = n;
    f->glyph_table_offset = to;
    f->bitmap_offset = bo;
    f->ascent = i16(p + 20);
    f->descent = i16(p + 22);
    f->line_gap = i16(p + 24);
    f->pixel_size = u16(p + 26);
    f->font_spacing = i16(p + 28);
    f->res_x = u16(p + 30);
    f->res_y = u16(p + 32);
    uint32_t prev = 0;
    for (uint32_t i = 0; i < n; i++) {
        MfGlyph g;
        glyph_at(f, i, &g);
        if ((i && g.codepoint <= prev) || g.codepoint > 0x10ffff || (g.codepoint >= 0xd800 && g.codepoint <= 0xdfff))
            goto bad;
        prev = g.codepoint;
        uint64_t bytes = (uint64_t)((g.width + 7u) / 8u) * g.height;
        if (bytes != g.bitmap_size || !range(size, (uint64_t)bo + g.bitmap_offset, bytes))
            goto bad;
    }
    return 0;
bad:
    memset(f, 0, sizeof(*f));
    return -1;
}
int mf_find_glyph(const MfFont *f, uint32_t cp, MfGlyph *g) {
    if (!f || !g || !f->data)
        return -1;
    uint32_t lo = 0, hi = f->glyph_count;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        uint32_t v = u32(f->data + f->glyph_table_offset + (size_t)mid * 24);
        if (v < cp)
            lo = mid + 1;
        else
            hi = mid;
    }
    return glyph_at(f, lo, g) == 0 && g->codepoint == cp ? 0 : -1;
}
int mf_glyph_pixel(const MfFont *f, const MfGlyph *g, uint32_t x, uint32_t y) {
    if (!f || !g || x >= g->width || y >= g->height)
        return 0;
    uint64_t off = (uint64_t)f->bitmap_offset + g->bitmap_offset + (uint64_t)y * ((g->width + 7u) / 8u) + x / 8;
    if (!range(f->size, off, 1))
        return 0;
    return (f->data[off] >> (7 - (x & 7))) & 1;
}
void mf_draw_glyph_rgb565(const MfFont *f, const MfGlyph *g, uint16_t *pix, uint32_t w, uint32_t h, uint32_t stride, int32_t x, int32_t baseline, uint16_t color) {
    if (!f || !g || !pix || stride < w)
        return;
    int64_t x0 = (int64_t)x + g->bearing_x, y0 = (int64_t)baseline - g->bearing_y;
    for (uint32_t gy = 0; gy < g->height; gy++) {
        int64_t sy = y0 + gy;
        if (sy < 0 || sy >= h)
            continue;
        for (uint32_t gx = 0; gx < g->width; gx++) {
            int64_t sx = x0 + gx;
            if (sx >= 0 && sx < w && mf_glyph_pixel(f, g, gx, gy))
                pix[(size_t)sy * stride + (size_t)sx] = color;
        }
    }
}
