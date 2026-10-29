#include "document.h"
#include <stdlib.h>
#include <string.h>

const MdPaperSize MD_PAPER_A4 = {5953, 8419};

static MdUnit round_div(int64_t num, int64_t den) {
    return (MdUnit)(num >= 0 ? (num + den / 2) / den : -((-num + den / 2) / den));
}
MdUnit md_units_from_mm10(int32_t tenths_of_mm) { return round_div((int64_t)tenths_of_mm * MD_UNITS_PER_INCH, 254); }
MdUnit md_units_from_pt(int32_t points) { return points * MD_UNITS_PER_POINT; }
MdUnit md_units_from_inch(int32_t inches) { return inches * MD_UNITS_PER_INCH; }

MdPageSettings md_page_settings_a4(void) {
    MdUnit m = md_units_from_mm10(200);
    return (MdPageSettings){MD_PAPER_A4, m, m, m, m, 2, md_units_from_mm10(50)};
}

/* Grow *items so that it can hold `count + 1` elements. */
static int reserve(void **items, uint32_t *capacity, uint32_t count, size_t size) {
    if (count < *capacity) return 0;
    uint32_t cap = *capacity ? *capacity * 2u : 8u;
    if (cap <= *capacity || (uint64_t)cap * size > SIZE_MAX) return -1;
    void *p = realloc(*items, (size_t)cap * size);
    if (!p) return -1;
    *items = p;
    *capacity = cap;
    return 0;
}
#define PUSH(arr, count, cap, value)                                        \
    (reserve((void **)&(arr), &(cap), (count), sizeof(*(arr))) ? UINT32_MAX \
                                                               : ((arr)[(count)] = (value), (count)++))

void md_document_init(MdDocument *doc, MdPageSettings page) {
    memset(doc, 0, sizeof(*doc));
    doc->page = page;
}
void md_document_free(MdDocument *doc) {
    if (!doc) return;
    for (uint32_t s = 0; s < doc->story_count; s++) {
        for (uint32_t i = 0; i < doc->stories[s].count; i++) {
            free(doc->stories[s].paragraphs[i].text);
            free(doc->stories[s].paragraphs[i].runs);
        }
        free(doc->stories[s].paragraphs);
    }
    free(doc->stories);
    free(doc->character_styles);
    free(doc->paragraph_styles);
    free(doc->graphics);
    memset(doc, 0, sizeof(*doc));
}

uint32_t md_add_character_style(MdDocument *doc, MdCharacterStyle style) {
    return PUSH(doc->character_styles, doc->character_style_count, doc->character_style_capacity, style);
}
uint32_t md_add_paragraph_style(MdDocument *doc, MdParagraphStyle style) {
    if (style.character_style >= doc->character_style_count) return UINT32_MAX;
    return PUSH(doc->paragraph_styles, doc->paragraph_style_count, doc->paragraph_style_capacity, style);
}
uint32_t md_add_story(MdDocument *doc) {
    MdTextStory story = {0};
    return PUSH(doc->stories, doc->story_count, doc->story_capacity, story);
}
uint32_t md_story_add_paragraph(MdDocument *doc, uint32_t story, uint32_t paragraph_style, const char *text) {
    if (story >= doc->story_count || paragraph_style >= doc->paragraph_style_count || !text) return UINT32_MAX;
    size_t n = strlen(text);
    if (n >= UINT32_MAX) return UINT32_MAX;
    char *copy = malloc(n + 1);
    if (!copy) return UINT32_MAX;
    memcpy(copy, text, n + 1);
    MdTextStory *s = &doc->stories[story];
    uint32_t id = PUSH(s->paragraphs, s->count, s->capacity, ((MdParagraph){copy, (uint32_t)n, paragraph_style, NULL, 0, 0}));
    if (id == UINT32_MAX) free(copy);
    return id;
}
uint32_t md_add_graphic(MdDocument *doc, MdGraphicObject graphic) {
    if (graphic.bounds.w <= 0 || graphic.bounds.h <= 0 || graphic.text_margin < 0 || graphic.wrap > MD_WRAP_BOTH) return UINT32_MAX;
    return PUSH(doc->graphics, doc->graphic_count, doc->graphic_capacity, graphic);
}

MdRect md_graphic_exclusion(const MdGraphicObject *g) {
    MdUnit m = g->text_margin;
    return (MdRect){g->bounds.x - m, g->bounds.y - m, g->bounds.w + 2 * m, g->bounds.h + 2 * m};
}
MdRect md_page_content(const MdPageSettings *p) {
    return (MdRect){p->margin_left, p->margin_top, p->paper.width - p->margin_left - p->margin_right,
        p->paper.height - p->margin_top - p->margin_bottom};
}
MdRect md_page_column(const MdPageSettings *p, uint32_t column) {
    MdRect c = md_page_content(p);
    uint32_t n = p->columns ? p->columns : 1;
    MdUnit w = (MdUnit)((c.w - (MdUnit)(n - 1) * p->column_gap) / (MdUnit)n);
    return (MdRect){c.x + (MdUnit)column * (w + p->column_gap), c.y, w, c.h};
}

int md_paragraph_add_run(MdDocument *doc, uint32_t story, uint32_t paragraph, uint32_t start, uint32_t end, uint32_t character_style) {
    if (story >= doc->story_count || paragraph >= doc->stories[story].count || character_style >= doc->character_style_count) return -1;
    MdParagraph *p = &doc->stories[story].paragraphs[paragraph];
    if (start >= end || end > p->length) return -1;
    uint32_t at = 0;
    while (at < p->run_count && p->runs[at].start < start) at++;
    if ((at > 0 && p->runs[at - 1].end > start) || (at < p->run_count && p->runs[at].start < end)) return -1;
    if (reserve((void **)&p->runs, &p->run_capacity, p->run_count, sizeof(MdStyleRun))) return -1;
    memmove(&p->runs[at + 1], &p->runs[at], sizeof(MdStyleRun) * (p->run_count - at));
    p->runs[at] = (MdStyleRun){start, end, character_style};
    p->run_count++;
    return 0;
}
uint32_t md_paragraph_style_at(const MdDocument *doc, const MdParagraph *p, uint32_t index) {
    for (uint32_t i = 0; i < p->run_count && p->runs[i].start <= index; i++)
        if (index < p->runs[i].end) return p->runs[i].character_style;
    return doc->paragraph_styles[p->paragraph_style].character_style;
}
