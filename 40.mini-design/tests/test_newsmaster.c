/* Regression against NewsMaster 1.5 itself: a paragraph typed in NewsMaster
   (Park 10, Normal view captured in DOSBox-X) and the same paragraph laid out
   by MiniDesign in a 473 px column must break into the same seven lines, with
   the same widths in font pixels and the same 11 px line pitch. */
#include "document_render.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *text = "MiniDesign is a desktop publishing program for the MiniCPU and MiniGPU, inspired by NewsMaster 1.5. "
                          "This page was not drawn by hand: a document model describes the paper, the margins, the columns and "
                          "the text, and a layout engine decides where every line and every glyph goes.";
/* Lines and widths (advance + font_spacing, space 5 px) measured in NewsMaster. */
static const struct {
    const char *text;
    int32_t px;
} expected[] = {
    {"MiniDesign is a desktop publishing program for", 447},
    {"the MiniCPU and MiniGPU, inspired by", 354},
    {"NewsMaster 1.5. This page was not drawn by", 444},
    {"hand: a document model describes the paper,", 441},
    {"the margins, the columns and the text, and a", 433},
    {"layout engine decides where every line and", 428},
    {"every glyph goes.", 179},
};
enum { LINES = sizeof expected / sizeof expected[0] };

static uint8_t *load(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb");
    assert(f);
    assert(!fseek(f, 0, SEEK_END));
    long z = ftell(f);
    rewind(f);
    uint8_t *p = malloc((size_t)z);
    assert(p && fread(p, 1, (size_t)z, f) == (size_t)z);
    fclose(f);
    *n = (size_t)z;
    return p;
}

int main(int argc, char **argv) {
    assert(argc == 2);
    size_t n;
    uint8_t *data = load(argv[1], &n);
    MfFont park;
    assert(mf_open(&park, data, n) == 0 && park.res_x == 120 && park.res_y == 72);
    const MfFont *fonts[1] = {&park};

    /* One column of 473 px (any width from 447 to 478 px gives NewsMaster's breaks). */
    MdUnit column = md_font_x(&park, 473), left = md_units_from_inch(1);
    assert(column == 473 * 6);
    MdPageSettings ps = md_page_settings_a4();
    ps.columns = 1, ps.margin_left = left, ps.margin_right = MD_PAPER_A4.width - left - column;
    MdDocument d;
    md_document_init(&d, ps);
    assert(md_add_character_style(&d, (MdCharacterStyle){0, 0, 0}) == 0);
    assert(md_add_paragraph_style(&d, (MdParagraphStyle){0, 0, 0, 0, 0, 0, MD_ALIGN_LEFT, MD_SPAN_COLUMN}) == 0);
    assert(md_add_story(&d) == 0 && md_story_add_paragraph(&d, 0, 0, text) == 0);
    MdLayout l;
    assert(md_layout_story(&d, 0, fonts, 1, &l) == 0);
    assert(l.line_count == LINES);
    for (uint32_t i = 0; i < LINES; i++) {
        const MdLine *line = &l.lines[i];
        char got[128];
        uint32_t k = 0;
        /* Rebuild the line's text: a gap between two glyphs is a space. */
        for (uint32_t j = 0; j < line->glyph_count; j++) {
            const MdGlyph *g = &l.glyphs[line->first_glyph + j];
            if (j && g->x != g[-1].x + g[-1].advance) got[k++] = ' ';
            got[k++] = (char)g->glyph_id;
        }
        got[k] = 0;
        if (strcmp(got, expected[i].text)) fprintf(stderr, "line %u: '%s', NewsMaster '%s'\n", i + 1, got, expected[i].text);
        assert(!strcmp(got, expected[i].text));
        assert(line->width == md_font_x(&park, expected[i].px));
        assert(line->height == md_font_y(&park, 11) && (i == 0 || line->top - line[-1].top == line->height));
    }

    /* Normal view (120 x 72 dpi, 1 x 1): whole pixels, 11 rows per line. */
    MdViewport vp;
    assert(md_viewport_actual_size(&vp, 640, 400, 120, 72, left, ps.margin_top) == 0 && md_viewport_native_text(&vp, &park));
    GfxResources res = {.fonts = fonts, .font_count = 1};
    MdRenderList rl;
    assert(md_render_page(&d, &l, 0, &vp, &res, NULL, &rl) == 0 && !rl.greeked && rl.run_count == LINES);
    for (uint32_t i = 0; i < LINES; i++) {
        const GfxGlyphRun *run = &rl.runs[i];
        const GfxPositionedGlyph *last = &run->glyphs[run->count - 1];
        MfGlyph g;
        assert(mf_find_glyph(&park, last->glyph_id, &g) == 0);
        assert(run->glyphs[0].x == 0 && last->x + g.advance_x + park.font_spacing == expected[i].px);
        assert(run->glyphs[0].y == park.ascent + 11 * (int32_t)i);
    }
    md_render_list_free(&rl);
    md_layout_free(&l);
    md_document_free(&d);
    free(data);
    puts("NewsMaster line breaks OK: 7 lines, widths and 11 px pitch match");
    return 0;
}
