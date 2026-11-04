#include "layout.h"
#include "test_fonts.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Small page: 2 columns of 900 x 1200 units = 12 lines of 100 units each. */
static uint8_t buf0[TF_SIZE], buf1[TF_SIZE], buf2[TF_SIZE];
static MfFont font0, font1, font2; /* font1: font_spacing = 1; font2: ascent 12 (15 px line) */
static const MfFont *fonts[3] = {&font0, &font1, &font2};

static void make_doc(MdDocument *d, MdParagraphStyle ps, MdUnit letter_spacing, uint32_t font_id) {
    MdPageSettings page = {{2200, 1400}, 100, 100, 100, 100, 2, 200};
    md_document_init(d, page);
    ps.character_style = md_add_character_style(d, (MdCharacterStyle){font_id, letter_spacing, 0});
    assert(md_add_paragraph_style(d, ps) == 0);
    assert(md_add_story(d) == 0);
}
static void add(MdDocument *d, const char *text) { assert(md_story_add_paragraph(d, 0, 0, text) != UINT32_MAX); }
static void layout(const MdDocument *d, MdLayout *l) { assert(md_layout_story(d, 0, fonts, 3, l) == 0); }
static uint32_t add_style(MdDocument *d, MdParagraphStyle ps) { return md_add_paragraph_style(d, ps); }
static void add_p(MdDocument *d, uint32_t style, const char *text) { assert(md_story_add_paragraph(d, 0, style, text) != UINT32_MAX); }
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
    tf_build(buf2, 0);
    buf2[20] = 12;
    assert(mf_open(&font2, buf2, TF_SIZE) == 0);
    MdParagraphStyle body = {0, 0, 0, 0, 0, 0, MD_ALIGN_LEFT, MD_SPAN_COLUMN};
    MdDocument d;
    MdLayout l;

    /* Proportional advances: real glyph advance + font_spacing + letter_spacing. */
    make_doc(&d, body, 0, 0);
    add(&d, "ilm");
    layout(&d, &l);
    assert(l.glyph_count == 3 && l.glyphs[0].x == 100 && l.glyphs[1].x == 120 && l.glyphs[2].x == 140 && l.glyphs[2].advance == 80);
    assert(md_space_advance(&font0, &d.character_styles[0]) == 30); /* half of 'n' (5 px), rounded up */
    /* Resolution: at 120 x 72 dpi (NewsMaster) a pixel is 6 units across and 10 down. */
    {
        static uint8_t nm_buf[TF_SIZE];
        MfFont nm;
        tf_build_res(nm_buf, 2, 120, 72);
        assert(mf_open(&nm, nm_buf, TF_SIZE) == 0);
        MfGlyph g;
        assert(mf_find_glyph(&nm, 'm', &g) == 0);
        assert(md_glyph_advance(&nm, &d.character_styles[0], &g) == (8 + 2) * 6);
        assert(md_space_advance(&nm, &d.character_styles[0]) == (3 + 2) * 6);
        assert(md_line_height(&nm, &body) == 10 * 10 && md_font_x(&nm, 7) == 42 && md_font_y(&nm, 7) == 70);
    }
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

    /* Alignment on "aaaa" x 10: natural widths 890, 890, 430 in a 900-unit column. */
    MdParagraphStyle al = body;
    al.align = MD_ALIGN_RIGHT;
    make_doc(&d, al, 0, 0);
    add(&d, ten);
    layout(&d, &l);
    for (uint32_t i = 0; i < 3; i++) assert(l.lines[i].x + l.lines[i].width == 1000);
    check_bounds(&l);
    md_layout_free(&l);
    md_document_free(&d);
    al.align = MD_ALIGN_CENTER;
    make_doc(&d, al, 0, 0);
    add(&d, ten);
    layout(&d, &l);
    assert(l.lines[0].x == 105 && l.lines[2].x == 335 && l.lines[2].width == 430);
    md_layout_free(&l);
    md_document_free(&d);
    al.align = MD_ALIGN_JUSTIFY;
    make_doc(&d, al, 0, 0);
    add(&d, ten);
    add(&d, "aaaaaaaaaaaaaaaa aaaa"); /* 800 + 30 + 200: one word per line */
    layout(&d, &l);
    assert(l.lines[0].x == 100 && l.lines[0].width == 900 && l.lines[1].width == 900);
    assert(l.glyphs[4].x == 100 + 200 + 30 + 4 && l.glyphs[8].x == 100 + 460 + 4 + 3 && l.glyphs[12].x == 100 + 690 + 10);
    assert(l.lines[2].x == 100 && l.lines[2].width == 430); /* last line of the paragraph */
    assert(l.lines[3].width == 800 && l.lines[4].width == 200); /* single word, then last line */
    assert(l.glyph_count == 40 + 16 + 4);
    check_bounds(&l);
    md_layout_free(&l);
    md_document_free(&d);

    /* MD_SPAN_ALL headline: one frame across both columns, text below it in columns. */
    MdParagraphStyle head = body;
    head.span = MD_SPAN_ALL;
    make_doc(&d, body, 0, 0);
    uint32_t p_head = add_style(&d, head);
    add_p(&d, p_head, ten);
    add(&d, long_text);
    layout(&d, &l);
    const MdTextFrame *hf = &l.frames[l.lines[0].frame];
    assert(hf->span == 2 && hf->rect.x == 100 && hf->rect.w == 2000 && hf->rect.h == 200);
    assert(l.lines[0].glyph_count == 32 && l.lines[1].frame == l.lines[0].frame && l.lines[2].top == 300);
    assert(l.frames[l.lines[2].frame].rect.y == 300 && l.frames[l.lines[2].frame].rect.h == 1000);
    uint32_t c1 = 0;
    while (l.frames[l.lines[c1].frame].column != 1) c1++;
    assert(c1 == 2 + 10 && l.lines[c1].top == 300 && l.lines[c1].x == 1200); /* 10 lines fit below the headline */
    assert(l.pages[0].frame_count == 3);
    check_bounds(&l);
    md_layout_free(&l);
    md_document_free(&d);
    /* Mid-column headline: the band above is cut, columns restart below it. */
    make_doc(&d, body, 0, 0);
    p_head = add_style(&d, head);
    char *five = repeat("aaaa", 4 * 5);
    add(&d, five);
    add_p(&d, p_head, "aaaa");
    add(&d, long_text);
    layout(&d, &l);
    assert(l.lines[5].top == 600 && l.frames[l.lines[5].frame].span == 2);
    assert(l.frames[1].rect.y == 100 && l.frames[1].rect.h == 500); /* column 1 of the first band */
    assert(l.lines[6].top == 700 && l.frames[l.lines[6].frame].rect.y == 700);
    check_bounds(&l);
    md_layout_free(&l);
    md_document_free(&d);
    /* Headline after the text moved to column 1: next page. */
    make_doc(&d, body, 0, 0);
    p_head = add_style(&d, head);
    char *fifteen = repeat("aaaa", 4 * 15);
    add(&d, fifteen);
    add_p(&d, p_head, "aaaa");
    layout(&d, &l);
    assert(l.lines[15].page == 1 && l.lines[15].top == 100 && l.frames[l.lines[15].frame].span == 2);
    md_layout_free(&l);
    md_document_free(&d);

    /* Character style runs: glyph styles, advances and the largest line metrics. */
    make_doc(&d, body, 0, 0);
    uint32_t cs_spaced = md_add_character_style(&d, (MdCharacterStyle){1, 0, 0});
    uint32_t cs_tall = md_add_character_style(&d, (MdCharacterStyle){2, 0, 0});
    add(&d, "aaaa aaaa");
    add(&d, "aaaa aaaa");
    add(&d, "aaaa");
    assert(md_paragraph_add_run(&d, 0, 0, 5, 9, cs_spaced) == 0);
    assert(md_paragraph_add_run(&d, 0, 1, 0, 2, cs_tall) == 0);
    layout(&d, &l);
    assert(l.glyphs[3].character_style == 0 && l.glyphs[4].character_style == cs_spaced);
    assert(l.glyphs[4].x == 100 + 200 + 30 && l.glyphs[5].x - l.glyphs[4].x == 60 && l.lines[0].width == 200 + 30 + 240);
    assert(l.lines[1].top == 200 && l.lines[1].height == 150 && l.lines[1].baseline == 200 + 120);
    assert(l.lines[2].top == 350 && l.lines[2].height == 100);
    md_layout_free(&l);
    md_document_free(&d);

    /* MD_WRAP_BOTH: text on both sides of a graphic in the middle of column 0. */
    make_doc(&d, body, 0, 0);
    add(&d, long_text);
    assert(md_add_graphic(&d, (MdGraphicObject){0, {475, 300, 150, 300}, 0, 0, MD_WRAP_BOTH, 0}) == 0);
    layout(&d, &l);
    assert(l.lines[2].top == 300 && l.lines[2].x == 100 && l.lines[3].top == 300 && l.lines[3].x == 625);
    assert(l.lines[4].top == 400 && l.lines[5].top == 400 && l.lines[8].top == 600 && l.lines[8].width == 890);
    for (uint32_t i = 2; i < 8; i++) assert(l.lines[i].glyph_count == 4);
    check_order(&l, long_text);
    check_bounds(&l);
    md_layout_free(&l);
    d.graphics[0].wrap = MD_WRAP_LARGEST; /* same picture: only the left piece (tie) */
    layout(&d, &l);
    assert(l.lines[2].top == 300 && l.lines[2].x == 100 && l.lines[3].top == 400);
    md_layout_free(&l);
    d.graphics[0].wrap = MD_WRAP_NONE;
    layout(&d, &l);
    assert(l.lines[2].top == 300 && l.lines[2].width == 890);
    md_layout_free(&l);
    md_document_free(&d);
    free(five);
    free(fifteen);

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
