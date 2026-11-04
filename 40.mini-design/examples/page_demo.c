/* Page demo: an A4 MiniDesign document built programmatically, composed by
   the layout engine and rendered through MiniGFX. Headline and kicker span
   all columns, the body is justified with italic runs, the first picture
   straddles the column gap and the second one has text on both sides.
   Output: page1-320x240, page1-640x480, page1-100, page1-200, page2-320x240,
           page2-640x480, page2-100 (.ppm)
   Usage: page_demo [font_dir] [resource_dir] [image_percent] [paragraphs] [columns]
   Changing any of the numbers recomposes lines, columns and pages. */
#include "document_render.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { FONT_BODY,
    FONT_TITLE,
    FONT_KICKER,
    FONT_ITALIC,
    FONT_COUNT };
static const char *font_files[FONT_COUNT] = {"news10.mf", "news24bold.mf", "park10bold.mf", "news10italic.mf"};
static const uint32_t shapes[2] = {130, 127}; /* "Newspaper" and "Antique Clock" in NEWS.SHP */

static const char *paragraphs[] = {
    "MiniDesign is a desktop publishing program for the MiniCPU and MiniGPU, inspired by NewsMaster 1.5. "
    "This page was not drawn by hand: a document model describes the paper, the margins, the columns and "
    "the text, and a layout engine decides where every line and every glyph goes.",
    "The document stores physical measurements in units of 1/720 inch. A sheet of A4 paper is 5953 by 8419 "
    "units, whatever the screen. The same composition is shown at 320x240, at 640x480 or at full size, "
    "and the line breaks never change with the zoom.",
    "Text flows through a story made of paragraphs. Each paragraph has a style that chooses a font, the "
    "leading, the indent of the first line and the space before and after. Fonts are proportional, so the "
    "real advance of every glyph is used, plus the spacing that each NewsMaster font defines.",
    "When a column is full the text continues at the top of the next one, and when the last column of a "
    "page is full a new page is created. Nobody has to say where a column ends: adding a sentence or "
    "removing one composes the whole story again.",
    "Illustrations come from the original clip art of NewsMaster. A graphic object has a position and a "
    "size in document units, a margin and an exclusion rectangle. Lines that cross the rectangle are made "
    "shorter, so the text runs around the picture instead of over it.",
    "The renderer knows nothing about pages, paragraphs or columns. It receives a display list with "
    "rectangles, bitmaps and glyph runs. At full size each line becomes a glyph run; when the whole page is "
    "shown the words become grey bars, as in the full page view of NewsMaster.",
    "Everything is computed on the CPU in plain C11 without external libraries, so the same code can later "
    "feed the display list of the MiniGPU. Editing, saving and loading documents, kerning, hyphenation and "
    "justification are left for later versions.",
};
#define PARAGRAPH_POOL (sizeof(paragraphs) / sizeof(paragraphs[0]))
/* Words set in italic, one per paragraph of the pool. */
static const char *emphasis[PARAGRAPH_POOL] = {"MiniDesign", "1/720 inch", "story", "a new page is created", "exclusion rectangle",
    "full page view", "plain C11"};

static int emphasize(MdDocument *doc, uint32_t story, uint32_t paragraph, const char *words, uint32_t style) {
    const char *text = doc->stories[story].paragraphs[paragraph].text, *at = strstr(text, words);
    if (!at) return -1;
    uint32_t start = (uint32_t)(at - text);
    return md_paragraph_add_run(doc, story, paragraph, start, start + (uint32_t)strlen(words), style);
}

static uint8_t *load(const char *dir, const char *name, size_t *n) {
    char path[1024];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    uint8_t *p = NULL;
    long z = (!fseek(f, 0, SEEK_END)) ? ftell(f) : -1;
    if (z > 0 && !fseek(f, 0, SEEK_SET) && (p = malloc((size_t)z)) && fread(p, 1, (size_t)z, f) != (size_t)z) {
        free(p);
        p = NULL;
    }
    fclose(f);
    if (p) *n = (size_t)z;
    return p;
}

/* NEWS.SDX: u32 LE offsets into NEWS.SHP. Record: u8 row_bytes, u8 height,
   u16 LE width, rows MSB first with 1 = black, then one trailing byte. */
static int shape_bitmap(const uint8_t *shp, size_t shp_n, const uint8_t *sdx, size_t sdx_n, uint32_t index, GfxBitmap *out) {
    if (sdx_n % 4 || (size_t)(index + 1) * 4 > sdx_n) return -1;
    const uint8_t *e = sdx + (size_t)index * 4;
    size_t at = (size_t)e[0] | (size_t)e[1] << 8 | (size_t)e[2] << 16 | (size_t)e[3] << 24;
    if (at + 4 > shp_n) return -1;
    uint32_t row = shp[at], h = shp[at + 1], w = (uint32_t)shp[at + 2] | (uint32_t)shp[at + 3] << 8;
    if (!w || !h || row < (w + 7) / 8 || at + 4 + (size_t)row * h > shp_n) return -1;
    *out = (GfxBitmap){shp + at + 4, w, h, row, GFX_BITMAP_MONO1};
    return 0;
}

