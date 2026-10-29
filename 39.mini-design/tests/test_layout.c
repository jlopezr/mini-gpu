#include "layout.h"
#include "test_fonts.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Small page: 2 columns of 900 x 1200 units = 12 lines of 100 units each. */
static uint8_t buf0[TF_SIZE], buf1[TF_SIZE];
static MfFont font0, font1; /* font1 has font_spacing = 1 */
static const MfFont *fonts[2] = {&font0, &font1};

static void make_doc(MdDocument *d, MdParagraphStyle ps, MdUnit letter_spacing, uint32_t font_id) {
    MdPageSettings page = {{2200, 1400}, 100, 100, 100, 100, 2, 200};
    md_document_init(d, page);
    ps.character_style = md_add_character_style(d, (MdCharacterStyle){font_id, letter_spacing, 0});
    assert(md_add_paragraph_style(d, ps) == 0);
    assert(md_add_story(d) == 0);
}
static void add(MdDocument *d, const char *text) { assert(md_story_add_paragraph(d, 0, 0, text) != UINT32_MAX); }
static void layout(const MdDocument *d, MdLayout *l) { assert(md_layout_story(d, 0, fonts, 2, l) == 0); }
static char *repeat(const char *word, int n) {
    size_t w = strlen(word);
    char *s = malloc((w + 1) * (size_t)n + 1);
    s[0] = 0;
    for (int i = 0; i < n; i++) strcat(strcat(s, i ? " " : ""), word);
    return s;
}
/* Glyphs of the layout must spell the text without its spaces. */
static void check_order(const MdLayout *l, const char *text) {
    uint32_t k = 0;
    for (const char *p = text; *p; p++)
        if (*p != ' ') assert(k < l->glyph_count && l->glyphs[k++].glyph_id == (uint32_t)(unsigned char)*p);
    assert(k == l->glyph_count);
}
/* Every line inside its frame, and glyphs inside the line. */
static void check_bounds(const MdLayout *l) {
    for (uint32_t i = 0; i < l->line_count; i++) {
        const MdLine *ln = &l->lines[i];
        MdRect f = l->frames[ln->frame].rect;
        assert(l->frames[ln->frame].page == ln->page);
        assert(ln->top >= f.y && ln->top + ln->height <= f.y + f.h);
        if (ln->overflow) continue;
        assert(ln->x >= f.x && ln->x + ln->width <= f.x + f.w);
        for (uint32_t j = 0; j < ln->glyph_count; j++) {
            const MdGlyph *g = &l->glyphs[ln->first_glyph + j];
            assert(g->x >= ln->x && g->x + g->advance <= ln->x + ln->width && g->y == ln->baseline);
        }
    }
}

