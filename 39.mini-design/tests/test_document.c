#include "document.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    /* Physical units: 1/720 inch, rounded to the nearest unit. */
    assert(md_units_from_mm10(254) == 720);
    assert(md_units_from_mm10(-254) == -720);
    assert(md_units_from_mm10(2100) == 5953 && md_units_from_mm10(2970) == 8419);
    assert(MD_PAPER_A4.width == 5953 && MD_PAPER_A4.height == 8419);
    assert(md_units_from_pt(10) == 100 && md_units_from_inch(2) == 1440);

    /* A4 defaults: 20 mm margins, two columns 5 mm apart. */
    MdPageSettings a4 = md_page_settings_a4();
    assert(a4.margin_top == 567 && a4.margin_left == 567 && a4.columns == 2 && a4.column_gap == 142);
    MdRect c = md_page_content(&a4);
    assert(c.x == 567 && c.y == 567 && c.w == 5953 - 1134 && c.h == 8419 - 1134);
    MdRect c0 = md_page_column(&a4, 0), c1 = md_page_column(&a4, 1);
    assert(c0.x == c.x && c0.w == c1.w && c0.w == (c.w - 142) / 2);
    assert(c1.x == c0.x + c0.w + a4.column_gap && c1.x + c1.w <= c.x + c.w);
    assert(c0.y == c.y && c0.h == c.h);

    /* Configurable number of columns. */
    MdPageSettings three = a4;
    three.columns = 3;
    MdRect t2 = md_page_column(&three, 2);
    assert(md_page_column(&three, 0).w == t2.w && t2.x + t2.w <= c.x + c.w && c.x + c.w - (t2.x + t2.w) < 3);

    /* Styles, stories and paragraphs; text is copied. */
    MdDocument doc;
    md_document_init(&doc, a4);
    assert(md_add_paragraph_style(&doc, (MdParagraphStyle){0}) == UINT32_MAX); /* unknown character style */
    uint32_t cs = md_add_character_style(&doc, (MdCharacterStyle){0, 5, 0});
    uint32_t ps = md_add_paragraph_style(&doc, (MdParagraphStyle){cs, 0, 120, 0, 0, 0, MD_ALIGN_LEFT});
    uint32_t story = md_add_story(&doc);
    assert(cs == 0 && ps == 0 && story == 0);
    char text[] = "Hello world";
    assert(md_story_add_paragraph(&doc, story, ps, text) == 0);
    text[0] = 'J';
    assert(!strcmp(doc.stories[0].paragraphs[0].text, "Hello world") && doc.stories[0].paragraphs[0].length == 11);
    assert(md_story_add_paragraph(&doc, story, 7, "x") == UINT32_MAX);
    assert(md_story_add_paragraph(&doc, 3, ps, "x") == UINT32_MAX);
    for (int i = 0; i < 100; i++) assert(md_story_add_paragraph(&doc, story, ps, "more") == (uint32_t)i + 1);

    /* Graphics: exclusion rectangle grows bounds by the text margin. */
    MdGraphicObject g = {0, {1000, 2000, 300, 200}, 0, 50, 1, 0};
    assert(md_add_graphic(&doc, g) == 0);
    MdRect e = md_graphic_exclusion(&doc.graphics[0]);
    assert(e.x == 950 && e.y == 1950 && e.w == 400 && e.h == 300);
    g.bounds.w = 0;
    assert(md_add_graphic(&doc, g) == UINT32_MAX);
    md_document_free(&doc);
    assert(doc.story_count == 0 && doc.graphics == NULL);
    puts("Document model OK");
    return 0;
}