static int write_page(const MdDocument *doc, const MdLayout *layout, uint32_t page, const MdViewport *vp, const GfxResources *res,
    const MdRenderOptions *opt, const char *path) {
    uint16_t *pixels = calloc((size_t)vp->screen_w * (size_t)vp->screen_h, sizeof(uint16_t));
    if (!pixels) return -1;
    GfxSurface surface = {pixels, (uint32_t)vp->screen_w, (uint32_t)vp->screen_h, (uint32_t)vp->screen_w};
    MdRenderList rl;
    int rc = md_render_page(doc, layout, page, vp, res, opt, &rl);
    if (!rc) rc = gfx_execute_cpu_resources(&rl.list, &surface, &rl.resources);
    if (!rc) rc = gfx_write_ppm(path, &surface);
    if (!rc) printf("Created %s (%s)\n", path, rl.greeked ? "greeked text" : "glyph runs");
    md_render_list_free(&rl);
    free(pixels);
    return rc;
}

int main(int argc, char **argv) {
    const char *font_dir = argc > 1 ? argv[1] : "build/fonts", *res_dir = argc > 2 ? argv[2] : "resources";
    int image_percent = argc > 3 ? atoi(argv[3]) : 175, count = argc > 4 ? atoi(argv[4]) : 14, columns = argc > 5 ? atoi(argv[5]) : 2;
    if (image_percent <= 0 || count < 0 || columns < 1 || columns > 8) {
        fprintf(stderr, "usage: %s [font_dir] [resource_dir] [image_percent] [paragraphs] [columns 1..8]\n", argv[0]);
        return 2;
    }
    int rc = 1;
    uint8_t *font_data[FONT_COUNT] = {0}, *shp = NULL, *sdx = NULL;
    MfFont fonts[FONT_COUNT];
    const MfFont *font_table[FONT_COUNT];
    for (int i = 0; i < FONT_COUNT; i++) {
        size_t n = 0;
        font_data[i] = load(font_dir, font_files[i], &n);
        if (!font_data[i] || mf_open(&fonts[i], font_data[i], n)) {
            fprintf(stderr, "Cannot open font %s/%s (run make flb-fonts)\n", font_dir, font_files[i]);
            goto done;
        }
        font_table[i] = &fonts[i];
    }
    size_t shp_n = 0, sdx_n = 0;
    GfxBitmap pictures[2];
    shp = load(res_dir, "NEWS.SHP", &shp_n);
    sdx = load(res_dir, "NEWS.SDX", &sdx_n);
    for (int i = 0; i < 2; i++)
        if (!shp || !sdx || shape_bitmap(shp, shp_n, sdx, sdx_n, shapes[i], &pictures[i])) {
            fprintf(stderr, "Cannot read shape %u from %s/NEWS.SHP and NEWS.SDX\n", shapes[i], res_dir);
            goto done;
        }

    MdDocument doc;
    MdPageSettings settings = md_page_settings_a4();
    settings.columns = (uint32_t)columns;
    md_document_init(&doc, settings);
    uint32_t c_body = md_add_character_style(&doc, (MdCharacterStyle){FONT_BODY, 0, 0x0000});
    uint32_t c_title = md_add_character_style(&doc, (MdCharacterStyle){FONT_TITLE, 0, 0x0000});
    uint32_t c_kicker = md_add_character_style(&doc, (MdCharacterStyle){FONT_KICKER, 0, 0x8000});
    uint32_t c_italic = md_add_character_style(&doc, (MdCharacterStyle){FONT_ITALIC, 0, 0x0000});
    MdUnit pt = md_units_from_pt(1);
    uint32_t p_kicker = md_add_paragraph_style(&doc, (MdParagraphStyle){c_kicker, 0, 100, 0, 4 * pt, 0, MD_ALIGN_CENTER, MD_SPAN_ALL});
    uint32_t p_title = md_add_paragraph_style(&doc, (MdParagraphStyle){c_title, 0, 100, 0, 2 * pt, 0, MD_ALIGN_CENTER, MD_SPAN_ALL});
    uint32_t p_byline = md_add_paragraph_style(&doc, (MdParagraphStyle){c_italic, 0, 100, 0, 14 * pt, 0, MD_ALIGN_CENTER, MD_SPAN_ALL});
    uint32_t p_body = md_add_paragraph_style(&doc, (MdParagraphStyle){c_body, 0, 115, 0, 5 * pt, 12 * pt, MD_ALIGN_JUSTIFY, MD_SPAN_COLUMN});
    uint32_t story = md_add_story(&doc);
    int fail = c_body == UINT32_MAX || c_title == UINT32_MAX || c_kicker == UINT32_MAX || c_italic == UINT32_MAX || p_kicker == UINT32_MAX ||
        p_title == UINT32_MAX || p_byline == UINT32_MAX || p_body == UINT32_MAX || story == UINT32_MAX;
    fail |= md_story_add_paragraph(&doc, story, p_kicker, "THE MINIGPU TIMES - VOLUME 0.5") == UINT32_MAX;
    fail |= md_story_add_paragraph(&doc, story, p_title, "Pages that compose themselves") == UINT32_MAX;
    fail |= md_story_add_paragraph(&doc, story, p_byline, "Justified columns, headlines across the page and text on both sides of a picture") ==
        UINT32_MAX;
    for (int i = 0; !fail && i < count; i++) {
        uint32_t id = md_story_add_paragraph(&doc, story, p_body, paragraphs[(size_t)i % PARAGRAPH_POOL]);
        fail |= id == UINT32_MAX || emphasize(&doc, story, id, emphasis[(size_t)i % PARAGRAPH_POOL], c_italic);
    }
    /* Page 1: centred picture; with two columns it straddles the gap and both columns wrap around it.
       NEWS.SHP pictures are 120 x 72 dpi, like the fonts. */
    MdUnit w = (MdUnit)((int64_t)md_units_from_pixels((int32_t)pictures[0].width, MD_NEWSMASTER_DPI_X) * image_percent / 100);
    MdUnit h = (MdUnit)((int64_t)md_units_from_pixels((int32_t)pictures[0].height, MD_NEWSMASTER_DPI_Y) * image_percent / 100);
    MdUnit top = md_page_content(&doc.page).y + md_units_from_mm10(800);
    fail |= md_add_graphic(&doc, (MdGraphicObject){0, {(doc.page.paper.width - w) / 2, top, w, h}, 0, 6 * pt, MD_WRAP_LARGEST, 0x0000}) ==
        UINT32_MAX;
    /* Page 2: picture in the middle of the first column, text on both sides. */
    MdRect col = md_page_column(&doc.page, 0);
    MdUnit w2 = md_units_from_pixels((int32_t)pictures[1].width, MD_NEWSMASTER_DPI_X);
    MdUnit h2 = md_units_from_pixels((int32_t)pictures[1].height, MD_NEWSMASTER_DPI_Y);
    MdUnit top2 = col.y + md_units_from_mm10(1200);
    fail |= md_add_graphic(&doc, (MdGraphicObject){1, {col.x + (col.w - w2) / 2, top2, w2, h2}, 1, 4 * pt, MD_WRAP_BOTH, 0x0010}) == UINT32_MAX;

    MdLayout layout;
    if (fail || md_layout_story(&doc, story, font_table, FONT_COUNT, &layout)) {
        fprintf(stderr, "Layout failed\n");
        md_document_free(&doc);
        goto done;
    }
    printf("Layout: %u page(s), %u lines, %u glyphs, %u overflow line(s)\n", layout.page_count, layout.line_count, layout.glyph_count,
        layout.overflow_count);

    GfxResources res = {.fonts = font_table, .font_count = FONT_COUNT, .bitmaps = pictures, .bitmap_count = 2};
    MdRenderOptions opt = md_render_default_options(), guides = opt;
    guides.show_guides = 1;
    MdViewport vp;
    char path[64];
    rc = 0;
    for (uint32_t p = 0; !rc && p < layout.page_count && p < 2; p++) {
        static const int32_t sizes[2][2] = {{320, 240}, {640, 480}};
        for (int s = 0; !rc && s < 2; s++) {
            snprintf(path, sizeof path, "page%u-%dx%d.ppm", p + 1, sizes[s][0], sizes[s][1]);
            rc = md_viewport_fit_page(&vp, sizes[s][0], sizes[s][1], doc.page.paper, 6) ||
                write_page(&doc, &layout, p, &vp, &res, &opt, path);
        }
    }
    /* 100 % (NewsMaster's Normal view): one font pixel per screen pixel on each
       axis, real glyphs around the pictures, with column and exclusion guides.
       The page is 992 px wide at 120 dpi, so the view is centred on it. */
    const uint32_t dx = MD_NEWSMASTER_DPI_X, dy = MD_NEWSMASTER_DPI_Y;
    MdUnit left = (doc.page.paper.width - md_units_from_pixels(640, dx)) / 2;
    if (!rc)
        rc = md_viewport_actual_size(&vp, 640, 480, dx, dy, left, top - md_units_from_mm10(400)) ||
            write_page(&doc, &layout, 0, &vp, &res, &guides, "page1-100.ppm");
    if (!rc && layout.page_count > 1)
        rc = md_viewport_actual_size(&vp, 640, 480, dx, dy, col.x - md_units_from_pixels(40, dx), top2 - md_units_from_mm10(250)) ||
            write_page(&doc, &layout, 1, &vp, &res, &guides, "page2-100.ppm");
    /* 200 % (Zoom view): the headline and the start of the first column, glyphs scaled by GLYPH_RUN. */
    if (!rc)
        rc = md_viewport_text_zoom(&vp, 640, 480, dx, dy, 2, doc.page.margin_left - md_units_from_mm10(50),
                 doc.page.margin_top - md_units_from_mm10(50)) ||
            write_page(&doc, &layout, 0, &vp, &res, &opt, "page1-200.ppm");
    md_layout_free(&layout);
    md_document_free(&doc);
    rc = rc ? 1 : 0;
done:
    for (int i = 0; i < FONT_COUNT; i++) free(font_data[i]);
    free(shp);
    free(sdx);
    return rc;
}
