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

/* ---- Paragraph text with per-byte character styles ---- */

typedef struct {
    const MdDocument *doc;
    const MdParagraph *p;
    const MfFont *const *fonts;
    const MdParagraphStyle *ps;
    MdUnit line_height, ascent;
} Para;

static uint32_t style_at(const Para *t, uint32_t i) { return md_paragraph_style_at(t->doc, t->p, i); }
static const MfFont *font_of(const Para *t, uint32_t style) { return t->fonts[t->doc->character_styles[style].font_id]; }
/* Advance of byte i: glyph advance, space advance, or 0 for a missing glyph. */
static MdUnit advance_at(const Para *t, uint32_t i, MfGlyph *g, int *has_glyph) {
    uint32_t st = style_at(t, i);
    const MfFont *font = font_of(t, st);
    const MdCharacterStyle *cs = &t->doc->character_styles[st];
    *has_glyph = 0;
    if (t->p->text[i] == ' ') return md_space_advance(font, cs);
    if (!find_glyph(font, (unsigned char)t->p->text[i], g)) return 0;
    *has_glyph = 1;
    return md_glyph_advance(font, cs, g);
}
static MdUnit width_of(const Para *t, uint32_t a, uint32_t b) {
    MdUnit w = 0;
    MfGlyph g;
    int has;
    for (uint32_t i = a; i < b; i++) w += advance_at(t, i, &g, &has);
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
/* Validates every style the paragraph uses and takes the largest metrics. */
static int para_init(Para *t, const MdDocument *doc, const MdParagraph *p, const MfFont *const *fonts, uint32_t font_count) {
    if (p->paragraph_style >= doc->paragraph_style_count) return -1;
    *t = (Para){doc, p, fonts, &doc->paragraph_styles[p->paragraph_style], 0, 0};
    for (uint32_t r = 0; r <= p->run_count; r++) {
        uint32_t st = r < p->run_count ? p->runs[r].character_style : t->ps->character_style;
        if (st >= doc->character_style_count) return -1;
        uint32_t id = doc->character_styles[st].font_id;
        if (id >= font_count || !fonts[id]) return -1;
        MdUnit lh = md_line_height(fonts[id], t->ps), asc = (MdUnit)fonts[id]->ascent * MD_UNITS_PER_FONT_PX;
        if (lh > t->line_height) t->line_height = lh;
        if (asc > t->ascent) t->ascent = asc;
    }
    return t->line_height > 0 ? 0 : -1;
}

/* ---- Pages, bands and frames ---- */

typedef struct {
    const MdDocument *doc;
    MdLayout *out;
    uint32_t page, band, column; /* band = index of the band's first frame */
    int spanning; /* current band is one frame across all columns */
    MdUnit y;
} Flow;

static uint32_t columns_of(const Flow *f) { return f->doc->page.columns ? f->doc->page.columns : 1; }
static const MdTextFrame *frame_of(const Flow *f) { return &f->out->frames[f->band + f->column]; }

/* Columns (or one spanning frame) from `top` to the bottom of the content area. */
static int new_band(Flow *f, MdUnit top, int spanning) {
    MdLayout *l = f->out;
    MdRect c = md_page_content(&f->doc->page);
    uint32_t columns = columns_of(f), n = spanning ? 1 : columns;
    f->band = l->frame_count;
    for (uint32_t i = 0; i < n; i++) {
        MdRect r = spanning ? c : md_page_column(&f->doc->page, i);
        r.h = c.y + c.h - top;
        r.y = top;
        MdTextFrame frame = {f->page, i, spanning ? columns : 1, r};
        if (PUSH(l->frames, l->frame_count, l->frame_capacity, frame)) return -1;
    }
    l->pages[f->page].frame_count += n;
    f->column = 0;
    f->spanning = spanning;
    f->y = top;
    return 0;
}
static int new_page(Flow *f, int spanning) {
    MdLayout *l = f->out;
    if (l->page_count >= MD_LAYOUT_MAX_PAGES) return -1;
    MdPage page = {l->frame_count, 0, l->line_count, 0};
    if (PUSH(l->pages, l->page_count, l->page_capacity, page)) return -1;
    f->page = l->page_count - 1;
    return new_band(f, md_page_content(&f->doc->page).y, spanning);
}
/* Ends the current band at y: its frames are cut there, or removed if empty. */
static void close_band(Flow *f) {
    MdLayout *l = f->out;
    uint32_t n = l->frame_count - f->band;
    if (f->column == 0 && f->y == l->frames[f->band].rect.y) {
        l->frame_count = f->band;
        l->pages[f->page].frame_count -= n;
        return;
    }
    for (uint32_t i = f->band; i < l->frame_count; i++) {
        MdRect *r = &l->frames[i].rect;
        r->h = f->y > r->y ? f->y - r->y : 0;
    }
}
static int next_frame(Flow *f) {
    if (!f->spanning && f->column + 1 < columns_of(f)) {
        f->column++;
        f->y = frame_of(f)->rect.y;
        return 0;
    }
    return new_page(f, f->spanning);
}
/* Spanning paragraphs start a spanning band where column 0 is (or on a new
   page if the text already moved to another column); text after them starts
   a new band of columns. */
static int enter_paragraph(Flow *f, const MdParagraphStyle *ps) {
    int want = ps->span == MD_SPAN_ALL;
    int at_top = f->y == frame_of(f)->rect.y;
    if (want == f->spanning) {
        if (!at_top) f->y += ps->space_before;
        return 0;
    }
    if (want && f->column > 0) return new_page(f, 1);
    MdUnit top = f->y + (at_top ? 0 : ps->space_before);
    f->y = top;
    close_band(f);
    MdRect c = md_page_content(&f->doc->page);
    if (top >= c.y + c.h) return new_page(f, want);
    return new_band(f, top, want);
}

/* ---- Free pieces of a line band ---- */

enum { MAX_SEG = 32 };
typedef struct {
    MdUnit x0[MAX_SEG], x1[MAX_SEG];
    int count, narrowed;
} Segments;

/* Pieces of `frame` in [y, y+h) not covered by exclusions, left to right.
   A MD_WRAP_LARGEST graphic in the band keeps only the widest piece. */
static void free_segments(const Flow *f, MdRect frame, MdUnit y, MdUnit h, Segments *s) {
    s->count = 1;
    s->x0[0] = frame.x;
    s->x1[0] = frame.x + frame.w;
    s->narrowed = 0;
    int largest = 0;
    for (uint32_t i = 0; i < f->doc->graphic_count; i++) {
        const MdGraphicObject *g = &f->doc->graphics[i];
        if (g->wrap == MD_WRAP_NONE || g->page != f->page) continue;
        MdRect e = md_graphic_exclusion(g);
        if (e.y >= y + h || e.y + e.h <= y || e.x >= frame.x + frame.w || e.x + e.w <= frame.x) continue;
        s->narrowed = 1;
        largest |= g->wrap == MD_WRAP_LARGEST;
        Segments t = {.count = 0};
        for (int k = 0; k < s->count; k++) {
            if (e.x + e.w <= s->x0[k] || e.x >= s->x1[k]) {
                t.x0[t.count] = s->x0[k], t.x1[t.count++] = s->x1[k];
                continue;
            }
            if (e.x > s->x0[k] && t.count < MAX_SEG) t.x0[t.count] = s->x0[k], t.x1[t.count++] = e.x;
            if (e.x + e.w < s->x1[k] && t.count < MAX_SEG) t.x0[t.count] = e.x + e.w, t.x1[t.count++] = s->x1[k];
        }
        memcpy(s->x0, t.x0, sizeof(t.x0));
        memcpy(s->x1, t.x1, sizeof(t.x1));
        s->count = t.count;
    }
    if (!s->narrowed) return;
    int m = 0, best = -1;
    for (int k = 0; k < s->count; k++)
        if (s->x1[k] - s->x0[k] >= MD_LAYOUT_MIN_SEGMENT) s->x0[m] = s->x0[k], s->x1[m++] = s->x1[k];
    s->count = m;
    if (!largest || m < 2) return;
    for (int k = 0; k < m; k++)
        if (best < 0 || s->x1[k] - s->x0[k] > s->x1[best] - s->x0[best]) best = k;
    s->x0[0] = s->x0[best], s->x1[0] = s->x1[best], s->count = 1;
}

/* ---- Lines ---- */

/* Places bytes [a, b) in [x, x1) with the paragraph alignment. */
static int emit_line(Flow *f, const Para *t, uint32_t index, uint32_t a, uint32_t b, MdUnit x, MdUnit x1, int last, int overflow) {
    MdLayout *l = f->out;
    const char *s = t->p->text;
    MdUnit natural = width_of(t, a, b), free_w = x1 - x - natural, start = x;
    uint32_t gaps = 0;
    for (uint32_t i = a + 1; i < b; i++) gaps += s[i] == ' ' && s[i - 1] != ' ';
    int justify = t->ps->align == MD_ALIGN_JUSTIFY && !last && !overflow && gaps > 0 && free_w > 0;
    if (free_w > 0 && !overflow) {
        if (t->ps->align == MD_ALIGN_RIGHT) start = x + free_w;
        if (t->ps->align == MD_ALIGN_CENTER) start = x + free_w / 2;
    }
    MdLine line = {f->page, f->band + f->column, index, t->ps->character_style, start, f->y, f->y + t->ascent, 0, t->line_height,
        l->glyph_count, 0, overflow};
    MdUnit pen = start;
    uint32_t gap = 0;
    MfGlyph g;
    int has;
    for (uint32_t i = a; i < b; i++) {
        if (justify && i > a && s[i] == ' ' && s[i - 1] != ' ') {
            pen += free_w / (MdUnit)gaps + (gap < (uint32_t)(free_w % (MdUnit)gaps) ? 1 : 0);
            gap++;
        }
        MdUnit adv = advance_at(t, i, &g, &has);
        if (has) {
            MdGlyph out = {g.codepoint, pen, line.baseline, adv, style_at(t, i)};
            if (PUSH(l->glyphs, l->glyph_count, l->glyph_capacity, out)) return -1;
            line.glyph_count++;
        }
        pen += adv;
    }
    line.width = pen - start;
    if (PUSH(l->lines, l->line_count, l->line_capacity, line)) return -1;
    l->pages[f->page].line_count++;
    if (overflow) l->overflow_count++;
    return 0;
}

/* Greedy fit of whole words from pos into avail; returns the end byte. */
static uint32_t fit_words(const Para *t, uint32_t pos, MdUnit avail) {
    const char *s = t->p->text;
    uint32_t n = t->p->length, end = pos, q = pos;
    MdUnit w = 0;
    while (q < n) {
        uint32_t e = word_end(s, q, n);
        MdUnit cand = w + width_of(t, end, q) + width_of(t, q, e); /* gap before the word, then the word */
        if (cand > avail) break;
        w = cand;
        end = e;
        q = skip_spaces(s, e, n);
    }
    return end;
}

static int flow_paragraph(Flow *f, uint32_t index, const MdParagraph *p, const MfFont *const *fonts, uint32_t font_count) {
    Para t;
    if (para_init(&t, f->doc, p, fonts, font_count) || enter_paragraph(f, t.ps)) return -1;
    const char *s = p->text;
    uint32_t n = p->length, pos = skip_spaces(s, 0, n);
    MdUnit lh = t.line_height;
    int first = 1;
    while (first || pos < n) {
        MdRect fr = frame_of(f)->rect;
        if (f->y + lh > fr.y + fr.h) {
            if (lh > md_page_content(&f->doc->page).h || next_frame(f)) return -1;
            continue;
        }
        Segments seg;
        free_segments(f, fr, f->y, lh, &seg);
        for (int k = 0; k < seg.count && (first || pos < n); k++) {
            MdUnit x = seg.x0[k] + (first ? t.ps->first_indent : 0), x1 = seg.x1[k];
            uint32_t end = fit_words(&t, pos, x1 - x);
            int overflow = 0;
            if (end == pos && pos < n) {
                if (seg.narrowed) continue; /* this piece is too narrow for the next word */
                /* A word longer than the whole column: break it by characters. */
                uint32_t e = word_end(s, pos, n);
                end = pos + 1;
                while (end < e && width_of(&t, pos, end + 1) <= x1 - x) end++;
                overflow = width_of(&t, pos, end) > x1 - x;
            }
            if (emit_line(f, &t, index, pos, end, x, x1, skip_spaces(s, end, n) >= n, overflow)) return -1;
            pos = skip_spaces(s, end, n);
            first = 0;
        }
        /* Next line; if nothing fitted beside an exclusion this keeps the leading grid. */
        f->y += lh;
    }
    f->y += t.ps->space_after;
    return 0;
}

int md_layout_story(const MdDocument *doc, uint32_t story, const MfFont *const *fonts, uint32_t font_count, MdLayout *out) {
    if (!out) return -1;
    memset(out, 0, sizeof(*out));
    if (!doc || !fonts || story >= doc->story_count) return -1;
    MdRect col = md_page_column(&doc->page, 0);
    if (col.w <= 0 || col.h <= 0) return -1;
    Flow f = {doc, out, 0, 0, 0, 0, col.y};
    int rc = new_page(&f, 0);
    const MdTextStory *s = &doc->stories[story];
    for (uint32_t i = 0; !rc && i < s->count; i++) rc = flow_paragraph(&f, i, &s->paragraphs[i], fonts, font_count);
    /* Pages that only hold graphics still exist. */
    for (uint32_t i = 0; !rc && i < doc->graphic_count; i++)
        while (!rc && doc->graphics[i].page >= out->page_count) rc = new_page(&f, 0);
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
