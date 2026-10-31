#include "document_render.h"
#include <stdlib.h>
#include <string.h>

static int reserve(void **items, uint32_t *capacity, uint32_t count, size_t size) {
    if (count < *capacity) return 0;
    uint32_t cap = *capacity ? *capacity * 2u : 64u;
    if (cap <= *capacity || (uint64_t)cap * size > SIZE_MAX) return -1;
    void *p = realloc(*items, (size_t)cap * size);
    if (!p) return -1;
    *items = p;
    *capacity = cap;
    return 0;
}
#define PUSH(arr, count, cap, value) \
    (reserve((void **)&(arr), &(cap), (count), sizeof(*(arr))) ? -1 : ((arr)[(count)++] = (value), 0))

MdRenderOptions md_render_default_options(void) {
    return (MdRenderOptions){0x8410, 0xFFFF, 0x4208, 0xAEDC, 0xFC10, 0x8C71, 0};
}

static int cmd(MdRenderList *o, GfxCommand c) { return gfx_list_add(&o->list, c); }
static int fill(MdRenderList *o, GfxRect r, uint16_t color) {
    if (r.w <= 0 || r.h <= 0) return 0;
    return cmd(o, (GfxCommand){.opcode = GFX_FILL_RECT, .data.fill_rect = {r, color}});
}
static int outline(MdRenderList *o, GfxRect r, uint16_t color) {
    int32_t x1 = r.x + r.w - 1, y1 = r.y + r.h - 1;
    int fail = 0;
    fail |= cmd(o, (GfxCommand){.opcode = GFX_DRAW_LINE, .data.line = {r.x, r.y, x1, r.y, color}});
    fail |= cmd(o, (GfxCommand){.opcode = GFX_DRAW_LINE, .data.line = {x1, r.y, x1, y1, color}});
    fail |= cmd(o, (GfxCommand){.opcode = GFX_DRAW_LINE, .data.line = {x1, y1, r.x, y1, color}});
    fail |= cmd(o, (GfxCommand){.opcode = GFX_DRAW_LINE, .data.line = {r.x, y1, r.x, r.y, color}});
    return fail;
}

/* Glyphs [first, first + count) as one bar per word: glyphs whose advances
   touch belong to the same word. */
static int greek_run(MdRenderList *o, const MdLayout *l, uint32_t first, uint32_t count, MdUnit baseline, const MdViewport *vp, MdUnit bar,
    uint16_t color) {
    const MdGlyph *g = &l->glyphs[first];
    for (uint32_t i = 0; i < count;) {
        uint32_t j = i + 1;
        while (j < count && g[j].x == g[j - 1].x + g[j - 1].advance) j++;
        MdUnit x0 = g[i].x, x1 = g[j - 1].x + g[j - 1].advance;
        GfxRect r = md_viewport_rect(vp, (MdRect){x0, baseline - bar, x1 - x0, bar});
        if (r.h <= 0) r.h = 1;
        if (r.w <= 0) r.w = 1;
        if (fill(o, r, color)) return -1;
        i = j;
    }
    return 0;
}

/* Glyphs [first, first + count) of the layout, all in one character style. */
static int text_run(MdRenderList *o, const MdLayout *l, uint32_t first, uint32_t count, const MdViewport *vp, uint32_t font_id) {
    GfxGlyphRun run = {(const GfxPositionedGlyph *)(uintptr_t)o->glyph_count, count, font_id};
    for (uint32_t i = 0; i < count; i++) {
        const MdGlyph *g = &l->glyphs[first + i];
        GfxPositionedGlyph pg = {g->glyph_id, md_viewport_x(vp, g->x), md_viewport_y(vp, g->y)};
        if (PUSH(o->glyphs, o->glyph_count, o->glyph_capacity, pg)) return -1;
    }
    if (PUSH(o->runs, o->run_count, o->run_capacity, run)) return -1;
    return 0;
}