int main(void) {
    tf_open(&font0, buf0, 0);
    tf_open(&font1, buf1, 1);
    MdParagraphStyle body = {0, 0, 0, 0, 0, 0, MD_ALIGN_LEFT};
    MdDocument d;
    MdLayout l;

    /* Proportional advances: real glyph advance + font_spacing + letter_spacing. */
    make_doc(&d, body, 0, 0);
    add(&d, "ilm");
    layout(&d, &l);
    assert(l.glyph_count == 3 && l.glyphs[0].x == 100 && l.glyphs[1].x == 120 && l.glyphs[2].x == 140 && l.glyphs[2].advance == 80);
    assert(md_space_advance(&font0, &d.character_styles[0]) == 30); /* half of 'n' (5 px), rounded up */
    md_layout_free(&l);
    md_document_free(&d);
    make_doc(&d, body, 3, 1);
    add(&d, "ilm");
    layout(&d, &l);
    assert(l.glyphs[1].x == 100 + 33 && l.glyphs[2].x == 100 + 66 && l.glyphs[2].advance == 93);
    md_layout_free(&l);
    md_document_free(&d);

    /* Words to lines: "aaaa" = 200, space = 30, so 4 words per 900-unit line. */
    make_doc(&d, body, 0, 0);
    char *ten = repeat("aaaa", 10);
    add(&d, ten);
    layout(&d, &l);
    assert(l.line_count == 3 && l.lines[0].glyph_count == 16 && l.lines[1].glyph_count == 16 && l.lines[2].glyph_count == 8);
    assert(l.lines[0].width == 890 && l.lines[0].x == 100);
    check_order(&l, ten);
    check_bounds(&l);
    /* Leading: automatic = (7 + 2 + 1) px = 100 units; baseline at top + ascent. */
    assert(l.lines[0].top == 100 && l.lines[0].baseline == 170 && l.lines[1].top == 200 && l.lines[2].baseline == 370);
    md_layout_free(&l);
    md_document_free(&d);
    MdParagraphStyle loose = body;
    loose.leading_percent = 150;
    make_doc(&d, loose, 0, 0);
    add(&d, ten);
    layout(&d, &l);
    assert(l.lines[1].top - l.lines[0].top == 150 && l.lines[2].baseline - l.lines[1].baseline == 150);
    md_layout_free(&l);
    md_document_free(&d);
    MdParagraphStyle fixed = body;
    fixed.leading = 123;
    make_doc(&d, fixed, 0, 0);
    add(&d, ten);
    layout(&d, &l);
    assert(l.lines[1].top - l.lines[0].top == 123);
    md_layout_free(&l);
    md_document_free(&d);

    /* Paragraph spacing and first-line indent; empty paragraphs take a line. */
    MdParagraphStyle spaced = body;
    spaced.space_before = 40, spaced.space_after = 10, spaced.first_indent = 60;
    make_doc(&d, spaced, 0, 0);
    add(&d, "aaaa");
    add(&d, "");
    add(&d, "aaaa");
    layout(&d, &l);
    assert(l.line_count == 3 && l.lines[0].top == 100 && l.lines[0].x == 160); /* no space_before at column top */
    assert(l.lines[1].glyph_count == 0 && l.lines[1].top == 100 + 100 + 10 + 40);
    assert(l.lines[2].top == l.lines[1].top + 100 + 10 + 40);
    md_layout_free(&l);
    md_document_free(&d);

    /* Column continuity and new pages: 12 lines per column, 24 per page. */
    make_doc(&d, body, 0, 0);
    char *long_text = repeat("aaaa", 4 * 30); /* 30 lines */
    add(&d, long_text);
    layout(&d, &l);
    assert(l.line_count == 30 && l.page_count == 2 && l.frame_count == 4);
    assert(l.lines[11].frame == 0 && l.lines[12].frame == 1 && l.lines[12].top == 100 && l.lines[12].x == 1200);
    assert(l.lines[24].page == 1 && l.lines[24].frame == 2 && l.lines[24].top == 100 && l.lines[24].x == 100);
    assert(l.pages[0].line_count == 24 && l.pages[1].first_line == 24 && l.pages[1].line_count == 6);
    check_order(&l, long_text);
    check_bounds(&l);
    MdLayout again;
    layout(&d, &again); /* deterministic */
    assert(again.glyph_count == l.glyph_count && !memcmp(again.glyphs, l.glyphs, sizeof(MdGlyph) * l.glyph_count));
    assert(!memcmp(again.lines, l.lines, sizeof(MdLine) * l.line_count));
    md_layout_free(&again);
    md_layout_free(&l);

    /* Rectangular exclusion: graphic over the right part of column 0. */
    MdGraphicObject pic = {0, {600, 300, 300, 300}, 0, 0, 1, 0};
    assert(md_add_graphic(&d, pic) == 0);
    layout(&d, &l);
    int narrowed = 0;
    for (uint32_t i = 0; i < l.line_count; i++) {
        const MdLine *ln = &l.lines[i];
        if (ln->page != 0 || ln->top >= 600 || ln->top + ln->height <= 300) continue;
        for (uint32_t j = 0; j < ln->glyph_count; j++) {
            const MdGlyph *g = &l.glyphs[ln->first_glyph + j];
            assert(g->x + g->advance <= 600 || g->x >= 900);
        }
        narrowed += ln->frame == 0;
    }
    assert(narrowed == 3); /* lines at 300, 400 and 500 */
    check_order(&l, long_text);
    check_bounds(&l);
    uint32_t lines_small = l.line_count;
    md_layout_free(&l);
    /* Bigger picture: recomposition without touching any coordinate. */
    d.graphics[0].bounds.h = 600;
    layout(&d, &l);
    assert(l.line_count > lines_small);
    check_order(&l, long_text);
    md_layout_free(&l);
    /* Full-width exclusion: text skips below it. */
    d.graphics[0].bounds = (MdRect){100, 300, 900, 200};
    layout(&d, &l);
    assert(l.lines[1].top == 200 && l.lines[2].top == 500);
    check_bounds(&l);
    md_layout_free(&l);
    /* Exclusions only affect their own page; graphic pages exist even without text. */
    d.graphics[0].page = 4;
    layout(&d, &l);
    assert(l.page_count == 5 && l.lines[2].top == 300 && l.pages[4].line_count == 0);
    md_layout_free(&l);
    md_document_free(&d);

    /* Three columns: 2000 = 3 * 600 + 2 * 100; text visits every column in order. */
    md_document_init(&d, (MdPageSettings){{2200, 1400}, 100, 100, 100, 100, 3, 100});
    assert(md_add_character_style(&d, (MdCharacterStyle){0, 0, 0}) == 0);
    assert(md_add_paragraph_style(&d, body) == 0 && md_add_story(&d) == 0);
    add(&d, long_text);
    layout(&d, &l);
    assert(l.pages[0].frame_count == 3 && l.frames[2].rect.x == 1500 && l.frames[2].rect.w == 600);
    assert(l.lines[0].frame == 0 && l.lines[12].frame == 1 && l.lines[24].frame == 2 && l.lines[24].x == 1500);
    check_order(&l, long_text);
    check_bounds(&l);
    md_layout_free(&l);
    md_document_free(&d);

    /* A word wider than a column is broken by characters (18 'a' fit in 900). */
    make_doc(&d, body, 0, 0);
    add(&d, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
    layout(&d, &l);
    assert(l.line_count == 2 && l.lines[0].glyph_count == 18 && l.lines[1].glyph_count == 12 && l.overflow_count == 0);
    check_bounds(&l);
    md_layout_free(&l);
    md_document_free(&d);

    /* Errors: unknown font id, line taller than a column. */
    make_doc(&d, body, 0, 7);
    add(&d, "x");
    assert(md_layout_story(&d, 0, fonts, 2, &l) != 0 && l.line_count == 0);
    md_document_free(&d);
    MdParagraphStyle tall = body;
    tall.leading = 5000;
    make_doc(&d, tall, 0, 0);
    add(&d, "x");
    assert(md_layout_story(&d, 0, fonts, 2, &l) != 0);
    md_document_free(&d);

    free(ten);
    free(long_text);
    puts("Layout OK");
    return 0;
}
