# MiniFont binary format v1

All integers little-endian; offsets are absolute from start of file unless noted.
No native C struct packing requirements. One fixed raster size per file.

**Header (32 bytes)**
- +0: magic `MFNT` (4 bytes)
- +4: version u16 = 1
- +6: flags u16; bit 0 (0x0001) = `font_spacing` present; other bits reserved
- +8: glyph_count u32
- +12: glyph_table_offset u32 (typically 32)
- +16: bitmap_offset u32
- +20: ascent i16 (pixels)
- +22: descent i16 (pixels, nonnegative)
- +24: line_gap i16
- +26: pixel_size u16
- +28: `font_spacing` u16 if flag 0x0001; otherwise zero (provisional FLB-derived spacing, pixels)
- +30: reserved u16 = 0

**Glyph table (24 bytes per entry)** sorted by Unicode codepoint:
- +0: codepoint u32
- +4: bitmap_offset u32 (relative to bitmap data region)
- +8: bearing_x i16 (pixels right from pen)
- +10: bearing_y i16 (pixels *up* from baseline to top of bitmap)
- +12: width u16
- +14: height u16
- +16: advance_x i16
- +18: reserved u16 = 0
- +20: bitmap_size u32

**Bitmap region:** each glyph is 1 bpp, rows top-down, MSB-left, byte-aligned per row. A bitmap of width w and height h occupies `ceil(w/8) * h` bytes. Unused low bits in the final byte of each row are zero. Blank glyphs (e.g., space) may have zero width/height, positive advance.

**Drawing:** top-left corner `(pen_x+bearing_x, baseline_y-bearing_y)`; pixel 1 draws the foreground color, 0 is transparent. All coordinates here are *raster pixel units*, while MiniDesign document layout retains its own resolution-independent physical units.

Version 1 deliberately lacks kerning, color, alpha, compression, font-family metadata and multiple strikes. Those belong to a higher-level catalog or later formats. Font data is read-only and owned by the caller.

**Advance semantics:** `glyph.advance_x` remains unchanged. Layout may calculate `glyph.advance_x + font.font_spacing + user_tracking`. `font_spacing` is not applied by `mf_draw_glyph_rgb565` or `GLYPH_RUN`. The FLB +80 field interpretation as font spacing is provisional and should be revisited after further verification. Legacy v1 files with flags=0 and all reserved bytes zero load with font_spacing=0.
