#include "layout.h"
#include <stdlib.h>
#include <string.h>

static int reserve(void **items, uint32_t *capacity, uint32_t count, size_t size) {
    if (count < *capacity) return 0;
    uint32_t cap = *capacity ? *capacity * 2u : 16u;
    if (cap <= *capacity || (uint64_t)cap * size > SIZE_MAX) return -1;
    void *p = realloc(*items, (size_t)cap * size);
    if (!p) return -1;
    *items = p;
    *capacity = cap;
    return 0;
}
#define PUSH(arr, count, cap, value) \
    (reserve((void **)&(arr), &(cap), (count), sizeof(*(arr))) ? -1 : ((arr)[(count)++] = (value), 0))

MdUnit md_glyph_advance(const MfFont *font, const MdCharacterStyle *style, const MfGlyph *glyph) {
    return (MdUnit)(glyph->advance_x + font->font_spacing) * MD_UNITS_PER_FONT_PX + style->letter_spacing;
}
/* MiniFont/NewsMaster fonts have no space glyph: use it if present, otherwise
   half the advance of 'n' (at least 2 px). */
MdUnit md_space_advance(const MfFont *font, const MdCharacterStyle *style) {
    MfGlyph g;
    if (!mf_find_glyph(font, ' ', &g)) return md_glyph_advance(font, style, &g);
    int32_t px = mf_find_glyph(font, 'n', &g) ? font->pixel_size / 3 : (g.advance_x + 1) / 2;
    if (px < 2) px = 2;
    return (MdUnit)(px + font->font_spacing) * MD_UNITS_PER_FONT_PX + style->letter_spacing;
}
MdUnit md_line_height(const MfFont *font, const MdParagraphStyle *style) {
    if (style->leading > 0) return style->leading;
    MdUnit h = (MdUnit)(font->ascent + font->descent + font->line_gap) * MD_UNITS_PER_FONT_PX;
    uint32_t pct = style->leading_percent ? style->leading_percent : 100;
    return (MdUnit)(((int64_t)h * pct + 50) / 100);
}

/* Missing glyphs fall back to '?', or are skipped if the font lacks it too. */
static int find_glyph(const MfFont *font, uint32_t cp, MfGlyph *g) {
    return mf_find_glyph(font, cp, g) == 0 || mf_find_glyph(font, '?', g) == 0;
}

typedef struct {
    const MdDocument *doc;
    MdLayout *out;
    uint32_t page, column;
    MdUnit y;
} Flow;

static int new_page(Flow *f) {
    MdLayout *l = f->out;
    if (l->page_count >= MD_LAYOUT_MAX_PAGES) return -1;
    uint32_t columns = f->doc->page.columns ? f->doc->page.columns : 1;
    MdPage page = {l->frame_count, columns, l->line_count, 0};
    if (PUSH(l->pages, l->page_count, l->page_capacity, page)) return -1;
    for (uint32_t c = 0; c < columns; c++) {
        MdTextFrame frame = {l->page_count - 1, c, md_page_column(&f->doc->page, c)};
        if (PUSH(l->frames, l->frame_count, l->frame_capacity, frame)) return -1;
    }
    return 0;
}
static const MdTextFrame *frame_of(const Flow *f) {
    return &f->out->frames[f->out->pages[f->page].first_frame + f->column];
}
static int next_frame(Flow *f) {
    if (++f->column >= f->out->pages[f->page].frame_count) {
        if (new_page(f)) return -1;
        f->page++;
        f->column = 0;
    }
    f->y = frame_of(f)->rect.y;
    return 0;
}

/* Widest horizontal piece of `frame` free of exclusions in the band [y, y+h).
   *narrowed tells whether an exclusion touched the band. */
static void free_segment(const Flow *f, MdRect frame, MdUnit y, MdUnit h, MdUnit *x0, MdUnit *x1, int *narrowed) {
    enum { MAX_SEG = 32 };
    MdUnit sx0[MAX_SEG], sx1[MAX_SEG];
    int n = 1;
    sx0[0] = frame.x;
    sx1[0] = frame.x + frame.w;
    *narrowed = 0;
    for (uint32_t i = 0; i < f->doc->graphic_count; i++) {
        const MdGraphicObject *g = &f->doc->graphics[i];
        if (!g->wrap || g->page != f->page) continue;
        MdRect e = md_graphic_exclusion(g);
        if (e.y >= y + h || e.y + e.h <= y || e.x >= frame.x + frame.w || e.x + e.w <= frame.x) continue;
        *narrowed = 1;
        int m = 0;
        MdUnit tx0[MAX_SEG], tx1[MAX_SEG];
        for (int s = 0; s < n; s++) {
            if (e.x + e.w <= sx0[s] || e.x >= sx1[s]) {
                tx0[m] = sx0[s], tx1[m++] = sx1[s];
                continue;
            }
            if (e.x > sx0[s] && m < MAX_SEG) tx0[m] = sx0[s], tx1[m++] = e.x;
            if (e.x + e.w < sx1[s] && m < MAX_SEG) tx0[m] = e.x + e.w, tx1[m++] = sx1[s];
        }
        memcpy(sx0, tx0, sizeof(MdUnit) * (size_t)m);
        memcpy(sx1, tx1, sizeof(MdUnit) * (size_t)m);
        n = m;
    }
    *x0 = *x1 = frame.x;
    for (int s = 0; s < n; s++)
        if (sx1[s] - sx0[s] > *x1 - *x0 && (!*narrowed || sx1[s] - sx0[s] >= MD_LAYOUT_MIN_SEGMENT)) *x0 = sx0[s], *x1 = sx1[s];
}

