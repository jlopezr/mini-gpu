# MiniDesign BLIT (CPU reference)

`GFX_BLIT` now supports 1bpp MSB-first bitmaps through `GfxResources.bitmaps`. The source rectangle must be wholly inside the bitmap, destination can lie off-screen. Nearest-neighbor resampling, half-open clip, opaque black/white mapping or transparent zero. Source (1) maps to foreground; source (0) maps to background in opaque mode or skips in transparent mode.

`make check-blit` tests scaling, transparency, clip and invalid bounds. `make run-blit` writes two PPM demos. Original 40x20 NewsMaster icons are displayed with square destination rectangles to correct their historical 1:2 pixel aspect ratio.

The example's embedded icon data was extracted from user-provided NEWS.ICN and is supplied solely for local study; do not redistribute. Next features: RGB565/ALPHA8 bitmap resources and GPU backend.
