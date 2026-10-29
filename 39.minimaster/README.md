# MiniMaster gfx prototype

Portable C11 display list + CPU RGB565 reference renderer.

Run `make run`; outputs `demo-320x240.ppm` and `demo-640x480.ppm`.
PPM P6 is viewable with most image tools and convertible to PNG.

Currently implemented: CLEAR, SET_CLIP, FILL_RECT, DRAW_LINE (1px).
Declared but intentionally **not yet implemented**: BLIT, GLYPH_RUN,
FILL_PATTERN; these return an error rather than silently disappearing.

Surface owns its pixels; list owns its command array. Coordinates are already
in framebuffer pixels. SET_CLIP replaces current clip, CLEAR fills the whole
surface. No target is embedded in the command list.
