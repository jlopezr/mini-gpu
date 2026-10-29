#ifndef MINIDESIGN_GFX_H
#define MINIDESIGN_GFX_H

#include <stdint.h>
#include "minifont.h"

typedef struct { int32_t x, y, w, h; } GfxRect;
typedef struct {
    uint16_t *pixels; /* RGB565 */
    uint32_t width, height;
    uint32_t stride; /* pixels, not bytes */
} GfxSurface;

typedef struct {
    uint32_t glyph_id;
    int32_t x, y;
} GfxPositionedGlyph;
typedef struct {
    const GfxPositionedGlyph *glyphs;
    uint32_t count;
    uint32_t font_id;
} GfxGlyphRun;
typedef enum { GFX_BITMAP_MONO1 = 1 } GfxBitmapFormat;
typedef struct {
    const uint8_t *pixels; /* row-major 1bpp, MSB first */
    uint32_t width, height;
    uint32_t stride_bytes; /* >= ceil(width/8) */
    GfxBitmapFormat format;
} GfxBitmap;
typedef enum { GFX_BLIT_OPAQUE = 0,
    GFX_BLIT_TRANSPARENT_ZERO = 1 } GfxBlitMode;
typedef struct {
    const MfFont *const *fonts;
    uint32_t font_count;
    const GfxGlyphRun *runs;
    uint32_t run_count;
    const GfxBitmap *bitmaps;
    uint32_t bitmap_count;
} GfxResources;

typedef enum {
    GFX_CLEAR,
    GFX_SET_CLIP,
    GFX_FILL_RECT,
    GFX_DRAW_LINE,
    GFX_BLIT,
    GFX_GLYPH_RUN,
    GFX_FILL_PATTERN
} GfxOpcode;

typedef struct {
    GfxOpcode opcode;
    union {
        struct { uint16_t color; } clear;
        struct { GfxRect rect; } clip;
        struct {
            GfxRect rect;
            uint16_t color;
        } fill_rect;
        struct {
            int32_t x0, y0, x1, y1;
            uint16_t color;
        } line;
        struct {
            uint32_t resource_id;
            GfxRect src, dst;
            uint16_t foreground, background;
            GfxBlitMode mode;
        } blit;
        struct {
            uint32_t run_id;
            uint16_t color;
        } glyph_run;
        struct {
            GfxRect rect;
            uint32_t pattern_id;
            uint16_t foreground, background;
        } pattern;
    } data;
} GfxCommand;

typedef struct {
    GfxCommand *commands;
    uint32_t count, capacity;
} GfxDisplayList;

/* Commands are copied into the list; callers retain ownership of resources. */
void gfx_list_init(GfxDisplayList *list);
void gfx_list_destroy(GfxDisplayList *list);
int gfx_list_add(GfxDisplayList *list, GfxCommand command);

/* CPU reference renderer. All clip rectangles are half-open; SET_CLIP resets
   the current clip to its intersection with the surface (not the prior clip).
   Lines are one pixel wide. BLIT samples nearest neighbor at destination pixel
   centers, without smoothing. Unimplemented commands return an error. */
int gfx_execute_cpu(const GfxDisplayList *list, GfxSurface *surface);
int gfx_execute_cpu_resources(const GfxDisplayList *list, GfxSurface *surface, const GfxResources *resources);

/* Save RGB565 surface to binary PPM (P6); useful for portable test output. */
int gfx_write_ppm(const char *filename, const GfxSurface *surface);

#endif
