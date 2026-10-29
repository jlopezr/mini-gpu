#ifndef MINIDESIGN_LAYOUT_H
#define MINIDESIGN_LAYOUT_H

/* Layout: derived data computed from an MdDocument and a font table.
   Everything is in document units (1/720 inch); nothing depends on the screen. */

#include "document.h"
#include "minifont.h"

typedef struct {
    uint32_t glyph_id; /* codepoint, as MiniFont v1 indexes glyphs */
    MdUnit x, y; /* pen position on the baseline, page coordinates */
    MdUnit advance;
} MdGlyph;

typedef struct {
    uint32_t page, frame, paragraph, character_style;
    MdUnit x, top, baseline, width, height;
    uint32_t first_glyph, glyph_count;
    int overflow; /* a single glyph wider than its column: drawn anyway */
} MdLine;

/* Region where the story flows: one per column and page. */
typedef struct {
    uint32_t page, column;
    MdRect rect;
} MdTextFrame;

typedef struct {
    uint32_t first_frame, frame_count;
    uint32_t first_line, line_count;
} MdPage;

typedef struct {
    MdPage *pages;
    uint32_t page_count, page_capacity;
    MdTextFrame *frames;
    uint32_t frame_count, frame_capacity;
    MdLine *lines;
    uint32_t line_count, line_capacity;
    MdGlyph *glyphs;
    uint32_t glyph_count, glyph_capacity;
    uint32_t overflow_count;
} MdLayout;

#define MD_LAYOUT_MAX_PAGES 256u
/* Narrower pieces left beside an exclusion are not used for text. */
#define MD_LAYOUT_MIN_SEGMENT (MD_UNITS_PER_INCH / 2)

/* Flow `story` through the columns of as many pages as needed. Fonts are
   resolved through `fonts[character_style.font_id]` (the same table given to
   GfxResources.fonts). Returns 0 on success; on error `out` is left empty. */
int md_layout_story(const MdDocument *doc, uint32_t story, const MfFont *const *fonts, uint32_t font_count, MdLayout *out);
void md_layout_free(MdLayout *layout);

/* Metrics used by the layout, in document units. */
MdUnit md_glyph_advance(const MfFont *font, const MdCharacterStyle *style, const MfGlyph *glyph);
MdUnit md_space_advance(const MfFont *font, const MdCharacterStyle *style);
MdUnit md_line_height(const MfFont *font, const MdParagraphStyle *style);

#endif