static MdUnit word_width(const MfFont *font, const MdCharacterStyle *cs, const char *s, uint32_t a, uint32_t b) {
    MdUnit w = 0;
    MfGlyph g;
    for (uint32_t i = a; i < b; i++)
        if (find_glyph(font, (unsigned char)s[i], &g)) w += md_glyph_advance(font, cs, &g);
    return w;
}
static uint32_t skip_spaces(const char *s, uint32_t i, uint32_t n) {
    while (i < n && s[i] == ' ') i++;
    return i;
}
static uint32_t word_end(const char *s, uint32_t i, uint32_t n) {
    while (i < n && s[i] != ' ') i++;
    return i;
}

static int emit_line(Flow *f, uint32_t paragraph, uint32_t cstyle, const MfFont *font, const MdCharacterStyle *cs, const char *s,
    uint32_t a, uint32_t b, MdUnit x, MdUnit lh, int overflow) {
    MdLayout *l = f->out;
    MdLine line = {f->page, f->out->pages[f->page].first_frame + f->column, paragraph, cstyle, x, f->y,
        f->y + (MdUnit)font->ascent * MD_UNITS_PER_FONT_PX, 0, lh, l->glyph_count, 0, overflow};
    MdUnit pen = x, space = md_space_advance(font, cs);
    MfGlyph g;
    for (uint32_t i = a; i < b; i++) {
        if (s[i] == ' ') {
            pen += space;
            continue;
        }
        if (!find_glyph(font, (unsigned char)s[i], &g)) continue;
        MdGlyph out = {g.codepoint, pen, line.baseline, md_glyph_advance(font, cs, &g)};
        if (PUSH(l->glyphs, l->glyph_count, l->glyph_capacity, out)) return -1;
        pen += out.advance;
        line.glyph_count++;
    }
    line.width = pen - x;
    if (PUSH(l->lines, l->line_count, l->line_capacity, line)) return -1;
    l->pages[f->page].line_count++;
    if (overflow) l->overflow_count++;
    return 0;
}

static int flow_paragraph(Flow *f, uint32_t index, const MdParagraph *p, const MfFont *const *fonts, uint32_t font_count) {
    const MdDocument *doc = f->doc;
    if (p->paragraph_style >= doc->paragraph_style_count) return -1;
    const MdParagraphStyle *ps = &doc->paragraph_styles[p->paragraph_style];
    if (ps->character_style >= doc->character_style_count) return -1;
    const MdCharacterStyle *cs = &doc->character_styles[ps->character_style];
    if (cs->font_id >= font_count || !fonts[cs->font_id]) return -1;
    const MfFont *font = fonts[cs->font_id];
    const char *s = p->text;
    uint32_t n = p->length, pos = skip_spaces(s, 0, n);
    MdUnit lh = md_line_height(font, ps), space = md_space_advance(font, cs);
    if (lh <= 0) return -1;
    if (f->y > frame_of(f)->rect.y) f->y += ps->space_before;
    int first = 1;
    while (first || pos < n) {
        for (;;) {
            MdRect fr = frame_of(f)->rect;
            if (f->y + lh > fr.y + fr.h) {
                if (lh > fr.h || next_frame(f)) return -1;
                continue;
            }
            MdUnit x0, x1;
            int narrowed;
            free_segment(f, fr, f->y, lh, &x0, &x1, &narrowed);
            MdUnit x = x0 + (first ? ps->first_indent : 0), avail = x1 - x;
            /* Greedy: as many whole words as fit. */
            uint32_t end = pos, q = pos;
            MdUnit w = 0;
            while (q < n) {
                uint32_t e = word_end(s, q, n);
                MdUnit cand = (end > pos ? w + space : 0) + word_width(font, cs, s, q, e);
                if (cand > avail) break;
                w = cand;
                end = e;
                q = skip_spaces(s, e, n);
            }
            int overflow = 0;
            if (end == pos && pos < n) {
                if (narrowed) { /* no room beside the exclusion: next line, keeping the leading grid */
                    f->y += lh;
                    continue;
                }
                /* A word longer than the whole column: break it by characters. */
                uint32_t e = word_end(s, pos, n);
                end = pos + 1;
                while (end < e && word_width(font, cs, s, pos, end + 1) <= avail) end++;
                overflow = word_width(font, cs, s, pos, end) > avail;
            }
            if (emit_line(f, index, ps->character_style, font, cs, s, pos, end, x, lh, overflow)) return -1;
            f->y += lh;
            pos = skip_spaces(s, end, n);
            break;
        }
        first = 0;
    }
    f->y += ps->space_after;
    return 0;
}

int md_layout_story(const MdDocument *doc, uint32_t story, const MfFont *const *fonts, uint32_t font_count, MdLayout *out) {
    if (!out) return -1;
    memset(out, 0, sizeof(*out));
    if (!doc || !fonts || story >= doc->story_count) return -1;
    MdRect col = md_page_column(&doc->page, 0);
    if (col.w <= 0 || col.h <= 0) return -1;
    Flow f = {doc, out, 0, 0, col.y};
    int rc = new_page(&f);
    const MdTextStory *s = &doc->stories[story];
    for (uint32_t i = 0; !rc && i < s->count; i++) rc = flow_paragraph(&f, i, &s->paragraphs[i], fonts, font_count);
    /* Pages that only hold graphics still exist. */
    for (uint32_t i = 0; !rc && i < doc->graphic_count; i++)
        while (!rc && doc->graphics[i].page >= out->page_count) rc = new_page(&f);
    if (rc) md_layout_free(out);
    return rc;
}

void md_layout_free(MdLayout *l) {
    if (!l) return;
    free(l->pages);
    free(l->frames);
    free(l->lines);
    free(l->glyphs);
    memset(l, 0, sizeof(*l));
}
