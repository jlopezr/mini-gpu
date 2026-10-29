#ifndef MINIFONT_H
#define MINIFONT_H
#include <stdint.h>
#include <stddef.h>
typedef struct {
 uint32_t codepoint, bitmap_offset;
 int16_t bearing_x, bearing_y;
 uint16_t width, height;
 int16_t advance_x;
 uint32_t bitmap_size;
} MfGlyph;
typedef struct {
 const uint8_t *data;
 size_t size;
 uint32_t glyph_count, glyph_table_offset, bitmap_offset;
 int16_t ascent, descent, line_gap;
 uint16_t pixel_size;
} MfFont;
/* All functions return 0 on success. Memory remains owned by caller. */
int mf_open(MfFont *font, const void *data, size_t size);
int mf_find_glyph(const MfFont *font, uint32_t codepoint, MfGlyph *glyph);
int mf_glyph_pixel(const MfFont *font, const MfGlyph *glyph, uint32_t x, uint32_t y);
/* Draw using RGB565 and baseline coordinates; transparent pixels unchanged. */
void mf_draw_glyph_rgb565(const MfFont *font, const MfGlyph *g,
 uint16_t *pixels, uint32_t width, uint32_t height, uint32_t stride,
 int32_t pen_x, int32_t baseline_y, uint16_t color);
#endif
