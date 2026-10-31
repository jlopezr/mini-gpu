#ifndef MINIDESIGN_VIEWPORT_H
#define MINIDESIGN_VIEWPORT_H

/* Document units -> screen pixels, per axis:
   px = origin + (unit - scroll) * num / den.
   Whole-page and arbitrary zooms use the same scale on both axes, so square
   screen pixels (320x240, 640x480) keep the page's real proportions. Text
   views use a font raster: one font pixel per screen pixel (times `factor`)
   on each axis, like the Normal and Zoom views of NewsMaster. Its 120 x 72 dpi
   fonts then look wider than on paper, as they did on screen. */

#include "document.h"
#include "gfx.h"

typedef struct {
    int32_t screen_w, screen_h;
    int32_t origin_x, origin_y; /* screen position of (scroll_x, scroll_y) */
    MdUnit scroll_x, scroll_y;
    uint32_t x_num, x_den, y_num, y_den; /* pixels per unit = num / den */
} MdViewport;

/* Whole page, centred, at least `margin_px` from the screen edges. */
int md_viewport_fit_page(MdViewport *vp, int32_t screen_w, int32_t screen_h, MdPaperSize paper, int32_t margin_px);
/* Arbitrary zoom; num/den = pixels per unit on both axes. (scroll_x, scroll_y) maps to (0, 0). */
int md_viewport_zoom(MdViewport *vp, int32_t screen_w, int32_t screen_h, uint32_t num, uint32_t den, MdUnit scroll_x, MdUnit scroll_y);
/* Text view of a raster with res_x x res_y dpi: one raster pixel is `factor`
   x `factor` screen pixels (1 = Normal view, 2 = Zoom). */
int md_viewport_text_zoom(MdViewport *vp, int32_t screen_w, int32_t screen_h, uint32_t res_x, uint32_t res_y, uint32_t factor,
    MdUnit scroll_x, MdUnit scroll_y);
/* Same as md_viewport_text_zoom() with factor 1. */
int md_viewport_actual_size(MdViewport *vp, int32_t screen_w, int32_t screen_h, uint32_t res_x, uint32_t res_y, MdUnit scroll_x,
    MdUnit scroll_y);
/* Screen pixels per pixel of `font` if both axes give the same whole number
   usable by GLYPH_RUN (1..GFX_GLYPH_MAX_SCALE), otherwise 0: text in that
   font is then drawn greeked. */
uint32_t md_viewport_text_scale(const MdViewport *vp, const MfFont *font);
/* Same as md_viewport_text_scale(vp, font) == 1. */
int md_viewport_native_text(const MdViewport *vp, const MfFont *font);

int32_t md_viewport_x(const MdViewport *vp, MdUnit x);
int32_t md_viewport_y(const MdViewport *vp, MdUnit y);
/* Edges are transformed separately, so adjacent rectangles stay adjacent. */
GfxRect md_viewport_rect(const MdViewport *vp, MdRect r);

#endif