int md_render_page(const MdDocument *doc, const MdLayout *l, uint32_t page, const MdViewport *vp, const GfxResources *base,
    const MdRenderOptions *options, MdRenderList *o) {
    if (!o) return -1;
    memset(o, 0, sizeof(*o));
    gfx_list_init(&o->list);
    if (!doc || !l || !vp || !base || page >= l->page_count) return -1;
    MdRenderOptions opt = options ? *options : md_render_default_options();
    GfxRect paper = md_viewport_rect(vp, (MdRect){0, 0, doc->page.paper.width, doc->page.paper.height});
    int fail = 0;
    fail |= cmd(o, (GfxCommand){.opcode = GFX_CLEAR, .data.clear = {opt.desk}});
    fail |= fill(o, (GfxRect){paper.x + 3, paper.y + 3, paper.w, paper.h}, opt.shadow);
    fail |= fill(o, paper, opt.paper);
    fail |= cmd(o, (GfxCommand){.opcode = GFX_SET_CLIP, .data.clip = {paper}});
    const MdPage *pg = &l->pages[page];
    if (opt.show_guides)
        for (uint32_t i = 0; i < pg->frame_count; i++) fail |= outline(o, md_viewport_rect(vp, l->frames[pg->first_frame + i].rect), opt.guides);
    for (uint32_t i = 0; !fail && i < doc->graphic_count; i++) {
        const MdGraphicObject *g = &doc->graphics[i];
        if (g->page != page) continue;
        if (g->bitmap_id >= base->bitmap_count || !base->bitmaps) return -1;
        const GfxBitmap *bm = &base->bitmaps[g->bitmap_id];
        if (opt.show_guides && g->wrap != MD_WRAP_NONE) fail |= outline(o, md_viewport_rect(vp, md_graphic_exclusion(g)), opt.exclusion);
        fail |= cmd(o, (GfxCommand){.opcode = GFX_BLIT, .data.blit = {.resource_id = g->bitmap_id, .src = {0, 0, (int32_t)bm->width, (int32_t)bm->height}, .dst = md_viewport_rect(vp, g->bounds), .foreground = g->color, .mode = GFX_BLIT_TRANSPARENT_ZERO}});
    }
    for (uint32_t i = 0; !fail && i < pg->line_count; i++) {
        const MdLine *line = &l->lines[pg->first_line + i];
        /* One GLYPH_RUN, or one set of bars, per stretch of glyphs in the same character style. */
        for (uint32_t a = line->first_glyph, end = line->first_glyph + line->glyph_count; !fail && a < end;) {
            uint32_t st = l->glyphs[a].character_style, b = a + 1;
            while (b < end && l->glyphs[b].character_style == st) b++;
            if (st >= doc->character_style_count) return -1;
            const MdCharacterStyle *cs = &doc->character_styles[st];
            if (cs->font_id >= base->font_count || !base->fonts || !base->fonts[cs->font_id]) return -1;
            const MfFont *font = base->fonts[cs->font_id];
            uint32_t text_scale = md_viewport_text_scale(vp, font);
            if (!text_scale) {
                /* Bar of roughly x-height: 3/5 of the ascent. */
                fail |= greek_run(o, l, a, b - a, line->baseline, vp, md_font_y(font, font->ascent) * 3 / 5, opt.greek);
                o->greeked = 1;
            } else {
                uint32_t run_id = o->run_count;
                fail |= text_run(o, l, a, b - a, vp, cs->font_id);
                fail |= cmd(o, (GfxCommand){.opcode = GFX_GLYPH_RUN, .data.glyph_run = {.run_id = run_id, .color = cs->color, .scale = (uint16_t)text_scale}});
            }
            a = b;
        }
    }
    fail |= cmd(o, (GfxCommand){.opcode = GFX_SET_CLIP, .data.clip = {{0, 0, vp->screen_w, vp->screen_h}}});
    if (fail) return -1;
    /* Runs were stored with glyph offsets while the array could still move. */
    for (uint32_t i = 0; i < o->run_count; i++) o->runs[i].glyphs = o->glyphs + (uintptr_t)o->runs[i].glyphs;
    o->resources = *base;
    o->resources.runs = o->runs;
    o->resources.run_count = o->run_count;
    return 0;
}

void md_render_list_free(MdRenderList *o) {
    if (!o) return;
    gfx_list_destroy(&o->list);
    free(o->glyphs);
    free(o->runs);
    memset(o, 0, sizeof(*o));
}
