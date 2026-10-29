#ifndef MINIDESIGN_DOCUMENT_H
#define MINIDESIGN_DOCUMENT_H

/* MiniDesign document model. Persistent content only: no pixels, no layout.
   All geometry is in MdUnit = 1/720 inch, independent of any screen. */

#include <stddef.h>
#include <stdint.h>

typedef int32_t MdUnit;
#define MD_UNITS_PER_INCH 720
#define MD_UNITS_PER_POINT 10
/* Bitmap fonts are screen fonts: one font pixel is taken as 1/72 inch
   (Park 10 is then 10 pt). Layout converts font metrics with this factor. */
#define MD_UNITS_PER_FONT_PX 10

/* Rounded to the nearest unit (half away from zero). */
MdUnit md_units_from_mm10(int32_t tenths_of_mm);
MdUnit md_units_from_pt(int32_t points);
MdUnit md_units_from_inch(int32_t inches);

typedef struct { MdUnit x, y, w, h; } MdRect;
typedef struct { MdUnit width, height; } MdPaperSize;
extern const MdPaperSize MD_PAPER_A4; /* 210 x 297 mm */

typedef struct {
    MdPaperSize paper;
    MdUnit margin_top, margin_bottom, margin_left, margin_right;
    uint32_t columns; /* >= 1 */
    MdUnit column_gap;
} MdPageSettings;

typedef struct {
    uint32_t font_id; /* index into the font table (GfxResources.fonts) */
    MdUnit letter_spacing; /* added to every advance, on top of the font's own font_spacing */
    uint16_t color; /* RGB565 */
} MdCharacterStyle;

typedef enum { MD_ALIGN_LEFT = 0 } MdAlign;

typedef struct {
    uint32_t character_style;
    MdUnit leading; /* line pitch; 0 = automatic from font metrics */
    uint16_t leading_percent; /* applied to automatic leading; 0 = 100 */
    MdUnit space_before, space_after, first_indent;
    MdAlign align;
} MdParagraphStyle;

typedef struct {
    char *text; /* owned, NUL-terminated; words are separated by spaces */
    uint32_t length;
    uint32_t paragraph_style;
} MdParagraph;

typedef struct {
    MdParagraph *paragraphs;
    uint32_t count, capacity;
} MdTextStory;

/* A bitmap placed on a page. The bitmap is a GfxResources.bitmaps entry. */
typedef struct {
    uint32_t page;
    MdRect bounds; /* page coordinates */
    uint32_t bitmap_id;
    MdUnit text_margin; /* extra space kept free around bounds */
    int wrap; /* nonzero: text flows around the exclusion rectangle */
    uint16_t color; /* RGB565 for 1 bits */
} MdGraphicObject;

typedef struct {
    MdPageSettings page;
    MdCharacterStyle *character_styles;
    uint32_t character_style_count, character_style_capacity;
    MdParagraphStyle *paragraph_styles;
    uint32_t paragraph_style_count, paragraph_style_capacity;
    MdTextStory *stories;
    uint32_t story_count, story_capacity;
    MdGraphicObject *graphics;
    uint32_t graphic_count, graphic_capacity;
} MdDocument;

/* A4, 20 mm margins, two columns 5 mm apart. */
MdPageSettings md_page_settings_a4(void);

void md_document_init(MdDocument *doc, MdPageSettings page);
void md_document_free(MdDocument *doc);

/* Functions returning an id return UINT32_MAX on failure. */
uint32_t md_add_character_style(MdDocument *doc, MdCharacterStyle style);
uint32_t md_add_paragraph_style(MdDocument *doc, MdParagraphStyle style);
uint32_t md_add_story(MdDocument *doc);
uint32_t md_story_add_paragraph(MdDocument *doc, uint32_t story, uint32_t paragraph_style, const char *text);
uint32_t md_add_graphic(MdDocument *doc, MdGraphicObject graphic);

/* Exclusion rectangle = bounds grown by text_margin on every side. */
MdRect md_graphic_exclusion(const MdGraphicObject *graphic);
/* Page area inside the margins. */
MdRect md_page_content(const MdPageSettings *page);
/* Rectangle of column `column` inside the content area; equal widths. */
MdRect md_page_column(const MdPageSettings *page, uint32_t column);

#endif
