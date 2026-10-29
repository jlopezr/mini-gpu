#ifndef MINIDESIGN_VIEWPORT_H
#define MINIDESIGN_VIEWPORT_H

/* Document units -> screen pixels: px = origin + (unit - scroll) * num / den.
   Pixels are square (320x240 and 640x480 are 4:3). */

#include "document.h"
#include "gfx.h"

typedef struct {
    int32_t screen_w, screen_h;
    int32_t origin_x, origin_y; /* screen position of (scroll_x, scroll_y) */
    MdUnit scroll_x, scroll_y;
    uint32_t scale_num, scale_den; /* pixels per unit = num / den */
} MdViewport;

/* Whole page, centred, at least `margin_px` from the screen edges. */
int md_viewport_fit_page(MdViewport *vp, int32_t screen_w, int32_t screen_h, MdPaperSize paper, int32_t margin_px);
/* Arbitrary zoom; num/den = pixels per unit. (scroll_x, scroll_y) maps to (0, 0). */
int md_viewport_zoom(MdViewport *vp, int32_t screen_w, int32_t screen_h, uint32_t num, uint32_t den, MdUnit scroll_x, MdUnit scroll_y);
/* 100 %: one font pixel is one screen pixel. */
int md_viewport_actual_size(MdViewport *vp, int32_t screen_w, int32_t screen_h, MdUnit scroll_x, MdUnit scroll_y);
/* Integer zoom: one font pixel is `factor` screen pixels (200 % = 2). */
int md_viewport_text_zoom(MdViewport *vp, int32_t screen_w, int32_t screen_h, uint32_t factor, MdUnit scroll_x, MdUnit scroll_y);
/* Screen pixels per font pixel if it is a whole number usable by GLYPH_RUN
   (1..GFX_GLYPH_MAX_SCALE), otherwise 0: text is then drawn greeked. */
uint32_t md_viewport_text_scale(const MdViewport *vp);
/* Same as md_viewport_text_scale(vp) == 1. */
int md_viewport_native_text(const MdViewport *vp);

int32_t md_viewport_x(const MdViewport *vp, MdUnit x);
int32_t md_viewport_y(const MdViewport *vp, MdUnit y);
/* Edges are transformed separately, so adjacent rectangles stay adjacent. */
GfxRect md_viewport_rect(const MdViewport *vp, MdRect r);

#endif
