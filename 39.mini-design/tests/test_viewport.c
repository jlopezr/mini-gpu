#include "document_render.h"
#include "test_fonts.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t font_buf[TF_SIZE];
static MfFont font;

/* Page proportions survive the transform within one pixel. */
static void check_fit(int32_t w, int32_t h, MdPaperSize paper) {
    MdViewport vp;
    assert(md_viewport_fit_page(&vp, w, h, paper, 6) == 0);
    GfxRect r = md_viewport_rect(&vp, (MdRect){0, 0, paper.width, paper.height});
    assert(r.x >= 6 && r.y >= 6 && r.x + r.w <= w - 6 && r.y + r.h <= h - 6);
    assert(r.w == w - 12 || r.h == h - 12);
    int64_t err = (int64_t)r.w * paper.height - (int64_t)r.h * paper.width;
    assert(llabs(err) <= paper.height || llabs(err) <= paper.width);
    assert(abs((r.x - 0) - (w - (r.x + r.w))) <= 1); /* centred */
    assert(!md_viewport_native_text(&vp));
}

static uint32_t count_ops(const GfxDisplayList *dl, GfxOpcode op) {
    uint32_t n = 0;
    for (uint32_t i = 0; i < dl->count; i++) n += dl->commands[i].opcode == op;
    return n;
}

