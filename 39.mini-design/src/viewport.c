#include "viewport.h"

static int64_t floor_div(int64_t a, int64_t b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

int md_viewport_zoom(MdViewport *vp, int32_t w, int32_t h, uint32_t num, uint32_t den, MdUnit sx, MdUnit sy) {
    if (!vp || w <= 0 || h <= 0 || !num || !den) return -1;
    *vp = (MdViewport){w, h, 0, 0, sx, sy, num, den};
    return 0;
}
int md_viewport_actual_size(MdViewport *vp, int32_t w, int32_t h, MdUnit sx, MdUnit sy) {
    return md_viewport_zoom(vp, w, h, 1, MD_UNITS_PER_FONT_PX, sx, sy);
}
int md_viewport_fit_page(MdViewport *vp, int32_t w, int32_t h, MdPaperSize paper, int32_t margin) {
    int32_t aw = w - 2 * margin, ah = h - 2 * margin;
    if (!vp || aw <= 0 || ah <= 0 || paper.width <= 0 || paper.height <= 0) return -1;
    /* Limited by height if aw/pw >= ah/ph. */
    uint32_t num, den;
    if ((int64_t)aw * paper.height >= (int64_t)ah * paper.width)
        num = (uint32_t)ah, den = (uint32_t)paper.height;
    else
        num = (uint32_t)aw, den = (uint32_t)paper.width;
    if (md_viewport_zoom(vp, w, h, num, den, 0, 0)) return -1;
    vp->origin_x = (w - (int32_t)floor_div((int64_t)paper.width * num, den)) / 2;
    vp->origin_y = (h - (int32_t)floor_div((int64_t)paper.height * num, den)) / 2;
    return 0;
}
int md_viewport_text_zoom(MdViewport *vp, int32_t w, int32_t h, uint32_t factor, MdUnit sx, MdUnit sy) {
    return md_viewport_zoom(vp, w, h, factor, MD_UNITS_PER_FONT_PX, sx, sy);
}
uint32_t md_viewport_text_scale(const MdViewport *vp) {
    uint64_t px = (uint64_t)vp->scale_num * MD_UNITS_PER_FONT_PX;
    if (px % vp->scale_den) return 0;
    px /= vp->scale_den;
    return px >= 1 && px <= GFX_GLYPH_MAX_SCALE ? (uint32_t)px : 0;
}
int md_viewport_native_text(const MdViewport *vp) { return md_viewport_text_scale(vp) == 1; }
int32_t md_viewport_x(const MdViewport *vp, MdUnit x) {
    return vp->origin_x + (int32_t)floor_div((int64_t)(x - vp->scroll_x) * vp->scale_num, vp->scale_den);
}
int32_t md_viewport_y(const MdViewport *vp, MdUnit y) {
    return vp->origin_y + (int32_t)floor_div((int64_t)(y - vp->scroll_y) * vp->scale_num, vp->scale_den);
}
GfxRect md_viewport_rect(const MdViewport *vp, MdRect r) {
    int32_t x0 = md_viewport_x(vp, r.x), y0 = md_viewport_y(vp, r.y);
    int32_t x1 = md_viewport_x(vp, r.x + r.w), y1 = md_viewport_y(vp, r.y + r.h);
    return (GfxRect){x0, y0, x1 - x0, y1 - y0};
}
