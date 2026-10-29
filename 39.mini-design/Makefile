CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic
CPPFLAGS += -Isrc
PYTHON ?= python3
# Originales de NewsMaster (NEWS.FLB/SHP/SDX/SDR/ICN). Las fuentes se extraen
# de NEWS.FLB en el build, no se guardan sueltas.
RES ?= resources
FLB ?= $(RES)/NEWS.FLB
FONT_DIR = build/fonts
FONTS_STAMP = $(FONT_DIR)/.stamp

# src/: librería (GFX, MiniFont, MiniDesign). examples/: demos. Todo se compila en build/.
HDRS = $(wildcard src/*.h)
GFX_OBJS = build/display_list.o build/renderer_cpu.o build/minifont.o
DOC_OBJS = build/document.o build/layout.o build/viewport.o build/document_render.o
DEMOS = build/glyph_demo build/blit_demo build/spacing_demo build/page_demo build/minifont_demo

.PHONY: all run clean test run-glyph run-blit check-blit test-minifont run-minifont flb-park10 flb-fonts flb-sheets test-flb test-flb-spacing run-spacing
.PHONY: shapes icons test-extractors check run-page test-document test-layout test-viewport test-design
all: $(DEMOS) flb-fonts

build:
	mkdir -p build
build/%.o: src/%.c $(HDRS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/%.o: examples/%.c $(HDRS) $(wildcard examples/*.h) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c -o $@ $<
build/glyph_demo build/blit_demo build/spacing_demo: build/%: build/%.o $(GFX_OBJS)
	$(CC) $(CFLAGS) -o $@ $^
build/page_demo: build/page_demo.o $(DOC_OBJS) $(GFX_OBJS)
	$(CC) $(CFLAGS) -o $@ $^
build/minifont_demo: build/minifont_demo.o build/minifont.o
	$(CC) $(CFLAGS) -o $@ $^
build/test_%: tests/test_%.c tests/test_fonts.h $(HDRS) $(DOC_OBJS) $(GFX_OBJS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ $< $(DOC_OBJS) $(GFX_OBJS)

clean:
	rm -rf build
	rm -f glyph-*.ppm blit-*.ppm spacing.ppm minifont*.ppm page*.ppm glyph-*.png blit-*.png spacing.png minifont*.png page*.png

# Demos (examples/README.md): make run-<tema>; make run las lanza todas.
run: run-glyph run-blit run-spacing run-minifont run-page
run-glyph: build/glyph_demo $(FONTS_STAMP)
	./build/glyph_demo $(FONT_DIR)/park10.mf
test: build/test_gfx $(FONTS_STAMP)
	./build/test_gfx $(FONT_DIR)/park10.mf
run-blit: build/blit_demo
	./build/blit_demo
check-blit: build/test_blit
	./build/test_blit
# Comparación visual: azul = solo advance_x, negro = advance_x + font_spacing.
run-spacing: build/spacing_demo $(FONTS_STAMP)
	./build/spacing_demo $(FONT_DIR) spacing.ppm

# MiniDesign v0.4: modelo de documento, layout, viewport y render a display list.
# page1-320x240, page1-640x480, page1-100 (100 %), page1-200 (200 %), page2-* y page2-100.
# Opcional: make run-page PAGE_ARGS="250 20 3"  (imagen en %, nº de párrafos, nº de columnas)
run-page: build/page_demo $(FONTS_STAMP)
	./build/page_demo $(FONT_DIR) $(RES) $(PAGE_ARGS)
test-document: build/test_document
	./build/test_document
test-layout: build/test_layout
	./build/test_layout
test-viewport: build/test_viewport
	./build/test_viewport
test-design: test-document test-layout test-viewport

# MiniFont: lector .mf, conversores y tests.
build/test.mf: fonts/test.bdf tools/bdf2mf.py | build
	$(PYTHON) tools/bdf2mf.py fonts/test.bdf $@
test-minifont: build/test_minifont build/test.mf
	./build/test_minifont build/test.mf
run-minifont: test-minifont build/minifont_demo
	./build/minifont_demo build/test.mf minifont.ppm

# Las 30 fuentes normales de NEWS.FLB -> build/fonts/<nombre>.mf (o FLB=/ruta/a/NEWS.FLB).
$(FONTS_STAMP): $(FLB) tools/flb2mf.py
	$(PYTHON) tools/flb2mf.py "$(FLB)" --all $(FONT_DIR)
	@touch $@
flb-fonts: $(FONTS_STAMP)
flb-park10: build/minifont_demo $(FONTS_STAMP)
	./build/minifont_demo $(FONT_DIR)/park10.mf minifont-park10.ppm
# Además hojas de muestra build/fonts/<nombre>.png; requiere Pillow.
flb-sheets:
	$(PYTHON) tools/flb2mf.py "$(FLB)" --all $(FONT_DIR) --sheets
	@touch $(FONTS_STAMP)
test-flb:
	$(PYTHON) tests/test_flb.py "$(FLB)"
# font_spacing de Park 10 (=2) y compatibilidad con cabeceras antiguas (flags=0).
test-flb-spacing: build/test_spacing $(FONTS_STAMP)
	./build/test_spacing $(FONT_DIR)/park10.mf

# Clipart e iconos de NewsMaster (NEWS.SHP/SDX/SDR/ICN en $(RES)); requiere Pillow.
shapes:
	$(PYTHON) tools/shp2png.py $(RES)/NEWS.SHP $(RES)/NEWS.SDX $(RES)/NEWS.SDR --output build/shapes
icons:
	$(PYTHON) tools/icn2png.py $(RES)/NEWS.ICN --output build/icons --correct-aspect
test-extractors:
	$(PYTHON) tests/test_extractors.py --resources $(RES)

check: test check-blit test-minifont test-flb test-flb-spacing test-design test-extractors