int main(void) {
    check_fit(320, 240, MD_PAPER_A4);
    check_fit(640, 480, MD_PAPER_A4);
    check_fit(240, 320, (MdPaperSize){8419, 5953}); /* limited by width */

    /* Transform: scroll maps to origin, floor rounding, adjacent rects stay adjacent. */
    MdViewport vp;
    assert(md_viewport_actual_size(&vp, 640, 480, 1000, 2000) == 0 && md_viewport_native_text(&vp));
    assert(md_viewport_x(&vp, 1000) == 0 && md_viewport_x(&vp, 1010) == 1 && md_viewport_x(&vp, 1009) == 0);
    assert(md_viewport_x(&vp, 999) == -1 && md_viewport_y(&vp, 2100) == 10);
    assert(md_viewport_zoom(&vp, 320, 240, 3, 70, 0, 0) == 0 && !md_viewport_native_text(&vp));
    GfxRect a = md_viewport_rect(&vp, (MdRect){0, 0, 333, 50}), b = md_viewport_rect(&vp, (MdRect){333, 0, 333, 50});
    assert(a.x + a.w == b.x);
    for (MdUnit x = -500; x < 500; x++) assert(md_viewport_x(&vp, x) <= md_viewport_x(&vp, x + 1));
    assert(md_viewport_zoom(&vp, 0, 240, 1, 1, 0, 0) != 0);
    /* Integer text zoom: GLYPH_RUN scale; anything else is greeked. */
    assert(md_viewport_actual_size(&vp, 640, 480, 0, 0) == 0 && md_viewport_text_scale(&vp) == 1);
    assert(md_viewport_text_zoom(&vp, 640, 480, 3, 0, 0) == 0 && md_viewport_text_scale(&vp) == 3 && !md_viewport_native_text(&vp));
    assert(md_viewport_zoom(&vp, 640, 480, 15, 100, 0, 0) == 0 && md_viewport_text_scale(&vp) == 0); /* 150 % */
    assert(md_viewport_zoom(&vp, 640, 480, 4, 20, 0, 0) == 0 && md_viewport_text_scale(&vp) == 2); /* 200 % as 4/20 */
    assert(md_viewport_text_zoom(&vp, 640, 480, GFX_GLYPH_MAX_SCALE + 1, 0, 0) == 0 && md_viewport_text_scale(&vp) == 0);
    assert(md_viewport_fit_page(&vp, 640, 480, MD_PAPER_A4, 6) == 0 && md_viewport_text_scale(&vp) == 0);

    /* Document with text and one picture, laid out once. */
    tf_open(&font, font_buf, 0);
    const MfFont *fonts[1] = {&font};
    MdDocument d;
    md_document_init(&d, md_page_settings_a4());
    uint32_t cs = md_add_character_style(&d, (MdCharacterStyle){0, 0, 0x001F});
    assert(md_add_paragraph_style(&d, (MdParagraphStyle){cs, 0, 0, 0, 0, 0, MD_ALIGN_LEFT, MD_SPAN_COLUMN}) == 0);
    assert(md_add_story(&d) == 0);
    for (int i = 0; i < 40; i++) assert(md_story_add_paragraph(&d, 0, 0, "Some words of Text in a column, many words.") != UINT32_MAX);
    static const uint8_t bits[2 * 8] = {0xFF, 0xFF, 0x80, 0x01, 0x80, 0x01, 0x80, 0x01, 0x80, 0x01, 0x80, 0x01, 0x80, 0x01, 0xFF, 0xFF};
    GfxBitmap bm = {bits, 16, 8, 2, GFX_BITMAP_MONO1};
    assert(md_add_graphic(&d, (MdGraphicObject){0, {2000, 1500, 1600, 800}, 0, 60, 1, 0xF800}) == 0);
    MdLayout l;
    assert(md_layout_story(&d, 0, fonts, 1, &l) == 0);
    MdGlyph *before = malloc(sizeof(MdGlyph) * l.glyph_count);
    memcpy(before, l.glyphs, sizeof(MdGlyph) * l.glyph_count);
    GfxResources base = {.fonts = fonts, .font_count = 1, .bitmaps = &bm, .bitmap_count = 1};

    /* 100 %: one GLYPH_RUN per non-empty line, positions = transformed layout. */
    uint16_t *px = calloc(640 * 480, sizeof(uint16_t));
    GfxSurface s640 = {px, 640, 480, 640};
    assert(md_viewport_actual_size(&vp, 640, 480, 0, 0) == 0);
    MdRenderList rl;
    assert(md_render_page(&d, &l, 0, &vp, &base, NULL, &rl) == 0 && !rl.greeked);
    uint32_t text_lines = 0;
    for (uint32_t i = 0; i < l.pages[0].line_count; i++) text_lines += l.lines[l.pages[0].first_line + i].glyph_count > 0;
    assert(count_ops(&rl.list, GFX_GLYPH_RUN) == text_lines && rl.run_count == text_lines);
    assert(count_ops(&rl.list, GFX_BLIT) == 1);
    const MdLine *first = &l.lines[0];
    const GfxPositionedGlyph *pg = &rl.runs[0].glyphs[0];
    assert(pg->x == md_viewport_x(&vp, l.glyphs[0].x) && pg->y == md_viewport_y(&vp, first->baseline));
    assert(gfx_execute_cpu_resources(&rl.list, &s640, &rl.resources) == 0);
    assert(px[(size_t)(pg->y - TF_H) * 640 + (size_t)pg->x] == 0x001F); /* top-left pixel of the first glyph */
    md_render_list_free(&rl);

    /* 200 %: same layout, GLYPH_RUN with scale 2, glyph pixels as 2x2 blocks. */
    assert(md_viewport_text_zoom(&vp, 640, 480, 2, 0, 0) == 0);
    memset(px, 0, 640 * 480 * sizeof(uint16_t));
    assert(md_render_page(&d, &l, 0, &vp, &base, NULL, &rl) == 0 && !rl.greeked);
    for (uint32_t i = 0; i < rl.list.count; i++)
        if (rl.list.commands[i].opcode == GFX_GLYPH_RUN) assert(rl.list.commands[i].data.glyph_run.scale == 2);
    pg = &rl.runs[0].glyphs[0];
    assert(pg->x == 2 * 567 / 10 && pg->y == md_viewport_y(&vp, first->baseline));
    assert(gfx_execute_cpu_resources(&rl.list, &s640, &rl.resources) == 0);
    for (int dy = 0; dy < 2; dy++)
        for (int dx = 0; dx < 2; dx++) assert(px[(size_t)(pg->y - 2 * TF_H + dy) * 640 + (size_t)(pg->x + dx)] == 0x001F);
    md_render_list_free(&rl);

    /* Fit page at both resolutions: greeking, bars inside the page, layout untouched. */
    static const int32_t sizes[2][2] = {{320, 240}, {640, 480}};
    for (int k = 0; k < 2; k++) {
        GfxSurface s = {px, (uint32_t)sizes[k][0], (uint32_t)sizes[k][1], (uint32_t)sizes[k][0]};
        assert(md_viewport_fit_page(&vp, sizes[k][0], sizes[k][1], d.page.paper, 6) == 0);
        assert(md_render_page(&d, &l, 0, &vp, &base, NULL, &rl) == 0 && rl.greeked);
        assert(count_ops(&rl.list, GFX_GLYPH_RUN) == 0 && count_ops(&rl.list, GFX_BLIT) == 1);
        GfxRect paper = md_viewport_rect(&vp, (MdRect){0, 0, d.page.paper.width, d.page.paper.height});
        uint32_t bars = 0;
        for (uint32_t i = 3; i < rl.list.count; i++) { /* after clear, shadow and paper */
            const GfxCommand *c = &rl.list.commands[i];
            if (c->opcode != GFX_FILL_RECT) continue;
            GfxRect r = c->data.fill_rect.rect;
            assert(r.x >= paper.x && r.y >= paper.y && r.x + r.w <= paper.x + paper.w && r.y + r.h <= paper.y + paper.h);
            bars++;
        }
        assert(bars > text_lines);
        assert(gfx_execute_cpu_resources(&rl.list, &s, &rl.resources) == 0);
        md_render_list_free(&rl);
    }
    assert(!memcmp(before, l.glyphs, sizeof(MdGlyph) * l.glyph_count));

    /* Errors: page out of range, missing bitmap. */
    assert(md_render_page(&d, &l, l.page_count, &vp, &base, NULL, &rl) != 0);
    md_render_list_free(&rl);
    base.bitmap_count = 0;
    assert(md_render_page(&d, &l, 0, &vp, &base, NULL, &rl) != 0);
    md_render_list_free(&rl);

    free(before);
    free(px);
    md_layout_free(&l);
    md_document_free(&d);
    puts("Viewport and render OK");
    return 0;
}
