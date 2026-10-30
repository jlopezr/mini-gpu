#ifndef MINIDESIGN_DOCUMENT_RENDER_H
#define MINIDESIGN_DOCUMENT_RENDER_H

/* Layout + viewport -> MiniGFX display list. Only existing primitives are
   emitted (CLEAR, SET_CLIP, FILL_RECT, DRAW_LINE, BLIT, GLYPH_RUN); MiniGFX
   never sees pages, paragraphs or columns. */

#include "gfx.h"
#include "layout.h"
#include "viewport.h"

typedef struct {
    uint16_t desk, paper, shadow, guides, exclusion, greek;
    int show_guides; /* column frames and text exclusions as outlines */
} MdRenderOptions;

/* Owns the display list and the glyph runs it references. `resources` is the
   caller's font and bitmap table plus these runs, ready for
   gfx_execute_cpu_resources(). */
typedef struct {
    GfxDisplayList list;
    GfxPositionedGlyph *glyphs;
    uint32_t glyph_count, glyph_capacity;
    GfxGlyphRun *runs;
    uint32_t run_count, run_capacity;
    GfxResources resources;
    int greeked; /* some text drawn as bars: the zoom is not a whole multiple of its font's raster */
} MdRenderList;

MdRenderOptions md_render_default_options(void);
/* When one font pixel is 1, 2, 3... screen pixels on both axes (see
   md_viewport_text_scale), text in that font becomes one GLYPH_RUN with that
   integer scale per line and character style; otherwise each word becomes a
   FILL_RECT bar ("greeking"). Graphics are drawn with BLIT at any zoom. */
int md_render_page(const MdDocument *doc, const MdLayout *layout, uint32_t page, const MdViewport *vp, const GfxResources *base,
    const MdRenderOptions *options, MdRenderList *out);
void md_render_list_free(MdRenderList *out);

#endif
