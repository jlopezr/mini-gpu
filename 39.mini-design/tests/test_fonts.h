/* Synthetic MiniFont for layout tests: ASCII 33..126, ascent 7, descent 2,
   line gap 1 (10 px line), proportional advances 'i' 'l' '.' = 2, 'm' 'w' 'M'
   'W' = 8, everything else 5. No space glyph, like the NewsMaster fonts. */
#ifndef TEST_FONTS_H
#define TEST_FONTS_H
#include "minifont.h"
#include <assert.h>
#include <string.h>

enum { TF_FIRST = 33,
    TF_LAST = 126,
    TF_COUNT = TF_LAST - TF_FIRST + 1,
    TF_H = 7 };
enum { TF_SIZE = 32 + TF_COUNT * 24 + TF_COUNT * TF_H };

static int tf_advance(uint32_t cp) {
    if (cp == 'i' || cp == 'l' || cp == '.') return 2;
    if (cp == 'm' || cp == 'w' || cp == 'M' || cp == 'W') return 8;
    return 5;
}
static void tf_put16(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v, p[1] = (uint8_t)(v >> 8); }
static void tf_put32(uint8_t *p, uint32_t v) { tf_put16(p, v), tf_put16(p + 2, v >> 16); }

/* Writes TF_SIZE bytes; font_spacing > 0 sets header flag 0x0001. */
static void tf_build(uint8_t *buf, uint16_t font_spacing) {
    memset(buf, 0, TF_SIZE);
    memcpy(buf, "MFNT", 4);
    tf_put16(buf + 4, 1);
    tf_put16(buf + 6, font_spacing ? 1 : 0);
    tf_put32(buf + 8, TF_COUNT);
    tf_put32(buf + 12, 32);
    tf_put32(buf + 16, 32 + TF_COUNT * 24);
    tf_put16(buf + 20, 7), tf_put16(buf + 22, 2), tf_put16(buf + 24, 1), tf_put16(buf + 26, 9);
    tf_put16(buf + 28, font_spacing);
    for (uint32_t i = 0; i < TF_COUNT; i++) {
        uint8_t *g = buf + 32 + i * 24;
        uint32_t adv = (uint32_t)tf_advance(TF_FIRST + i), w = adv > 1 ? adv - 1 : 1;
        tf_put32(g, TF_FIRST + i);
        tf_put32(g + 4, i * TF_H);
        tf_put16(g + 10, TF_H);
        tf_put16(g + 12, w), tf_put16(g + 14, TF_H), tf_put16(g + 16, adv);
        tf_put32(g + 20, TF_H);
        memset(buf + 32 + TF_COUNT * 24 + i * TF_H, (int)(0xFF00u >> w) & 0xFF, TF_H);
    }
}
static void tf_open(MfFont *font, uint8_t *buf, uint16_t font_spacing) {
    tf_build(buf, font_spacing);
    assert(mf_open(font, buf, TF_SIZE) == 0);
}
#endif
